#pragma once

#include "Wire.h"
#include <stdexcept>

enum mlx90393_gain_t { MLX90393_GAIN_1X };
enum mlx90393_resolution_t { MLX90393_RES_16 };
enum mlx90393_oversampling_t { MLX90393_OSR_0 };
enum mlx90393_filter_t { MLX90393_FILTER_0 };
enum mlx90393_axis { MLX90393_X, MLX90393_Y, MLX90393_Z };

static std::set<uint8_t> fakeMlxAddresses;
static bool fakeReadFailures[128]{};
static bool fakeClearFailureOnReset[128]{};
static unsigned fakeBegins[128]{};
static unsigned fakeResets[128]{};

class Adafruit_MLX90393 {
 public:
  bool begin_I2C(uint8_t address, TwoWire*) {
    if (bound_) throw std::runtime_error("driver rebound: repeated begin_I2C");
    address_ = address;
    bound_ = true;
    ++fakeBegins[address];
    return fakeMlxAddresses.count(address);
  }
  bool exitMode() { return fakeMlxAddresses.count(address_); }
  bool reset() {
    ++fakeResets[address_];
    if (fakeClearFailureOnReset[address_]) fakeReadFailures[address_] = false;
    return fakeMlxAddresses.count(address_);
  }
  bool setGain(mlx90393_gain_t) { return true; }
  bool setResolution(mlx90393_axis, mlx90393_resolution_t) { return true; }
  bool setOversampling(mlx90393_oversampling_t) { return true; }
  bool setFilter(mlx90393_filter_t) { return true; }
  bool setTrigInt(bool) { return true; }
  bool startSingleMeasurement() {
    fakeUs += 25;
    return fakeMlxAddresses.count(address_) && !fakeReadFailures[address_];
  }
  bool readMeasurement(float* x, float* y, float* z) {
    fakeUs += 25;
    if (!fakeMlxAddresses.count(address_) || fakeReadFailures[address_]) return false;
    if (address_ == 0x0C) { *x = 100; *y = 200; *z = 300; }
    else { *x = 700; *y = 800; *z = 900; }
    return true;
  }
 private:
  uint8_t address_ = 0;
  bool bound_ = false;
};
