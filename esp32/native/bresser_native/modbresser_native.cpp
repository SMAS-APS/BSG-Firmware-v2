extern "C" {
#include "py/obj.h"
#include "py/objstr.h"
#include "py/runtime.h"
}

#include <cstdint>

#include "bresser_decoder.hpp"
#include "sx1276_receiver.hpp"

namespace {

bresser::Sx1276Receiver receiver;

struct ModuleStats {
  std::uint32_t packets_seen = 0;
  std::uint32_t packets_decoded = 0;
  std::uint32_t sync_errors = 0;
  std::uint32_t parity_errors = 0;
  std::uint32_t checksum_errors = 0;
  std::uint32_t radio_errors = 0;
};

ModuleStats module_stats;

void dict_store(mp_obj_t dictionary, qstr key, mp_obj_t value) {
  mp_obj_dict_store(dictionary, MP_OBJ_NEW_QSTR(key), value);
}

mp_obj_t optional_float(bool valid, float value) {
  return valid ? mp_obj_new_float(value) : mp_const_none;
}

mp_obj_t optional_int(bool valid, mp_int_t value) {
  return valid ? mp_obj_new_int(value) : mp_const_none;
}

mp_obj_t reading_to_dict(const bresser::Reading& reading,
                         float rssi,
                         const std::uint8_t* raw_payload) {
  mp_obj_t result = mp_obj_new_dict(16);
  dict_store(result, MP_QSTR_protocol,
             mp_obj_new_str("bresser_5in1", sizeof("bresser_5in1") - 1));
  dict_store(result, MP_QSTR_sensor_id, mp_obj_new_int_from_uint(reading.sensor_id));
  dict_store(result, MP_QSTR_sensor_type,
             mp_obj_new_int_from_uint(reading.sensor_type));
  dict_store(result, MP_QSTR_startup,
             mp_obj_new_bool(reading.startup));
  dict_store(result, MP_QSTR_battery_ok,
             mp_obj_new_bool(reading.battery_ok));
  dict_store(result, MP_QSTR_temperature,
             optional_float(reading.temperature_ok, reading.temperature_c));
  dict_store(result, MP_QSTR_humidity,
             optional_int(reading.humidity_ok, reading.humidity));
  dict_store(result, MP_QSTR_wind_gust,
             optional_float(reading.wind_ok, reading.wind_gust_m_s));
  dict_store(result, MP_QSTR_wind_speed,
             optional_float(reading.wind_ok, reading.wind_avg_m_s));
  dict_store(result, MP_QSTR_wind_direction,
             optional_float(reading.wind_ok, reading.wind_direction_deg));
  dict_store(result, MP_QSTR_precipitation,
             optional_float(reading.rain_ok, reading.rain_mm));
  dict_store(result, MP_QSTR_rssi, mp_obj_new_float(rssi));
  if (raw_payload != nullptr) {
    dict_store(result, MP_QSTR_raw,
               mp_obj_new_bytes(raw_payload, bresser::kPayloadSize5In1));
  }
  return result;
}

void record_decode_error(bresser::DecodeStatus status) {
  switch (status) {
    case bresser::DecodeStatus::kParityError:
      ++module_stats.parity_errors;
      break;
    case bresser::DecodeStatus::kChecksumError:
      ++module_stats.checksum_errors;
      break;
    default:
      break;
  }
}

[[noreturn]] void raise_receiver_error(const char* operation,
                                       bresser::ReceiverResult result) {
  mp_raise_msg_varg(&mp_type_RuntimeError,
                    MP_ERROR_TEXT("%s: %s"),
                    operation,
                    bresser::receiver_result_name(result));
}

mp_obj_t module_init(std::size_t n_args,
                     const mp_obj_t* positional_args,
                     mp_map_t* keyword_args) {
  enum {
    kSpiHost,
    kSck,
    kMosi,
    kMiso,
    kCs,
    kReset,
    kDio0,
    kFrequencyHz,
    kFrequencyOffsetHz,
  };

  static const mp_arg_t allowed_args[] = {
      {MP_QSTR_spi_host, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 3}},
      {MP_QSTR_sck, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 18}},
      {MP_QSTR_mosi, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 23}},
      {MP_QSTR_miso, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 19}},
      {MP_QSTR_cs, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 27}},
      {MP_QSTR_reset, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 32}},
      {MP_QSTR_dio0, MP_ARG_INT | MP_ARG_KW_ONLY, {.u_int = 21}},
      {MP_QSTR_frequency_hz,
       MP_ARG_INT | MP_ARG_KW_ONLY,
       {.u_int = 868300000}},
      {MP_QSTR_frequency_offset_hz,
       MP_ARG_INT | MP_ARG_KW_ONLY,
       {.u_int = 0}},
  };

  mp_arg_val_t arguments[MP_ARRAY_SIZE(allowed_args)];
  mp_arg_parse_all(n_args,
                   positional_args,
                   keyword_args,
                   MP_ARRAY_SIZE(allowed_args),
                   allowed_args,
                   arguments);

  bresser::ReceiverConfig config{};
  config.spi_host = arguments[kSpiHost].u_int;
  config.sck = arguments[kSck].u_int;
  config.mosi = arguments[kMosi].u_int;
  config.miso = arguments[kMiso].u_int;
  config.cs = arguments[kCs].u_int;
  config.reset = arguments[kReset].u_int;
  config.dio0 = arguments[kDio0].u_int;
  config.frequency_hz = arguments[kFrequencyHz].u_int;
  config.frequency_offset_hz = arguments[kFrequencyOffsetHz].u_int;

  const bresser::ReceiverResult result = receiver.begin(config);
  if (result != bresser::ReceiverResult::kOk) {
    raise_receiver_error("SX1276 init failed", result);
  }

  module_stats = {};
  return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_KW(module_init_obj, 0, module_init);

