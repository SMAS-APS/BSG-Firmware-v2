import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load("bsg_build", ROOT / "build_firmware.py")
qstr = load("bsg_qstr", ROOT / "native/preprocess_qstr.py")


class BuildToolsTests(unittest.TestCase):
    def test_qstr_quotes_before_preprocessing_and_unquotes_after(self):
        with tempfile.TemporaryDirectory() as folder:
            first = pathlib.Path(folder) / "qstrdefs.h"
            second = pathlib.Path(folder) / "port.h"
            output = pathlib.Path(folder) / "qstr.i"
            first.write_text("Q(temperature)\n#define TEST 1\n")
            second.write_text("Q(wind_speed)\n")
            with patch.object(qstr, "ResponsePopen") as compiler:
                process = compiler.return_value.__enter__.return_value
                process.communicate.return_value = ('"Q(temperature)"\n"Q(wind_speed)"\n', None)
                process.returncode = 0
                qstr.preprocess(output, "compiler.exe", [first, second], ["-Ipath with spaces"])
            self.assertIn('"Q(temperature)"', process.communicate.call_args.args[0])
            self.assertIn('"Q(wind_speed)"', process.communicate.call_args.args[0])
            self.assertEqual(output.read_text(), "Q(temperature)\nQ(wind_speed)\n")
            self.assertEqual(compiler.call_args.args[0], ["compiler.exe", "-E", "-Ipath with spaces", "-"])

    def test_build_uses_original_radio_module_and_manifest(self):
        with patch.object(build, "run") as command:
            build.idf_command(pathlib.Path("sdk"), "python", {}, ["build"])
        arguments = command.call_args.args[0]
        self.assertIn("MICROPY_BOARD=ESP32_GENERIC", arguments)
        self.assertIn("USER_C_MODULES=" + (ROOT / "native/micropython.cmake").as_posix(), arguments)
        self.assertIn("MICROPY_FROZEN_MANIFEST=" + (ROOT / "manifest.py").as_posix(), arguments)
        self.assertEqual(arguments[-1], "build")

    def test_flash_uses_explicit_port_and_idf_partition_map(self):
        with patch.object(build, "run") as command:
            build.idf_command(pathlib.Path("sdk"), "python", {}, ["flash"], "COM5")
        self.assertEqual(command.call_args.args[0][-3:], ["-p", "COM5", "flash"])


if __name__ == "__main__":
    unittest.main()
