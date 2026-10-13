import calendar
import copy
import json
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode
from test_ap_portal import wifi
import config_store
from dashboard_service import DashboardService
from station_clock import DEFAULT_CLOCK, ClockService, offset_minutes, validate_clock


def epoch(year, month, day, hour=0, minute=0, second=0):
    return calendar.timegm((year, month, day, hour, minute, second))


class DashboardTests(unittest.TestCase):
    def service(self):
        cfg = config_store._copy_defaults()
        cfg['wifi'].update(ssid='home', password='private')
        cfg['amms']['token'] = 'private-token'
        return DashboardService(cfg, Mock(), {'sensors': {'temperature': 20}, 'received': 5})

    def request(self, service, path, form, origin=None):
        body = urlencode(form).encode()
        headers = b'Host: 192.168.4.1\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n'
        if origin:
            headers += b'Origin: ' + origin.encode() + b'\r\n'
        with patch.object(wifi.time, 'ticks_ms', return_value=123, create=True):
            response = wifi._ap_response(b'POST '+path.encode()+b' HTTP/1.1\r\n'+headers+b'\r\n'+body,
                                         service.state, service.config, service)
        return response, json.loads(response.split(b'\r\n\r\n', 1)[1])

    def test_ui_omits_alert_tab_and_uses_only_reported_numeric_sensor_keys(self):
        html = wifi._dashboard(config_store._copy_defaults())
        self.assertNotIn('data-page="alert"', html)
        self.assertNotIn('id="page-alert"', html)
        self.assertNotIn('id="alert-badge"', html)
        self.assertIn('Object.keys(station?.sensors||{}).filter(key=>Number.isFinite(station.sensors[key]))', html)
        self.assertNotIn('Object.keys(metadata).slice(0,8)', html)

    def test_wifi_save_preserves_other_services_and_blank_password(self):
        svc = self.service()
        previous = copy.deepcopy(svc.config)
        with patch('dashboard_service.save') as save:
            response, data = self.request(svc, '/api/config', dict(section='wifi', ssid='home', password=''))
        self.assertTrue(response.startswith(b'HTTP/1.1 200'))
        self.assertTrue(data['restart'])
        self.assertEqual(svc.config['amms'], previous['amms'])
        self.assertEqual(svc.config['wifi']['password'], 'private')
        self.assertEqual(svc.state['restart_requested'], 123)
        save.assert_called_once()

    def test_wunderground_save_returns_json_confirmation_before_restart(self):
        svc = self.service()
        svc.config['weather_underground'].update(station_id='ISTATION', station_key='private-wu')
        form = dict(section='integrations', wu_enabled='on', wu_station_id='ISTATION',
                    wu_station_key='', wu_mode='standard', wu_interval='10', wu_utc_offset='60', mqtt_ca_cert='')
        with patch.object(wifi, 'save') as save:
            response, data = self.request(svc, '/api/config', form)
        self.assertTrue(response.startswith(b'HTTP/1.1 200'))
        self.assertTrue(data['restart'])
        self.assertEqual(svc.state['restart_requested'], 123)
        self.assertTrue(svc.config['weather_underground']['enabled'])
        self.assertNotIn(b'private-wu', response)
        save.assert_called_once()

    def test_network_status_reports_sta_with_ap_off_and_ap_after_disconnect(self):
        svc = self.service()
        svc.wlan.ifconfig.return_value = ('192.168.1.48', '255.255.255.0', '192.168.1.1', '192.168.1.1')
        svc.clock.tick = Mock()
        svc.clock.snapshot = Mock(return_value={})
        svc.state['ap_active'] = False
        svc.tick(0, True)
        self.assertEqual(svc.state['network']['mode'], 'STA')
        self.assertFalse(svc.state['network']['ap_active'])
        self.assertIsNone(svc.state['network']['ap_ip'])
        self.assertEqual(svc.state['network']['ip'], '192.168.1.48')
        svc.state['ap_active'] = True
        svc.tick(1, False)
        self.assertEqual(svc.state['network']['mode'], 'AP')
        self.assertEqual(svc.state['network']['ap_ip'], '192.168.4.1')

    def test_wifi_new_network_clears_previous_password_and_explicit_open_network(self):
        for ssid, extra in [('new', {}), ('home', {'clear_wifi_password': 'on'})]:
            svc = self.service()
            with patch('dashboard_service.save'):
                self.request(svc, '/api/config', dict(section='wifi', ssid=ssid, password='', **extra))
            self.assertEqual(svc.config['wifi']['password'], '')

    def test_invalid_clock_and_flash_failure_preserve_config(self):
        for form, error in [(dict(section='clock', timezone='Unknown'), None),
                             (dict(section='wifi', ssid='new'), OSError('full'))]:
            svc = self.service()
            previous = copy.deepcopy(svc.config)
            with patch('dashboard_service.save', side_effect=error):
                response, data = self.request(svc, '/api/config', form)
            self.assertFalse(response.startswith(b'HTTP/1.1 200'))
            self.assertEqual(svc.config, previous)
            self.assertNotIn('restart_requested', svc.state)

    def test_clock_save_applies_without_reboot_and_requests_sync(self):
        svc = self.service()
        with patch('dashboard_service.save'):
            response, data = self.request(svc, '/api/config', dict(section='clock', timezone='Europe/Rome', ntp_enabled='on', dst_auto='on', ntp_server='time.google.com', utc_offset_minutes='60', sync_interval_seconds='600'))
        self.assertTrue(response.startswith(b'HTTP/1.1 200'))
        self.assertFalse(data['restart'])
        self.assertEqual(svc.clock.settings['ntp_server'], 'time.google.com')
        self.assertTrue(svc.clock.force)

    def test_terminal_logs_are_bounded_unknown_commands_do_not_execute(self):
        svc = self.service()
        for i in range(200):
            svc.log('x'*2000)
        self.assertLessEqual(len(svc.lines), 60)
        self.assertLessEqual(sum(len(line) for line in svc.lines), 6000)
        self.assertLessEqual(len(svc.lines[-1]), 1000)
        response, _ = self.request(svc, '/api/terminal', dict(command="import os"))
        self.assertTrue(response.startswith(b'HTTP/1.1 400'))
        svc.command('clear')
        self.assertEqual(svc.lines, ['Registro pulito'])
        svc.command('serial 5')
        self.assertEqual(svc.monitor_interval, 5)

    def test_cross_origin_mutations_rejected(self):
        svc = self.service()
        with patch('dashboard_service.save') as save:
            response, _ = self.request(svc, '/api/config', dict(section='wifi', ssid='evil'), 'https://example.org')
        self.assertTrue(response.startswith(b'HTTP/1.1 400'))
        save.assert_not_called()

    def test_battery_console_preserves_real_rf_states_per_station(self):
        svc = self.service()
        svc.state['stations'] = {'a': dict(battery_ok=True, age_seconds=3),
                                 'b': dict(battery_ok=False, age_seconds=300), 'c': dict(battery_ok=None)}
        svc.command('battery')
        result = json.loads(svc.lines[-1])
        self.assertEqual(result['a']['status'], 'OK')
        self.assertEqual(result['b']['status'], 'LOW')
        self.assertEqual(result['b']['age_seconds'], 300)
        self.assertEqual(result['c']['status'], 'non disponibile')

    def test_scan_keeps_all_access_points_and_infers_hidden_empty_ssid(self):
        svc = self.service()
        svc.wlan.scan.return_value = [(b'home', bytes([0,1,2,3,4,i]), 6, -50-i, 3, False) for i in range(40)]
        svc.wlan.scan.return_value += [(b'', bytes([0,1,2,3,4,99]), 1, -80, 0, False)]
        svc._scan_worker()
        self.assertEqual(len(svc.networks), 41)
        hidden = [n for n in svc.networks if n['hidden']][0]
        self.assertEqual(hidden['bssid'], '00:01:02:03:04:63')
        self.assertEqual(hidden['security_code'], 0)

    def test_hidden_network_save_preserves_exact_ssid_and_open_network_is_explicit(self):
        svc = self.service()
        with patch('dashboard_service.save'):
            self.request(svc, '/api/config', dict(section='wifi', ssid=' hidden name ', password='secret123', network_hidden='on'))
        self.assertTrue(svc.config['wifi']['hidden'])
        self.assertEqual(svc.config['wifi']['ssid'], ' hidden name ')
        self.assertEqual(svc.config['wifi']['password'], 'secret123')

    def test_local_scan_worker_sorts_networks_and_decodes_unicode(self):
        svc = self.service()
        svc.wlan.scan.return_value = [(b'weak', b'', 1, -80, 0, False), ('caffè'.encode(), b'', 6, -40, 3, False)]
        svc._scan_worker()
        self.assertEqual(svc.networks[0]['ssid'], 'caffè')
        self.assertEqual(svc.networks[0]['security'], 'WPA2-PSK')
        self.assertFalse(svc.scanning)