mp_obj_t module_poll() {
  std::uint8_t payload[bresser::kPayloadSize5In1]{};
  float rssi = 0.0F;
  const bresser::ReceiverResult receive_result = receiver.poll(payload, &rssi);

  if (receive_result == bresser::ReceiverResult::kNoPacket) {
    return mp_const_none;
  }
  if (receive_result == bresser::ReceiverResult::kBadSync) {
    ++module_stats.sync_errors;
    return mp_const_none;
  }
  if (receive_result != bresser::ReceiverResult::kOk) {
    ++module_stats.radio_errors;
    raise_receiver_error("SX1276 poll failed", receive_result);
  }

  ++module_stats.packets_seen;
  bresser::Reading reading{};
  const bresser::DecodeStatus decode_result =
      bresser::decode_5in1(payload, sizeof(payload), &reading);
  if (decode_result != bresser::DecodeStatus::kOk) {
    record_decode_error(decode_result);
    return mp_const_none;
  }

  ++module_stats.packets_decoded;
  return reading_to_dict(reading, rssi, payload);
}
MP_DEFINE_CONST_FUN_OBJ_0(module_poll_obj, module_poll);

mp_obj_t module_decode(mp_obj_t payload_object) {
  mp_buffer_info_t payload{};
  mp_get_buffer_raise(payload_object, &payload, MP_BUFFER_READ);
  if (payload.len != bresser::kPayloadSize5In1) {
    mp_raise_ValueError(MP_ERROR_TEXT("payload must contain 26 bytes"));
  }

  bresser::Reading reading{};
  const auto* bytes = static_cast<const std::uint8_t*>(payload.buf);
  const bresser::DecodeStatus result =
      bresser::decode_5in1(bytes, payload.len, &reading);
  if (result != bresser::DecodeStatus::kOk) {
    mp_raise_msg_varg(&mp_type_ValueError,
                      MP_ERROR_TEXT("invalid Bresser payload: %s"),
                      bresser::decode_status_name(result));
  }
  return reading_to_dict(reading, 0.0F, bytes);
}
MP_DEFINE_CONST_FUN_OBJ_1(module_decode_obj, module_decode);

