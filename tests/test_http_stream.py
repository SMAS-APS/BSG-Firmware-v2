import io
import gzip
import json
import unittest
from unittest.mock import Mock, patch

from test_ap_portal import wifi
import config_store
import dashboard
from tools.build_web_assets import build_assets, ROOT
from dashboard_service import DashboardService


class HTTPStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build_assets(ROOT)

    def test_dashboard_is_sent_in_small_chunks_without_rendering_full_page(self):
        config = config_store._copy_defaults()
        config['wifi'].update(ssid='Casa <&>', password='secret-never-rendered')
        response = wifi._ap_response(b'GET / HTTP/1.1\r\n\r\n', {}, config, stream=True)
        received = []

        def send(data):
            count = min(len(data), 37)  # Simulate short writes on the ESP32.
            received.append(bytes(data[:count]))
            return count

        client = Mock()
        client.send.side_effect = send
        with patch.object(wifi, '_dashboard', side_effect=AssertionError('full page allocated')):
            while not response.send(client):
                pass
        raw = b''.join(received)
        header, body = raw.split(b'\r\n\r\n', 1)
        self.assertIn(b'Connection: close', header)
        self.assertIn(('Content-Length: %d' % len(body)).encode(), header)
        self.assertEqual(body, (ROOT / '.pio/web/dashboard.static.html').read_bytes())
        self.assertNotIn(b'Casa &lt;&amp;&gt;', body)
        self.assertNotIn(b'secret-never-rendered', body)
        self.assertTrue(all(len(call.args[0]) <= 512 for call in client.send.call_args_list))

    def drain(self, response):
        chunks = []
        client = Mock()
        client.send.side_effect = lambda data: chunks.append(bytes(data)) or len(data)
        while not response.send(client):
            pass
        return b''.join(chunks)

    def test_gzip_shell_has_matching_length_and_supports_conditional_cache(self):
        raw = self.drain(wifi._ap_response(b'GET / HTTP/1.1\r\nAccept-Encoding: gzip\r\n\r\n', {}, stream=True))
        header, body = raw.split(b'\r\n\r\n', 1)
        self.assertIn(b'Content-Encoding: gzip', header)
        self.assertEqual(gzip.decompress(body), (ROOT / '.pio/web/dashboard.static.html').read_bytes())
        self.assertLess(len(body), len(gzip.decompress(body)) // 2)
        etag = next(line.split(b': ', 1)[1] for line in header.split(b'\r\n') if line.startswith(b'ETag:'))
        cached = self.drain(wifi._ap_response(b'GET / HTTP/1.1\r\nIf-None-Match: '+etag+b'\r\n\r\n', {}, stream=True))
        self.assertTrue(cached.startswith(b'HTTP/1.1 304'))
        self.assertEqual(cached.split(b'\r\n\r\n', 1)[1], b'')

    def test_streamed_json_avoids_serializing_whole_response(self):
        state = {'stations': {str(i): {'temperature': i, 'battery_ok': False} for i in range(8)},
                 'lines': ['Unicode città ' + 'x' * 900 for _ in range(12)], 'empty': None}
        original = wifi.json.dumps

        def guarded(value):
            self.assertNotIsInstance(value, (dict, list))
            return original(value)

        with patch.object(wifi.json, 'dumps', side_effect=guarded):
            raw = self.drain(wifi._ap_response(b'GET /api/readings HTTP/1.1\r\n\r\n', state, stream=True))
        self.assertEqual(json.loads(raw.split(b'\r\n\r\n', 1)[1]), state)

    def test_settings_fill_fields_without_returning_credentials(self):
        config = config_store._copy_defaults()
        config['wifi'].update(ssid='Casa <&>', password='secret-wifi')
        config['amms'].update(secret_hex='secret-hmac', token='secret-token')
        config['weather_underground'].update(station_key='secret-wu')
        service = DashboardService(config, Mock(), {})
        raw = self.drain(wifi._ap_response(b'GET /api/settings HTTP/1.1\r\n\r\n', {}, config, service, stream=True))
        settings = json.loads(raw.split(b'\r\n\r\n', 1)[1])
        self.assertEqual(settings['wifi']['ssid'], 'Casa <&>')
        self.assertTrue(settings['wifi']['has_password'])
        for secret in ('secret-wifi', 'secret-hmac', 'secret-token', 'secret-wu'):
            self.assertNotIn(secret.encode(), raw)

    def test_placeholders_crossing_flash_blocks_are_replaced(self):
        for position in range(490, 530):
            source = io.BytesIO(b'x' * position + b'__SSID__' + ' citta\u00e0'.encode())
            with patch.object(dashboard, '_open_template', return_value=source), \
                 patch.object(dashboard, '_values', return_value={'__SSID__': '<&>'}):
                parts = list(dashboard.iter_render({}, '', str))
            self.assertEqual(b''.join(parts), b'x' * position + b'<&>' + ' citta\u00e0'.encode())
            self.assertTrue(all(len(part) <= 512 for part in parts))
            self.assertTrue(source.closed)

    def test_would_block_keeps_pending_bytes_and_disconnect_closes_source(self):
        source = Mock()
        source.__iter__ = Mock(return_value=source)
        source.__next__ = Mock(side_effect=[b'abcdef', StopIteration])
        response = wifi._HTTPStream(source)
        client = Mock()
        client.send.side_effect = [OSError(11, 'would block'), 2, 4]
        with self.assertRaises(OSError):
            response.send(client)
        self.assertFalse(response.send(client))
        self.assertFalse(response.send(client))
        self.assertTrue(response.send(client))
        self.assertEqual([bytes(call.args[0]) for call in client.send.call_args_list],
                         [b'abcdef', b'abcdef', b'cdef'])
        response.close()
        source.close.assert_called_once()