class ClockTests(unittest.TestCase):
    def test_rome_exact_dst_boundaries_and_other_years(self):
        for year, march, october in [(2024, 31, 27), (2026, 29, 25), (2027, 28, 31)]:
            start, end = epoch(year, 3, march, 1), epoch(year, 10, october, 1)
            for timestamp, expected in [(start-1, (60, False)), (start, (120, True)), (end-1, (120, True)), (end, (60, False))]:
                self.assertEqual(offset_minutes(DEFAULT_CLOCK, timestamp), expected)

    def test_utc_manual_offset_and_dst_disabled(self):
        summer = epoch(2026, 7, 1)
        self.assertEqual(offset_minutes(dict(DEFAULT_CLOCK, timezone='UTC'), summer), (0, False))
        self.assertEqual(offset_minutes(dict(DEFAULT_CLOCK, timezone='Custom', utc_offset_minutes=330), summer), (330, False))
        self.assertEqual(offset_minutes(dict(DEFAULT_CLOCK, dst_auto=False), summer), (60, False))

    def test_sync_runs_in_background_retries_and_does_not_run_offline(self):
        clock = ClockService(dict(DEFAULT_CLOCK))
        worker = Mock()
        with patch.dict('sys.modules', {'_thread': types.SimpleNamespace(start_new_thread=worker)}), patch.object(wifi.time, 'ticks_diff', side_effect=lambda a,b: a-b, create=True):
            clock.tick(0, False)
            worker.assert_not_called()
            clock.tick(0, True)
            worker.assert_called_once()
            self.assertTrue(clock.busy)
            clock.tick(1000, True)
            worker.assert_called_once()
            with patch.dict('sys.modules', {'ntptime': types.SimpleNamespace(settime=Mock(side_effect=OSError('offline')))}):
                clock._sync()
            self.assertFalse(clock.busy)
            clock.tick(59000, True)
            worker.assert_called_once()
            clock.tick(60000, True)
            self.assertEqual(worker.call_count, 2)

    def test_clock_validation_rejects_malformed_hosts_and_intervals(self):
        for values in [dict(ntp_server='http://pool.ntp.org'), dict(sync_interval_seconds=1), dict(utc_offset_minutes=9999)]:
            with self.assertRaises(ValueError):
                validate_clock(dict(DEFAULT_CLOCK, **values))


if __name__ == '__main__':
    unittest.main()
