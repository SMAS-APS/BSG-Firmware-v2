#!/usr/bin/env python3
"""Gateway Bresser 5-in-1 per Raspberry Pi OS."""

import json
import logging
import os
import signal
import ssl
import sys
import time
import urllib.error
import urllib.request

import bresser_native


CONFIG_PATH = os.environ.get("BSG_CONFIG", "/etc/bsg-gateway/config.json")
STOP_REQUESTED = False


def _request_stop(signum, _frame):
    global STOP_REQUESTED
    logging.info("Ricevuto segnale %s: arresto in corso", signum)
    STOP_REQUESTED = True


def load_config(path):
    with open(path, "r", encoding="utf-8") as stream:
        config = json.load(stream)

    token = config.get("amms", {}).get("token", "").strip()
    url = config.get("amms", {}).get("url", "").strip()
    if not token:
        raise ValueError("token AMMS mancante in %s" % path)
    if not url.startswith("https://"):
        raise ValueError("l'URL AMMS deve iniziare con https://")
    return config


def payload_from_reading(reading):
    sensors = {}
    for source, destination in (
        ("temperature", "temperature"),
        ("humidity", "humidity"),
        ("wind_speed", "wind_speed"),
        ("wind_direction", "wind_direction"),
        ("precipitation", "precipitation"),
    ):
        value = reading.get(source)
        if value is not None:
            sensors[destination] = value
    return {"sensors": sensors, "station": {}}


def send_to_amms(reading, config):
    amms = config["amms"]
    encoded = json.dumps(payload_from_reading(reading)).encode("utf-8")
    request = urllib.request.Request(
        amms["url"],
        data=encoded,
        headers={
            "Authorization": "Bearer " + amms["token"],
            "Content-Type": "application/json",
            "User-Agent": "BSG-RaspberryPi/1.0",
        },
        method="POST",
    )
    context = ssl.create_default_context()
    timeout = int(amms.get("timeout_seconds", 15))
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        body = response.read(4096).decode("utf-8", "replace")
        return response.status, body


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


def run():
    config = load_config(CONFIG_PATH)
    configure_logging(config)
    init_radio(config)

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
    logging.info("Gateway pronto; in attesa di pacchetti Bresser 5-in-1")

    try:
        while not STOP_REQUESTED:
            reading = bresser_native.poll()
            if reading is not None:
                logging.info("Ricevuto: %s", reading)
                try:
                    status, body = send_to_amms(reading, config)
                    logging.info("AMMS HTTP %s: %s", status, body[:300])
                except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                    logging.exception("Invio AMMS non riuscito: %s", exc)
            if time.monotonic() >= next_stats:
                logging.info("Statistiche ricevitore: %s", bresser_native.stats())
                next_stats = time.monotonic() + stats_interval
            time.sleep(poll_seconds)
    finally:
        logging.info("Statistiche finali: %s", bresser_native.stats())
        bresser_native.deinit()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        logging.exception("Errore irreversibile del gateway")
        raise
