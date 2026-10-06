#pragma once

#include <cstddef>
#include <cstdint>

#include "driver/spi_master.h"

namespace bresser {

constexpr std::size_t kRadioFrameSize = 27;

struct ReceiverConfig {
  int spi_host = 3;
  int sck = 18;
  int mosi = 23;
  int miso = 19;
  int cs = 27;
  int reset = 32;
  int dio0 = 21;
  std::uint32_t frequency_hz = 868300000;
  std::int32_t frequency_offset_hz = 0;
};

enum class ReceiverResult : int {
  kOk = 0,
  kNoPacket = 1,
  kBadSync = 2,
  kNotInitialized = -1,
  kInvalidConfig = -2,
  kSpiBusError = -3,
  kSpiDeviceError = -4,
  kGpioError = -5,
  kChipNotFound = -6,
  kTransactionError = -7,
};

class Sx1276Receiver {
 public:
  Sx1276Receiver() = default;
  ~Sx1276Receiver();

  Sx1276Receiver(const Sx1276Receiver&) = delete;
  Sx1276Receiver& operator=(const Sx1276Receiver&) = delete;

  ReceiverResult begin(const ReceiverConfig& config);
  void deinit();
  ReceiverResult poll(std::uint8_t* payload26, float* rssi_dbm);
  ReceiverResult sleep();
  ReceiverResult wake();

  bool initialized() const { return initialized_; }
  std::uint8_t chip_version() const { return chip_version_; }
  const ReceiverConfig& config() const { return config_; }

 private:
  ReceiverResult configure_radio();
  ReceiverResult restart_receive();
  ReceiverResult write_register(std::uint8_t address, std::uint8_t value);
  ReceiverResult read_register(std::uint8_t address, std::uint8_t* value);
  ReceiverResult read_burst(std::uint8_t address,
                            std::uint8_t* destination,
                            std::size_t length);

  ReceiverConfig config_{};
  spi_device_handle_t spi_device_ = nullptr;
  bool bus_owned_ = false;
  bool initialized_ = false;
  std::uint8_t chip_version_ = 0;
};

const char* receiver_result_name(ReceiverResult result);

}  // namespace bresser
