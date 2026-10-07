import json


CONFIG_PATH = "/config.json"

DEFAULT_CONFIG = {
    "wifi": {
        "ssid": "",
        "password": "",
    },
    "amms": {
        "transport": "mqtt",
        "auth_mode": "hmac-sha256",
        "station_id": "",
        "key_id": "",
        "secret_hex": "",
        "token": "",
        "url": "https://weather.iacca.ml/api/data/point",
        "timeout_seconds": 15,
        "mqtt_host": "weather.iacca.ml",
        "mqtt_port": 8883,
        "mqtt_ca_cert": "/mqtt-ca.crt",
    },
    "radio": {
        "spi_host": 3,
        "sck": 18,
        "mosi": 23,
        "miso": 19,
        "cs": 27,
        "reset": 32,
        "dio0": 21,
        "frequency_hz": 868_300_000,
        "frequency_offset_hz": 0,
    },
    "runtime": {
        "poll_interval_ms": 25,
        "reconnect_interval_seconds": 15,
    },
}


def _copy_defaults():
    return {section: values.copy() for section, values in DEFAULT_CONFIG.items()}


def load(path=CONFIG_PATH):
    config = _copy_defaults()
    try:
        with open(path, "r") as stream:
            stored = json.load(stream)
    except (OSError, ValueError):
        return config

    if not isinstance(stored, dict):
        return config

    for section, values in stored.items():
        if section in config and isinstance(values, dict):
            config[section].update(values)
    stored_amms = stored.get("amms", {})
    if isinstance(stored_amms, dict) and "transport" not in stored_amms:
        # Le configurazioni precedenti restano su HTTP dopo l'aggiornamento.
        config["amms"]["transport"] = "http"
    if (
        isinstance(stored_amms, dict)
        and "auth_mode" not in stored_amms
        and stored_amms.get("token")
    ):
        config["amms"]["auth_mode"] = "bearer"
    return config


def save(config, path=CONFIG_PATH):
    temporary_path = path + ".tmp"
    with open(temporary_path, "w") as stream:
        json.dump(config, stream)

    try:
        import os
        try:
            os.remove(path)
        except OSError:
            pass
        os.rename(temporary_path, path)
    except Exception:
        # Mantiene il file temporaneo per non perdere i dati in caso di errore flash.
        raise


def _file_exists(path):
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def is_provisioned(config):
    amms = config["amms"]
    if amms.get("auth_mode") == "hmac-sha256":
        authentication_ready = all(
            amms.get(name) for name in ("station_id", "key_id", "secret_hex")
        )
    else:
        authentication_ready = bool(amms.get("token"))
    transport_ready = True
    if amms.get("transport") == "mqtt":
        transport_ready = (
            bool(amms.get("mqtt_host"))
            and amms.get("auth_mode") == "hmac-sha256"
            and _file_exists(amms.get("mqtt_ca_cert", "/mqtt-ca.crt"))
        )
    return bool(config["wifi"].get("ssid") and authentication_ready and transport_ready)
