import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))
sys.path.insert(0, str(ROOT / "external" / "AMMSUtils"))

import activation_service
import config_store


def claimed_document():
    return {
        "schema": 1,
        "status": "claimed",
        "client_type": "bsg-esp32",
        "identity": {
            "algorithm": "hmac-sha256",
            "station_id": "bsg-server",
            "key_id": "key-server",
            "secret_hex": "11" * 32,
        },
        "api": {
            "data_url": "https://151.242.0.96/api/data/point",
            "update_base_url": "https://151.242.0.96",
        },
        "mqtt": {
            "host": "151.242.0.96", "port": 8883, "topic": "amms/v1/stations/bsg-server/telemetry",
            "qos": 1, "ca_url": "https://151.242.0.96/api/mqtt/ca.crt",
        },
    }


class ActivationServiceTests(unittest.TestCase):
    def config(self):
        value = config_store._copy_defaults()
        value["wifi"].update(ssid="home", password="secret")
        return value

    def test_lost_confirmation_is_resumed_without_reclaiming(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = str(pathlib.Path(directory) / "activation.json")
            config, state = self.config(), {}
            calls = []

            def first_transport(url, payload, headers, timeout):
                calls.append(url)
                if url.endswith("/confirm"):
                    return 503, json.dumps({"detail": "offline"})
                return 200, json.dumps(claimed_document())

            service = activation_service.ActivationService(
                config, Mock(isconnected=Mock(return_value=True)), state,
                state_path=state_path, http_post=first_transport,
                http_get=lambda *args: (200, "-----BEGIN CERTIFICATE-----\nCA\n-----END CERTIFICATE-----"),
                sleep=Mock(side_effect=RuntimeError("stop test")),
                thread_start=lambda *args: None,
            )
            with patch.object(service, "_write_ca", return_value="/mqtt-ca-test.crt"), \
                    patch.object(activation_service, "save"):
                service.queue("AMMS-ABCD-2345-EFGH-6723-JKMN")
                # Il thread e' simulato esplicitamente per controllare la perdita di risposta.
                service.busy = True
                with self.assertRaises(RuntimeError):
                    service._worker()
            pending = json.loads(pathlib.Path(state_path).read_text())
            self.assertEqual(pending["document"]["identity"]["station_id"], "bsg-server")
            self.assertEqual(config["amms"]["station_id"], "")

            second_calls = []

            def second_transport(url, payload, headers, timeout):
                second_calls.append(url)
                return 200, json.dumps({"schema": 1, "status": "active"})

            resumed = activation_service.ActivationService(
                config, Mock(isconnected=Mock(return_value=True)), state,
                state_path=state_path, http_post=second_transport,
                http_get=Mock(side_effect=AssertionError("CA gia' persistita")),
            )
            with patch.object(activation_service, "save"):
                resumed.busy = True
                resumed._worker()
            self.assertFalse(pathlib.Path(state_path).exists())
            self.assertEqual(config["amms"]["station_id"], "bsg-server")
            self.assertEqual(len(second_calls), 1)
            self.assertTrue(second_calls[0].endswith("/confirm"))
            self.assertIn("restart_requested", state)

    def test_invalid_ca_preserves_previous_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            config, state = self.config(), {}
            previous = json.loads(json.dumps(config))
            service = activation_service.ActivationService(
                config, Mock(isconnected=Mock(return_value=True)), state,
                state_path=str(pathlib.Path(directory) / "activation.json"),
                http_post=lambda *args: (200, json.dumps(claimed_document())),
                http_get=lambda *args: (200, "not a certificate"),
                sleep=Mock(side_effect=RuntimeError("stop test")),
                thread_start=lambda *args: None,
            )
            service.queue("AMMS-ABCD-2345-EFGH-6723-JKMN")
            service.busy = True
            with self.assertRaises(RuntimeError):
                service._worker()
            self.assertEqual(config, previous)


if __name__ == "__main__":
    unittest.main()
