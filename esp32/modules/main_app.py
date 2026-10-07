import gc
import time

import bresser_native

from amms import AMMSClient, AMMSMQTTClient, AMMSPayload, HMACAuth
from amms.transports.micropython_http import post_json
from config_store import is_provisioned, load
from mqtt_transport import MicroPythonMQTTPublisher
import wifi_manager


def _sync_clock():
    try:
        import ntptime
        ntptime.settime()
        print("Orologio sincronizzato via NTP")
        return True
    except Exception as exc:
        print("Sincronizzazione NTP non riuscita:", exc)
        return False


def _init_radio(radio):
    bresser_native.init(
        spi_host=int(radio["spi_host"]),
        sck=int(radio["sck"]),
        mosi=int(radio["mosi"]),
        miso=int(radio["miso"]),
        cs=int(radio["cs"]),
        reset=int(radio["reset"]),
        dio0=int(radio["dio0"]),
        frequency_hz=int(radio["frequency_hz"]),
        frequency_offset_hz=int(radio.get("frequency_offset_hz", 0)),
    )
    print("Ricevitore:", bresser_native.status())


def _payload_from_reading(reading):
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


def _build_client(amms_config):
    transport = amms_config.get("transport", "http").lower()
    if transport == "mqtt":
        if amms_config.get("auth_mode") != "hmac-sha256":
            raise ValueError("MQTT richiede credenziali per stazione")
        publisher = MicroPythonMQTTPublisher(
            station_id=amms_config["station_id"],
            password=amms_config["secret_hex"],
            host=amms_config["mqtt_host"],
            port=int(amms_config.get("mqtt_port", 8883)),
            ca_cert=amms_config.get("mqtt_ca_cert", "/mqtt-ca.crt"),
        )
        return AMMSMQTTClient(amms_config["station_id"], publisher), "MQTT"

    auth = None
    auth_mode = amms_config.get("auth_mode", "")
    if auth_mode == "hmac-sha256":
        auth = HMACAuth.from_config(amms_config)
    elif auth_mode != "bearer":
        raise ValueError("modalita' di autenticazione AMMS non supportata")
    return AMMSClient(
        amms_config.get("token", ""),
        post_json,
        url=amms_config["url"],
        timeout_seconds=int(amms_config.get("timeout_seconds", 15)),
        user_agent="BSG-MicroPython/2.2",
        auth=auth,
    ), "HTTP"


def run():
    config = load()
    if not is_provisioned(config):
        print("Configurazione incompleta")
        wifi_manager.provision(config)
        return

    try:
        wifi_manager.ensure_connected(config)
    except OSError as exc:
        print("Wi-Fi non disponibile:", exc)
        wifi_manager.provision(config)
        return

    _sync_clock()
    _init_radio(config["radio"])

    amms_config = config["amms"]
    client, transport = _build_client(amms_config)

    poll_interval = int(config["runtime"].get("poll_interval_ms", 25))
    reconnect_interval = int(config["runtime"].get("reconnect_interval_seconds", 15))
    last_reconnect_attempt = time.ticks_ms()

    print("Gateway pronto con trasporto %s; in attesa di pacchetti Bresser 5-in-1" % transport)
    try:
        while True:
            reading = bresser_native.poll()
            if reading is not None:
                print("Ricevuto:", reading)
                try:
                    wifi_manager.ensure_connected(config, timeout_seconds=reconnect_interval)
                    result = client.send(_payload_from_reading(reading))
                    if result.ok:
                        print("AMMS %s:" % transport, result.body)
                    else:
                        print("Invio AMMS non riuscito:", result.error, result.body)
                except Exception as exc:
                    print("Invio AMMS non riuscito:", exc)
                finally:
                    gc.collect()

            wlan = wifi_manager.station()
            if not wlan.isconnected():
                now = time.ticks_ms()
                if time.ticks_diff(now, last_reconnect_attempt) >= reconnect_interval * 1000:
                    last_reconnect_attempt = now
                    try:
                        wifi_manager.ensure_connected(config, timeout_seconds=reconnect_interval)
                        _sync_clock()
                    except OSError as exc:
                        print("Riconnessione Wi-Fi non riuscita:", exc)

            time.sleep_ms(poll_interval)
    finally:
        client.close()
        bresser_native.deinit()
