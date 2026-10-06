import gc
import time

import bresser_native

from amms import AMMSClient
from config_store import is_provisioned, load
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
    client = AMMSClient(
        amms_config["token"],
        amms_config["url"],
        int(amms_config.get("timeout_seconds", 15)),
    )

    poll_interval = int(config["runtime"].get("poll_interval_ms", 25))
    reconnect_interval = int(config["runtime"].get("reconnect_interval_seconds", 15))
    last_reconnect_attempt = time.ticks_ms()

    print("Gateway pronto; in attesa di pacchetti Bresser 5-in-1")
    while True:
        reading = bresser_native.poll()
        if reading is not None:
            print("Ricevuto:", reading)
            try:
                wifi_manager.ensure_connected(config, timeout_seconds=reconnect_interval)
                response = client.send(reading)
                print("AMMS:", response.status)
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
