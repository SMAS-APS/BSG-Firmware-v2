#pragma once

#include <cstddef>
#include <cstdint>

namespace bresser {

constexpr std::size_t kPayloadSize5In1 = 26;

enum class DecodeStatus : std::uint8_t {
  kOk = 0,
  kWrongLength,
  kParityError,
  kChecksumError,
};

struct Reading {
  std::uint16_t sensor_id = 0;
  std::uint8_t sensor_type = 0;
  bool startup = false;
  bool battery_ok = false;

  bool temperature_ok = false;
  float temperature_c = 0.0F;

  bool humidity_ok = false;
  std::uint8_t humidity = 0;

  bool wind_ok = false;
  float wind_gust_m_s = 0.0F;
  float wind_avg_m_s = 0.0F;
  float wind_direction_deg = 0.0F;

  bool rain_ok = false;
  float rain_mm = 0.0F;
};

DecodeStatus decode_5in1(const std::uint8_t* payload,
                         std::size_t length,
                         Reading* reading);

const char* decode_status_name(DecodeStatus status);

}  // namespace bresser
