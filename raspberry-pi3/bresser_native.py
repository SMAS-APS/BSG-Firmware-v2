"""Driver Python per SX1276/RFM95W e decoder Bresser 5-in-1.

L'API replica il modulo C++ usato dal firmware ESP32, ma accede all'hardware
tramite spidev e gpiozero su Raspberry Pi OS.
"""

import re
import time


PAYLOAD_SIZE = 26
FRAME_SIZE = 27

_CRYSTAL_HZ = 32_000_000
_BIT_RATE = 8_210
_FREQUENCY_DEVIATION_HZ = 57_136
_EXPECTED_CHIP_VERSION = 0x12

_REG_FIFO = 0x00
_REG_OP_MODE = 0x01
_REG_BITRATE_MSB = 0x02
_REG_BITRATE_LSB = 0x03
_REG_FDEV_MSB = 0x04
_REG_FDEV_LSB = 0x05
_REG_FRF_MSB = 0x06
_REG_FRF_MID = 0x07
_REG_FRF_LSB = 0x08
_REG_LNA = 0x0C
_REG_RX_CONFIG = 0x0D
_REG_RSSI_THRESHOLD = 0x10
_REG_RSSI_VALUE = 0x11
_REG_RX_BANDWIDTH = 0x12
_REG_AFC_BANDWIDTH = 0x13
_REG_PREAMBLE_MSB = 0x25
_REG_PREAMBLE_LSB = 0x26
_REG_SYNC_CONFIG = 0x27
_REG_SYNC_VALUE_1 = 0x28
_REG_SYNC_VALUE_2 = 0x29
_REG_PACKET_CONFIG_1 = 0x30
_REG_PACKET_CONFIG_2 = 0x31
_REG_PAYLOAD_LENGTH = 0x32
_REG_FIFO_THRESHOLD = 0x35
_REG_IRQ_FLAGS_2 = 0x3F
_REG_DIO_MAPPING_1 = 0x40
_REG_DIO_MAPPING_2 = 0x41
_REG_VERSION = 0x42
_REG_TEST_DAGC = 0x6F

_MODE_SLEEP_FSK = 0x00
_MODE_STANDBY_FSK = 0x01
_MODE_RECEIVE_FSK = 0x05
_IRQ_PAYLOAD_READY = 0x04


class DecodeError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class RadioError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _is_bcd_digit(value):
    return 0 <= value <= 9


def _valid_bcd2(value):
    return _is_bcd_digit(value & 0x0F) and _is_bcd_digit((value >> 4) & 0x0F)


