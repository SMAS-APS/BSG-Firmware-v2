"""Trasporto MQTT/TLS per Raspberry Pi OS."""

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

from amms import status_topic


class RaspberryMQTTPublisher:
    """Publisher sincrono QoS 1 con TLS e credenziali per stazione."""

    def __init__(
        self,
        station_id,
        password,
        host,
        port=8883,
        ca_cert="/etc/bsg-gateway/mqtt-ca.crt",
        keepalive=45,
        connect_timeout=20,
    ):
        self.station_id = station_id
        self.status_topic = status_topic(station_id)
        self._connected = threading.Event()
        self._last_error = None
        self._closed = False
        try:
            self._client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=station_id,
                protocol=mqtt.MQTTv5,
            )
        except AttributeError:  # paho-mqtt 1.x su Raspberry Pi OS meno recente.
            self._client = mqtt.Client(client_id=station_id, protocol=mqtt.MQTTv311)
        self._client.username_pw_set(station_id, password)
        self._client.tls_set(ca_certs=ca_cert)
        self._client.will_set(
            self.status_topic,
            payload=self._status(False),
            qos=1,
            retain=True,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.connect_async(host, int(port), int(keepalive))
        self._client.loop_start()
        if not self._connected.wait(float(connect_timeout)):
            self.close(graceful=False)
            detail = ": %s" % self._last_error if self._last_error else ""
            raise OSError("timeout connessione MQTT/TLS%s" % detail)
        self.publish(self.status_topic, self._status(True), qos=1, retain=True)

    @staticmethod
    def _status(online):
        return json.dumps(
            {"online": bool(online), "ts": int(time.time())},
            separators=(",", ":"),
        ).encode("utf-8")

    def _on_connect(self, _client, _userdata, _flags, reason_code, *_args):
        if getattr(reason_code, "value", reason_code) == 0:
            self._last_error = None
            self._connected.set()
        else:
            self._last_error = reason_code
            self._connected.clear()

    def _on_disconnect(self, _client, _userdata, *args):
        self._connected.clear()
        if args:
            self._last_error = args[-1]

    def publish(self, topic, body, qos=1, retain=False):
        if self._closed:
            raise OSError("client MQTT chiuso")
        if not self._connected.wait(10):
            raise OSError("broker MQTT non connesso")
        info = self._client.publish(topic, body, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise OSError("pubblicazione MQTT rifiutata: %s" % info.rc)
        self._wait_published(info, 20)
        logging.debug("MQTT QoS %s pubblicato su %s", qos, topic)

    @staticmethod
    def _wait_published(info, timeout):
        deadline = time.monotonic() + timeout
        while not info.is_published():
            if time.monotonic() >= deadline:
                raise OSError("timeout conferma MQTT QoS 1")
            time.sleep(0.05)

    def close(self, graceful=True):
        if self._closed:
            return
        if graceful and self._connected.is_set():
            try:
                info = self._client.publish(
                    self.status_topic,
                    self._status(False),
                    qos=1,
                    retain=True,
                )
                self._wait_published(info, 5)
            except Exception:
                pass
        self._closed = True
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
