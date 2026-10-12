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
        "spi_host": 1,
        "sck": 12,
        "mosi": 11,
        "miso": 13,
        "cs": 10,
        "reset": 14,
        "dio0": 6,
        "frequency_hz": 868_300_000,
        "frequency_offset_hz": 0,
    },
    "weather_underground": {
        "enabled": False,
        "station_id": "",
        "station_key": "",
        "mode": "rapidfire",
        "upload_interval_seconds": 10,
        "utc_offset_minutes": 60,
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


def validate_weather_underground(config):
    section = config.get("weather_underground", {})
    if not section.get("enabled"):
        return
    if not section.get("station_id") or not section.get("station_key"):
        raise ValueError("credenziali Weather Underground incomplete")
    if section.get("mode") not in ("rapidfire", "standard"):
        raise ValueError("modalita' Weather Underground non valida")
    interval = int(section.get("upload_interval_seconds", 10))
    if interval < 10:
        raise ValueError("intervallo Weather Underground minimo: 10 secondi")
    offset = int(section.get("utc_offset_minutes", 60))
    if offset < -720 or offset > 840:
        raise ValueError("offset UTC Weather Underground non valido")


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
