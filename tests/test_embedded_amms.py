import pathlib
import sys
import unittest


EMBEDDED_AMMS = pathlib.Path(__file__).resolve().parents[1] / "external" / "AMMSUtils"
sys.path.insert(0, str(EMBEDDED_AMMS))

from amms import AMMSPayload, WeatherUndergroundClient
from amms.mqtt import compact_document


class EmbeddedAMMSTests(unittest.TestCase):
    def test_frozen_library_contains_wu_and_wind_gust(self):
        payload = AMMSPayload(
            sensors={"temperature": 20.0, "wind_speed": 7.2, "wind_gust": 10.8}
        )
        compact = compact_document(payload)
        self.assertEqual(compact["w"], 7.2)
        self.assertEqual(compact["g"], 10.8)

        calls = []
        client = WeatherUndergroundClient(
            "ISTATION1",
            "station-key",
            lambda url, headers, timeout: (calls.append(url) or (200, "success")),
        )
        self.assertTrue(client.send(payload, 1_700_000_000))
        self.assertIn("windgustmph", calls[0])


if __name__ == "__main__":
    unittest.main()
