#include <Arduino.h>

// 仅验证 GPIO35/接口板是否能翻转，不连接 HBS57 24 V 动力。
// 如果 ESP32-S3 是 N8R8/N32R16V 等 Octal 模组，请换用 GPIO4。
constexpr int TEST_PIN = 35;

void setup() {
  pinMode(TEST_PIN, OUTPUT);
  digitalWrite(TEST_PIN, LOW);
  Serial.begin(115200);
  delay(300);
  Serial.println("GPIO slow test ready");
}

void loop() {
  digitalWrite(TEST_PIN, HIGH);
  Serial.println("GPIO35 HIGH");
  delay(500);

  digitalWrite(TEST_PIN, LOW);
  Serial.println("GPIO35 LOW");
  delay(500);
}
