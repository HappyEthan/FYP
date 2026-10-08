#include <Adafruit_MLX90393.h>
#include <Wire.h>
#include <esp_timer.h>

// 0: 原始磁场 CSV：t_us,Bx,By,Bz（单位 uT）
// 1: Arduino Serial Plotter：dBx/dBy/dBz（三条平滑显示曲线）
// 2: 真实 Delta B CSV：t_us,dBx,dBy,dBz（单位 uT，未经平滑）
#ifndef SENSOR_OUTPUT_MODE
#define SENSOR_OUTPUT_MODE 1
#endif
constexpr uint8_t OUTPUT_RAW_CSV = 0;
constexpr uint8_t OUTPUT_PLOTTER = 1;
constexpr uint8_t OUTPUT_DELTA_CSV = 2;
constexpr uint8_t OUTPUT_MODE = SENSOR_OUTPUT_MODE;
static_assert(OUTPUT_MODE <= OUTPUT_DELTA_CSV, "invalid SENSOR_OUTPUT_MODE");
constexpr bool PLOTTER_MODE = OUTPUT_MODE == OUTPUT_PLOTTER;

constexpr uint8_t SENSOR_ADDRESS = 0x0E;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr int64_t SAMPLE_PERIOD_US = 10000;   // 100 Hz
constexpr uint32_t CONVERSION_WAIT_US = 4000;
constexpr uint16_t SETTLE_SAMPLES = 50;       // 启动后先丢弃 0.5 s
constexpr uint16_t BASELINE_SAMPLES = 200;    // 未按压静止采 2 s

// 只平滑 Plotter 显示，不改变 CSV 模式中的原始 B。
constexpr bool SMOOTH_PLOT = true;
constexpr float EMA_ALPHA = 0.25f;

constexpr uint8_t CONFIG_REGISTER_1 = 0x01;
constexpr uint16_t TCMP_EN_MASK = 0x0400;     // register 0x01, bit 10

Adafruit_MLX90393 sensor;

float b0_x = 0.0f;
float b0_y = 0.0f;
float b0_z = 0.0f;
float filtered_x = 0.0f;
float filtered_y = 0.0f;
float filtered_z = 0.0f;
int64_t next_sample_us = 0;

bool status_ok(uint8_t status) {
  return (status >> 2) == MLX90393_STATUS_OK;
}

void drain_wire() {
  while (Wire.available()) {
    Wire.read();
  }
}

bool read_register(uint8_t address, uint16_t &value) {
  Wire.beginTransmission(SENSOR_ADDRESS);
  Wire.write(MLX90393_REG_RR);
  Wire.write(static_cast<uint8_t>(address << 2));
  if (Wire.endTransmission() != 0) {
    return false;
  }

  if (Wire.requestFrom(SENSOR_ADDRESS, static_cast<uint8_t>(3)) != 3) {
    drain_wire();
    return false;
  }

  const uint8_t status = Wire.read();
  if (!status_ok(status)) {
    drain_wire();
    return false;
  }

  value = (static_cast<uint16_t>(Wire.read()) << 8) | Wire.read();
  return true;
}

bool write_register(uint8_t address, uint16_t value) {
  // WR 只修改易失 RAM，不写入 NVRAM。
  Wire.beginTransmission(SENSOR_ADDRESS);
  Wire.write(MLX90393_REG_WR);
  Wire.write(static_cast<uint8_t>(value >> 8));
  Wire.write(static_cast<uint8_t>(value & 0xFF));
  Wire.write(static_cast<uint8_t>(address << 2));
  if (Wire.endTransmission() != 0) {
    return false;
  }

  if (Wire.requestFrom(SENSOR_ADDRESS, static_cast<uint8_t>(1)) != 1) {
    drain_wire();
    return false;
  }
  return status_ok(Wire.read());
}

bool configure_signed_output() {
  uint16_t config = 0;
  if (!read_register(CONFIG_REGISTER_1, config)) {
    return false;
  }

  config &= static_cast<uint16_t>(~TCMP_EN_MASK);
  if (!write_register(CONFIG_REGISTER_1, config)) {
    return false;
  }

  uint16_t verified = 0;
  return read_register(CONFIG_REGISTER_1, verified) &&
         (verified & TCMP_EN_MASK) == 0;
}

bool read_field(float &bx, float &by, float &bz) {
  if (!sensor.startSingleMeasurement()) {
    return false;
  }
  delayMicroseconds(CONVERSION_WAIT_US);
  return sensor.readMeasurement(&bx, &by, &bz);
}

void wait_until(int64_t deadline_us) {
  while (true) {
    const int64_t remaining_us = deadline_us - esp_timer_get_time();
    if (remaining_us <= 0) {
      return;
    }
    if (remaining_us > 1200) {
      delay(1);
    } else {
      delayMicroseconds(static_cast<uint32_t>(remaining_us));
    }
  }
}

