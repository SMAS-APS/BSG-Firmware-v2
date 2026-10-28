"""Attivazione AMMS ripristinabile, eseguita fuori dal ciclo radio."""
import binascii
import hashlib
import json
import os
import time

from config_store import replace_file, save


STATE_PATH = "/activation-state.json"
DEFAULT_SERVER_URL = "https://151.242.0.96"
_service = None


def _copy_config(config):
    return {key: value.copy() for key, value in config.items()}


def _save_json(path, document):
    temporary = path + ".tmp"
    with open(temporary, "w") as stream:
        json.dump(document, stream)
    replace_file(temporary, path)


def _load_json(path):
    try:
        with open(path, "r") as stream:
            document = json.load(stream)
        return document if isinstance(document, dict) else None
    except (OSError, ValueError):
        return None


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def validate_request(activation_key, server_url):
    from amms import normalize_activation_key
    key = normalize_activation_key(activation_key)
    server = str(server_url or DEFAULT_SERVER_URL).strip().rstrip("/")
    if not server.startswith("https://") or len(server) > 256:
        raise ValueError("il server AMMS deve usare HTTPS")
    return key, server


class ActivationService:
    def __init__(
        self,
        config,
        wlan,
        state,
        state_path=STATE_PATH,
        http_post=None,
        http_get=None,
        sleep=time.sleep,
        thread_start=None,
    ):
        self.config = config
        self.wlan = wlan
        self.state = state
        self.state_path = state_path
        self.http_post = http_post
        self.http_get = http_get
        self.sleep = sleep
        self.thread_start = thread_start
        self.busy = False
        self.status = "attiva" if config.get("amms", {}).get("secret_hex") else "non attivata"

    def queue(self, activation_key, server_url=DEFAULT_SERVER_URL):
        key, server = validate_request(activation_key, server_url)
        pending = _load_json(self.state_path)
        if not pending or pending.get("activation_key") != key:
            from amms import generate_claim_id
            pending = {
                "schema": 1,
                "activation_key": key,
                "server_url": server,
                "claim_id": generate_claim_id(),
            }
        else:
            pending["server_url"] = server
        _save_json(self.state_path, pending)
        self.status = "attivazione in attesa della rete"
        self.start()

    def start(self):
        if self.busy or not _load_json(self.state_path):
            return
        self.busy = True
        starter = self.thread_start
        if starter is None:
            import _thread
            starter = _thread.start_new_thread
        try:
            starter(self._worker, ())
        except Exception:
            self.busy = False
            self.status = "impossibile avviare l'attivazione"

    def _write_ca(self, pem):
        if not isinstance(pem, str) or len(pem) > 16384:
            raise ValueError("certificato CA non valido")
        if "-----BEGIN CERTIFICATE-----" not in pem or "-----END CERTIFICATE-----" not in pem:
            raise ValueError("certificato CA non valido")
        digest = binascii.hexlify(hashlib.sha256(pem.encode()).digest()).decode()[:16]
        path = "/mqtt-ca-" + digest + ".crt"
        temporary = path + ".tmp"
        with open(temporary, "w") as stream:
            stream.write(pem)
        replace_file(temporary, path)
        return path

    def _set_status(self, value):
        self.status = value

    def _prepare_document(self, pending):
        mqtt = pending["document"]["mqtt"]
        if not pending.get("ca_path"):
            status, pem = self.http_get(mqtt["ca_url"], {}, 20)
            if not 200 <= int(status) < 300:
                raise OSError("download CA MQTT rifiutato: HTTP %d" % int(status))
            pending["ca_path"] = self._write_ca(pem)
            _save_json(self.state_path, pending)

    def _apply_document(self, pending):
        document = pending["document"]
        identity, api, mqtt = document["identity"], document["api"], document["mqtt"]
        if not pending.get("ca_path"):
            raise ValueError("certificato CA MQTT non preparato")
        candidate = _copy_config(self.config)
        candidate["amms"].update({
            "enabled": True,
            "transport": "mqtt",
            "auth_mode": "hmac-sha256",
            "station_id": identity["station_id"],
            "key_id": identity["key_id"],
            "secret_hex": identity["secret_hex"],
            "token": "",
            "url": api["data_url"],
            "mqtt_host": mqtt["host"],
            "mqtt_port": int(mqtt["port"]),
            "mqtt_ca_cert": pending["ca_path"],
        })
        candidate["updates"].update(enabled=True, server_url=api["update_base_url"])
        candidate["activation"]["server_url"] = pending["server_url"]
        save(candidate)
        self.config.update(candidate)

    def _worker(self):
        from amms import ActivationClient, ActivationError
        if self.http_post is None or self.http_get is None:
            from amms.transports.micropython_http import get_text, post_json
            self.http_post = self.http_post or post_json
            self.http_get = self.http_get or get_text
        try:
            while True:
                pending = _load_json(self.state_path)
                if not pending:
                    return
                if not self.wlan.isconnected():
                    self._set_status("attivazione in attesa del Wi-Fi")
                    self.sleep(5)
                    continue
                try:
                    client = ActivationClient(self.http_post, pending["server_url"], 20)
                    if not pending.get("document"):
                        self._set_status("richiesta identita' AMMS")
                        pending["document"] = client.claim(
                            pending["activation_key"], "bsg-esp32", pending["claim_id"]
                        )
                        _save_json(self.state_path, pending)
                    self._set_status("download e verifica CA MQTT")
                    self._prepare_document(pending)
                    self._set_status("conferma attivazione AMMS")
                    client.confirm(pending["document"], pending["claim_id"])
                    self._set_status("salvataggio identita' AMMS")
                    self._apply_document(pending)
                    _remove(self.state_path)
                    self._set_status("attiva; riavvio in corso")
                    ticks = getattr(time, "ticks_ms", lambda: int(time.time() * 1000))
                    self.state["restart_requested"] = ticks()
                    return
                except ActivationError as exc:
                    self._set_status("attivazione rifiutata: " + str(exc))
                    if getattr(exc, "http_status", None) in (400, 401, 409):
                        return
                except Exception as exc:
                    self._set_status("attivazione da riprovare: " + str(exc))
                self.sleep(10)
        finally:
            self.busy = False


def start_activation_service(config, wlan, state):
    global _service
    _service = ActivationService(config, wlan, state)
    _service.start()
    return _service


def queue_activation(activation_key, server_url=DEFAULT_SERVER_URL):
    if _service is None:
        raise RuntimeError("servizio di attivazione non disponibile")
    _service.queue(activation_key, server_url)
