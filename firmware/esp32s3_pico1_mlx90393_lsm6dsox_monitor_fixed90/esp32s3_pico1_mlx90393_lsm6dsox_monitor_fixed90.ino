// MLX90393 multi-address monitor plus LSM6DSOX IMU, ESP32-S3-PICO-1 (8 MB Flash + 8 MB PSRAM) native USB.
// Wiring: SDA=GPIO1, SCL=GPIO2. Scan all non-reserved 7-bit I2C addresses.
// Primary (prefer 0x0C): t_us,Bx_uT,By_uT,Bz_uT, compatible with Monitor.
// Every sensor also emits: # sensor,0xNN,t_us,Bx_uT,By_uT,Bz_uT
// IMU emits: # imu,t_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_C.
// Comment-prefixed streams are ignored by legacy Monitor consumers.
// REBOOT\n retains the fixed90 ACK/READY handshake.

#include <Wire.h>
#include "Adafruit_MLX90393.h"
#include "frame_guard.h"
#include "lsm6dsox.h"
#include "serial_commands.h"

#if !defined(CONFIG_IDF_TARGET_ESP32S3)
#error "Select ESP32S3 Dev Module for the ESP32-S3-PICO-1 firmware."
#endif
#if !defined(ARDUINO_USB_CDC_ON_BOOT) || !ARDUINO_USB_CDC_ON_BOOT
#error "Enable USB CDC On Boot and use the board's native USB port."
#endif

static const uint32_t SERIAL_BAUD = 115200;
static const uint32_t SAMPLE_INTERVAL_US = 3000;
static const uint8_t MEASURE_DELAY_MS = 2;
static const uint32_t STATUS_INTERVAL_MS = 1000;
static const uint32_t RETRY_DELAY_MS = 2000;
static const uint8_t SDA_PIN = 1;
static const uint8_t SCL_PIN = 2;
static const uint32_t I2C_CLOCK = 400000;
static const uint16_t I2C_TIMEOUT_MS = 10;
static const size_t MAX_SENSORS = 8;
static const uint8_t IMU_I2C_ADDRESS = 0x6A;
static const uint32_t IMU_SAMPLE_INTERVAL_US = 10000;

struct SensorSlot {
  Adafruit_MLX90393 sensor;
  uint8_t address = 0;
  bool transportBound = false;
  bool ready = false;
  FrameGuard guard{1000.0f, 250.0f, 5.0f};
  AcquisitionStats stats{};
  uint32_t windowCount = 0;
  float windowMaxMag = 0.0f;
};

SensorSlot slots[MAX_SENSORS];
size_t slotCount = 0;
int primaryIndex = -1;
Lsm6dsox imu;
bool imuReady = false;
bool imuStreamEnabled = true;
SerialCommandParser serialCommands;
uint32_t lastSampleUs = 0;
uint32_t lastImuSampleUs = 0;
uint32_t lastStatusMs = 0;
uint32_t lastRetryMs = 0;
uint32_t lastImuRetryMs = 0;
uint32_t imuWindowCount = 0;
uint32_t imuReadErrors = 0;

void printImuStatus();

void printAddress(uint8_t address) {
  Serial.print("0x");
  if (address < 16) Serial.print('0');
  Serial.print(address, HEX);
}

void handleSerialCommands() {
  while (Serial.available()) {
    const SerialCommand command = serialCommands.feed(static_cast<char>(Serial.read()));
    switch (command) {
      case SerialCommand::Reboot:
        Serial.println("# fw=fixed90 reboot requested");
        Serial.flush();
        delay(200);
        ESP.restart();
        break;
      case SerialCommand::ImuOn:
        imuStreamEnabled = true;
        Serial.println("# imu stream=on");
        break;
      case SerialCommand::ImuOff:
        imuStreamEnabled = false;
        Serial.println("# imu stream=off");
        break;
      case SerialCommand::ImuStatus:
        printImuStatus();
        break;
      case SerialCommand::None:
        break;
    }
  }
}

