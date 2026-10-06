import pathlib
import sys
import unittest


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import bresser_native


NORMAL_PAYLOAD = bytes(
    (
        0xEE, 0x93, 0x7F, 0xF7, 0xBF, 0xFB, 0xEF, 0x9E, 0xFE,
        0xAE, 0xBF, 0xFF, 0xFF, 0x11, 0x6C, 0x80, 0x08, 0x40,
        0x04, 0x10, 0x61, 0x01, 0x51, 0x40, 0x00, 0x00,
    )
)

NEGATIVE_TEMPERATURE_PAYLOAD = bytes(
    (
        0xED, 0xA1, 0xFF, 0xFF, 0x1F, 0xFF, 0xEF, 0x8F, 0xFF,
        0xD6, 0xDF, 0xFF, 0x77, 0x12, 0x5E, 0x00, 0x00, 0xE0,
        0x00, 0x10, 0x70, 0x00, 0x29, 0x20, 0x00, 0x88,
    )
)


class DecoderTests(unittest.TestCase):
    def test_normal_payload(self):
        reading = bresser_native.decode(NORMAL_PAYLOAD)
        self.assertEqual(reading["sensor_id"], 0x6C)
        self.assertEqual(reading["sensor_type"], 0)
        self.assertFalse(reading["startup"])
        self.assertTrue(reading["battery_ok"])
        self.assertAlmostEqual(reading["temperature"], 16.1)
        self.assertEqual(reading["humidity"], 51)
        self.assertAlmostEqual(reading["wind_gust"], 0.8)
        self.assertAlmostEqual(reading["wind_speed"], 0.4)
        self.assertAlmostEqual(reading["wind_direction"], 90.0)
        self.assertAlmostEqual(reading["precipitation"], 4.0)

    def test_negative_temperature_and_low_battery(self):
        reading = bresser_native.decode(NEGATIVE_TEMPERATURE_PAYLOAD)
        self.assertAlmostEqual(reading["temperature"], -7.0)
        self.assertFalse(reading["battery_ok"])
        self.assertEqual(reading["humidity"], 29)

    def test_parity_error(self):
        payload = bytearray(NORMAL_PAYLOAD)
        payload[3] ^= 0x01
        with self.assertRaisesRegex(ValueError, "parity_error"):
            bresser_native.decode(payload)

    def test_checksum_error(self):
        payload = bytearray(NORMAL_PAYLOAD)
        payload[13] += 1
        payload[0] = (~payload[13]) & 0xFF
        with self.assertRaisesRegex(ValueError, "checksum_error"):
            bresser_native.decode(payload)

    def test_wrong_length(self):
        with self.assertRaisesRegex(ValueError, "wrong_length"):
            bresser_native.decode(NORMAL_PAYLOAD[:-1])


if __name__ == "__main__":
    unittest.main()