mp_obj_t module_status() {
  mp_obj_t result = mp_obj_new_dict(12);
  const bresser::ReceiverConfig& config = receiver.config();
  dict_store(result, MP_QSTR_initialized,
             mp_obj_new_bool(receiver.initialized()));
  dict_store(result, MP_QSTR_chip_version,
             mp_obj_new_int_from_uint(receiver.chip_version()));
  dict_store(result, MP_QSTR_spi_host, mp_obj_new_int(config.spi_host));
  dict_store(result, MP_QSTR_sck, mp_obj_new_int(config.sck));
  dict_store(result, MP_QSTR_mosi, mp_obj_new_int(config.mosi));
  dict_store(result, MP_QSTR_miso, mp_obj_new_int(config.miso));
  dict_store(result, MP_QSTR_cs, mp_obj_new_int(config.cs));
  dict_store(result, MP_QSTR_reset, mp_obj_new_int(config.reset));
  dict_store(result, MP_QSTR_dio0, mp_obj_new_int(config.dio0));
  dict_store(result, MP_QSTR_frequency_hz,
             mp_obj_new_int_from_uint(config.frequency_hz));
  dict_store(result, MP_QSTR_frequency_offset_hz,
             mp_obj_new_int(config.frequency_offset_hz));
  return result;
}
MP_DEFINE_CONST_FUN_OBJ_0(module_status_obj, module_status);

mp_obj_t module_stats_function() {
  mp_obj_t result = mp_obj_new_dict(6);
  dict_store(result, MP_QSTR_packets_seen,
             mp_obj_new_int_from_uint(module_stats.packets_seen));
  dict_store(result, MP_QSTR_packets_decoded,
             mp_obj_new_int_from_uint(module_stats.packets_decoded));
  dict_store(result, MP_QSTR_sync_errors,
             mp_obj_new_int_from_uint(module_stats.sync_errors));
  dict_store(result, MP_QSTR_parity_errors,
             mp_obj_new_int_from_uint(module_stats.parity_errors));
  dict_store(result, MP_QSTR_checksum_errors,
             mp_obj_new_int_from_uint(module_stats.checksum_errors));
  dict_store(result, MP_QSTR_radio_errors,
             mp_obj_new_int_from_uint(module_stats.radio_errors));
  return result;
}
MP_DEFINE_CONST_FUN_OBJ_0(module_stats_obj, module_stats_function);

mp_obj_t module_reset_stats() {
  module_stats = {};
  return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_0(module_reset_stats_obj, module_reset_stats);

mp_obj_t module_sleep() {
  const bresser::ReceiverResult result = receiver.sleep();
  if (result != bresser::ReceiverResult::kOk) {
    raise_receiver_error("SX1276 sleep failed", result);
  }
  return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_0(module_sleep_obj, module_sleep);

mp_obj_t module_wake() {
  const bresser::ReceiverResult result = receiver.wake();
  if (result != bresser::ReceiverResult::kOk) {
    raise_receiver_error("SX1276 wake failed", result);
  }
  return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_0(module_wake_obj, module_wake);

mp_obj_t module_deinit() {
  receiver.deinit();
  return mp_const_none;
}
MP_DEFINE_CONST_FUN_OBJ_0(module_deinit_obj, module_deinit);

const mp_rom_map_elem_t module_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_bresser_native)},
    {MP_ROM_QSTR(MP_QSTR_init), MP_ROM_PTR(&module_init_obj)},
    {MP_ROM_QSTR(MP_QSTR_poll), MP_ROM_PTR(&module_poll_obj)},
    {MP_ROM_QSTR(MP_QSTR_decode), MP_ROM_PTR(&module_decode_obj)},
    {MP_ROM_QSTR(MP_QSTR_status), MP_ROM_PTR(&module_status_obj)},
    {MP_ROM_QSTR(MP_QSTR_stats), MP_ROM_PTR(&module_stats_obj)},
    {MP_ROM_QSTR(MP_QSTR_reset_stats), MP_ROM_PTR(&module_reset_stats_obj)},
    {MP_ROM_QSTR(MP_QSTR_sleep), MP_ROM_PTR(&module_sleep_obj)},
    {MP_ROM_QSTR(MP_QSTR_wake), MP_ROM_PTR(&module_wake_obj)},
    {MP_ROM_QSTR(MP_QSTR_deinit), MP_ROM_PTR(&module_deinit_obj)},
};

MP_DEFINE_CONST_DICT(module_globals, module_globals_table);

}  // namespace

extern "C" {
extern const mp_obj_module_t bresser_native_module = {
    .base = {&mp_type_module},
    .globals = const_cast<mp_obj_dict_t*>(&module_globals),
};

MP_REGISTER_MODULE(MP_QSTR_bresser_native, bresser_native_module);
}