def _decode_payload(payload, rssi=0.0):
    payload = bytes(payload)
    if len(payload) != PAYLOAD_SIZE:
        raise DecodeError("wrong_length")

    for index in range(PAYLOAD_SIZE // 2):
        if payload[index] ^ payload[index + 13] != 0xFF:
            raise DecodeError("parity_error")

    bit_count = sum(bin(value).count("1") for value in payload[14:])
    if bit_count != payload[13]:
        raise DecodeError("checksum_error")

    temp_units = payload[20] & 0x0F
    temp_tens = (payload[20] >> 4) & 0x0F
    temp_hundreds = payload[21] & 0x0F
    temperature_ok = all(
        _is_bcd_digit(value) for value in (temp_units, temp_tens, temp_hundreds)
    )
    temperature = None
    if temperature_ok:
        raw_temperature = temp_units + temp_tens * 10 + temp_hundreds * 100
        if payload[25] & 0x0F:
            raw_temperature = -raw_temperature
        temperature = raw_temperature * 0.1

    humidity = None
    if _valid_bcd2(payload[22]):
        humidity = (payload[22] & 0x0F) + ((payload[22] >> 4) & 0x0F) * 10

    wind_units = payload[18] & 0x0F
    wind_tens = (payload[18] >> 4) & 0x0F
    wind_hundreds = payload[19] & 0x0F
    wind_ok = all(
        _is_bcd_digit(value) for value in (wind_units, wind_tens, wind_hundreds)
    )
    wind_gust = None
    wind_speed = None
    wind_direction = None
    if wind_ok:
        wind_gust = (((payload[17] & 0x0F) << 8) | payload[16]) * 0.1
        wind_speed = (wind_units + wind_tens * 10 + wind_hundreds * 100) * 0.1
        wind_direction = ((payload[17] >> 4) & 0x0F) * 22.5

    rain_units = payload[23] & 0x0F
    rain_tens = (payload[23] >> 4) & 0x0F
    rain_hundreds = payload[24] & 0x0F
    rain_thousands = (payload[24] >> 4) & 0x0F
    rain_ok = all(
        _is_bcd_digit(value)
        for value in (rain_units, rain_tens, rain_hundreds, rain_thousands)
    )
    precipitation = None
    sensor_type = payload[15] & 0x7F
    if rain_ok:
        precipitation = (
            rain_units
            + rain_tens * 10
            + rain_hundreds * 100
            + rain_thousands * 1000
        ) * 0.1
        if 0x39 <= sensor_type <= 0x3B:
            precipitation *= 2.5

    return {
        "protocol": "bresser_5in1",
        "sensor_id": payload[14],
        "sensor_type": sensor_type,
        "startup": (payload[15] & 0x80) == 0,
        "battery_ok": (payload[25] & 0x80) == 0,
        "temperature": temperature,
        "humidity": humidity,
        "wind_gust": wind_gust,
        "wind_speed": wind_speed,
        "wind_direction": wind_direction,
        "precipitation": precipitation,
        "rssi": float(rssi),
        "raw": payload,
    }


class _Sx1276Receiver:
    def __init__(self):
        self.spi = None
        self.reset_line = None
        self.dio0_line = None
        self.initialized = False
        self.chip_version = 0
        self.config = {}

    @staticmethod
    def _parse_spi_device(path):
        match = re.fullmatch(r"/dev/spidev(\d+)\.(\d+)", path)
        if not match:
            raise ValueError("spi_device non valido: %s" % path)
        return int(match.group(1)), int(match.group(2))

    def begin(
        self,
        spi_device="/dev/spidev0.0",
        reset=25,
        dio0=24,
        frequency_hz=868_300_000,
        frequency_offset_hz=0,
    ):
        self.deinit()
        tuned_frequency = int(frequency_hz) + int(frequency_offset_hz)
        if not 862_000_000 <= tuned_frequency <= 1_020_000_000:
            raise ValueError("frequenza radio non valida")

        try:
            import spidev
            from gpiozero import DigitalInputDevice, OutputDevice
        except ImportError as exc:
            raise RuntimeError(
                "dipendenze hardware mancanti: installare python3-spidev e python3-gpiozero"
            ) from exc

        bus, device = self._parse_spi_device(spi_device)
        self.config = {
            "spi_device": spi_device,
            "reset": int(reset),
            "dio0": int(dio0),
            "frequency_hz": int(frequency_hz),
            "frequency_offset_hz": int(frequency_offset_hz),
        }

        try:
            self.spi = spidev.SpiDev()
            self.spi.open(bus, device)
            self.spi.max_speed_hz = 4_000_000
            self.spi.mode = 0
            self.spi.bits_per_word = 8

            self.reset_line = OutputDevice(int(reset), active_high=True, initial_value=True)
            self.dio0_line = DigitalInputDevice(int(dio0), pull_up=None)
            self.reset_line.off()
            time.sleep(0.002)
            self.reset_line.on()
            time.sleep(0.010)

            self.chip_version = self._read_register(_REG_VERSION)
            if self.chip_version != _EXPECTED_CHIP_VERSION:
                raise RadioError(
                    "chip_not_found: atteso 0x12, letto 0x%02x" % self.chip_version
                )
            self._configure_radio(tuned_frequency)
            self.initialized = True
        except Exception:
            self.deinit()
            raise

    def _write_register(self, address, value):
        if self.spi is None:
            raise RadioError("not_initialized")
        self.spi.xfer2([address | 0x80, value & 0xFF])

    def _read_register(self, address):
        if self.spi is None:
            raise RadioError("not_initialized")
        return self.spi.xfer2([address & 0x7F, 0])[1]

    def _read_burst(self, address, length):
        if self.spi is None:
            raise RadioError("not_initialized")
        return bytes(self.spi.xfer2([address & 0x7F] + [0] * length)[1:])

    def _configure_radio(self, frequency_hz):
        self._write_register(_REG_OP_MODE, _MODE_SLEEP_FSK)
        time.sleep(0.001)
        self._write_register(_REG_OP_MODE, _MODE_STANDBY_FSK)

        frf = (frequency_hz * (1 << 19) + _CRYSTAL_HZ // 2) // _CRYSTAL_HZ
        bitrate = (_CRYSTAL_HZ + _BIT_RATE // 2) // _BIT_RATE
        frequency_deviation = (
            _FREQUENCY_DEVIATION_HZ * (1 << 19) + _CRYSTAL_HZ // 2
        ) // _CRYSTAL_HZ

        settings = (
            (_REG_BITRATE_MSB, bitrate >> 8),
            (_REG_BITRATE_LSB, bitrate),
            (_REG_FDEV_MSB, frequency_deviation >> 8),
            (_REG_FDEV_LSB, frequency_deviation),
            (_REG_FRF_MSB, frf >> 16),
            (_REG_FRF_MID, frf >> 8),
            (_REG_FRF_LSB, frf),
            (_REG_RX_CONFIG, 0x1F),
            (_REG_RSSI_THRESHOLD, 0xFF),
            (_REG_RX_BANDWIDTH, 0x41),
            (_REG_AFC_BANDWIDTH, 0x41),
            (_REG_PREAMBLE_MSB, 0x00),
            (_REG_PREAMBLE_LSB, 0x04),
            (_REG_SYNC_CONFIG, 0x99),
            (_REG_SYNC_VALUE_1, 0xAA),
            (_REG_SYNC_VALUE_2, 0x2D),
            (_REG_PACKET_CONFIG_1, 0x00),
            (_REG_PACKET_CONFIG_2, 0x40),
            (_REG_PAYLOAD_LENGTH, FRAME_SIZE),
            (_REG_FIFO_THRESHOLD, 0x0F),
            (_REG_DIO_MAPPING_1, 0x00),
            (_REG_DIO_MAPPING_2, 0x00),
            (_REG_TEST_DAGC, 0x30),
        )
        for address, value in settings:
            self._write_register(address, value)
        self._write_register(_REG_LNA, self._read_register(_REG_LNA) | 0x03)
        self._restart_receive()

    def _restart_receive(self):
        self._write_register(_REG_OP_MODE, _MODE_STANDBY_FSK)
        time.sleep(0.0001)
        self._write_register(_REG_OP_MODE, _MODE_RECEIVE_FSK)

    def poll_frame(self):
        if not self.initialized:
            raise RadioError("not_initialized")
        if not self.dio0_line.value:
            return None
        if not self._read_register(_REG_IRQ_FLAGS_2) & _IRQ_PAYLOAD_READY:
            return None

        rssi = -self._read_register(_REG_RSSI_VALUE) / 2.0
        frame = self._read_burst(_REG_FIFO, FRAME_SIZE)
        self._restart_receive()
        if frame[0] != 0xD4:
            raise RadioError("bad_sync")
        return frame[1:], rssi

    def sleep(self):
        if not self.initialized:
            raise RadioError("not_initialized")
        self._write_register(_REG_OP_MODE, _MODE_SLEEP_FSK)

    def wake(self):
        if not self.initialized:
            raise RadioError("not_initialized")
        self._restart_receive()

    def deinit(self):
        if self.spi is not None:
            try:
                self._write_register(_REG_OP_MODE, _MODE_SLEEP_FSK)
            except Exception:
                pass
        self.initialized = False
        self.chip_version = 0
        for line_name in ("dio0_line", "reset_line"):
            line = getattr(self, line_name)
            if line is not None:
                try:
                    line.close()
                except Exception:
                    pass
                setattr(self, line_name, None)
        if self.spi is not None:
            try:
                self.spi.close()
            finally:
                self.spi = None

    def status(self):
        result = dict(self.config)
        result.update(
            {
                "initialized": self.initialized,
                "chip_version": self.chip_version,
            }
        )
        return result


_receiver = _Sx1276Receiver()
_stats = {}


def reset_stats():
    _stats.clear()
    _stats.update(
        {
            "packets_seen": 0,
            "packets_decoded": 0,
            "sync_errors": 0,
            "parity_errors": 0,
            "checksum_errors": 0,
            "radio_errors": 0,
        }
    )


def init(**kwargs):
    _receiver.begin(**kwargs)
    reset_stats()


def poll():
    try:
        result = _receiver.poll_frame()
    except RadioError as exc:
        if exc.code == "bad_sync":
            _stats["sync_errors"] += 1
            return None
        _stats["radio_errors"] += 1
        raise
    if result is None:
        return None

    payload, rssi = result
    _stats["packets_seen"] += 1
    try:
        reading = _decode_payload(payload, rssi)
    except DecodeError as exc:
        if exc.code == "parity_error":
            _stats["parity_errors"] += 1
        elif exc.code == "checksum_error":
            _stats["checksum_errors"] += 1
        return None
    _stats["packets_decoded"] += 1
    return reading


def decode(payload):
    try:
        return _decode_payload(payload)
    except DecodeError as exc:
        raise ValueError("payload Bresser non valido: %s" % exc.code) from exc


def status():
    return _receiver.status()


def stats():
    return dict(_stats)


def sleep():
    _receiver.sleep()


def wake():
    _receiver.wake()


def deinit():
    _receiver.deinit()


reset_stats()
