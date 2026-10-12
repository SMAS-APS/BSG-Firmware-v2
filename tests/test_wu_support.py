import datetime
import json
import pathlib
import sys
import tempfile
import unittest


MODULES = pathlib.Path(__file__).resolve().parents[1] / "modules"
sys.path.insert(0, str(MODULES))

from wu_support import RainTracker, canonical_sensor_values


def epoch(year, month, day, hour=0, minute=0, second=0):
    return int(
        datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
        ).timestamp()
    )


def reading(rain, sensor_id=1, sensor_type=1, startup=False):
    return {
        "precipitation": rain,
        "sensor_id": sensor_id,
        "sensor_type": sensor_type,
        "startup": startup,
    }


class RainTrackerTests(unittest.TestCase):
    def test_6_and_7in1_counter_rollover_uses_six_bcd_digits(self):
        for protocol in ("bresser_6in1", "bresser_7in1"):
            with tempfile.TemporaryDirectory() as directory:
                tracker = self.make_tracker(directory)
                start = epoch(2026, 1, 1, 12)
                tracker.update(dict(reading(99999.8), protocol=protocol), start)
                tracker.update(dict(reading(0.2), protocol=protocol), start + 12)
                self.assertAlmostEqual(tracker._state["normalized_mm"], 0.4)

    def make_tracker(self, directory, offset=60):
        return RainTracker(
            offset,
            path=str(pathlib.Path(directory) / "rain.json"),
            flush_interval_seconds=300,
        )

    def test_cold_start_omits_unknown_periods(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = self.make_tracker(directory)
            start = epoch(2026, 1, 1, 12)
            self.assertEqual(tracker.update(reading(12.0), start), (None, None))
            hourly, daily = tracker.update(reading(12.0), start + 3600)
            self.assertEqual(hourly, 0)
            self.assertIsNone(daily)

    def test_hourly_rain_and_normal_counter_increment(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = self.make_tracker(directory)
            start = epoch(2026, 1, 1, 12)
            tracker.update(reading(10.0), start)
            tracker.update(reading(10.0), start + 3600)
            hourly, _ = tracker.update(reading(11.5), start + 3612)
            self.assertAlmostEqual(hourly, 1.5)

    def test_midnight_uses_configured_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = self.make_tracker(directory, offset=60)
            before_midnight = epoch(2026, 1, 1, 22, 59, 50)
            tracker.update(reading(10.0), before_midnight)
            _, daily = tracker.update(reading(11.0), before_midnight + 20)
            self.assertAlmostEqual(daily, 1.0)

    def test_normal_and_professional_counter_wrap(self):
        with tempfile.TemporaryDirectory() as directory:
            start = epoch(2026, 1, 1, 12)
            normal = self.make_tracker(directory)
            normal.update(reading(999.8), start)
            normal.update(reading(999.8), start + 3600)
            hourly, _ = normal.update(reading(0.1), start + 3612)
            self.assertAlmostEqual(hourly, 0.3)

        with tempfile.TemporaryDirectory() as directory:
            professional = self.make_tracker(directory)
            professional.update(reading(2499.75, sensor_type=0x39), start)
            professional.update(reading(2499.75, sensor_type=0x39), start + 3600)
            hourly, _ = professional.update(
                reading(0.25, sensor_type=0x39), start + 3612
            )
            self.assertAlmostEqual(hourly, 0.5)

    def test_reset_and_sensor_change_do_not_create_rain(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = self.make_tracker(directory)
            start = epoch(2026, 1, 1, 12)
            tracker.update(reading(20.0), start)
            tracker.update(reading(20.0), start + 3600)
            hourly, _ = tracker.update(reading(0.0, startup=True), start + 3612)
            self.assertEqual(hourly, 0)
            hourly, _ = tracker.update(
                reading(100.0, sensor_id=2), start + 3624
            )
            self.assertIsNone(hourly)

    def test_sensor_replacement_cannot_retain_previous_stations_rain_events(self):
        with tempfile.TemporaryDirectory() as directory:
            tracker = self.make_tracker(directory)
            start = epoch(2026, 1, 1, 12)
            tracker.update(reading(20), start)
            tracker.update(reading(22), start + 12)
            tracker.update(reading(50, sensor_id=2), start + 24)
            self.assertEqual(tracker._state["events"], [])
            self.assertEqual(tracker._state["normalized_mm"], 0)

    def test_persisted_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            start = epoch(2026, 1, 1, 12)
            tracker = self.make_tracker(directory)
            tracker.update(reading(10.0), start)
            tracker.update(reading(10.0), start + 3600)
            tracker.update(reading(11.0), start + 3612)
            tracker.flush(start + 3900)

            restored = self.make_tracker(directory)
            hourly, _ = restored.update(reading(11.5), start + 3900)
            self.assertAlmostEqual(hourly, 1.5)

    def test_corrupt_state_starts_without_fabricated_rain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "rain.json"
            path.write_text("not-json", encoding="utf-8")
            tracker = self.make_tracker(directory)
            self.assertEqual(
                tracker.update(reading(500.0), epoch(2026, 1, 1, 12)),
                (None, None),
            )
            json.loads(path.read_text(encoding="utf-8"))

    def test_wind_is_normalised_to_kilometres_per_hour(self):
        sensors = canonical_sensor_values(
            {
                "temperature": 20,
                "wind_speed": 2.0,
                "wind_gust": 3.0,
                "precipitation": 4.0,
            }
        )
        self.assertEqual(sensors["temperature"], 20)
        self.assertAlmostEqual(sensors["wind_speed"], 7.2)
        self.assertAlmostEqual(sensors["wind_gust"], 10.8)
        self.assertEqual(sensors["precipitation"], 4.0)


if __name__ == "__main__":
    unittest.main()
