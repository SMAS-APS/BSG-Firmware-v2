import json


CONFIG_PATH = "/config.json"

DEFAULT_CONFIG = {
    "wifi": {
        "ssid": "",
        "password": "",
    },
    "amms": {
        "enabled": False,
        "upload_interval_seconds": 10,
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
        "mqtt_keepalive": 45,
        "mqtt_ca_cert": "/mqtt-ca.crt",
    },
    "radio": {
        "spi_host": 1,
        "sck": 18,
        "mosi": 23,
        "miso": 19,
        "cs": 27,
        "reset": 32,
        "dio0": 21,
        "dio1": 33,
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
        "mode": "ap",
        "ap_ssid": "Bresser Gateway",
        "poll_interval_ms": 25,
        "reconnect_interval_seconds": 15,
        "led_pin": 2,
        "led_active_low": False,
        "led_pulse_ms": 100,
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
    old_radio = stored.get("radio", {})
    if isinstance(old_radio, dict) and "dio1" not in old_radio and all(
        old_radio.get(key) == value for key, value in
        (("sck", 18), ("mosi", 23), ("miso", 19), ("cs", 27), ("reset", 14), ("dio0", 26))
    ):
        # Migra esclusivamente il precedente cablaggio predefinito WROOM.
        config["radio"].update({"reset": 32, "dio0": 21, "dio1": 33})
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

    replace_file(temporary_path, path)


def replace_file(source, target):
    # LittleFS (ESP32) sostituisce atomicamente con rename. Su CPython/Windows
    # serve replace: in entrambi i casi non eliminiamo prima il vecchio file.
    import os
    getattr(os, "replace", os.rename)(source, target)


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


def validate_amms(config, certificate_available=None):
    amms = config["amms"]
    if not amms.get("enabled"):
        return
    if not config["wifi"].get("ssid"):
        raise ValueError("AMMS richiede Wi-Fi")
    if amms.get("transport") not in ("http", "mqtt"):
        raise ValueError("trasporto AMMS non valido")
    if amms.get("auth_mode") == "hmac-sha256":
        secret = amms.get("secret_hex", "")
        if not amms.get("station_id") or not amms.get("key_id") or len(secret) != 64:
            raise ValueError("credenziali HMAC incomplete: chiave da 32 byte")
        try:
            bytes.fromhex(secret)
        except ValueError:
            raise ValueError("chiave HMAC non esadecimale")
    elif amms.get("auth_mode") == "bearer":
        if not amms.get("token"):
            raise ValueError("token AMMS mancante")
    else:
        raise ValueError("autenticazione AMMS non valida")
    if not 1 <= int(amms.get("timeout_seconds", 15)) <= 60:
        raise ValueError("timeout AMMS deve essere 1..60 secondi")
    if not 1 <= int(amms.get("upload_interval_seconds", 10)) <= 86400:
        raise ValueError("intervallo AMMS deve essere 1..86400 secondi")
    if amms["transport"] == "mqtt":
        if amms["auth_mode"] != "hmac-sha256" or not amms.get("mqtt_host"):
            raise ValueError("MQTT richiede host e credenziali HMAC per stazione")
        if any(char in amms["station_id"] for char in ("/", "+", "#")):
            raise ValueError("ID stazione MQTT contiene separatori o wildcard")
        if not 1 <= int(amms.get("mqtt_port", 8883)) <= 65535:
            raise ValueError("porta MQTT non valida")
        if not 10 <= int(amms.get("mqtt_keepalive", 45)) <= 3600:
            raise ValueError("keepalive MQTT deve essere 10..3600 secondi")
        if certificate_available is None:
            certificate_available = _file_exists(amms.get("mqtt_ca_cert", "/mqtt-ca.crt"))
        if not certificate_available:
            raise ValueError("certificato CA MQTT mancante")
    elif not amms.get("url", "").startswith("https://"):
        raise ValueError("URL AMMS deve usare HTTPS")
