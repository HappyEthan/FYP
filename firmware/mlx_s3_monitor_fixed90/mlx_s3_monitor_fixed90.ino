// 触觉毛笔 · MLX90393 monitor 兼容固件 fixed90
// Board: Seeed XIAO ESP32-S3; SDA=D8/GPIO7; SCL=D9/GPIO8.
// Data protocol remains: t_us,Bx_uT,By_uT,Bz_uT @115200.
// Lines beginning with '#' are diagnostics and are ignored by monitor.
// Host command: REBOOT\n; acknowledge, restart ESP32, reinitialize MLX90393.

#include <Wire.h>
#include "Adafruit_MLX90393.h"
#include "frame_guard.h"
#include "serial_commands.h"

SerialCommandParser serialCommands;

static const uint32_t SERIAL_BAUD = 115200;
static const uint32_t SAMPLE_INTERVAL_US = 3000;
static const uint8_t MEASURE_DELAY_MS = 2;
static const uint32_t STATUS_INTERVAL_MS = 1000;
static const uint32_t RETRY_DELAY_MS = 2000;

struct PinPair {
  uint8_t sda;
  uint8_t scl;
};

static const PinPair PRIMARY = {7, 8};
static const PinPair FALLBACK[] = {
    {8, 7}, {3, 2}, {2, 3}, {5, 6}, {6, 5}, {1, 2}, {4, 5}};
static const size_t N_FALLBACK = sizeof(FALLBACK) / sizeof(FALLBACK[0]);
static const uint8_t CAND_ADDRS[] = {0x0C, 0x0D, 0x1E, 0x1F};
static const size_t N_CAND = sizeof(CAND_ADDRS) / sizeof(CAND_ADDRS[0]);

// 400 kHz preserves the existing 333 Hz operating point. If physical-layer
// errors continue after connector/pull-up checks, test 100000 here and compare
// the reported drop/read_err rates.
static const uint32_t I2C_CLOCK = 400000;
static const uint16_t I2C_TIMEOUT_MS = 10;

static const mlx90393_gain_t CFG_GAIN = MLX90393_GAIN_1X;
static const mlx90393_resolution_t CFG_RES = MLX90393_RES_16;
static const mlx90393_oversampling_t CFG_OSR = MLX90393_OSR_0;
static const mlx90393_filter_t CFG_FILTER = MLX90393_FILTER_0;

struct SensorTransport {
  Adafruit_MLX90393 sensor;
  bool bound = false;
};

// Keep one transport per candidate address. BusIO holds &Wire, so changing
// Wire's pin pair does not require rebinding a driver to that same address.
SensorTransport transports[N_CAND];
Adafruit_MLX90393* activeSensor = nullptr;
uint8_t mlxAddr = 0;
uint8_t activeSda = PRIMARY.sda;
uint8_t activeScl = PRIMARY.scl;

FrameGuard frameGuard(1000.0f, 250.0f, 5.0f);
AcquisitionStats acquisitionStats{};
uint32_t lastSampleUs = 0;
uint32_t lastStatusMs = 0;
uint32_t windowCount = 0;
float windowMaxMag = 0.0f;

void handleSerialCommands() {
  while (Serial.available()) {
    if (serialCommands.feed(static_cast<char>(Serial.read()))) {
      Serial.println("# fw=fixed90 reboot requested");
      Serial.flush();
      // Give the host time to receive the ACK before native USB disconnects.
      delay(200);
      ESP.restart();
    }
  }
}

void configureWire(uint8_t sda, uint8_t scl) {
  Wire.end();
  delay(2);
  Wire.begin(sda, scl);
  Wire.setClock(I2C_CLOCK);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
}

uint8_t scanCandidates() {
  for (size_t i = 0; i < N_CAND; ++i) {
    Wire.beginTransmission(CAND_ADDRS[i]);
    if (Wire.endTransmission() == 0) return CAND_ADDRS[i];
  }
  return 0;
}

