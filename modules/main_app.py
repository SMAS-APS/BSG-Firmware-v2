import gc
import time

import bresser_native

from config_store import is_provisioned, load, validate_weather_underground
from bsg_runtime import FIRMWARE_BOARD, FIRMWARE_VERSION, FIRMWARE_STAGE
import wifi_manager
from wu_support import canonical_sensor_values
from bresser_protocols import AutoReceiver
from rx_led import ReceiveLED


def _sync_clock():
    try:
        import ntptime
        ntptime.settime()
        print("Orologio sincronizzato via NTP")
        return True
    except Exception as exc:
        print("Sincronizzazione NTP non riuscita:", exc)
        return False


def _clock_is_valid():
    try:
        return time.gmtime()[0] >= 2024
    except Exception:
        return False


def _init_radio(radio):
    if FIRMWARE_BOARD == "ESP32-WROOM-32":
        for name in ("sck", "mosi", "miso", "cs", "reset", "dio0", "dio1"):
            if 6 <= int(radio.get(name, 33)) <= 11:
                raise ValueError("GPIO6-11 riservati alla flash WROOM-32: aggiornare radio in /config.json")
    bresser_native.init(
        spi_host=int(radio["spi_host"]),
        sck=int(radio["sck"]),
        mosi=int(radio["mosi"]),
        miso=int(radio["miso"]),
        cs=int(radio["cs"]),
        reset=int(radio["reset"]),
        dio0=int(radio["dio0"]),
        dio1=int(radio.get("dio1", 33)),
        frequency_hz=int(radio["frequency_hz"]),
        frequency_offset_hz=int(radio.get("frequency_offset_hz", 0)),
    )
    print("Ricevitore:", bresser_native.status())


def _payload_from_reading(reading):
    from amms import AMMSPayload
    payload = AMMSPayload()
    for name, value in canonical_sensor_values(reading).items():
        payload.set_sensor(name, value)
    return payload


def _build_client(amms_config):
    from amms import AMMSClient, AMMSMQTTClient, HMACAuth
    from amms.transports.micropython_http import post_json
    from mqtt_transport import MicroPythonMQTTPublisher
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
            keepalive=int(amms_config.get("mqtt_keepalive", 45)),
            timeout_seconds=int(amms_config.get("timeout_seconds", 15)),
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
        user_agent="BSG-MicroPython/" + FIRMWARE_VERSION,
        auth=auth,
    ), "HTTP"


def _weather_underground_get(url, headers, timeout):
    from amms.transports.ca_cert import AMAZON_ROOT_CA_1
    from amms.transports.micropython_http import get_text
    return get_text(url, headers, timeout, ca_cert=AMAZON_ROOT_CA_1)


def _build_weather_underground(config):
    from amms import WeatherUndergroundClient
    from wu_support import RainTracker
    wu_config = config["weather_underground"]
    if not wu_config.get("enabled"):
        return None, None
    validate_weather_underground(config)
    client = WeatherUndergroundClient(
        wu_config["station_id"],
        wu_config["station_key"],
        _weather_underground_get,
        mode=wu_config.get("mode", "rapidfire"),
        upload_interval_seconds=int(wu_config.get("upload_interval_seconds", 10)),
        timeout_seconds=5,
        user_agent="BSG-MicroPython/" + FIRMWARE_VERSION,
    )
    tracker = RainTracker(int(wu_config.get("utc_offset_minutes", 60)))
    return client, tracker


