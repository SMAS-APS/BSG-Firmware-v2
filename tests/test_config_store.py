import json
import pathlib
import sys
import tempfile
import unittest


MODULES = pathlib.Path(__file__).resolve().parents[1] / "modules"
sys.path.insert(0, str(MODULES))

import config_store


WROOM32_RADIO_CONFIG = {
    "spi_host": 1,
    "sck": 18,
    "mosi": 23,
    "miso": 19,
    "cs": 27,
    "reset": 14,
    "dio0": 26,
    "frequency_hz": 868_300_000,
    "frequency_offset_hz": 0,
}


class ConfigStoreTests(unittest.TestCase):
    def _load(self, document):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return config_store.load(str(path))

    def test_migrates_legacy_token_to_bearer_mode(self):
        config = self._load(
            {
                "wifi": {"ssid": "test", "password": ""},
                "amms": {"token": "legacy"},
            }
        )
        self.assertEqual(config["amms"]["auth_mode"], "bearer")
        self.assertEqual(config["amms"]["transport"], "http")
        self.assertTrue(config_store.is_provisioned(config))

    def test_new_configuration_defaults_to_mqtt(self):
        config = config_store.load("file-that-does-not-exist.json")
        self.assertEqual(config["amms"]["transport"], "mqtt")
        self.assertEqual(config["amms"]["mqtt_port"], 8883)
        self.assertFalse(config["weather_underground"]["enabled"])
        self.assertEqual(
            config["weather_underground"]["upload_interval_seconds"], 10
        )

    def test_wroom32_radio_defaults_match_example(self):
        self.assertEqual(config_store.DEFAULT_CONFIG["radio"], WROOM32_RADIO_CONFIG)
        example_path = MODULES.parent / "config.example.json"
        with example_path.open("r", encoding="utf-8") as stream:
            example = json.load(stream)
        self.assertEqual(example["radio"], WROOM32_RADIO_CONFIG)

    def test_hmac_requires_all_credentials(self):
        config = config_store._copy_defaults()
        config["wifi"]["ssid"] = "test"
        config["amms"]["transport"] = "http"
        self.assertFalse(config_store.is_provisioned(config))
        config["amms"].update(
            {
                "station_id": "bsg-test",
                "key_id": "key-test",
                "secret_hex": "01" * 32,
            }
        )
        self.assertTrue(config_store.is_provisioned(config))

    def test_weather_underground_is_optional_for_provisioning(self):
        config = config_store._copy_defaults()
        config["wifi"]["ssid"] = "test"
        config["amms"].update(
            {
                "transport": "http",
                "station_id": "bsg-test",
                "key_id": "key-test",
                "secret_hex": "01" * 32,
            }
        )
        config["weather_underground"]["enabled"] = False
        config_store.validate_weather_underground(config)
        self.assertTrue(config_store.is_provisioned(config))

    def test_weather_underground_validation(self):
        config = config_store._copy_defaults()
        wu = config["weather_underground"]
        wu.update(
            {
                "enabled": True,
                "station_id": "ISTATION1",
                "station_key": "secret",
                "mode": "standard",
                "upload_interval_seconds": 300,
                "utc_offset_minutes": 120,
            }
        )
        config_store.validate_weather_underground(config)

        wu["upload_interval_seconds"] = 9
        with self.assertRaises(ValueError):
            config_store.validate_weather_underground(config)
        wu["upload_interval_seconds"] = 10
        wu["utc_offset_minutes"] = 900
        with self.assertRaises(ValueError):
            config_store.validate_weather_underground(config)


if __name__ == "__main__":
    unittest.main()
