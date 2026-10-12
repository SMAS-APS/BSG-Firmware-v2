"""Supporto Weather Underground specifico del firmware BSG ESP32."""

import json
import time


STATE_VERSION = 1
DEFAULT_STATE_PATH = "/wu-rain-state.json"
MAX_GAP_SECONDS = 300
HOUR_SECONDS = 3600
FLUSH_INTERVAL_SECONDS = 300


def canonical_sensor_values(reading):
    """Converte una lettura Bresser nelle unita' canoniche AMMS."""

    sensors = {}
    for name in ("temperature", "humidity", "wind_direction", "precipitation"):
        value = reading.get(name)
        if value is not None:
            sensors[name] = value
    for name in ("wind_speed", "wind_gust"):
        value = reading.get(name)
        if value is not None:
            sensors[name] = float(value) * 3.6
    return sensors


def _day_key(epoch, utc_offset_minutes):
    parts = time.gmtime(int(epoch) + int(utc_offset_minutes) * 60)
    return "%04d-%02d-%02d" % (parts[0], parts[1], parts[2])


def _counter_modulus(sensor_type):
    if sensor_type is not None and 0x39 <= int(sensor_type) <= 0x3B:
        return 2500.0
    return 1000.0


def _atomic_write(path, value):
    temporary_path = path + ".tmp"
    with open(temporary_path, "w") as stream:
        json.dump(value, stream)
    import os
    try:
        os.remove(path)
    except OSError:
        pass
    os.rename(temporary_path, path)


class RainTracker:
    """Deriva pioggia oraria/giornaliera da un contatore Bresser cumulativo."""

    def __init__(
        self,
        utc_offset_minutes,
        path=DEFAULT_STATE_PATH,
        flush_interval_seconds=FLUSH_INTERVAL_SECONDS,
    ):
        self.utc_offset_minutes = int(utc_offset_minutes)
        self.path = path
        self.flush_interval_seconds = int(flush_interval_seconds)
        self._state = None
        self._dirty = False
        self._last_flush = None
        self._startup_active = False
        self._load()

    def _load(self):
        try:
            with open(self.path, "r") as stream:
                value = json.load(stream)
            required = (
                "sensor_id",
                "sensor_type",
                "last_raw_mm",
                "normalized_mm",
                "last_timestamp",
                "day_key",
                "day_base_mm",
                "day_valid",
                "hour_valid_after",
                "events",
            )
            if value.get("version") != STATE_VERSION or any(
                name not in value for name in required
            ):
                raise ValueError("stato pioggia incompleto")
            if not isinstance(value["events"], list):
                raise ValueError("eventi pioggia non validi")
            value["last_raw_mm"] = float(value["last_raw_mm"])
            value["normalized_mm"] = float(value["normalized_mm"])
            value["day_base_mm"] = float(value["day_base_mm"])
            value["last_timestamp"] = int(value["last_timestamp"])
            value["hour_valid_after"] = int(value["hour_valid_after"])
            value["events"] = [
                [int(item[0]), float(item[1])]
                for item in value["events"]
                if isinstance(item, (list, tuple)) and len(item) == 2
            ]
            self._state = value
            self._last_flush = value["last_timestamp"]
        except (OSError, ValueError, TypeError, KeyError):
            self._state = None

    def _initialise(self, reading, counter, timestamp):
        self._state = {
            "version": STATE_VERSION,
            "sensor_id": reading.get("sensor_id"),
            "sensor_type": reading.get("sensor_type"),
            "last_raw_mm": counter,
            "normalized_mm": 0.0,
            "last_timestamp": timestamp,
            "day_key": _day_key(timestamp, self.utc_offset_minutes),
            "day_base_mm": 0.0,
            "day_valid": False,
            "hour_valid_after": timestamp + HOUR_SECONDS,
            "events": [],
        }
        self._startup_active = bool(reading.get("startup"))
        self._dirty = True
        self.flush(timestamp, force=True)

    def _delta(self, counter, sensor_type, reset_signal):
        previous = self._state["last_raw_mm"]
        if reset_signal:
            return 0.0
        if counter >= previous:
            return counter - previous
        modulus = _counter_modulus(sensor_type)
        if previous >= modulus * 0.9 and counter <= modulus * 0.1:
            return modulus - previous + counter
        return 0.0

    def _trim_events(self, timestamp):
        cutoff = timestamp - HOUR_SECONDS
        events = self._state["events"]
        kept = [event for event in events if event[0] > cutoff]
        if len(kept) != len(events):
            self._state["events"] = kept
            self._dirty = True

    def update(self, reading, timestamp):
        timestamp = int(timestamp)
        counter_value = reading.get("precipitation")
        if counter_value is None:
            return self.values(timestamp)
        counter = float(counter_value)
        if counter < 0:
            return self.values(timestamp)
        if self._state is None:
            self._initialise(reading, counter, timestamp)
            return self.values(timestamp)

        state = self._state
        sensor_id = reading.get("sensor_id")
        sensor_type = reading.get("sensor_type")
        startup = bool(reading.get("startup"))
        sensor_changed = sensor_id != state["sensor_id"]
        reset_signal = sensor_changed or (startup and not self._startup_active)
        self._startup_active = startup

        previous_timestamp = state["last_timestamp"]
        gap = max(0, timestamp - previous_timestamp)
        old_day = state["day_key"]
        current_day = _day_key(timestamp, self.utc_offset_minutes)
        day_changed = current_day != old_day

        previous_counter = state["last_raw_mm"]
        delta = self._delta(counter, sensor_type, reset_signal)
        counter_reset = counter < previous_counter and delta == 0.0
        if day_changed and gap > MAX_GAP_SECONDS:
            # Non e' possibile stabilire su quale lato della mezzanotte sia
            # caduta la pioggia durante un'assenza prolungata.
            delta_for_totals = 0.0
        else:
            delta_for_totals = delta

        if day_changed:
            state["day_key"] = current_day
            state["day_base_mm"] = state["normalized_mm"]
            state["day_valid"] = True

        if delta_for_totals > 0:
            state["normalized_mm"] += delta_for_totals
            if gap <= MAX_GAP_SECONDS:
                state["events"].append([timestamp, delta_for_totals])
            else:
                # Il totale giornaliero resta noto, ma il momento esatto della
                # pioggia non consente un totale orario affidabile.
                state["hour_valid_after"] = timestamp + HOUR_SECONDS
                state["events"] = []

        state["sensor_id"] = sensor_id
        state["sensor_type"] = sensor_type
        state["last_raw_mm"] = counter
        state["last_timestamp"] = timestamp
        self._dirty = (
            self._dirty or day_changed or reset_signal or counter_reset or delta > 0
        )
        self._trim_events(timestamp)
        self.flush(timestamp, force=day_changed or reset_signal or counter_reset)
        return self.values(timestamp)

    def values(self, timestamp):
        if self._state is None:
            return None, None
        timestamp = int(timestamp)
        self._trim_events(timestamp)
        if timestamp >= self._state["hour_valid_after"]:
            hourly = sum(event[1] for event in self._state["events"])
        else:
            hourly = None
        if self._state["day_valid"]:
            daily = self._state["normalized_mm"] - self._state["day_base_mm"]
        else:
            daily = None
        return hourly, daily

    def flush(self, timestamp, force=False):
        if not self._dirty or self._state is None:
            return False
        timestamp = int(timestamp)
        if (
            not force
            and self._last_flush is not None
            and timestamp - self._last_flush < self.flush_interval_seconds
        ):
            return False
        _atomic_write(self.path, self._state)
        self._dirty = False
        self._last_flush = timestamp
        return True
