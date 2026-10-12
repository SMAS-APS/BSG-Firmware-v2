"""Autoriconoscimento Bresser FSK; il decoder nativo 5-in-1 resta invariato.

6/7-in-1: adattamento dei formati di WeatherSensorDecoders.cpp di
matthias-bs/BresserWeatherSensorReceiver (MIT, vedi BRESSER-NOTICES.md).
Un nome indica la famiglia radio, non il codice commerciale della console.
"""
import time


FIELDS = ("temperature", "humidity", "wind_speed", "wind_gust",
          "wind_direction", "precipitation", "uv_index", "light_lux",
          "globe_temperature", "soil_moisture", "pm1", "pm2_5", "pm10",
          "co2_ppm", "hcho_ppb", "voc_level")
TYPES6 = {1: "Bresser 6-in-1 / 3-in-1 anemometro",
          2: "Bresser termoigrometro", 3: "Bresser termometro piscina",
          4: "Bresser temperatura/umidita suolo"}
TYPES7 = {1: "Bresser 7-in-1", 12: "Bresser 3-in-1 temperatura/umidita/pioggia",
          13: "Bresser 8-in-1", 8: "Bresser qualita aria PM",
          10: "Bresser CO2", 11: "Bresser HCHO/VOC"}


def _digest(data, key):
    value = 0
    for byte in data:
        for bit in range(7, -1, -1):
            if byte & (1 << bit):
                value ^= key
            key = (key >> 1) ^ (0x8810 if key & 1 else 0)
    return value


def _bcd(digits):
    value = 0
    for digit in digits:
        if digit > 9:
            return None
        value = value * 10 + digit
    return value


def _digits(data):
    for byte in data:
        yield byte >> 4
        yield byte & 15


def _scale(value, factor):
    return None if value is None else value * factor


def _base(protocol, sensor_id, sensor_type, channel, startup, battery):
    value = dict((key, None) for key in FIELDS)
    value.update(protocol=protocol, sensor_id=sensor_id, sensor_type=sensor_type,
                 channel=channel, startup=startup, battery_ok=bool(battery))
    return value


def decode_6in1(msg):
    if len(msg) < 18 or ((msg[0] << 8) | msg[1]) != _digest(msg[2:17], 0x5412):
        raise ValueError("digest 6-in-1 non valido")
    if sum(msg[2:18]) & 255 != 255:
        raise ValueError("checksum 6-in-1 non valido")
    kind, flags = msg[6] >> 4, msg[16] & 15
    if kind not in TYPES6 or flags not in (0, 1):
        raise ValueError("variante 6-in-1 non supportata: tipo=%d flags=%d" % (kind, flags))
    value = _base("bresser_6in1", int.from_bytes(msg[2:6], "big"), kind,
                  msg[6] & 7, not bool(msg[6] & 8), msg[13] & 2)
    value["model"] = TYPES6[kind]
    if flags == 0:
        raw = _bcd((msg[12] >> 4, msg[12] & 15, msg[13] >> 4))
        if raw is not None:
            temp = (raw - 1000 if msg[13] & 8 else raw) * 0.1
            value["temperature"] = -raw * 0.1 if temp < -50 else temp
        humidity = _bcd(_digits(msg[14:15]))
        if kind == 4:
            moisture = (0, 7, 13, 20, 27, 33, 40, 47, 53, 60, 67, 73, 80, 87, 93, 99)
            if humidity is not None and 1 <= humidity <= 16:
                value["soil_moisture"] = moisture[humidity - 1]
        elif kind != 3:
            value["humidity"] = humidity
        if kind == 1:
            value["uv_index"] = _scale(_bcd(((msg[15] ^ 255) >> 4,
                (msg[15] ^ 255) & 15, (msg[16] ^ 255) >> 4)), 0.1)
    if kind == 1:
        a, b, c = (msg[i] ^ 255 for i in (7, 8, 9))
        value["wind_gust"] = _scale(_bcd((a >> 4, a & 15, b >> 4)), 0.1)
        value["wind_speed"] = _scale(_bcd((c >> 4, c & 15, b & 15)), 0.1)
        value["wind_direction"] = _bcd((msg[10] >> 4, msg[10] & 15, msg[11] >> 4))
        if flags == 1:
            value["precipitation"] = _scale(_bcd(_digits(bytes(x ^ 255 for x in msg[12:15]))), 0.1)
    return value


