import pathlib
import sys
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "external" / "AMMSUtils"))
sys.path.insert(0, str(REPOSITORY_ROOT / "raspberry-pi3"))

import gateway
from amms import HMACAuth


class GatewayPayloadTests(unittest.TestCase):
    def test_maps_bresser_reading_to_generic_amms_payload(self):
        reading = {
            "temperature": 16.1,
            "humidity": 51,
            "wind_gust": 0.8,
            "wind_speed": 0.4,
            "wind_direction": 90.0,
            "precipitation": 4.0,
            "battery_ok": True,
            "rssi": -72.5,
        }

        payload = gateway.payload_from_reading(reading).as_dict()

        self.assertEqual(
            payload,
            {
                "sensors": {
                    "temperature": 16.1,
                    "humidity": 51,
                    "wind_speed": 0.4,
                    "wind_direction": 90.0,
                    "precipitation": 4.0,
                },
                "station": {},
            },
        )

    def test_builds_hmac_authentication(self):
        auth = gateway._authentication(
            {
                "auth_mode": "hmac-sha256",
                "station_id": "bsg-test",
                "key_id": "key-test",
                "secret_hex": "01" * 32,
            }
        )
        self.assertIsInstance(auth, HMACAuth)

    def test_accepts_legacy_bearer_configuration(self):
        auth = gateway._authentication({"token": "legacy-secret"})
        self.assertIsNone(auth)

    def test_rejects_incomplete_hmac_configuration(self):
        with self.assertRaises(ValueError):
            gateway._authentication(
                {
                    "auth_mode": "hmac-sha256",
                    "station_id": "bsg-test",
                    "key_id": "key-test",
                    "secret_hex": "",
                }
            )

    def test_builds_mqtt_client(self):
        calls = []

        class Publisher:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            def publish(self, *_args, **_kwargs):
                pass

        amms = {
            "transport": "mqtt",
            "auth_mode": "hmac-sha256",
            "station_id": "bsg-test",
            "key_id": "key-test",
            "secret_hex": "01" * 32,
            "mqtt_host": "broker.example",
            "mqtt_port": 8883,
            "mqtt_ca_cert": "/tmp/ca.crt",
        }
        client, transport = gateway._build_client(amms, mqtt_publisher_class=Publisher)
        self.assertEqual(transport, "MQTT")
        self.assertEqual(client.station_id, "bsg-test")
        self.assertEqual(calls, [{
            "station_id": "bsg-test",
            "password": "01" * 32,
            "host": "broker.example",
            "port": 8883,
            "ca_cert": "/tmp/ca.crt",
        }])


if __name__ == "__main__":
    unittest.main()