bool configureSensor(Adafruit_MLX90393& sensor) {
  if (!sensor.setGain(CFG_GAIN)) return false;
  if (!sensor.setResolution(MLX90393_X, CFG_RES)) return false;
  if (!sensor.setResolution(MLX90393_Y, CFG_RES)) return false;
  if (!sensor.setResolution(MLX90393_Z, CFG_RES)) return false;
  if (!sensor.setOversampling(CFG_OSR)) return false;
  if (!sensor.setFilter(CFG_FILTER)) return false;
  return true;
}

bool initSensor(uint8_t address) {
  for (size_t i = 0; i < N_CAND; ++i) {
    if (CAND_ADDRS[i] != address) continue;
    SensorTransport& transport = transports[i];
    Adafruit_MLX90393& sensor = transport.sensor;
    bool ok;
    if (!transport.bound) {
      // Even a failed begin_I2C allocates the device. In Adafruit MLX90393
      // 2.0.5 a second call deletes it and then dereferences the stale pointer.
      transport.bound = true;
      ok = sensor.begin_I2C(address, &Wire);
    } else {
      ok = sensor.exitMode() && sensor.reset() && sensor.setTrigInt(false);
    }
    Wire.setTimeOut(I2C_TIMEOUT_MS);
    if (!ok) {
      Serial.println("# fw=fixed90 init stage=driver failed");
      return false;
    }
    if (!configureSensor(sensor)) {
      Serial.println("# fw=fixed90 init stage=configuration failed");
      return false;
    }
    activeSensor = &sensor;
    return true;
  }
  return false;
}

bool tryPinPair(const PinPair& pair) {
  configureWire(pair.sda, pair.scl);
  const uint8_t address = scanCandidates();
  Serial.print("# fw=fixed90 probe SDA=");
  Serial.print(pair.sda);
  Serial.print(" SCL=");
  Serial.print(pair.scl);
  if (!address) {
    Serial.println(" no candidate ACK");
    return false;
  }
  Serial.print(" addr=0x");
  if (address < 16) Serial.print('0');
  Serial.println(address, HEX);
  if (!initSensor(address)) return false;
  activeSda = pair.sda;
  activeScl = pair.scl;
  mlxAddr = address;
  return true;
}

bool probeAndInit() {
  if (tryPinPair(PRIMARY)) return true;
  for (size_t i = 0; i < N_FALLBACK; ++i) {
    if (tryPinPair(FALLBACK[i])) return true;
  }
  mlxAddr = 0;
  return false;
}

bool readSensor(MagFrame& frame) {
  if (!activeSensor || !activeSensor->startSingleMeasurement()) return false;
  delay(MEASURE_DELAY_MS);
  return activeSensor->readMeasurement(&frame.x, &frame.y, &frame.z);
}

bool recoverSensor() {
  Serial.print("# fw=fixed90 recovery start SDA=");
  Serial.print(activeSda);
  Serial.print(" SCL=");
  Serial.print(activeScl);
  Serial.print(" addr=0x");
  if (mlxAddr < 16) Serial.print('0');
  Serial.println(mlxAddr, HEX);

  configureWire(activeSda, activeScl);
  const bool ok = mlxAddr && initSensor(mlxAddr);
  Serial.println(ok ? "# fw=fixed90 recovery ok"
                    : "# fw=fixed90 recovery failed");
  return ok;
}

struct SensorReader {
  bool operator()(MagFrame& frame) { return readSensor(frame); }
};

struct SensorRecoverer {
  bool operator()() { return recoverSensor(); }
};

