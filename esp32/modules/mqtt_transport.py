"""Trasporto MQTT/TLS minimale per MicroPython."""

import json
import ssl
import time

from amms import status_topic
from umqtt.simple import MQTTClient


class MicroPythonMQTTPublisher:
    def __init__(
        self,
        station_id,
        password,
        host,
        port=8883,
        ca_cert="/mqtt-ca.crt",
        keepalive=45,
    ):
        self.station_id = station_id
        self.password = password
        self.host = host
        self.port = int(port)
        self.ca_cert = ca_cert
        self.keepalive = int(keepalive)
        self._status_topic = status_topic(station_id).encode("utf-8")
        self._client = None
        self._connect()

    @staticmethod
    def _status(online):
        try:
            value = json.dumps({"online": bool(online), "ts": int(time.time())}, separators=(",", ":"))
        except TypeError:
            value = json.dumps({"online": bool(online), "ts": int(time.time())})
        return value.encode("utf-8")

    def _tls_context(self):
        with open(self.ca_cert, "rb") as stream:
            ca_data = stream.read()
        if b"-----BEGIN CERTIFICATE-----" not in ca_data:
            raise ValueError("CA MQTT non valida")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cadata=ca_data)
        try:
            context.check_hostname = True
        except AttributeError:
            pass
        return context

    def _new_client(self):
        client = MQTTClient(
            client_id=self.station_id.encode("utf-8"),
            server=self.host,
            port=self.port,
            user=self.station_id.encode("utf-8"),
            password=self.password.encode("utf-8"),
            keepalive=self.keepalive,
            ssl=self._tls_context(),
        )
        client.set_last_will(
            self._status_topic,
            self._status(False),
            retain=True,
            qos=1,
        )
        return client

    def _connect(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
        self._client = self._new_client()
        self._client.connect()
        self._client.publish(self._status_topic, self._status(True), retain=True, qos=1)

    def publish(self, topic, body, qos=1, retain=False):
        encoded_topic = topic.encode("utf-8") if isinstance(topic, str) else topic
        try:
            self._client.publish(encoded_topic, body, retain=retain, qos=qos)
        except OSError:
            self._connect()
            self._client.publish(encoded_topic, body, retain=retain, qos=qos)

    def close(self):
        if self._client is None:
            return
        try:
            self._client.publish(self._status_topic, self._status(False), retain=True, qos=1)
            self._client.disconnect()
        finally:
            self._client = None
