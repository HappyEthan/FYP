#pragma once

#include <cstdint>
#include <iomanip>
#include <set>
#include <sstream>
#include <string>

static uint64_t fakeUs = 0;
inline uint32_t micros() { return static_cast<uint32_t>(fakeUs); }
inline uint32_t millis() { return static_cast<uint32_t>(fakeUs / 1000); }
inline void delay(uint32_t ms) { fakeUs += ms * 1000; }
static const int HEX = 16;

struct FakeSerial {
  std::ostringstream output;
  void begin(uint32_t) {}
  explicit operator bool() const { return true; }
  int available() const { return 0; }
  int read() { return -1; }
  void flush() {}
  template <typename T> void print(const T& value) { output << value; }
  void print(uint8_t value) { output << static_cast<unsigned>(value); }
  void print(uint8_t value, int base) {
    if (base == HEX) output << std::uppercase << std::hex;
    output << static_cast<unsigned>(value) << std::dec;
  }
  void print(float value, int digits) {
    output << std::fixed << std::setprecision(digits) << value;
  }
  void println() { output << '\n'; }
  template <typename T> void println(const T& value) {
    print(value);
    println();
  }
  void println(uint8_t value, int base) { print(value, base); println(); }
  void println(float value, int digits) { print(value, digits); println(); }
  std::string text() const { return output.str(); }
  void clear() { output.str(""); output.clear(); }
};
static FakeSerial Serial;
struct FakeEsp { void restart() {} };
static FakeEsp ESP;

struct TwoWire {
  std::set<uint8_t> connected;
  uint8_t address = 0;
  void end() {}
  void begin(uint8_t, uint8_t) {}
  void setClock(uint32_t) {}
  void setTimeOut(uint16_t) {}
  void beginTransmission(uint8_t value) { address = value; }
  uint8_t endTransmission() {
    fakeUs += 25;
    return connected.count(address) ? 0 : 2;
  }
};
static TwoWire Wire;
