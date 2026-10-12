import builtins
import importlib.util
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
import config_store


class ApplicationStartupTests(unittest.TestCase):
    def test_legacy_s3_pins_cannot_reconfigure_wroom_flash_gpio(self):
        radio = Mock()
        wifi = types.SimpleNamespace(run_ap=Mock())
        spec = importlib.util.spec_from_file_location("bsg_legacy_test", ROOT / "modules/main_app.py")
        app = importlib.util.module_from_spec(spec)
        config = config_store._copy_defaults()
        config["radio"].update({"cs": 10, "mosi": 11, "dio0": 6})
        with patch.dict(sys.modules, {"bresser_native": radio, "wifi_manager": wifi}), patch("builtins.print"):
            spec.loader.exec_module(app)
            with patch.object(app, "load", return_value=config):
                app.run()
        radio.init.assert_not_called()
        self.assertIn("GPIO6-11", wifi.run_ap.call_args.args[2])

    def test_universal_dashboard_starts_in_gateway_mode_without_credentials(self):
        radio = Mock()
        wifi = types.SimpleNamespace(run_ap=Mock())
        spec = importlib.util.spec_from_file_location("bsg_gateway_test", ROOT / "modules/main_app.py")
        app = importlib.util.module_from_spec(spec)
        config = config_store._copy_defaults()
        config['runtime']['mode'] = 'gateway'
        with patch.dict(sys.modules, {"bresser_native": radio, "wifi_manager": wifi}), patch("builtins.print"):
            spec.loader.exec_module(app)
            with patch.object(app, "load", return_value=config):
                app.run()
        wifi.run_ap.assert_called_once_with(config, radio, '')
        radio.deinit.assert_called_once()

    def test_ap_starts_without_importing_amms_mqtt_or_tls_transports(self):
        radio = Mock()
        wifi = types.SimpleNamespace(run_ap=Mock())
        spec = importlib.util.spec_from_file_location("bsg_app_test", ROOT / "modules/main_app.py")
        app = importlib.util.module_from_spec(spec)
        original_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name.startswith("amms") or name == "mqtt_transport":
                raise AssertionError("AP non deve caricare i trasporti remoti")
            return original_import(name, *args, **kwargs)

        with patch.dict(sys.modules, {"bresser_native": radio, "wifi_manager": wifi}), \
             patch("builtins.__import__", side_effect=guarded), patch("builtins.print"):
            spec.loader.exec_module(app)
            with patch.object(app, "load", return_value=config_store._copy_defaults()):
                app.run()
        wifi.run_ap.assert_called_once()
        radio.init.assert_called_once()
        radio.deinit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
