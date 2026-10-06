#include "sx1276_receiver.hpp"

#include <array>
#include <cstring>

#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_idf_version.h"
#include "esp_rom_sys.h"

namespace bresser {
namespace {

constexpr std::uint32_t kCrystalFrequencyHz = 32000000;
constexpr std::uint32_t kBitRate = 8210;
constexpr std::uint32_t kFrequencyDeviationHz = 57136;

constexpr std::uint8_t kRegFifo = 0x00;
constexpr std::uint8_t kRegOpMode = 0x01;
constexpr std::uint8_t kRegBitrateMsb = 0x02;
constexpr std::uint8_t kRegBitrateLsb = 0x03;
constexpr std::uint8_t kRegFdevMsb = 0x04;
constexpr std::uint8_t kRegFdevLsb = 0x05;
constexpr std::uint8_t kRegFrfMsb = 0x06;
constexpr std::uint8_t kRegFrfMid = 0x07;
constexpr std::uint8_t kRegFrfLsb = 0x08;
constexpr std::uint8_t kRegLna = 0x0C;
constexpr std::uint8_t kRegRxConfig = 0x0D;
constexpr std::uint8_t kRegRssiThreshold = 0x10;
constexpr std::uint8_t kRegRssiValue = 0x11;
constexpr std::uint8_t kRegRxBandwidth = 0x12;
constexpr std::uint8_t kRegAfcBandwidth = 0x13;
constexpr std::uint8_t kRegPreambleMsb = 0x25;
constexpr std::uint8_t kRegPreambleLsb = 0x26;
constexpr std::uint8_t kRegSyncConfig = 0x27;
constexpr std::uint8_t kRegSyncValue1 = 0x28;
constexpr std::uint8_t kRegSyncValue2 = 0x29;
constexpr std::uint8_t kRegPacketConfig1 = 0x30;
constexpr std::uint8_t kRegPacketConfig2 = 0x31;
constexpr std::uint8_t kRegPayloadLength = 0x32;
constexpr std::uint8_t kRegFifoThreshold = 0x35;
constexpr std::uint8_t kRegIrqFlags2 = 0x3F;
constexpr std::uint8_t kRegDioMapping1 = 0x40;
constexpr std::uint8_t kRegDioMapping2 = 0x41;
constexpr std::uint8_t kRegVersion = 0x42;
constexpr std::uint8_t kRegTestDagc = 0x6F;

constexpr std::uint8_t kModeSleepFsk = 0x00;
constexpr std::uint8_t kModeStandbyFsk = 0x01;
constexpr std::uint8_t kModeReceiveFsk = 0x05;
constexpr std::uint8_t kIrqPayloadReady = 0x04;

constexpr std::uint8_t kExpectedChipVersion = 0x12;

std::uint16_t register_value_from_ratio(std::uint32_t numerator,
                                        std::uint32_t denominator) {
  return static_cast<std::uint16_t>((numerator + denominator / 2) / denominator);
}

}  // namespace

Sx1276Receiver::~Sx1276Receiver() { deinit(); }

ReceiverResult Sx1276Receiver::begin(const ReceiverConfig& config) {
  deinit();

  const std::int64_t tuned_frequency =
      static_cast<std::int64_t>(config.frequency_hz) + config.frequency_offset_hz;
  if (config.spi_host < 1 || config.spi_host > 3 ||
      !GPIO_IS_VALID_OUTPUT_GPIO(config.sck) ||
      !GPIO_IS_VALID_OUTPUT_GPIO(config.mosi) ||
      !GPIO_IS_VALID_GPIO(config.miso) ||
      !GPIO_IS_VALID_OUTPUT_GPIO(config.cs) ||
      !GPIO_IS_VALID_OUTPUT_GPIO(config.reset) ||
      !GPIO_IS_VALID_GPIO(config.dio0) ||
      tuned_frequency < 862000000 || tuned_frequency > 1020000000) {
    return ReceiverResult::kInvalidConfig;
  }

  config_ = config;

  spi_bus_config_t bus_config{};
  bus_config.mosi_io_num = config_.mosi;
  bus_config.miso_io_num = config_.miso;
  bus_config.sclk_io_num = config_.sck;
  bus_config.quadwp_io_num = -1;
  bus_config.quadhd_io_num = -1;
#if ESP_IDF_VERSION_MAJOR >= 5
  bus_config.data4_io_num = -1;
  bus_config.data5_io_num = -1;
  bus_config.data6_io_num = -1;
  bus_config.data7_io_num = -1;
#endif
  bus_config.max_transfer_sz = 64;

  const auto host = static_cast<spi_host_device_t>(config_.spi_host);
  esp_err_t error = spi_bus_initialize(host, &bus_config, SPI_DMA_DISABLED);
  if (error != ESP_OK) {
    return ReceiverResult::kSpiBusError;
  }
  bus_owned_ = true;

  spi_device_interface_config_t device_config{};
  device_config.clock_speed_hz = 4 * 1000 * 1000;
  device_config.mode = 0;
  device_config.spics_io_num = config_.cs;
  device_config.queue_size = 1;

  error = spi_bus_add_device(host, &device_config, &spi_device_);
  if (error != ESP_OK) {
    deinit();
    return ReceiverResult::kSpiDeviceError;
  }

  gpio_config_t reset_config{};
  reset_config.pin_bit_mask = 1ULL << config_.reset;
  reset_config.mode = GPIO_MODE_OUTPUT;
  reset_config.pull_up_en = GPIO_PULLUP_DISABLE;
  reset_config.pull_down_en = GPIO_PULLDOWN_DISABLE;
  reset_config.intr_type = GPIO_INTR_DISABLE;
  if (gpio_config(&reset_config) != ESP_OK) {
    deinit();
    return ReceiverResult::kGpioError;
  }

  gpio_config_t dio_config{};
  dio_config.pin_bit_mask = 1ULL << config_.dio0;
  dio_config.mode = GPIO_MODE_INPUT;
  dio_config.pull_up_en = GPIO_PULLUP_DISABLE;
  dio_config.pull_down_en = GPIO_PULLDOWN_DISABLE;
  dio_config.intr_type = GPIO_INTR_DISABLE;
  if (gpio_config(&dio_config) != ESP_OK) {
    deinit();
    return ReceiverResult::kGpioError;
  }

  gpio_set_level(static_cast<gpio_num_t>(config_.reset), 0);
  esp_rom_delay_us(2000);
  gpio_set_level(static_cast<gpio_num_t>(config_.reset), 1);
  esp_rom_delay_us(10000);

  ReceiverResult result = read_register(kRegVersion, &chip_version_);
  if (result != ReceiverResult::kOk) {
    deinit();
    return result;
  }
  if (chip_version_ != kExpectedChipVersion) {
    deinit();
    return ReceiverResult::kChipNotFound;
  }

  result = configure_radio();
  if (result != ReceiverResult::kOk) {
    deinit();
    return result;
  }

  initialized_ = true;
  return ReceiverResult::kOk;
}

void Sx1276Receiver::deinit() {
  initialized_ = false;
  if (spi_device_ != nullptr) {
    write_register(kRegOpMode, kModeSleepFsk);
    spi_bus_remove_device(spi_device_);
    spi_device_ = nullptr;
  }
  if (bus_owned_) {
    spi_bus_free(static_cast<spi_host_device_t>(config_.spi_host));
    bus_owned_ = false;
  }
  chip_version_ = 0;
}

ReceiverResult Sx1276Receiver::configure_radio() {
  ReceiverResult result = write_register(kRegOpMode, kModeSleepFsk);
  if (result != ReceiverResult::kOk) return result;
  esp_rom_delay_us(1000);
  result = write_register(kRegOpMode, kModeStandbyFsk);
  if (result != ReceiverResult::kOk) return result;

  const std::int64_t frequency_hz =
      static_cast<std::int64_t>(config_.frequency_hz) + config_.frequency_offset_hz;
  const std::uint32_t frf = static_cast<std::uint32_t>(
      (frequency_hz * (1ULL << 19) + kCrystalFrequencyHz / 2) /
      kCrystalFrequencyHz);

  const std::uint16_t bitrate =
      register_value_from_ratio(kCrystalFrequencyHz, kBitRate);
  const std::uint16_t frequency_deviation = static_cast<std::uint16_t>(
      (static_cast<std::uint64_t>(kFrequencyDeviationHz) * (1ULL << 19) +
       kCrystalFrequencyHz / 2) /
      kCrystalFrequencyHz);

  const struct RegisterValue {
    std::uint8_t address;
    std::uint8_t value;
  } settings[] = {
      {kRegBitrateMsb, static_cast<std::uint8_t>(bitrate >> 8)},
      {kRegBitrateLsb, static_cast<std::uint8_t>(bitrate)},
      {kRegFdevMsb, static_cast<std::uint8_t>(frequency_deviation >> 8)},
      {kRegFdevLsb, static_cast<std::uint8_t>(frequency_deviation)},
      {kRegFrfMsb, static_cast<std::uint8_t>(frf >> 16)},
      {kRegFrfMid, static_cast<std::uint8_t>(frf >> 8)},
      {kRegFrfLsb, static_cast<std::uint8_t>(frf)},
      // AFC e AGC automatici; trigger sia su RSSI sia sul preambolo.
      {kRegRxConfig, 0x1F},
      {kRegRssiThreshold, 0xFF},
      // Mantissa 16, esponente 1 -> 250 kHz; DCC frequency predefinita.
      {kRegRxBandwidth, 0x41},
      {kRegAfcBandwidth, 0x41},
      // Il trasmettitore usa 40 bit 0xAA. Ne assorbiamo 8 nel sync word.
      {kRegPreambleMsb, 0x00},
      {kRegPreambleLsb, 0x04},
      // Auto restart con PLL, sync attivo, FIFO dopo sync, 2 byte di sync.
      {kRegSyncConfig, 0x99},
      {kRegSyncValue1, 0xAA},
      {kRegSyncValue2, 0x2D},
      // Pacchetto fisso, NRZ, nessun address filter e nessun CRC radio.
      {kRegPacketConfig1, 0x00},
      {kRegPacketConfig2, 0x40},
      // D4 residuo del sync + 26 byte di payload.
      {kRegPayloadLength, static_cast<std::uint8_t>(kRadioFrameSize)},
      {kRegFifoThreshold, 0x0F},
      // DIO0 = PayloadReady in FSK packet mode.
      {kRegDioMapping1, 0x00},
      {kRegDioMapping2, 0x00},
      // Continuous DAGC, valore raccomandato per la famiglia SX1276.
      {kRegTestDagc, 0x30},
  };

  for (const auto& setting : settings) {
    result = write_register(setting.address, setting.value);
    if (result != ReceiverResult::kOk) return result;
  }

  std::uint8_t lna = 0;
  result = read_register(kRegLna, &lna);
  if (result != ReceiverResult::kOk) return result;
  result = write_register(kRegLna, static_cast<std::uint8_t>(lna | 0x03));
  if (result != ReceiverResult::kOk) return result;

  return restart_receive();
}

ReceiverResult Sx1276Receiver::restart_receive() {
  ReceiverResult result = write_register(kRegOpMode, kModeStandbyFsk);
  if (result != ReceiverResult::kOk) return result;
  esp_rom_delay_us(100);
  return write_register(kRegOpMode, kModeReceiveFsk);
}

ReceiverResult Sx1276Receiver::poll(std::uint8_t* payload26, float* rssi_dbm) {
  if (!initialized_ || payload26 == nullptr || rssi_dbm == nullptr) {
    return ReceiverResult::kNotInitialized;
  }

  if (gpio_get_level(static_cast<gpio_num_t>(config_.dio0)) == 0) {
    return ReceiverResult::kNoPacket;
  }

  std::uint8_t irq_flags = 0;
  ReceiverResult result = read_register(kRegIrqFlags2, &irq_flags);
  if (result != ReceiverResult::kOk) return result;
  if ((irq_flags & kIrqPayloadReady) == 0) {
    return ReceiverResult::kNoPacket;
  }

  std::uint8_t rssi_raw = 0;
  result = read_register(kRegRssiValue, &rssi_raw);
  if (result != ReceiverResult::kOk) return result;

  std::array<std::uint8_t, kRadioFrameSize> frame{};
  result = read_burst(kRegFifo, frame.data(), frame.size());
  const ReceiverResult restart_result = restart_receive();
  if (result != ReceiverResult::kOk) return result;
  if (restart_result != ReceiverResult::kOk) return restart_result;

  *rssi_dbm = -static_cast<float>(rssi_raw) / 2.0F;
  if (frame[0] != 0xD4) {
    return ReceiverResult::kBadSync;
  }

  std::memcpy(payload26, frame.data() + 1, kRadioFrameSize - 1);
  return ReceiverResult::kOk;
}

ReceiverResult Sx1276Receiver::sleep() {
  if (!initialized_) return ReceiverResult::kNotInitialized;
  return write_register(kRegOpMode, kModeSleepFsk);
}

ReceiverResult Sx1276Receiver::wake() {
  if (!initialized_) return ReceiverResult::kNotInitialized;
  return restart_receive();
}

ReceiverResult Sx1276Receiver::write_register(std::uint8_t address,
                                               std::uint8_t value) {
  if (spi_device_ == nullptr) return ReceiverResult::kNotInitialized;

  spi_transaction_t transaction{};
  transaction.flags = SPI_TRANS_USE_TXDATA;
  transaction.length = 16;
  transaction.tx_data[0] = address | 0x80;
  transaction.tx_data[1] = value;
  return spi_device_transmit(spi_device_, &transaction) == ESP_OK
             ? ReceiverResult::kOk
             : ReceiverResult::kTransactionError;
}

ReceiverResult Sx1276Receiver::read_register(std::uint8_t address,
                                              std::uint8_t* value) {
  if (spi_device_ == nullptr || value == nullptr) {
    return ReceiverResult::kNotInitialized;
  }

  spi_transaction_t transaction{};
  transaction.flags = SPI_TRANS_USE_TXDATA | SPI_TRANS_USE_RXDATA;
  transaction.length = 16;
  transaction.tx_data[0] = address & 0x7F;
  transaction.tx_data[1] = 0;
  if (spi_device_transmit(spi_device_, &transaction) != ESP_OK) {
    return ReceiverResult::kTransactionError;
  }
  *value = transaction.rx_data[1];
  return ReceiverResult::kOk;
}

ReceiverResult Sx1276Receiver::read_burst(std::uint8_t address,
                                          std::uint8_t* destination,
                                          std::size_t length) {
  if (spi_device_ == nullptr || destination == nullptr || length == 0 ||
      length + 1 > 64) {
    return ReceiverResult::kInvalidConfig;
  }

  std::array<std::uint8_t, 64> transmit{};
  std::array<std::uint8_t, 64> receive{};
  transmit[0] = address & 0x7F;

  spi_transaction_t transaction{};
  transaction.length = (length + 1) * 8;
  transaction.tx_buffer = transmit.data();
  transaction.rx_buffer = receive.data();
  if (spi_device_transmit(spi_device_, &transaction) != ESP_OK) {
    return ReceiverResult::kTransactionError;
  }

  std::memcpy(destination, receive.data() + 1, length);
  return ReceiverResult::kOk;
}

const char* receiver_result_name(ReceiverResult result) {
  switch (result) {
    case ReceiverResult::kOk:
      return "ok";
    case ReceiverResult::kNoPacket:
      return "no_packet";
    case ReceiverResult::kBadSync:
      return "bad_sync";
    case ReceiverResult::kNotInitialized:
      return "not_initialized";
    case ReceiverResult::kInvalidConfig:
      return "invalid_config";
    case ReceiverResult::kSpiBusError:
      return "spi_bus_error";
    case ReceiverResult::kSpiDeviceError:
      return "spi_device_error";
    case ReceiverResult::kGpioError:
      return "gpio_error";
    case ReceiverResult::kChipNotFound:
      return "chip_not_found";
    case ReceiverResult::kTransactionError:
      return "transaction_error";
  }
  return "unknown";
}

}  // namespace bresser
