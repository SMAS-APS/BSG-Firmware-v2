import bresser_native

from config_store import load, validate_weather_underground
from bsg_runtime import FIRMWARE_BOARD, FIRMWARE_VERSION, FIRMWARE_STAGE
import wifi_manager
from wu_support import canonical_sensor_values
from bresser_protocols import AutoReceiver
from rx_led import ReceiveLED


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
    from ota_runtime import initialize_version
    initialize_version(FIRMWARE_VERSION)
    radio_error = ""
    try:
        _init_radio(config["radio"])
        from ota_runtime import mark
        mark("radio")
    except Exception as exc:
        radio_error = str(exc)
        print("Errore ricevitore:", radio_error)
    try:
        from ota_runtime import start_guard
        start_guard(300)
        wifi_manager.run_ap(config, bresser_native, radio_error)
    finally:
        bresser_native.deinit()
    return
