"""Vettori RF di SensorTransmitter (MIT) e regressioni autoriconoscimento."""
import pathlib
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "modules"))
import bresser_protocols as bp

V6 = bytes.fromhex("2aaf2110342718ffaaff2928ffbb89ff011f")
V7 = bytes.fromhex("c4d63ac5bdfa18aaaaaaaaabfcaa98da89a32fecaf9aaaaaaaaa00")


def seal6(data):
    data = bytearray(data)
    digest = bp._digest(data[2:17], 0x5412)
    data[:2] = digest.to_bytes(2, "big")
    data[17] = (255 - sum(data[2:17])) & 255
    return bytes(data)


def variant7(kind, battery=False):
    data = bytearray(x ^ 0xAA for x in V7[:25])
    data[6] = ((kind << 4) | 8) ^ 0xAA
    if battery:
        data[15] |= 6
    digest = bp._digest(data[2:25], 0xBA95) ^ 0x6DF1
    data[:2] = digest.to_bytes(2, "big")
    return bytes(x ^ 0xAA for x in data)


class ProtocolTests(unittest.TestCase):
    def test_captured_station_frames_from_esp32_rfm95_with_user_pinout(self):
        # Ricevuti nel test su COM3: due messaggi alternati dello stesso sensore.
        temperature = bp.decode_6in1(bytes.fromhex("62ef311440a318fefffe1388168057fff04daa00000000000000"))
        rain = bp.decode_6in1(bytes.fromhex("a0f9311440a318ff77ff1388ff99a9ff016eaa00000000000000"))
        self.assertEqual(temperature["sensor_id"], rain["sensor_id"])
        self.assertEqual(temperature["sensor_id"], 0x311440A3)
        self.assertAlmostEqual(temperature["temperature"], 16.8)
        self.assertEqual(temperature["humidity"], 57)
        self.assertAlmostEqual(rain["precipitation"], 665.6)
    def test_reference_6in1_rain_frame(self):
        value = bp.decode_6in1(V6)
        self.assertEqual(value["sensor_id"], 0x21103427)
        self.assertEqual(value["wind_direction"], 292)
        self.assertAlmostEqual(value["precipitation"], 447.6)
        self.assertIsNone(value["temperature"])

    def test_reference_7in1_frame(self):
        value = bp.decode_7in1(V7)
        self.assertEqual(value["sensor_id"], 0x906F)
        self.assertAlmostEqual(value["temperature"], 32.7)
        self.assertEqual(value["humidity"], 23)
        self.assertAlmostEqual(value["precipitation"], 15.6)
        self.assertAlmostEqual(value["uv_index"], 5.3)
        self.assertEqual(value["light_lux"], 98546)

    def test_checksum_rejects_every_single_byte_corruption(self):
        for payload, decode, length in ((V6, bp.decode_6in1, 18), (V7, bp.decode_7in1, 25)):
            for i in range(length):
                altered = bytearray(payload)
                altered[i] ^= 1
                with self.subTest(protocol=decode.__name__, byte=i), self.assertRaises(ValueError):
                    decode(altered)

    def test_7in1_weather_variants_and_battery(self):
        for kind in (1, 12, 13):
            value = bp.decode_7in1(variant7(kind, True))
            self.assertEqual(value["sensor_type"], kind)
            self.assertFalse(value["battery_ok"])
            self.assertIsNone(value["wind_speed"]) if kind == 12 else self.assertEqual(value["wind_speed"], 0)
        with self.assertRaisesRegex(ValueError, "non supportata"):
            bp.decode_7in1(variant7(15))

    def test_6in1_indoor_pool_and_soil_do_not_invent_wind(self):
        for kind in (2, 3, 4):
            data = bytearray(V6)
            data[6] = (kind << 4) | 8
            data[12:17] = bytes.fromhex("234250ff00")
            value = bp.decode_6in1(seal6(data))
            self.assertAlmostEqual(value["temperature"], 23.4)
            self.assertIsNone(value["wind_speed"])
            self.assertIsNone(value["humidity"]) if kind in (3, 4) else self.assertEqual(value["humidity"], 50)

    def test_6in1_alternated_fields_merge_without_crossing_station_ids_or_expiry(self):
        temp = bytearray(V6)
        temp[12:17] = bytes.fromhex("234250ff00")
        other = bytearray(temp)
        other[5] ^= 1
        native = Mock()
        native.decode.side_effect = ValueError("not 5-in-1")
        native.poll_raw.side_effect = [dict(raw=seal6(temp)), dict(raw=V6), dict(raw=seal6(other)), dict(raw=V6), dict(raw=V6)]
        rx = bp.AutoReceiver(native)
        with patch.object(bp.time, "ticks_ms", side_effect=[0, 20000, 40000, 100000, 130000], create=True), patch.object(bp.time, "ticks_diff", side_effect=lambda a, b: a - b, create=True):
            rx.poll()
            combined = rx.poll()
            self.assertAlmostEqual(combined["temperature"], 23.4)
            self.assertAlmostEqual(combined["precipitation"], 447.6)
            self.assertIsNone(rx.poll()["precipitation"])
            self.assertAlmostEqual(rx.poll()["temperature"], 23.4)
            self.assertIsNone(rx.poll()["temperature"])

    def test_native_5in1_decoder_is_retained_and_unknown_frame_reports_error(self):
        native = Mock()
        native.decode.return_value = dict(protocol="bresser_5in1", sensor_id=3, sensor_type=0, temperature=12)
        native.poll_raw.return_value = dict(raw=bytes(26), rssi=-80)
        rx = bp.AutoReceiver(native)
        with patch.object(bp.time, "ticks_ms", return_value=0, create=True):
            self.assertEqual(rx.poll()["model"], "Bresser 5-in-1")
        native.decode.side_effect = ValueError("invalid 5-in-1")
        self.assertIn("non riconosciuto", rx.poll()["error"])
        native.poll_raw.return_value = dict(raw=bytes(26), sync_ok=False)
        self.assertIn("sincronismo", rx.poll()["error"])

    def test_old_native_image_cannot_silently_claim_multi_protocol_support(self):
        with self.assertRaisesRegex(RuntimeError, "flashare"):
            bp.AutoReceiver(object())


if __name__ == "__main__":
    unittest.main()