def run():
    print("Bresser Gateway firmware %s (%s)" % (FIRMWARE_VERSION, FIRMWARE_STAGE))
    config = load()
    if config["runtime"].get("mode", "ap") == "ap":
        radio_error = ""
        try:
            _init_radio(config["radio"])
        except Exception as exc:
            radio_error = str(exc)
            print("Errore ricevitore:", radio_error)
        try:
            wifi_manager.run_ap(config, bresser_native, radio_error)
        finally:
            bresser_native.deinit()
        return
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

    clock_valid = _sync_clock() or _clock_is_valid()
    _init_radio(config["radio"])

    receiver = AutoReceiver(bresser_native)
    led = ReceiveLED(config["runtime"])

    amms_config = config["amms"]
    client, transport = _build_client(amms_config)
    try:
        wu_client, rain_tracker = _build_weather_underground(config)
    except (TypeError, ValueError) as exc:
        print("Weather Underground disabilitato:", exc)
        wu_client, rain_tracker = None, None

    poll_interval = int(config["runtime"].get("poll_interval_ms", 25))
    reconnect_interval = int(config["runtime"].get("reconnect_interval_seconds", 15))
    last_reconnect_attempt = time.ticks_ms()
    last_clock_attempt = time.ticks_ms()
    last_wu_upload = None

    print("Gateway pronto con trasporto %s; autoriconoscimento Bresser 5/6/7-in-1 e varianti" % transport)
    try:
        while True:
            led.tick(time.ticks_ms())
            reading = receiver.poll()
            if reading is not None:
                led.pulse(time.ticks_ms())
                if reading.get("error"):
                    print("ERRORE RF:", reading)
                    time.sleep_ms(poll_interval)
                    continue
            if reading is not None:
                print("Ricevuto:", reading)
                payload = _payload_from_reading(reading)
                observed_at = int(time.time()) if clock_valid else None
                hourly_rain_mm = None
                daily_rain_mm = None
                if rain_tracker is not None and observed_at is not None:
                    try:
                        hourly_rain_mm, daily_rain_mm = rain_tracker.update(
                            reading, observed_at
                        )
                    except Exception as exc:
                        print("Stato pioggia WU non aggiornato:", exc)

                connected = False
                try:
                    wifi_manager.ensure_connected(config, timeout_seconds=reconnect_interval)
                    connected = True
                except Exception as exc:
                    print("Wi-Fi non disponibile per gli invii:", exc)

                if connected:
                    try:
                        result = client.send(payload, clear_on_success=False)
                        if result.ok:
                            print("AMMS %s:" % transport, result.body)
                        else:
                            print("Invio AMMS non riuscito:", result.error, result.body)
                    except Exception as exc:
                        print("Invio AMMS non riuscito:", exc)

                if connected and wu_client is not None and clock_valid:
                    now_ticks = time.ticks_ms()
                    interval_ms = wu_client.upload_interval_seconds * 1000
                    due = last_wu_upload is None or time.ticks_diff(
                        now_ticks, last_wu_upload
                    ) >= interval_ms
                    if due:
                        last_wu_upload = now_ticks
                        try:
                            wu_result = wu_client.send(
                                payload,
                                observed_at,
                                hourly_rain_mm=hourly_rain_mm,
                                daily_rain_mm=daily_rain_mm,
                            )
                            if wu_result.ok:
                                print("Weather Underground: dati pubblicati")
                            else:
                                print(
                                    "Invio Weather Underground non riuscito:",
                                    wu_result.error,
                                    wu_result.body,
                                )
                        except Exception as exc:
                            print("Invio Weather Underground non riuscito:", exc)
                gc.collect()

            wlan = wifi_manager.station()
            if not wlan.isconnected():
                now = time.ticks_ms()
                if time.ticks_diff(now, last_reconnect_attempt) >= reconnect_interval * 1000:
                    last_reconnect_attempt = now
                    try:
                        wifi_manager.ensure_connected(config, timeout_seconds=reconnect_interval)
                        clock_valid = _sync_clock() or _clock_is_valid()
                        last_clock_attempt = time.ticks_ms()
                    except OSError as exc:
                        print("Riconnessione Wi-Fi non riuscita:", exc)

            if wlan.isconnected() and not clock_valid:
                now = time.ticks_ms()
                if time.ticks_diff(now, last_clock_attempt) >= 300_000:
                    last_clock_attempt = now
                    clock_valid = _sync_clock() or _clock_is_valid()

            time.sleep_ms(poll_interval)
    finally:
        client.close()
        led.off()
        bresser_native.deinit()
