#pragma once
// Host-only Arduino I/O/time shim. Motion logic uses the real AccelStepper library.
#include <cstdint>
#include <cstdio>
#include <cmath>
#include <string>
#include <algorithm>
using boolean = bool;
using std::min; using std::max;
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define constrain(x,a,b) ((x)<(a)?(a):((x)>(b)?(b):(x)))
extern unsigned long fakeMicros;
inline unsigned long micros() { return fakeMicros; }
inline unsigned long millis() { return fakeMicros / 1000; }
inline void delayMicroseconds(unsigned long n) { fakeMicros += n; }
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline void yield() {}
struct FakeSerial {
  std::string input, output;
  int capacity = 4096;
  bool online = true;
  void begin(int) {}
  operator bool() { return online; }
  int availableForWrite() { return capacity; }
  int available() { return (int)input.size(); }
  int read() { char c = input[0]; input.erase(0, 1); return c; }
  size_t write(const uint8_t *s, size_t n) { output.append((const char *)s, n); return n; }
  size_t write(char c) { output += c; return 1; }
};
extern FakeSerial Serial;