void printImuFrame(uint32_t timestamp, const ImuSample& sample) {
  Serial.print("# imu,");
  Serial.print(timestamp);
  Serial.print(',');
  Serial.print(sample.ax_g, 6);
  Serial.print(',');
  Serial.print(sample.ay_g, 6);
  Serial.print(',');
  Serial.print(sample.az_g, 6);
  Serial.print(',');
  Serial.print(sample.gx_dps, 4);
  Serial.print(',');
  Serial.print(sample.gy_dps, 4);
  Serial.print(',');
  Serial.print(sample.gz_dps, 4);
  Serial.print(',');
  Serial.println(sample.temperature_c, 2);
}

void printImuStatus() {
  const uint32_t now = millis();
  const uint32_t elapsed = now - lastStatusMs;
  const float rate = elapsed ? imuWindowCount * 1000.0f / elapsed : 0.0f;
  Serial.print("# imu_status ready=");
  Serial.print(imuReady ? 1 : 0);
  Serial.print(" stream=");
  Serial.print(imuStreamEnabled ? 1 : 0);
  Serial.print(" rate=");
  Serial.print(rate, 1);
  Serial.print("Hz ok=");
  Serial.print(imuWindowCount);
  Serial.print(" read_err=");
  Serial.println(imuReadErrors);
  imuWindowCount = 0;
  imuReadErrors = 0;
}

void initializeImu() {
  imuReady = imu.begin(Wire, IMU_I2C_ADDRESS);
  Serial.print(imuReady ? "# imu ready model=LSM6DSOX addr="
                        : "# imu init failed model=LSM6DSOX addr=");
  printAddress(IMU_I2C_ADDRESS);
  Serial.println(" odr=104Hz accel=4g gyro=500dps");
}

void retryImu() {
  if (imuReady) return;
  const uint32_t now = millis();
  if (now - lastImuRetryMs < RETRY_DELAY_MS) return;
  lastImuRetryMs = now;
  initializeImu();
}

void sampleImu(uint32_t nowUs) {
  if (!imuReady || nowUs - lastImuSampleUs < IMU_SAMPLE_INTERVAL_US) return;
  lastImuSampleUs += IMU_SAMPLE_INTERVAL_US;
  if (nowUs - lastImuSampleUs > IMU_SAMPLE_INTERVAL_US) lastImuSampleUs = nowUs;

  ImuSample sample{};
  if (!imu.readSample(sample)) {
    ++imuReadErrors;
    return;
  }
  ++imuWindowCount;
  if (imuStreamEnabled) printImuFrame(micros(), sample);
}

bool configureSensor(SensorSlot& slot) {
  if (!slot.sensor.setGain(MLX90393_GAIN_1X)) return false;
  if (!slot.sensor.setResolution(MLX90393_X, MLX90393_RES_16)) return false;
  if (!slot.sensor.setResolution(MLX90393_Y, MLX90393_RES_16)) return false;
  if (!slot.sensor.setResolution(MLX90393_Z, MLX90393_RES_16)) return false;
  if (!slot.sensor.setOversampling(MLX90393_OSR_0)) return false;
  return slot.sensor.setFilter(MLX90393_FILTER_0);
}

bool readSensor(SensorSlot& slot, MagFrame& frame) {
  if (!slot.sensor.startSingleMeasurement()) return false;
  delay(MEASURE_DELAY_MS);
  return slot.sensor.readMeasurement(&frame.x, &frame.y, &frame.z);
}

bool warmupAndSeed(SensorSlot& slot) {
  MagFrame frame{};
  double sx = 0.0, sy = 0.0, sz = 0.0;
  int collected = 0;
  for (int attempt = 0; attempt < 500 && collected < 100; ++attempt) {
    if (!readSensor(slot, frame) || !std::isfinite(frame.x) ||
        !std::isfinite(frame.y) || !std::isfinite(frame.z)) continue;
    sx += frame.x;
    sy += frame.y;
    sz += frame.z;
    ++collected;
    if (collected <= 20) delay(5);
  }
  if (collected < 100) return false;
  slot.guard.commit(MagFrame{static_cast<float>(sx / collected),
                            static_cast<float>(sy / collected),
                            static_cast<float>(sz / collected)});
  return true;
}

bool resetAndConfigure(SensorSlot& slot) {
  // begin_I2C binds this driver exactly once. Adafruit MLX90393 2.0.5
  // deletes a non-null I2C device without clearing its pointer on re-entry.
  // Recover using commands addressed to the existing device instead.
  return slot.sensor.exitMode() && slot.sensor.reset() && configureSensor(slot);
}

