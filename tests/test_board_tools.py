import hashlib
import importlib.util
import io
import json
import pathlib
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bsg_tools", ROOT / "bsg.py")
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


class BoardToolsTests(unittest.TestCase):
    def test_version_check_accepts_earlier_updateable_firmware(self):
        runtime = types.SimpleNamespace(FIRMWARE_SCHEMA=2)
        with patch.dict("sys.modules", {"bresser_native": types.SimpleNamespace(), "bsg_runtime": runtime}), \
             patch("builtins.print"):
            exec(board.VERIFY_CODE, {})

    def test_deploy_rejects_missing_multi_protocol_native_api_before_copying(self):
        runtime = types.SimpleNamespace(FIRMWARE_SCHEMA=2)
        with patch.dict("sys.modules", {"bresser_native": types.SimpleNamespace(), "bsg_runtime": runtime}), patch("builtins.print"):
            with self.assertRaisesRegex(AssertionError, "flashare"):
                exec(board.DEPLOY_VERIFY_CODE, {})

    def image(self, folder):
        image = pathlib.Path(folder) / "firmware.bin"
        image.write_bytes(b"test-bsg-image")
        image.with_suffix(".bin.json").write_text(json.dumps({
            "schema": 2, "chip": "esp32", "flash_offset": 4096,
            "native_modules": ["bresser_native"], "native_api": 2,
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        }))
        return image

    def test_corrupt_or_wrong_board_image_is_rejected_before_flash(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.image(folder)
            image.write_bytes(b"corrupted")
            with patch.object(board, "require"), patch.object(board, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "SHA256"):
                    board.flash("COM5", image, erase=True)
                run.assert_not_called()
            data = json.loads(image.with_suffix(".bin.json").read_text())
            data["chip"] = "esp32s3"
            image.with_suffix(".bin.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(RuntimeError, "WROOM"):
                board.validate_image(image)

    def test_flash_does_not_erase_by_default_and_deploys_python(self):
        with tempfile.TemporaryDirectory() as folder:
            image = self.image(folder)
            with patch.object(board, "require"), patch.object(board, "python_files"), \
                 patch.object(board, "run") as run, patch.object(board, "deploy") as deploy:
                board.flash("COM5", image)
            self.assertEqual(run.call_count, 1)
            command = run.call_args.args[0]
            self.assertIn("write_flash", command)
            self.assertIn("0x1000", command)
            self.assertNotIn("erase_flash", command)
            deploy.assert_called_once_with("COM5")

    def test_explicit_erase_runs_before_write(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(board, "require"), patch.object(board, "python_files"), \
                 patch.object(board, "run") as run, patch.object(board, "deploy"):
                board.flash("COM5", self.image(folder), erase=True)
            self.assertEqual(run.call_args_list[0].args[0][-1], "erase_flash")
            self.assertIn("write_flash", run.call_args_list[1].args[0])

    def test_deploy_validates_native_module_and_preserves_config(self):
        files = [(ROOT / "main.py", "/main.py"), (ROOT / "modules/wifi_manager.py", "/wifi_manager.py")]
        with patch.object(board, "require"), patch.object(board, "python_files", return_value=files), \
             patch.object(board, "run") as run:
            board.deploy("COM5")
        command = run.call_args.args[0]
        self.assertLess(command.index(board.DEPLOY_VERIFY_CODE), command.index("fs"))
        self.assertNotIn(":/config.json", command)
        self.assertIn(":/main.py.bsg-tmp", command)
        self.assertIn("import os; os.rename('/main.py.bsg-tmp', '/main.py')", command)
        self.assertEqual(command[-1], "import machine; machine.reset()")

    def test_deployment_contains_app_and_amms_without_native_sources(self):
        files = board.python_files()
        targets = [remote for _, remote in files]
        self.assertIn("/main.py", targets)
        self.assertIn("/main_app.py", targets)
        self.assertIn("/lib/amms/__init__.py", targets)
        self.assertNotIn("/config.json", targets)
        self.assertTrue(all(local.suffix == ".py" for local, _ in files))

    def test_frozen_main_honours_filesystem_main(self):
        context = {}
        with patch("builtins.open", return_value=io.StringIO("started_from_filesystem = True\n")):
            exec((ROOT / "native/main.py").read_text(), context)
        self.assertTrue(context["started_from_filesystem"])

    def test_frozen_main_has_application_fallback(self):
        app = types.SimpleNamespace(run=Mock())
        with patch("builtins.open", side_effect=OSError(2, "missing")), \
             patch.dict("sys.modules", {"main_app": app}):
            exec((ROOT / "native/main.py").read_text(), {})
        app.run.assert_called_once()

    def test_frozen_boot_prioritises_filesystem_modules(self):
        system = types.SimpleNamespace(path=["", ".frozen", "/lib"])
        context = {}
        with patch("builtins.open", return_value=io.StringIO("boot_override = True\n")), \
             patch.dict("sys.modules", {"sys": system}):
            exec((ROOT / "native/boot.py").read_text(), context)
        self.assertTrue(context["boot_override"])
        self.assertEqual(system.path[:2], ["/", "/lib"])


if __name__ == "__main__":
    unittest.main()
