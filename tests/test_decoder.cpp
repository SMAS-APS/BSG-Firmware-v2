#include <array>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>

#include "bresser_decoder.hpp"

namespace {

using Payload = std::array<std::uint8_t, bresser::kPayloadSize5In1>;

constexpr Payload kNormalPayload = {
    0xEE, 0x93, 0x7F, 0xF7, 0xBF, 0xFB, 0xEF, 0x9E, 0xFE,
    0xAE, 0xBF, 0xFF, 0xFF, 0x11, 0x6C, 0x80, 0x08, 0x40,
    0x04, 0x10, 0x61, 0x01, 0x51, 0x40, 0x00, 0x00,
};

constexpr Payload kNegativeTemperaturePayload = {
    0xED, 0xA1, 0xFF, 0xFF, 0x1F, 0xFF, 0xEF, 0x8F, 0xFF,
    0xD6, 0xDF, 0xFF, 0x77, 0x12, 0x5E, 0x00, 0x00, 0xE0,
    0x00, 0x10, 0x70, 0x00, 0x29, 0x20, 0x00, 0x88,
};

bool nearly_equal(float left, float right) {
  return std::fabs(left - right) < 0.001F;
}

void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    std::exit(1);
  }
}

void test_normal_payload() {
  bresser::Reading reading{};
  const auto status =
      bresser::decode_5in1(kNormalPayload.data(), kNormalPayload.size(), &reading);

  require(status == bresser::DecodeStatus::kOk, "normal payload status");
  require(reading.sensor_id == 0x6C, "sensor id");
  require(reading.sensor_type == 0, "sensor type");
  require(!reading.startup, "startup flag");
  require(reading.battery_ok, "battery");
  require(reading.temperature_ok && nearly_equal(reading.temperature_c, 16.1F),
          "temperature");
  require(reading.humidity_ok && reading.humidity == 51, "humidity");
  require(reading.wind_ok && nearly_equal(reading.wind_gust_m_s, 0.8F),
          "wind gust");
  require(nearly_equal(reading.wind_avg_m_s, 0.4F), "wind average");
  require(nearly_equal(reading.wind_direction_deg, 90.0F), "wind direction");
  require(reading.rain_ok && nearly_equal(reading.rain_mm, 4.0F), "rain");
}

void test_negative_temperature_and_low_battery() {
  bresser::Reading reading{};
  const auto status = bresser::decode_5in1(
      kNegativeTemperaturePayload.data(), kNegativeTemperaturePayload.size(), &reading);

  require(status == bresser::DecodeStatus::kOk, "negative payload status");
  require(reading.temperature_ok && nearly_equal(reading.temperature_c, -7.0F),
          "negative temperature");
  require(!reading.battery_ok, "low battery");
  require(reading.humidity_ok && reading.humidity == 29, "negative sample humidity");
}

void test_parity_error() {
  Payload payload = kNormalPayload;
  payload[3] ^= 0x01;
  bresser::Reading reading{};
  require(bresser::decode_5in1(payload.data(), payload.size(), &reading) ==
              bresser::DecodeStatus::kParityError,
          "parity error detection");
}

void test_checksum_error() {
  Payload payload = kNormalPayload;
  payload[13] = static_cast<std::uint8_t>(payload[13] + 1);
  payload[0] = static_cast<std::uint8_t>(~payload[13]);
  bresser::Reading reading{};
  require(bresser::decode_5in1(payload.data(), payload.size(), &reading) ==
              bresser::DecodeStatus::kChecksumError,
          "checksum error detection");
}

void test_wrong_length() {
  bresser::Reading reading{};
  require(bresser::decode_5in1(kNormalPayload.data(), 25, &reading) ==
              bresser::DecodeStatus::kWrongLength,
          "length check");
}

}  // namespace

int main() {
  test_normal_payload();
  test_negative_temperature_and_low_battery();
  test_parity_error();
  test_checksum_error();
  test_wrong_length();
  std::cout << "All Bresser decoder tests passed\n";
  return 0;
}
