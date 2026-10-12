import importlib.util
import json
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


MODULES = pathlib.Path(__file__).resolve().parents[1] / "modules"
sys.path.insert(0, str(MODULES))
spec = importlib.util.spec_from_file_location("ap_wifi_manager", MODULES / "wifi_manager.py")
wifi = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "network": types.SimpleNamespace(WLAN=lambda _: None),
    "select": types.SimpleNamespace(POLLIN=1, POLLOUT=4, POLLERR=8,
                                   POLLHUP=16, poll=lambda: None),
}):
    spec.loader.exec_module(wifi)


def question(record_type=1):
    return (b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
            b"\x07example\x03com\x00" + record_type.to_bytes(2, "big") + b"\x00\x01")


class APPortalTests(unittest.TestCase):
    def test_dns_resolves_arbitrary_domain_to_ap(self):
        request = question()
        response = wifi._dns_reply(request)
        self.assertEqual(response[:2], request[:2])
        self.assertEqual(response[6:8], b"\x00\x01")
        self.assertEqual(response[12:12 + len(request) - 12], request[12:])
        self.assertEqual(response[-4:], b"\xc0\xa8\x04\x01")

    def test_dns_ipv6_does_not_return_an_ipv4_record(self):
        response = wifi._dns_reply(question(28))
        self.assertEqual(response[6:8], b"\x00\x00")
        self.assertEqual(len(response), len(question(28)))

    def test_dns_ignores_truncated_or_compressed_queries(self):
        self.assertIsNone(wifi._dns_reply(question()[:18]))
        self.assertIsNone(wifi._dns_reply(question()[:12] + b"\xc0\x0c\x00\x01\x00\x01"))
        self.assertIsNone(wifi._dns_reply(b""))

    def test_captive_probes_redirect_to_local_dashboard(self):
        for path in (b"/generate_204", b"/hotspot-detect.html", b"/connecttest.txt"):
            response = wifi._ap_response(b"GET " + path + b" HTTP/1.1\r\n\r\n", {})
            self.assertTrue(response.startswith(b"HTTP/1.1 302"))
            self.assertIn(b"Location: http://192.168.4.1/", response)

    def test_api_returns_json_and_correct_content_length(self):
        state = {"sensors": {"temperature": 21.5}, "age_seconds": 3, "received": 1}
        response = wifi._ap_response(b"GET /api/readings HTTP/1.1\r\n\r\n", state)
        header, body = response.split(b"\r\n\r\n", 1)
        self.assertEqual(json.loads(body), state)
        self.assertIn(b"Content-Type: application/json", header)
        self.assertIn(("Content-Length: %d" % len(body)).encode(), header)

    def test_dashboard_available_without_provisioning(self):
        response = wifi._ap_response(b"GET / HTTP/1.1\r\n\r\n", {})
        self.assertTrue(response.startswith(b"HTTP/1.1 200"))
        self.assertIn(b"/api/readings", response)
        self.assertIn(b"km/h", response)

    def test_ap_does_not_accept_configuration_posts(self):
        response = wifi._ap_response(b"POST /save HTTP/1.1\r\n\r\n", {})
        self.assertTrue(response.startswith(b"HTTP/1.1 405"))

    def test_radio_dns_and_http_are_served_in_the_same_loop(self):
        server, dns, client = Mock(), Mock(), Mock()
        station, ap = Mock(), Mock()
        server.accept.return_value = (client, ("192.168.4.2", 1234))
        dns.recvfrom.return_value = (question(), ("192.168.4.2", 5678))
        client.recv.return_value = b"GET /api/readings HTTP/1.1\r\n\r\n"
        client.send.side_effect = lambda data: len(data)
        poller = Mock()
        poller.poll.side_effect = [
            [(dns, wifi.select.POLLIN), (server, wifi.select.POLLIN)],
            [(client, wifi.select.POLLIN)], [(client, wifi.select.POLLOUT)],
        ]
        radio = Mock()
        radio.poll.side_effect = [
            {"temperature": 22, "wind_speed": 2, "sensor_id": 7},
            None, None, KeyboardInterrupt(),
        ]
        with patch.object(wifi.network, "WLAN", side_effect=[station, ap]), \
             patch.object(wifi.socket, "socket", side_effect=[server, dns]), \
             patch.object(wifi.select, "poll", return_value=poller), \
             patch.object(wifi.time, "ticks_ms", return_value=100, create=True), \
             patch.object(wifi.time, "ticks_diff", side_effect=lambda a, b: a - b, create=True), \
             patch("builtins.print") as output:
            with self.assertRaises(KeyboardInterrupt):
                wifi.run_ap({"runtime": {}}, radio)
        self.assertEqual(radio.poll.call_count, 4)
        self.assertEqual(dns.sendto.call_args.args[0][-4:], b"\xc0\xa8\x04\x01")
        response = client.send.call_args.args[0]
        data = json.loads(response.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(data["sensors"]["wind_speed"], 7.2)
        self.assertEqual(data["received"], 1)
        self.assertTrue(any(call.args[0] == "Ricevuto:" for call in output.call_args_list))
        client.close.assert_called_once()
        server.close.assert_called_once()
        dns.close.assert_called_once()
        ap.active.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
