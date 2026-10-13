import copy
import types
import unittest
from unittest.mock import Mock, patch
from test_ap_portal import wifi
import config_store
from serial_commands import SerialCommands
from wifi_recovery import WifiRecovery


class SerialConfigurationTests(unittest.TestCase):
    def make(self):
        config = config_store._copy_defaults()
        config['wifi'].update(ssid='old', password='previous')
        output = []
        service = types.SimpleNamespace(log=Mock(), command=Mock(), lines=[])
        recovery = Mock()
        console = SerialCommands(config, recovery, service, output.append)
        return config, output, service, recovery, console

    def test_config_saves_then_forces_connection_without_password_echo_or_log(self):
        config, output, service, recovery, console = self.make()
        with patch('serial_commands.save') as save:
            console.feed(b'config\r\nhidden-name\r\npassword123\r\n')
        self.assertEqual(config['wifi']['ssid'], 'hidden-name')
        self.assertEqual(config['wifi']['password'], 'password123')
        self.assertFalse(console.configuring)
        save.assert_called_once()
        recovery.request_connect.assert_called_once()
        self.assertNotIn('password123', ''.join(output))
        self.assertNotIn('password123', str(service.log.call_args_list))
        service.command.assert_not_called()

    def test_empty_password_explicitly_configures_open_network(self):
        config, _, _, _, console = self.make()
        with patch('serial_commands.save'):
            console.feed(b'config\nopen-network\n\n')
        self.assertEqual(config['wifi']['password'], '')

    def test_flash_failure_preserves_old_network_and_does_not_connect(self):
        config, output, service, recovery, console = self.make()
        previous = copy.deepcopy(config)
        with patch('serial_commands.save', side_effect=OSError('secret123')):
            console.feed(b'config\nnew\nsecret123\n')
        self.assertEqual(config, previous)
        recovery.request_connect.assert_not_called()
        self.assertNotIn('secret123', ''.join(output))

    def test_unicode_spaces_backspace_and_long_input(self):
        config, _, _, recovery, console = self.make()
        with patch('serial_commands.save'):
            console.feed('config\n café X\b \nabc12345\n')
        self.assertEqual(config['wifi']['ssid'], ' café  ')
        recovery.request_connect.assert_called_once()
        config, _, _, recovery, console = self.make()
        with patch('serial_commands.save') as save:
            console.feed(b'config\n' + b'x'*200 + b'\n')
        save.assert_not_called()
        self.assertFalse(console.configuring)


class WifiRecoveryTests(unittest.TestCase):
    def make(self):
        cfg = config_store._copy_defaults()
        cfg['wifi'].update(ssid='home', password='private')
        wlan, ap, emit = Mock(), Mock(), Mock()
        wlan.isconnected.return_value = False
        wlan.status.return_value = 0
        wlan.ifconfig.return_value = ('192.168.1.10', '', '', '')
        ap.config.return_value = 1
        ap.status.return_value = []
        with patch.object(wifi.time, 'ticks_ms', return_value=0, create=True):
            recovery = WifiRecovery(cfg, wlan, ap, emit)
        return cfg, wlan, ap, emit, recovery

    def tick(self, recovery, now, scanning=False):
        with patch.object(wifi.time, 'ticks_diff', side_effect=lambda a,b:a-b, create=True):
            return recovery.tick(now, scanning)

    def test_startup_grace_and_no_repeated_disconnect_during_active_attempt(self):
        _, wlan, _, _, recovery = self.make()
        self.tick(recovery, 9999)
        wlan.connect.assert_not_called()
        self.tick(recovery, 10000)
        wlan.connect.assert_called_once()
        wlan.disconnect.assert_not_called()
        wlan.status.return_value = 1001
        self.tick(recovery, 100000)
        wlan.connect.assert_called_once()

    def test_ap_client_and_scan_pause_auto_connect_but_config_forces_it(self):
        _, wlan, ap, _, recovery = self.make()
        ap.status.return_value = [(b'mac', '192.168.4.2')]
        self.tick(recovery, 10000)
        wlan.connect.assert_not_called()
        recovery.request_connect()
        self.tick(recovery, 11000, scanning=True)
        wlan.connect.assert_not_called()
        self.tick(recovery, 12000)
        wlan.disconnect.assert_called_once()
        wlan.connect.assert_called_once_with('home', 'private')

    def test_forced_config_reconnects_even_when_already_connected(self):
        cfg, wlan, _, output, recovery = self.make()
        wlan.isconnected.return_value = True
        self.tick(recovery, 1000)
        cfg['wifi'].update(ssid='new', password='new-password')
        recovery.request_connect()
        self.tick(recovery, 1001)
        wlan.connect.assert_called_once_with('new', 'new-password')
        self.assertNotIn('new-password', str(output.call_args_list))

    def test_failed_network_uses_backoff_and_reports_reason(self):
        _, wlan, _, output, recovery = self.make()
        wlan.status.return_value = -3
        self.tick(recovery, 10000)
        self.tick(recovery, 40000)
        wlan.connect.assert_called_once()
        self.tick(recovery, 70000)
        self.assertEqual(wlan.connect.call_count, 2)
        self.assertTrue(any('password rifiutata' in call.args[0] for call in output.call_args_list))


if __name__ == '__main__':
    unittest.main()