bool initializeSensor(SensorSlot& slot) {
  bool ok;
  if (!slot.transportBound) {
    slot.transportBound = true;
    ok = slot.sensor.begin_I2C(slot.address, &Wire) && configureSensor(slot);
  } else {
    ok = resetAndConfigure(slot);
  }
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  slot.ready = ok && warmupAndSeed(slot);
  return slot.ready;
}

void retryPendingSensors() {
  const uint32_t now = millis();
  if (now - lastRetryMs < RETRY_DELAY_MS) return;
  lastRetryMs = now;
  for (size_t i = 0; i < slotCount; ++i) {
    SensorSlot& slot = slots[i];
    if (slot.ready) continue;
    const bool ok = initializeSensor(slot);
    Serial.print(ok ? "# sensor ready addr=" : "# sensor init failed addr=");
    printAddress(slot.address);
    Serial.println();
  }
}

SensorSlot* findOrAddSlot(uint8_t address) {
  for (size_t i = 0; i < slotCount; ++i) {
    if (slots[i].address == address) return &slots[i];
  }
  if (slotCount == MAX_SENSORS) return nullptr;
  SensorSlot& slot = slots[slotCount++];
  slot.address = address;
  return &slot;
}

bool scanAndInit() {
  Serial.print("# i2c scan SDA=");
  Serial.print(SDA_PIN);
  Serial.print(" SCL=");
  Serial.println(SCL_PIN);
  bool anyReady = false;
  for (uint8_t address = 0x08; address <= 0x77; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() != 0) continue;
    if (address == IMU_I2C_ADDRESS) {
      Serial.print("# i2c addr=");
      printAddress(address);
      Serial.println(" (LSM6DSOX IMU)");
      continue;
    }
    Serial.print("# i2c addr=");
    printAddress(address);
    Serial.println();
    SensorSlot* slot = findOrAddSlot(address);
    if (!slot) {
      Serial.println("# sensor capacity reached; maximum 8 acknowledged devices");
      continue;
    }
    if (slot->ready || initializeSensor(*slot)) {
      anyReady = true;
      Serial.print("# sensor ready addr=");
    } else {
      Serial.print("# sensor init failed addr=");
    }
    printAddress(address);
    Serial.println();
  }
  return anyReady;
}

bool recoverSensor(SensorSlot& slot) {
  Serial.print("# sensor recovery start addr=");
  printAddress(slot.address);
  Serial.println();
  const bool ok = resetAndConfigure(slot);
  Serial.print(ok ? "# sensor recovery ok addr=" : "# sensor recovery failed addr=");
  printAddress(slot.address);
  Serial.println();
  return ok;
}

struct SensorReader {
  SensorSlot& slot;
  bool first;
  bool started;
  SensorReader(SensorSlot& value, bool startOk)
      : slot(value), first(true), started(startOk) {}
  bool operator()(MagFrame& frame) {
    if (!first) return readSensor(slot, frame);
    first = false;
    return started && slot.sensor.readMeasurement(&frame.x, &frame.y, &frame.z);
  }
};

struct SensorRecoverer {
  SensorSlot& slot;
  bool operator()() { return recoverSensor(slot); }
};

void printFrame(uint32_t timestamp, const MagFrame& frame) {
  Serial.print(timestamp);
  Serial.print(',');
  Serial.print(frame.x, 3);
  Serial.print(',');
  Serial.print(frame.y, 3);
  Serial.print(',');
  Serial.println(frame.z, 3);
}

