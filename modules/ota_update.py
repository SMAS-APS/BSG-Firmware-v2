"""Agente OTA HTTPS a memoria limitata per BSG ESP32."""
import gc
import binascii
import hashlib
import json
import os
import socket
import ssl
import time

from amms import HMACAuth
from amms.auth import _constant_time_equal, _hmac_sha256
from amms.transports.ca_cert import ISRG_ROOT_X1
from amms.transports.micropython_http import _parse_https_url, get_text, post_json
from ota_boot import load_state, stage


COMMAND_PATH = "/ota-command.json"
MAX_TOTAL = 2 * 1024 * 1024
BOOTSTRAP_COMPATIBILITY = {
    "board": "ESP32-WROOM-32", "firmware_schema": 3,
    "native_api": 2, "rf_driver_revision": 2,
}


def _canonical(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return str(value).lower()
    if isinstance(value, list):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key) + ":" + _canonical(value[key]) for key in sorted(value)) + "}"
    raise ValueError("valore manifest non supportato")


def verify_manifest(document, secret_hex, station_id):
    if not isinstance(document, dict):
        raise ValueError("manifest OTA non valido")
    unsigned = document.copy()
    signature = unsigned.pop("signature", "")
    expected = _hmac_sha256(binascii.unhexlify(secret_hex), _canonical(unsigned).encode())
    try:
        supplied = binascii.unhexlify(signature)
    except (ValueError, TypeError):
        raise ValueError("firma OTA non valida")
    if not _constant_time_equal(supplied, expected):
        raise ValueError("firma OTA non valida")
    if (unsigned.get("schema") != 2 or unsigned.get("target") != "bsg-esp32"
            or unsigned.get("station_id") != station_id):
        raise ValueError("manifest OTA destinato a un altro dispositivo")
    if unsigned.get("operation", "install") not in ("install", "rollback"):
        raise ValueError("operazione OTA non valida")
    files = unsigned.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("elenco file OTA mancante")
    return unsigned


def _version_tuple(value):
    base = value.split("-", 1)[0].split("+", 1)[0]
    return tuple(int(part) for part in base.split("."))


def _mkdirs(path):
    current = ""
    for part in path.strip("/").split("/"):
        current += "/" + part
        try:
            os.mkdir(current)
        except OSError:
            pass


def _remove_tree(path):
    try:
        entries = list(os.ilistdir(path))
    except OSError:
        return
    for entry in entries:
        child = path + "/" + entry[0]
        if entry[1] & 0x4000:
            _remove_tree(child)
        else:
            os.remove(child)
    os.rmdir(path)


