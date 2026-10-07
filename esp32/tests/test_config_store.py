import json
import pathlib
import sys
import tempfile
import unittest


MODULES = pathlib.Path(__file__).resolve().parents[1] / "modules"
sys.path.insert(0, str(MODULES))

import config_store


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
        self.assertTrue(config_store.is_provisioned(config))

    def test_hmac_requires_all_credentials(self):
        config = config_store._copy_defaults()
        config["wifi"]["ssid"] = "test"
        self.assertFalse(config_store.is_provisioned(config))
        config["amms"].update(
            {
                "station_id": "bsg-test",
                "key_id": "key-test",
                "secret_hex": "01" * 32,
            }
        )
        self.assertTrue(config_store.is_provisioned(config))


if __name__ == "__main__":
    unittest.main()
