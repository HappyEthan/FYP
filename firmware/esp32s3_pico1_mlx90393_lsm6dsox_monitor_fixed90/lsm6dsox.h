#pragma once

#include <Arduino.h>
#include <Wire.h>

struct ImuSample {
  float ax_g = 0.0f;
  float ay_g = 0.0f;
  float az_g = 0.0f;
  float gx_dps = 0.0f;
  float gy_dps = 0.0f;
  float gz_dps = 0.0f;
  float temperature_c = 0.0f;
};

class Lsm6dsox {
 public:
  static constexpr uint8_t DEFAULT_ADDRESS = 0x6A;
  static constexpr uint8_t WHO_AM_I_REGISTER = 0x0F;
  static constexpr uint8_t WHO_AM_I_VALUE = 0x6C;

  bool begin(TwoWire& wire, uint8_t address = DEFAULT_ADDRESS) {
    wire_ = &wire;
    address_ = address;
    uint8_t whoAmI = 0;
    if (!readRegister(WHO_AM_I_REGISTER, whoAmI) || whoAmI != WHO_AM_I_VALUE) return false;
    if (!writeRegister(CTRL3_C, CTRL3_C_SW_RESET)) return false;
    delay(20);
    if (!writeRegister(CTRL3_C, CTRL3_C_BDU | CTRL3_C_IF_INC)) return false;
    if (!writeRegister(CTRL1_XL, CTRL1_XL_ODR_104HZ | CTRL1_XL_FS_4G)) return false;
    if (!writeRegister(CTRL2_G, CTRL2_G_ODR_104HZ | CTRL2_G_FS_500DPS)) return false;
    return true;
  }

  bool readSample(ImuSample& sample) {
    uint8_t raw[14]{};
    if (!readRegisters(OUT_TEMP_L, raw, sizeof(raw))) return false;
    const int16_t temperatureRaw = static_cast<int16_t>(raw[0] | (raw[1] << 8));
    const int16_t gxRaw = static_cast<int16_t>(raw[2] | (raw[3] << 8));
    const int16_t gyRaw = static_cast<int16_t>(raw[4] | (raw[5] << 8));
    const int16_t gzRaw = static_cast<int16_t>(raw[6] | (raw[7] << 8));
    const int16_t axRaw = static_cast<int16_t>(raw[8] | (raw[9] << 8));
    const int16_t ayRaw = static_cast<int16_t>(raw[10] | (raw[11] << 8));
    const int16_t azRaw = static_cast<int16_t>(raw[12] | (raw[13] << 8));
    sample.temperature_c = 25.0f + static_cast<float>(temperatureRaw) / 16.0f;
    sample.gx_dps = static_cast<float>(gxRaw) * 0.0175f;
    sample.gy_dps = static_cast<float>(gyRaw) * 0.0175f;
    sample.gz_dps = static_cast<float>(gzRaw) * 0.0175f;
    sample.ax_g = static_cast<float>(axRaw) * 0.000122f;
    sample.ay_g = static_cast<float>(ayRaw) * 0.000122f;
    sample.az_g = static_cast<float>(azRaw) * 0.000122f;
    return true;
  }

 private:
  static constexpr uint8_t CTRL1_XL = 0x10;
  static constexpr uint8_t CTRL2_G = 0x11;
  static constexpr uint8_t CTRL3_C = 0x12;
  static constexpr uint8_t OUT_TEMP_L = 0x20;
  static constexpr uint8_t CTRL1_XL_ODR_104HZ = 0x40;
  static constexpr uint8_t CTRL1_XL_FS_4G = 0x08;
  static constexpr uint8_t CTRL2_G_ODR_104HZ = 0x40;
  static constexpr uint8_t CTRL2_G_FS_500DPS = 0x04;
  static constexpr uint8_t CTRL3_C_SW_RESET = 0x01;
  static constexpr uint8_t CTRL3_C_BDU = 0x40;
  static constexpr uint8_t CTRL3_C_IF_INC = 0x04;

  bool writeRegister(uint8_t reg, uint8_t value) {
    wire_->beginTransmission(address_);
    wire_->write(reg);
    wire_->write(value);
    return wire_->endTransmission() == 0;
  }

  bool readRegister(uint8_t reg, uint8_t& value) {
    return readRegisters(reg, &value, 1);
  }

  bool readRegisters(uint8_t reg, uint8_t* values, size_t length) {
    wire_->beginTransmission(address_);
    wire_->write(reg);
    if (wire_->endTransmission(false) != 0) return false;
    const uint8_t received = wire_->requestFrom(static_cast<int>(address_),
                                                 static_cast<int>(length), true);
    if (received != length) return false;
    for (size_t i = 0; i < length; ++i) values[i] = wire_->read();
    return true;
  }

  TwoWire* wire_ = nullptr;
  uint8_t address_ = DEFAULT_ADDRESS;
};
