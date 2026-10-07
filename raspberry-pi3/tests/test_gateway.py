import pathlib
import sys
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "external" / "AMMSUtils"))
sys.path.insert(0, str(REPOSITORY_ROOT / "raspberry-pi3"))

import gateway


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


if __name__ == "__main__":
    unittest.main()
