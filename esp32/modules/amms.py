from secure_http import post_json


class AMMSClient:
    def __init__(self, token, url, timeout_seconds=15):
        if not token:
            raise ValueError("Token AMMS mancante")
        self.token = token
        self.url = url
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def payload_from_reading(reading):
        sensors = {}

        mappings = (
            ("temperature", "temperature"),
            ("humidity", "humidity"),
            ("wind_speed", "wind_speed"),
            ("wind_direction", "wind_direction"),
            ("precipitation", "precipitation"),
        )
        for source, destination in mappings:
            value = reading.get(source)
            if value is not None:
                sensors[destination] = value

        # Mantiene lo stesso schema prodotto dalla libreria C++ originale.
        # ID, batteria e RSSI restano disponibili nel log locale ma non vengono
        # aggiunti all'API finche' il contratto del server non li prevede.
        return {"sensors": sensors, "station": {}}

    def send(self, reading):
        response = post_json(
            self.url,
            self.payload_from_reading(reading),
            headers={"Authorization": "Bearer " + self.token},
            timeout=self.timeout_seconds,
        )
        if response.status < 200 or response.status >= 300:
            raise OSError("AMMS HTTP %d: %s" % (response.status, response.text))
        return response