void halt_with_error(const char *message) {
  if (!PLOTTER_MODE) {
    Serial.print("# ERROR ");
    Serial.println(message);
  }
#ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
#endif
  while (true) {
#ifdef LED_BUILTIN
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
#endif
    delay(250);
  }
}

bool calculate_baseline() {
  double sum_x = 0.0;
  double sum_y = 0.0;
  double sum_z = 0.0;
  uint16_t valid_samples = 0;
  uint16_t discarded_samples = 0;
  uint16_t attempts = 0;
  int64_t next_us = esp_timer_get_time();

  while (valid_samples < BASELINE_SAMPLES && attempts < 1000) {
    wait_until(next_us);
    next_us += SAMPLE_PERIOD_US;
    ++attempts;

    float bx = 0.0f;
    float by = 0.0f;
    float bz = 0.0f;
    if (!read_field(bx, by, bz)) {
      continue;
    }

    if (discarded_samples < SETTLE_SAMPLES) {
      ++discarded_samples;
      continue;
    }

    sum_x += bx;
    sum_y += by;
    sum_z += bz;
    ++valid_samples;
  }

  if (valid_samples != BASELINE_SAMPLES) {
    return false;
  }

  b0_x = static_cast<float>(sum_x / BASELINE_SAMPLES);
  b0_y = static_cast<float>(sum_y / BASELINE_SAMPLES);
  b0_z = static_cast<float>(sum_z / BASELINE_SAMPLES);
  return true;
}

void write_line(const char *line, int length) {
  if (length > 0 && Serial.availableForWrite() >= length) {
    Serial.write(reinterpret_cast<const uint8_t *>(line), length);
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin(D1, D2);
  Wire.setClock(400000);

  if (!sensor.begin_I2C(SENSOR_ADDRESS, &Wire)) {
    halt_with_error("sensor_not_found");
  }
  if (!configure_signed_output()) {
    halt_with_error("tcmp_configuration_failed");
  }

  bool configured = true;
  configured &= sensor.setGain(MLX90393_GAIN_1X);
  configured &= sensor.setResolution(MLX90393_X, MLX90393_RES_17);
  configured &= sensor.setResolution(MLX90393_Y, MLX90393_RES_17);
  configured &= sensor.setResolution(MLX90393_Z, MLX90393_RES_16);
  configured &= sensor.setOversampling(MLX90393_OSR_0);
  configured &= sensor.setFilter(MLX90393_FILTER_2);
  if (!configured) {
    halt_with_error("sensor_configuration_failed");
  }

  // 复位后请保持磁化硅胶未按压、静止约 2.5 秒。
  if (!calculate_baseline()) {
    halt_with_error("baseline_failed");
  }

  if (!PLOTTER_MODE) {
    Serial.println("# MLX90393 100Hz units=uT tcmp_en=0");
    Serial.printf("# B0 %.3f,%.3f,%.3f\n", b0_x, b0_y, b0_z);
    if (OUTPUT_MODE == OUTPUT_DELTA_CSV) {
      Serial.println("t_us,dBx,dBy,dBz");
    } else {
      Serial.println("t_us,Bx,By,Bz");
    }
  }

  next_sample_us = esp_timer_get_time();
}

void loop() {
  const int64_t now_us = esp_timer_get_time();
  if (now_us < next_sample_us) {
    wait_until(next_sample_us);
  } else if (now_us - next_sample_us >= SAMPLE_PERIOD_US) {
    // 若串口或系统曾阻塞，不补发旧样本，直接恢复 100 Hz 节拍。
    next_sample_us = now_us;
  }

  const int64_t timestamp_us = esp_timer_get_time();
  next_sample_us += SAMPLE_PERIOD_US;

  float bx = 0.0f;
  float by = 0.0f;
  float bz = 0.0f;
  if (!read_field(bx, by, bz)) {
    return;
  }

  const float dx = bx - b0_x;
  const float dy = by - b0_y;
  const float dz = bz - b0_z;

  char line[96];
  int length = 0;
  if (PLOTTER_MODE) {
    if (SMOOTH_PLOT) {
      filtered_x += EMA_ALPHA * (dx - filtered_x);
      filtered_y += EMA_ALPHA * (dy - filtered_y);
      filtered_z += EMA_ALPHA * (dz - filtered_z);
    } else {
      filtered_x = dx;
      filtered_y = dy;
      filtered_z = dz;
    }

    length = snprintf(line, sizeof(line),
                      "Ymin:-600,dBx:%.2f,dBy:%.2f,dBz:%.2f,Ymax:600\n",
                      filtered_x, filtered_y, filtered_z);
  } else if (OUTPUT_MODE == OUTPUT_DELTA_CSV) {
    length = snprintf(line, sizeof(line), "%lld,%.3f,%.3f,%.3f\n",
                      static_cast<long long>(timestamp_us), dx, dy, dz);
  } else {
    length = snprintf(line, sizeof(line), "%lld,%.3f,%.3f,%.3f\n",
                      static_cast<long long>(timestamp_us), bx, by, bz);
  }

  if (length < static_cast<int>(sizeof(line))) {
    write_line(line, length);
  }
}
