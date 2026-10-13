import hashlib
import json
import pathlib
import tempfile
import unittest
import zipfile
import builtins
import types
from unittest.mock import Mock, patch

from amms.auth import _hmac_sha256

import ota_boot
import ota_runtime
from ota_update import _canonical, verify_manifest
from tools.build_ota_release import build_release


ROOT = pathlib.Path(__file__).resolve().parents[1]


class OTABootTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_state = ota_boot.STATE_PATH
        self.previous_root = ota_boot.OTA_ROOT
        ota_boot.STATE_PATH = str(pathlib.Path(self.directory.name) / "state.json")
        ota_boot.OTA_ROOT = str(pathlib.Path(self.directory.name) / "ota")
        for slot in ("a", "b"):
            path = pathlib.Path(ota_boot.OTA_ROOT) / slot
            path.mkdir(parents=True)
            (path / "main.py").write_text("pass\n", encoding="utf-8")

    def tearDown(self):
        ota_boot.STATE_PATH = self.previous_state
        ota_boot.OTA_ROOT = self.previous_root
        self.directory.cleanup()

    def test_stage_confirm_and_rollback_preserve_a_bootable_slot(self):
        state = ota_boot.load_state()
        state["versions"] = {"a": "0.1.0"}
        ota_boot.save_state(state)
        ota_boot.stage("b", "0.2.0", "upd-one")
        pending = ota_boot.load_state()
        self.assertEqual(pending["active"], "b")
        self.assertEqual(pending["previous"], "a")
        self.assertTrue(ota_boot.confirm())
        self.assertEqual(ota_boot.load_state()["report_pending"]["status"], "success")

        ota_boot.stage("a", "0.3.0", "upd-two")
        ota_boot.rollback("health timeout")
        rolled_back = ota_boot.load_state()
        self.assertEqual(rolled_back["active"], "b")
        self.assertEqual(rolled_back["report_pending"]["status"], "rolled_back")


class OTAManifestTests(unittest.TestCase):
    def test_disabled_ota_does_not_import_https_agent(self):
        original_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == 'ota_update':
                raise AssertionError('Disabled OTA loaded HTTPS client')
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=guarded), patch.object(ota_runtime, 'set_reporter'):
            self.assertIsNone(ota_runtime.start_updater({}))
            self.assertIsNone(ota_runtime.start_updater({'updates': {'enabled': False}}))

    def test_configured_ota_still_starts_and_registers_reporter(self):
        agent = Mock()
        config = {'amms': {'enabled': True, 'url': 'https://example.org/api',
                          'auth_mode': 'hmac-sha256', 'station_id': 'one',
                          'key_id': 'key', 'secret_hex': '12' * 32}}
        module = types.SimpleNamespace(OTAUpdater=Mock(return_value=agent))
        with patch.dict('sys.modules', {'ota_update': module}), patch.object(ota_runtime, 'set_reporter') as reporter:
            self.assertIs(ota_runtime.start_updater(config), agent)
        agent.start.assert_called_once()
        reporter.assert_called_once_with(agent.report_boot_result)

    def test_signature_and_tampering(self):
        secret = "12" * 32
        document = {
            "schema": 2, "job_id": "upd-one", "station_id": "bsg-one",
            "target": "bsg-esp32", "version": "0.2.0", "operation": "install",
            "compatibility": {},
            "files": [{"path": "main.py", "size": 4, "sha256": "ab" * 32,
                       "download_path": "/file"}],
        }
        self.assertEqual(
            _canonical(document),
            json.dumps(document, sort_keys=True, separators=(",", ":")),
        )
        document["signature"] = _hmac_sha256(
            bytes.fromhex(secret), _canonical(document).encode()
        ).hex()
        self.assertEqual(verify_manifest(document, secret, "bsg-one")["version"], "0.2.0")
        document["version"] = "0.2.1"
        with self.assertRaises(ValueError):
            verify_manifest(document, secret, "bsg-one")

    def test_release_is_reproducible_and_excludes_frozen_loader(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            one, manifest = build_release(ROOT, pathlib.Path(first) / "one.ammsfw")
            two, _ = build_release(ROOT, pathlib.Path(second) / "two.ammsfw")
            self.assertEqual(hashlib.sha256(one.read_bytes()).digest(), hashlib.sha256(two.read_bytes()).digest())
            paths = {item["path"] for item in manifest["files"]}
            self.assertIn("main.py", paths)
            self.assertIn("modules/main_app.py", paths)
            self.assertIn("dashboard.html.gz", paths)
            self.assertIn("dashboard.static.html", paths)
            self.assertIn("dashboard.etag", paths)
            self.assertFalse(any(path.startswith("modules/ota_") for path in paths))
            with zipfile.ZipFile(one) as archive:
                self.assertIn("manifest.json", archive.namelist())
                self.assertIn("payload/main.py", archive.namelist())


if __name__ == "__main__":
    unittest.main()
