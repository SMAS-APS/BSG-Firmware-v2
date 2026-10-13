import copy
import json
import types
import unittest
from urllib.parse import urlencode
from unittest.mock import Mock, patch
from test_ap_portal import wifi
import config_store
import bresser_protocols
from rx_led import ReceiveLED
from ap_uplink import Uplink


class ConfigurationTests(unittest.TestCase):
    def config(self):
        result = config_store._copy_defaults()
        result["wifi"].update(ssid="home", password="private-wifi")
        result["weather_underground"].update(station_id="ISTATION", station_key="private-wu")
        result["amms"].update(station_id="bsg", key_id="key", secret_hex="ab" * 32, token="private-token", transport="http")
        return result

    def form(self):
        return dict(ssid="home", password="", wu_enabled="on", wu_station_id="ISTATION", wu_station_key="",
                    wu_mode="rapidfire", wu_interval="10", wu_utc_offset="60", amms_enabled="on",
                    transport="http", auth_mode="hmac-sha256", station_id="bsg", key_id="key",
                    secret_hex="", token="", url="https://example.org/api/data/point", mqtt_host="broker.example.org",
                    mqtt_port="8883", mqtt_keepalive="45", mqtt_ca_cert="/mqtt-ca.crt", timeout_seconds="10", amms_interval="15")

    def test_dashboard_has_separate_pages_and_every_original_remote_setting(self):
        cfg = self.config()
        html = wifi._dashboard(cfg)
        for page in ("status", "wifi", "config", "terminal"):
            self.assertIn('id="page-%s"' % page, html)
        for name in self.form():
            self.assertIn('name="%s"' % name, html)
        self.assertIn('name="mqtt_ca_pem"', html)
        for secret in ("private-wifi", "private-wu", "private-token", "ab" * 32):
            self.assertNotIn(secret, html)

    def test_config_attributes_are_html_escaped(self):
        cfg = self.config()
        cfg["wifi"]["ssid"] = '\"><script>alert(1)</script>'
        html = wifi._dashboard(cfg)
        self.assertNotIn(cfg["wifi"]["ssid"], html)
        self.assertIn("&lt;script&gt;", html)

    def test_blank_secrets_are_preserved_and_http_and_wu_enable_independently(self):
        cfg = self.config()
        with patch.object(wifi, "save") as save:
            wifi._save_ap_configuration(cfg, self.form())
        self.assertTrue(cfg["amms"]["enabled"])
        self.assertTrue(cfg["weather_underground"]["enabled"])
        self.assertEqual(cfg["wifi"]["password"], "private-wifi")
        self.assertEqual(cfg["amms"]["secret_hex"], "ab" * 32)
        self.assertEqual(cfg["weather_underground"]["station_key"], "private-wu")
        self.assertEqual(cfg["runtime"]["mode"], "ap")
        save.assert_called_once()

    def test_new_mqtt_ca_does_not_overwrite_previous_ca_before_commit(self):
        cfg = self.config()
        original = copy.deepcopy(cfg)
        form = self.form()
        form.update(transport="mqtt", mqtt_ca_pem="-----BEGIN CERTIFICATE-----\nNEW\n-----END CERTIFICATE-----")
        with patch.object(wifi, "_save_mqtt_ca") as ca, patch.object(wifi, "save", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                wifi._save_ap_configuration(cfg, form)
        self.assertEqual(cfg, original)
        self.assertNotEqual(ca.call_args.args[0], "/mqtt-ca.crt")

    def test_wunderground_can_be_saved_with_disabled_amms_and_blank_ca_path(self):
        cfg = self.config()
        cfg['amms']['mqtt_ca_cert'] = ''
        form = self.form()
        form.pop('amms_enabled')
        form.update(wu_mode='standard', mqtt_ca_cert='', transport='mqtt', url='http:\\bad', mqtt_host='http:\\bad')
        with patch.object(wifi, 'save') as save:
            wifi._save_ap_configuration(cfg, form)
        self.assertTrue(cfg['weather_underground']['enabled'])
        self.assertEqual(cfg['weather_underground']['station_key'], 'private-wu')
        self.assertEqual(cfg['weather_underground']['mode'], 'standard')
        self.assertFalse(cfg['amms']['enabled'])
        self.assertEqual(cfg['amms']['mqtt_ca_cert'], '/mqtt-ca.crt')
        save.assert_called_once()

    def test_disabled_wu_fields_are_preserved_when_browser_omits_them(self):
        cfg = self.config()
        previous = cfg['weather_underground'].copy()
        with patch.object(wifi, 'save'):
            wifi._save_ap_configuration(cfg, dict(ssid='home', password=''))
        self.assertFalse(cfg['weather_underground']['enabled'])
        for name in ('station_id', 'station_key', 'mode', 'upload_interval_seconds'):
            self.assertEqual(cfg['weather_underground'][name], previous[name])

    def test_invalid_hmac_or_bearer_mqtt_does_not_change_configuration(self):
        for changes in (dict(secret_hex="bad"), dict(transport="mqtt", auth_mode="bearer"), dict(mqtt_port="70000", transport="mqtt")):
            cfg = self.config()
            original = copy.deepcopy(cfg)
            form = self.form()
            form.update(changes)
            with patch.object(wifi, "save") as save, patch.object(wifi, "_file_exists", return_value=True):
                with self.assertRaises(ValueError):
                    wifi._save_ap_configuration(cfg, form)
            save.assert_not_called()
            self.assertEqual(cfg, original)

    def test_body_can_arrive_after_headers(self):
        body = urlencode(self.form()).encode()
        request = b"POST /save HTTP/1.1\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n"
        self.assertFalse(wifi._request_complete(request))
        self.assertFalse(wifi._request_complete(request + body[:10]))
        self.assertTrue(wifi._request_complete(request + body))
        cfg, state = self.config(), {}
        with patch.object(wifi, "save"), patch.object(wifi.time, "ticks_ms", return_value=123, create=True):
            response = wifi._ap_response(request + body, state, cfg)
        self.assertTrue(response.startswith(b"HTTP/1.1 200"))
        self.assertEqual(state["restart_requested"], 123)
        self.assertNotIn(b"private", response)

    def test_request_rejects_excessive_negative_and_duplicate_lengths(self):
        for header in (b"Content-Length: 8000", b"Content-Length: -1", b"Content-Length: 1\r\nContent-Length: 1", b"Transfer-Encoding: chunked"):
            with self.assertRaises(ValueError):
                wifi._request_complete(b"POST /save HTTP/1.1\r\n" + header + b"\r\n\r\n")

    def test_previous_default_pinout_migrates_and_custom_pinout_is_retained(self):
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / "config.json"
            old = dict(spi_host=1, sck=18, mosi=23, miso=19, cs=27, reset=14, dio0=26)
            path.write_text(json.dumps(dict(radio=old)))
            self.assertEqual(config_store.load(str(path))["radio"]["reset"], 32)
            old["cs"] = 5
            path.write_text(json.dumps(dict(radio=old)))
            self.assertEqual(config_store.load(str(path))["radio"]["reset"], 14)

    def test_led_pulse_is_nonblocking_and_has_configurable_polarity(self):
        for active_low in (False, True):
            pin = Mock()
            with patch.dict("sys.modules", {"machine": types.SimpleNamespace(Pin=Mock(OUT=1, return_value=pin))}), patch.object(bresser_protocols.time, "ticks_diff", side_effect=lambda a, b: a - b, create=True):
                led = ReceiveLED(dict(led_active_low=active_low))
                led.pulse(100)
                pin.value.assert_called_with(0 if active_low else 1)
                led.tick(150)
                self.assertIsNotNone(led.started)
                led.tick(200)
                pin.value.assert_called_with(1 if active_low else 0)

    def test_remote_queue_selects_one_station_and_keeps_only_latest_packet(self):
        cfg = self.config()
        cfg["weather_underground"]["enabled"] = True
        cfg["amms"]["enabled"] = True
        import threading
        worker = Mock()
        with patch.dict("sys.modules", {"_thread": types.SimpleNamespace(allocate_lock=threading.Lock, start_new_thread=worker)}), patch.object(bresser_protocols.time, "ticks_ms", return_value=100, create=True):
            uplink = Uplink(cfg, Mock())
            first = dict(protocol="bresser_7in1", sensor_id=1, sensor_type=1, temperature=20)
            uplink.submit(first)
            uplink.submit(dict(first, sensor_id=2, temperature=99))
            self.assertEqual(uplink.pending[0]["sensor_id"], 1)
            uplink.submit(dict(first, temperature=21))
            self.assertEqual(uplink.pending[0]["temperature"], 21)
            worker.assert_called_once()
            uplink.stop()


if __name__ == "__main__":
    unittest.main()
