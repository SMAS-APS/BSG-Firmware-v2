import pathlib
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "modules"))
from ap_uplink import Uplink
import ap_uplink


class UplinkWorkerTests(unittest.TestCase):
    def run_worker(self, amms_failure=False, stale=False):
        cfg = {"amms": {"upload_interval_seconds": 10}}
        service = Uplink(cfg, Mock(isconnected=Mock(return_value=True)))
        service.wu_enabled = True
        service.amms_enabled = True
        service.running = True
        service.lock = threading.Lock()
        service.pending = (dict(protocol="bresser_7in1", sensor_id=1, sensor_type=1, temperature=20), -130000 if stale else 100)
        amms, wu, tracker = Mock(), Mock(upload_interval_seconds=10), Mock()
        tracker.update.return_value = (1, 2)
        amms.send.return_value = types.SimpleNamespace(ok=True)
        if amms_failure:
            amms.send.side_effect = OSError("network failure")
        wu.send.return_value = types.SimpleNamespace(ok=True)
        app = types.SimpleNamespace(_build_client=Mock(return_value=(amms, "HTTP")),
                                    _build_weather_underground=Mock(return_value=(wu, tracker)),
                                    _payload_from_reading=lambda r: {"sensors": {"temperature": r["temperature"]}})
        with patch.dict(sys.modules, {"main_app": app, "ntptime": types.SimpleNamespace(settime=Mock())}), \
             patch.object(ap_uplink.time, "ticks_ms", return_value=100, create=True), \
             patch.object(ap_uplink.time, "ticks_diff", side_effect=lambda a, b: a - b, create=True), \
             patch.object(ap_uplink.time, "sleep_ms", side_effect=lambda ms: service.stop(), create=True), \
             patch.object(ap_uplink.time, "time", return_value=1700000000), patch("builtins.print"):
            service._worker()
        return amms, wu, service

    def test_amms_and_wu_send_independently_in_same_worker(self):
        amms, wu, service = self.run_worker()
        amms.send.assert_called_once()
        wu.send.assert_called_once()
        self.assertEqual(wu.send.call_args.kwargs["hourly_rain_mm"], 1)
        self.assertEqual(service.status, "dati pubblicati")
        self.assertIn("HTTP", service.amms_status)

    def test_amms_failure_does_not_prevent_wu_upload(self):
        amms, wu, service = self.run_worker(amms_failure=True)
        amms.send.assert_called_once()
        wu.send.assert_called_once()
        self.assertEqual(service.amms_status, "errore connessione AMMS")

    def test_stale_radio_data_is_not_uploaded(self):
        amms, wu, _ = self.run_worker(stale=True)
        amms.send.assert_not_called()
        wu.send.assert_not_called()