bool warmupAndSeed() {
  MagFrame frame{};
  double sx = 0.0, sy = 0.0, sz = 0.0;
  int collected = 0;
  for (int attempt = 0; attempt < 500 && collected < 100; ++attempt) {
    if (!readSensor(frame)) continue;
    sx += frame.x;
    sy += frame.y;
    sz += frame.z;
    ++collected;
    if (collected <= 20) delay(5);
  }
  if (collected < 100) {
    Serial.print("# fw=fixed90 init stage=warmup failed collected=");
    Serial.print(collected);
    Serial.println("/100");
    return false;
  }

  const MagFrame baseline{
      static_cast<float>(sx / collected),
      static_cast<float>(sy / collected),
      static_cast<float>(sz / collected)};
  frameGuard.commit(baseline);
  Serial.print("# fw=fixed90 seed B=(");
  Serial.print(baseline.x, 1);
  Serial.print(',');
  Serial.print(baseline.y, 1);
  Serial.print(',');
  Serial.print(baseline.z, 1);
  Serial.println(") uT");
  return true;
}

void printStatus() {
  const uint32_t now = millis();
  const uint32_t elapsed = now - lastStatusMs;
  const float rate = elapsed ? windowCount * 1000.0f / elapsed : 0.0f;
  Serial.print("# fw=fixed90 rate=");
  Serial.print(rate, 1);
  Serial.print("Hz max=");
  Serial.print(windowMaxMag, 1);
  Serial.print("uT ok=");
  Serial.print(acquisitionStats.goodFrames);
  Serial.print(" drop=");
  Serial.print(acquisitionStats.droppedFrames);
  Serial.print(" read_err=");
  Serial.print(acquisitionStats.readErrors);
  Serial.print(" suspect=");
  Serial.print(acquisitionStats.suspectFrames);
  Serial.print(" retry=");
  Serial.print(acquisitionStats.retries);
  Serial.print(" recovery=");
  Serial.print(acquisitionStats.recoveries);
  Serial.print('/');
  Serial.print(acquisitionStats.recoveryAttempts);
  Serial.print(" SDA=");
  Serial.print(activeSda);
  Serial.print(" SCL=");
  Serial.print(activeScl);
  Serial.print(" addr=0x");
  if (mlxAddr < 16) Serial.print('0');
  Serial.println(mlxAddr, HEX);
  lastStatusMs = now;
  windowCount = 0;
  windowMaxMag = 0.0f;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  const uint32_t serialWaitStart = millis();
  while (!Serial && millis() - serialWaitStart < 4000) delay(10);
  Serial.println();
  Serial.println("# MLX90393 monitor fixed90 @ XIAO ESP32-S3");
  Serial.println("# fw=fixed90 build=xiao-init-retry-safe-v1");

  while (!probeAndInit() || !warmupAndSeed()) {
    Serial.println("# fw=fixed90 init failed; retry in 2s");
    delay(RETRY_DELAY_MS);
  }

  Serial.print("# fw=fixed90 ready SDA=");
  Serial.print(activeSda);
  Serial.print(" SCL=");
  Serial.print(activeScl);
  Serial.print(" addr=0x");
  if (mlxAddr < 16) Serial.print('0');
  Serial.println(mlxAddr, HEX);
  Serial.println("READY");
  lastSampleUs = micros();
  lastStatusMs = millis();
}

void loop() {
  handleSerialCommands();
  const uint32_t nowUs = micros();
  if (nowUs - lastSampleUs < SAMPLE_INTERVAL_US) return;
  lastSampleUs += SAMPLE_INTERVAL_US;
  if (nowUs - lastSampleUs > SAMPLE_INTERVAL_US) lastSampleUs = nowUs;

  SensorReader reader;
  SensorRecoverer recoverer;
  MagFrame frame{};
  if (acquireGuardedFrame(frameGuard, reader, recoverer, acquisitionStats,
                          frame)) {
    Serial.print(micros());
    Serial.print(',');
    Serial.print(frame.x, 3);
    Serial.print(',');
    Serial.print(frame.y, 3);
    Serial.print(',');
    Serial.println(frame.z, 3);
    ++windowCount;
    const float magnitude =
        sqrt(frame.x * frame.x + frame.y * frame.y + frame.z * frame.z);
    if (magnitude > windowMaxMag) windowMaxMag = magnitude;
  }

  if (millis() - lastStatusMs >= STATUS_INTERVAL_MS) printStatus();
}