def decode_7in1(msg):
    if len(msg) < 25:
        raise ValueError("payload 7-in-1 incompleto")
    data = bytes(x ^ 0xAA for x in msg[:25])
    if (((data[0] << 8) | data[1]) ^ _digest(data[2:25], 0xBA95)) != 0x6DF1:
        raise ValueError("digest 7-in-1 non valido")
    kind = msg[6] >> 4
    if kind not in TYPES7:
        raise ValueError("variante 7-in-1 non supportata: tipo=%d" % kind)
    value = _base("bresser_7in1", (data[2] << 8) | data[3], kind,
                  msg[6] & 7, not bool(msg[6] & 8), (data[15] & 6) != 6)
    value["model"] = TYPES7[kind]
    if kind in (1, 12, 13):
        raw = _bcd((data[14] >> 4, data[14] & 15, data[15] >> 4))
        if raw is not None:
            value["temperature"] = (raw - 1000 if raw > 600 else raw) * 0.1
        value["humidity"] = _bcd(_digits(data[16:17]))
        value["precipitation"] = _scale(_bcd(_digits(data[10:13])), 0.1)
        if kind != 12:
            value["wind_direction"] = _bcd((data[4] >> 4, data[4] & 15, data[5] >> 4))
            value["wind_gust"] = _scale(_bcd((data[7] >> 4, data[7] & 15, data[8] >> 4)), 0.1)
            value["wind_speed"] = _scale(_bcd((data[8] & 15, data[9] >> 4, data[9] & 15)), 0.1)
            value["light_lux"] = _bcd(_digits(data[17:20]))
            value["uv_index"] = _scale(_bcd((data[20] >> 4, data[20] & 15, data[21] >> 4)), 0.1)
        if kind == 13:
            value["globe_temperature"] = _scale(_bcd((data[22] >> 4, data[22] & 15, data[23] >> 4)), 0.1)
    elif kind == 8:
        for name, a, b, c in (("pm1", 8, 9, 10), ("pm2_5", 10, 11, 12), ("pm10", 12, 13, 14)):
            value[name] = _bcd((data[a] & 15, data[b] >> 4, data[b] & 15, data[c] >> 4))
    else:
        value["co2_ppm" if kind == 10 else "hcho_ppb"] = _bcd(_digits(data[4:6]))
        if kind == 11 and data[22] != 15:
            value["voc_level"] = data[22] & 15
    return value


class AutoReceiver:
    """Eventi validi/errore; unisce i messaggi alternati solo per lo stesso ID."""
    def __init__(self, native):
        self.native = native
        self.cache = {}
        self.poll_raw = getattr(native, "poll_raw", None)
        if self.poll_raw is None:
            raise RuntimeError("Ricompilare e flashare l'immagine BSG: manca poll_raw per 6/7-in-1")

    def poll(self):
        frame = self.poll_raw()
        if frame is None:
            return None
        raw = frame["raw"]
        if not frame.get("sync_ok", True):
            return {"error": "sincronismo RF non riconosciuto", "rssi": frame.get("rssi")}
        errors = []
        reading = None
        for decoder in (self.native.decode, decode_7in1, decode_6in1):
            try:
                reading = decoder(raw)
                break
            except ValueError as exc:
                errors.append(str(exc))
        if reading is None:
            return {"error": "pacchetto non riconosciuto o corrotto: " + "; ".join(errors),
                    "rssi": frame.get("rssi"), "raw_hex": "".join("%02x" % x for x in raw)}
        if reading["protocol"] == "bresser_5in1":
            kind = reading["sensor_type"]
            rain_only = 0x39 <= kind <= 0x3B
            reading["model"] = "Bresser pluviometro professionale" if rain_only else "Bresser 5-in-1"
            reading["channel"] = 0
            if rain_only:
                for key in ("humidity", "wind_speed", "wind_gust", "wind_direction"):
                    reading[key] = None
        reading.pop("raw", None)
        reading["rssi"] = frame.get("rssi")
        now = time.ticks_ms()
        key = (reading["protocol"], reading["sensor_id"], reading["channel"])
        previous = self.cache.get(key)
        field_times = {}
        # Evita di trascinare campi di pacchetti precedenti dopo reset o 120 s.
        if previous and not reading.get("startup") and time.ticks_diff(now, previous[0]) <= 120000:
            for name in FIELDS:
                if reading.get(name) is None and previous[1].get(name) is not None and time.ticks_diff(now, previous[2].get(name, previous[0])) <= 120000:
                    reading[name] = previous[1][name]
                    field_times[name] = previous[2].get(name, previous[0])
        for name in FIELDS:
            if reading.get(name) is not None and name not in field_times:
                field_times[name] = now
        if key not in self.cache and len(self.cache) >= 8:
            oldest = max(self.cache, key=lambda k: time.ticks_diff(now, self.cache[k][0]))
            del self.cache[oldest]
        self.cache[key] = (now, reading.copy(), field_times)
        return reading