class OTAUpdater:
    def __init__(self, config):
        amms = config.get("amms", {})
        updates = config.get("updates", {})
        endpoint = updates.get("server_url") or amms.get("url", "")
        marker = endpoint.find("/", 8)
        self.base_url = endpoint if marker < 0 else endpoint[:marker]
        self.station_id = amms.get("station_id", "")
        self.secret_hex = amms.get("secret_hex", "")
        self.poll_interval = max(60, int(updates.get("poll_interval_seconds", 60)))
        self.enabled = bool(updates.get("enabled", True) and amms.get("enabled")
                            and endpoint.startswith("https://")
                            and amms.get("auth_mode") == "hmac-sha256"
                            and self.station_id and amms.get("key_id") and len(self.secret_hex) == 64)
        self.auth = (HMACAuth(self.station_id, amms["key_id"], self.secret_hex)
                     if self.enabled else None)
        self.status = "disabilitato" if not self.enabled else "in attesa"

    def start(self):
        if not self.enabled:
            return
        import _thread
        _thread.start_new_thread(self._run, ())

    def _headers(self, method, path, body=b""):
        return self.auth.headers(method, path, body)

    def _json(self, method, path, document=None):
        url = self.base_url + path
        body = b"" if document is None else json.dumps(document).encode()
        headers = self._headers(method, path, body)
        if document is None:
            status, text = get_text(url, headers, 15, ca_cert=ISRG_ROOT_X1)
        else:
            status, text = post_json(url, document, headers, 15, ca_cert=ISRG_ROOT_X1)
        if status < 200 or status >= 300:
            raise OSError("server OTA HTTP %d" % status)
        return json.loads(text)

    def _report(self, job_id, status, progress, error=None, installed_version=None):
        document = {"job_id": job_id, "status": status, "progress": int(progress)}
        if error:
            document["error"] = str(error)[:160]
        if installed_version:
            document["installed_version"] = installed_version
        try:
            self._json("POST", "/api/stations/%s/updates/status" % self.station_id, document)
            return True
        except Exception:
            return False

    def report_boot_result(self, report):
        return self._report(
            report["job_id"], report["status"], 100,
            error=report.get("error"), installed_version=report.get("installed_version"),
        )

    def _download(self, path, destination, maximum):
        host, port, target = _parse_https_url(self.base_url + path)
        headers = self._headers("GET", target)
        address = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
        raw = socket.socket(address[0], socket.SOCK_STREAM, address[2])
        raw.settimeout(20)
        secure = None
        digest, total = hashlib.sha256(), 0
        try:
            raw.connect(address[-1])
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(cadata=ISRG_ROOT_X1)
            secure = context.wrap_socket(raw, server_hostname=host)
            secure.write(("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n" % (target, host)).encode())
            for name, value in headers.items():
                secure.write(("%s: %s\r\n" % (name, value)).encode())
            secure.write(b"\r\n")
            parts = secure.readline().split(None, 2)
            if len(parts) < 2 or int(parts[1]) != 200:
                raise OSError("download OTA rifiutato")
            length = None
            while True:
                line = secure.readline()
                if not line or line == b"\r\n":
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
                if line.lower().startswith(b"transfer-encoding:"):
                    raise OSError("risposta chunked non supportata")
            if length is None or length > maximum:
                raise OSError("dimensione OTA non valida")
            with open(destination, "wb") as output:
                while total < length:
                    chunk = secure.read(min(1024, length - total))
                    if not chunk:
                        raise OSError("download OTA interrotto")
                    total += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
            return total, binascii.hexlify(digest.digest()).decode()
        finally:
            (secure or raw).close()

    def process_once(self):
        response = self._json("GET", "/api/stations/%s/updates/desired" % self.station_id)
        if response.get("status") != "update":
            return False
        manifest = verify_manifest(response.get("manifest"), self.secret_hex, self.station_id)
        compatibility = manifest.get("compatibility", {})
        actual = BOOTSTRAP_COMPATIBILITY
        for key, expected in compatibility.items():
            valid = actual.get(key) == expected
            if key == "firmware_schema":
                valid = int(actual.get(key, 0)) >= int(expected)
            if not valid:
                raise ValueError("release incompatibile: " + key)
        state = load_state()
        installed_version = state.get("version")
        if installed_version:
            requested = _version_tuple(manifest["version"])
            installed = _version_tuple(installed_version)
            if requested < installed and manifest.get("operation", "install") != "rollback":
                raise ValueError("downgrade OTA senza rollback esplicito")
            if manifest.get("operation") == "rollback" and requested >= installed:
                raise ValueError("rollback OTA richiede una versione precedente")
        inactive = "b" if state.get("active") == "a" else "a"
        root = "/ota/" + inactive
        job_id = manifest["job_id"]
        try:
            self.status = "download %s" % manifest["version"]
            self._report(job_id, "downloading", 5)
            _remove_tree(root)
            _mkdirs(root)
            expected_total = sum(int(item["size"]) for item in manifest["files"])
            available = os.statvfs("/")[0] * os.statvfs("/")[3]
            if expected_total > MAX_TOTAL or available < expected_total + 64 * 1024:
                raise OSError("spazio flash insufficiente")
            completed = 0
            for item in manifest["files"]:
                relative = item["path"]
                if relative.startswith("/") or ".." in relative.split("/") or "\\" in relative:
                    raise ValueError("percorso OTA non sicuro")
                destination = root + "/" + relative
                _mkdirs(destination.rsplit("/", 1)[0])
                temporary = destination + ".tmp"
                size, digest = self._download(item["download_path"], temporary, int(item["size"]))
                if size != item["size"] or digest != item["sha256"]:
                    raise ValueError("checksum OTA non valido")
                getattr(os, "replace", os.rename)(temporary, destination)
                completed += size
                self._report(job_id, "downloading", 5 + int(completed * 55 / expected_total))
                gc.collect()
            self._report(job_id, "verifying", 70)
            if not os.stat(root + "/main.py"):
                raise ValueError("release priva di main.py")
            self._report(job_id, "installing", 85)
            stage(inactive, manifest["version"], job_id)
            self._report(job_id, "restarting", 95)
            self.status = "riavvio"
            time.sleep(1)
            import machine
            machine.reset()
        except Exception as exc:
            self.status = "errore: %s" % str(exc)[:80]
            self._report(job_id, "failed", 0, error=exc)
            raise
        return True

    def _run(self):
        next_poll = 0
        while True:
            commanded = False
            try:
                os.stat(COMMAND_PATH)
                commanded = True
            except OSError:
                pass
            now = time.time()
            if time.gmtime()[0] >= 2024 and (commanded or now >= next_poll):
                try:
                    if commanded:
                        os.remove(COMMAND_PATH)
                    self.process_once()
                    self.status = "nessun aggiornamento"
                except Exception as exc:
                    print("OTA:", str(exc))
                next_poll = now + self.poll_interval
            time.sleep(5)
