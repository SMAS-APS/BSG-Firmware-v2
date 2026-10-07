#!/usr/bin/env python3
"""Gateway Bresser 5-in-1 per Raspberry Pi OS."""

import json
import logging
import os
import signal
import sys
import time

import bresser_native
from amms import AMMSClient, AMMSMQTTClient, AMMSPayload, HMACAuth
from amms.transports.cpython_http import post_json


CONFIG_PATH = os.environ.get("BSG_CONFIG", "/etc/bsg-gateway/config.json")
STOP_REQUESTED = False


def _request_stop(signum, _frame):
    global STOP_REQUESTED
    logging.info("Ricevuto segnale %s: arresto in corso", signum)
    STOP_REQUESTED = True


def load_config(path):
    with open(path, "r", encoding="utf-8") as stream:
        config = json.load(stream)

    amms = config.get("amms", {})
    url = amms.get("url", "").strip()
    if not url.startswith("https://"):
        raise ValueError("l'URL AMMS deve iniziare con https://")
    _authentication(amms)
    transport = amms.get("transport", "http").strip().lower()
    if transport not in ("http", "mqtt"):
        raise ValueError("trasporto AMMS non supportato")
    if transport == "mqtt":
        if amms.get("auth_mode", "hmac-sha256") != "hmac-sha256":
            raise ValueError("MQTT richiede credenziali HMAC per stazione")
        if not amms.get("mqtt_host", "").strip():
            raise ValueError("host MQTT mancante")
    return config


def _authentication(amms):
    mode = amms.get("auth_mode", "").strip().lower()
    has_hmac = all(
        amms.get(name, "").strip()
        for name in ("station_id", "key_id", "secret_hex")
    )
    if mode == "hmac-sha256" or (not mode and has_hmac):
        return HMACAuth.from_config(amms)
    if mode not in ("", "bearer"):
        raise ValueError("modalita' di autenticazione AMMS non supportata")
    if not amms.get("token", "").strip():
        raise ValueError("credenziali AMMS mancanti")
    return None


def payload_from_reading(reading):
    payload = AMMSPayload()
    for source, destination in (
        ("temperature", "temperature"),
        ("humidity", "humidity"),
        ("wind_speed", "wind_speed"),
        ("wind_direction", "wind_direction"),
        ("precipitation", "precipitation"),
    ):
        value = reading.get(source)
        if value is not None:
            payload.set_sensor(destination, value)
    return payload


def configure_logging(config):
    level_name = config.get("runtime", {}).get("log_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def init_radio(config):
    radio = config["radio"]
    bresser_native.init(
        spi_device=radio.get("spi_device", "/dev/spidev0.0"),
        reset=int(radio.get("reset", 25)),
        dio0=int(radio.get("dio0", 24)),
        frequency_hz=int(radio.get("frequency_hz", 868_300_000)),
        frequency_offset_hz=int(radio.get("frequency_offset_hz", 0)),
    )
    logging.info("Ricevitore inizializzato: %s", bresser_native.status())


def _build_client(amms, mqtt_publisher_class=None):
    transport = amms.get("transport", "http").strip().lower()
    if transport == "mqtt":
        if mqtt_publisher_class is None:
            from mqtt_transport import RaspberryMQTTPublisher
            mqtt_publisher_class = RaspberryMQTTPublisher
        publisher = mqtt_publisher_class(
            station_id=amms["station_id"],
            password=amms["secret_hex"],
            host=amms["mqtt_host"],
            port=int(amms.get("mqtt_port", 8883)),
            ca_cert=amms.get("mqtt_ca_cert", "/etc/bsg-gateway/mqtt-ca.crt"),
        )
        return AMMSMQTTClient(amms["station_id"], publisher), "MQTT"

    return AMMSClient(
        amms.get("token", ""),
        post_json,
        url=amms["url"],
        timeout_seconds=int(amms.get("timeout_seconds", 15)),
        user_agent="BSG-RaspberryPi/2.2",
        auth=_authentication(amms),
    ), "HTTP"


def run():
    config = load_config(CONFIG_PATH)
    configure_logging(config)
    init_radio(config)
    amms = config["amms"]
    client, transport = _build_client(amms)

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    poll_seconds = max(
        0.005,
        int(config.get("runtime", {}).get("poll_interval_ms", 25)) / 1000.0,
    )
    stats_interval = max(
        30,
        int(config.get("runtime", {}).get("stats_interval_seconds", 300)),
    )
    next_stats = time.monotonic() + stats_interval
    logging.info("Gateway pronto con trasporto %s; in attesa di pacchetti Bresser 5-in-1", transport)

    try:
        while not STOP_REQUESTED:
            reading = bresser_native.poll()
            if reading is not None:
                logging.info("Ricevuto: %s", reading)
                result = client.send(payload_from_reading(reading))
                if result.ok:
                    logging.info("AMMS %s: %s", transport, result.body[:300])
                else:
                    logging.warning(
                        "Invio AMMS non riuscito: %s; HTTP=%s; risposta=%s",
                        result.error,
                        result.http_status,
                        result.body[:300],
                    )
            if time.monotonic() >= next_stats:
                logging.info("Statistiche ricevitore: %s", bresser_native.stats())
                next_stats = time.monotonic() + stats_interval
            time.sleep(poll_seconds)
    finally:
        client.close()
        logging.info("Statistiche finali: %s", bresser_native.stats())
        bresser_native.deinit()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        logging.exception("Errore irreversibile del gateway")
        raise
