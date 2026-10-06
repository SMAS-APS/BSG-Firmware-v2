#include "bresser_decoder.hpp"

namespace bresser {
namespace {

std::uint8_t popcount8(std::uint8_t value) {
  std::uint8_t count = 0;
  while (value != 0) {
    value = static_cast<std::uint8_t>(value & (value - 1));
    ++count;
  }
  return count;
}

bool is_bcd_digit(std::uint8_t value) { return value <= 9; }

bool valid_bcd2(std::uint8_t value) {
  return is_bcd_digit(value & 0x0F) && is_bcd_digit((value >> 4) & 0x0F);
}

}  // namespace

DecodeStatus decode_5in1(const std::uint8_t* payload,
                         std::size_t length,
                         Reading* reading) {
  if (payload == nullptr || reading == nullptr || length != kPayloadSize5In1) {
    return DecodeStatus::kWrongLength;
  }

  for (std::size_t index = 0; index < kPayloadSize5In1 / 2; ++index) {
    if (static_cast<std::uint8_t>(payload[index] ^ payload[index + 13]) != 0xFF) {
      return DecodeStatus::kParityError;
    }
  }

  std::uint8_t bit_count = 0;
  for (std::size_t index = 14; index < kPayloadSize5In1; ++index) {
    bit_count = static_cast<std::uint8_t>(bit_count + popcount8(payload[index]));
  }
  if (bit_count != payload[13]) {
    return DecodeStatus::kChecksumError;
  }

  Reading decoded{};
  decoded.sensor_id = payload[14];
  decoded.sensor_type = payload[15] & 0x7F;
  decoded.startup = (payload[15] & 0x80) == 0;
  decoded.battery_ok = (payload[25] & 0x80) == 0;

  const std::uint8_t temp_units = payload[20] & 0x0F;
  const std::uint8_t temp_tens = (payload[20] >> 4) & 0x0F;
  const std::uint8_t temp_hundreds = payload[21] & 0x0F;
  decoded.temperature_ok = is_bcd_digit(temp_units) &&
                           is_bcd_digit(temp_tens) &&
                           is_bcd_digit(temp_hundreds);
  if (decoded.temperature_ok) {
    int raw_temperature = temp_units + temp_tens * 10 + temp_hundreds * 100;
    if ((payload[25] & 0x0F) != 0) {
      raw_temperature = -raw_temperature;
    }
    decoded.temperature_c = static_cast<float>(raw_temperature) * 0.1F;
  }

  decoded.humidity_ok = valid_bcd2(payload[22]);
  if (decoded.humidity_ok) {
    decoded.humidity = static_cast<std::uint8_t>(
        (payload[22] & 0x0F) + ((payload[22] >> 4) & 0x0F) * 10);
  }

  const std::uint8_t wind_units = payload[18] & 0x0F;
  const std::uint8_t wind_tens = (payload[18] >> 4) & 0x0F;
  const std::uint8_t wind_hundreds = payload[19] & 0x0F;
  decoded.wind_ok = is_bcd_digit(wind_units) &&
                    is_bcd_digit(wind_tens) &&
                    is_bcd_digit(wind_hundreds);
  if (decoded.wind_ok) {
    const int gust_raw = ((payload[17] & 0x0F) << 8) | payload[16];
    const int wind_raw = wind_units + wind_tens * 10 + wind_hundreds * 100;
    decoded.wind_gust_m_s = static_cast<float>(gust_raw) * 0.1F;
    decoded.wind_avg_m_s = static_cast<float>(wind_raw) * 0.1F;
    decoded.wind_direction_deg =
        static_cast<float>((payload[17] >> 4) & 0x0F) * 22.5F;
  }

  const std::uint8_t rain_units = payload[23] & 0x0F;
  const std::uint8_t rain_tens = (payload[23] >> 4) & 0x0F;
  const std::uint8_t rain_hundreds = payload[24] & 0x0F;
  const std::uint8_t rain_thousands = (payload[24] >> 4) & 0x0F;
  decoded.rain_ok = is_bcd_digit(rain_units) &&
                    is_bcd_digit(rain_tens) &&
                    is_bcd_digit(rain_hundreds) &&
                    is_bcd_digit(rain_thousands);
  if (decoded.rain_ok) {
    const int rain_raw = rain_units + rain_tens * 10 + rain_hundreds * 100 +
                         rain_thousands * 1000;
    decoded.rain_mm = static_cast<float>(rain_raw) * 0.1F;

    // I tipi 0x39..0x3B sono pluviometri professionali con scala 2,5x.
    if (decoded.sensor_type >= 0x39 && decoded.sensor_type <= 0x3B) {
      decoded.rain_mm *= 2.5F;
    }
  }

  *reading = decoded;
  return DecodeStatus::kOk;
}

const char* decode_status_name(DecodeStatus status) {
  switch (status) {
    case DecodeStatus::kOk:
      return "ok";
    case DecodeStatus::kWrongLength:
      return "wrong_length";
    case DecodeStatus::kParityError:
      return "parity_error";
    case DecodeStatus::kChecksumError:
      return "checksum_error";
  }
  return "unknown";
}

}  // namespace bresser