void printStatus() {
  const uint32_t now = millis();
  const uint32_t elapsed = now - lastStatusMs;
  for (size_t i = 0; i < slotCount; ++i) {
    SensorSlot& slot = slots[i];
    if (!slot.ready) continue;
    const float rate = elapsed ? slot.windowCount * 1000.0f / elapsed : 0.0f;
    Serial.print(static_cast<int>(i) == primaryIndex ? "# fw=fixed90 rate="
                                                   : "# sensor_status rate=");
    Serial.print(rate, 1);
    Serial.print("Hz max=");
    Serial.print(slot.windowMaxMag, 1);
    Serial.print("uT ok=");
    Serial.print(slot.stats.goodFrames);
    Serial.print(" drop=");
    Serial.print(slot.stats.droppedFrames);
    Serial.print(" read_err=");
    Serial.print(slot.stats.readErrors);
    Serial.print(" suspect=");
    Serial.print(slot.stats.suspectFrames);
    Serial.print(" retry=");
    Serial.print(slot.stats.retries);
    Serial.print(" recovery=");
    Serial.print(slot.stats.recoveries);
    Serial.print('/');
    Serial.print(slot.stats.recoveryAttempts);
    Serial.print(" SDA=");
    Serial.print(SDA_PIN);
    Serial.print(" SCL=");
    Serial.print(SCL_PIN);
    Serial.print(" addr=");
    printAddress(slot.address);
    Serial.println();
    slot.windowCount = 0;
    slot.windowMaxMag = 0.0f;
  }
  printImuStatus();
  lastStatusMs = now;
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  const uint32_t serialWaitStart = millis();
  while (!Serial && millis() - serialWaitStart < 4000) delay(10);
  Serial.println();
  Serial.println("# MLX90393 multi-address + LSM6DSOX @ ESP32-S3-PICO-1 (8 MB Flash + 8 MB PSRAM, native USB)");
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(I2C_CLOCK);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  initializeImu();
  while (!scanAndInit()) {
    Serial.println("# fw=fixed90 init failed; retry in 2s");
    handleSerialCommands();
    delay(RETRY_DELAY_MS);
  }
  for (size_t i = 0; i < slotCount; ++i) {
    if (!slots[i].ready) continue;
    if (primaryIndex < 0 || slots[i].address == 0x0C) primaryIndex = static_cast<int>(i);
  }
  Serial.print("# fw=fixed90 ready SDA=");
  Serial.print(SDA_PIN);
  Serial.print(" SCL=");
  Serial.print(SCL_PIN);
  Serial.print(" addr=");
  printAddress(slots[primaryIndex].address);
  Serial.println();
  Serial.println("# format: # sensor,addr,t_us,Bx_uT,By_uT,Bz_uT");
  Serial.println("# imu format: # imu,t_us,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps,temp_C");
  Serial.println("READY");
  lastSampleUs = micros();
  lastImuSampleUs = lastSampleUs;
  lastStatusMs = millis();
  lastRetryMs = lastStatusMs;
  lastImuRetryMs = lastStatusMs;
}

void loop() {
  handleSerialCommands();
  retryImu();
  retryPendingSensors();
  const uint32_t nowUs = micros();
  sampleImu(nowUs);
  if (nowUs - lastSampleUs < SAMPLE_INTERVAL_US) return;
  lastSampleUs += SAMPLE_INTERVAL_US;
  if (nowUs - lastSampleUs > SAMPLE_INTERVAL_US) lastSampleUs = nowUs;

  // Start all conversions before waiting, so a second sensor does not add
  // another complete conversion delay to every healthy sampling cycle.
  bool started[MAX_SENSORS]{};
  for (size_t i = 0; i < slotCount; ++i) {
    if (slots[i].ready) started[i] = slots[i].sensor.startSingleMeasurement();
  }
  delay(MEASURE_DELAY_MS);
  for (size_t i = 0; i < slotCount; ++i) {
    SensorSlot& slot = slots[i];
    if (!slot.ready) continue;
    SensorReader reader(slot, started[i]);
    SensorRecoverer recoverer{slot};
    MagFrame frame{};
    if (!acquireGuardedFrame(slot.guard, reader, recoverer, slot.stats, frame)) continue;
    const uint32_t timestamp = micros();
    if (static_cast<int>(i) == primaryIndex) printFrame(timestamp, frame);
    Serial.print("# sensor,");
    printAddress(slot.address);
    Serial.print(',');
    printFrame(timestamp, frame);
    ++slot.windowCount;
    const float magnitude = std::sqrt(frame.x * frame.x + frame.y * frame.y + frame.z * frame.z);
    if (magnitude > slot.windowMaxMag) slot.windowMaxMag = magnitude;
  }
  if (millis() - lastStatusMs >= STATUS_INTERVAL_MS) printStatus();
}
