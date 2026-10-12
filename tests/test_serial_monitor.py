import importlib.util
import pathlib
import unittest
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("serial_monitor_tested", ROOT / "serial_monitor.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class SerialMonitorTests(unittest.TestCase):
    def test_restart_waits_for_friendly_prompt_before_running_main(self):
        port = Mock(in_waiting=0)
        port.read.side_effect = [b"boot", b"raw REPL", b"\r\n>>", b"> "]
        monitor.restart_python(port)
        self.assertEqual(port.read.call_count, 4)
        self.assertEqual(port.write.call_args.args[0], b"\x04")
        self.assertIn(b"\x03", port.write.call_args_list[0].args[0])
        self.assertIn(b"\x02", port.write.call_args_list[0].args[0])

    def test_restart_timeout_reports_problem_without_starting_blindly(self):
        port = Mock(in_waiting=0)
        port.read.return_value = b"no prompt"
        with patch.object(monitor.time, "monotonic", side_effect=[0, 0, 1, 2, 3, 10]):
            with self.assertRaisesRegex(RuntimeError, "REPL"):
                monitor.restart_python(port, timeout_seconds=4)
        self.assertFalse(any(call.args[0] == b"\x04" for call in port.write.call_args_list))
