#include <Arduino.h>
#include <AccelStepper.h>  // AccelStepper 1.64.0
#include <math.h>

// ===== HBS57 单轴：共阳 + 外部低侧驱动接口 =====
// GPIO4/5 不应直接接 HBS57 输入端，必须经过 NMOS/NPN/ULN/光耦接口。
constexpr uint8_t STEP_PIN = 4;  // 接口板输入 -> HBS57 PU-
constexpr uint8_t DIR_PIN  = 5;  // 接口板输入 -> HBS57 DR-

// 低侧接口若为“GPIO 高电平 -> 下拉导通”，保持 false。
// 若实际波形极性相反，再改为 true。
constexpr bool DIR_INVERT  = false;
constexpr bool STEP_INVERT = false;

constexpr float DEFAULT_MAX_SPEED = 10.0f;  // 脉冲/秒，首轮低速
constexpr float DEFAULT_ACCEL     = 10.0f;   // 脉冲/秒^2
constexpr uint16_t MIN_PULSE_US   = 20;      // HBS57 要求至少约 2.5 us

AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
bool armed = false;

void printHelp() {
  Serial.println();
  Serial.println("AccelStepper HBS57 Z-axis test");
  Serial.println("  ARM");
  Serial.println("  DISARM");
  Serial.println("  MOVE <relative_pulses> <speed_hz>");
  Serial.println("      example: MOVE 10 10");
  Serial.println("  SPEED <speed_hz>");
  Serial.println("  ACCEL <steps_per_s2>");
  Serial.println("  STOP");
  Serial.println("  ZERO");
  Serial.println("  STATUS");
  Serial.println("  HELP");
  Serial.println();
}

void printStatus() {
  Serial.print("armed=");
  Serial.print(armed ? 1 : 0);
  Serial.print(" current=");
  Serial.print(stepper.currentPosition());
  Serial.print(" target=");
  Serial.print(stepper.targetPosition());
  Serial.print(" remaining=");
  Serial.print(stepper.distanceToGo());
  Serial.print(" speed=");
  Serial.println(stepper.speed(), 2);
}

void emergencySoftwareStop() {
  // 软件停止；硬件急停仍需独立实现。
  stepper.moveTo(stepper.currentPosition());
  stepper.setSpeed(0);
}

void handleCommand(String line) {
  line.replace("\r", "");
  line.trim();
  if (line.length() == 0) return;
  line.toUpperCase();

  int split = line.indexOf(' ');
  String command = (split >= 0) ? line.substring(0, split) : line;
  String args = (split >= 0) ? line.substring(split + 1) : "";
  command.trim();
  args.trim();

  if (command == "ARM") {
    armed = true;
    stepper.enableOutputs();
    Serial.println("OK ARM");
    return;
  }

  if (command == "DISARM") {
    armed = false;
    emergencySoftwareStop();
    Serial.println("OK DISARM");
    return;
  }

  if (command == "STOP") {
    emergencySoftwareStop();
    Serial.println("OK STOP");
    return;
  }

  if (command == "ZERO") {
    if (stepper.distanceToGo() != 0) {
      Serial.println("ERR BUSY");
      return;
    }
    stepper.setCurrentPosition(0);
    Serial.println("OK ZERO");
    return;
  }

  if (command == "STATUS") {
    printStatus();
    return;
  }

  if (command == "HELP") {
    printHelp();
    return;
  }

  float value;
  if (command == "SPEED" && sscanf(args.c_str(), "%f", &value) == 1 && value > 0.0f) {
    stepper.setMaxSpeed(value);
    Serial.print("OK SPEED ");
    Serial.println(value, 2);
    return;
  }

  if (command == "ACCEL" && sscanf(args.c_str(), "%f", &value) == 1 && value > 0.0f) {
    stepper.setAcceleration(value);
    Serial.print("OK ACCEL ");
    Serial.println(value, 2);
    return;
  }

  long pulses;
  float speedHz;
  if (command == "MOVE" && sscanf(args.c_str(), "%ld %f", &pulses, &speedHz) == 2) {
    if (!armed) {
      Serial.println("ERR NOT_ARMED");
      return;
    }
    if (pulses == 0 || speedHz <= 0.0f) {
      Serial.println("ERR BAD_MOVE");
      return;
    }

    stepper.setMaxSpeed(fabs(speedHz));
    stepper.move(pulses);  // 相对移动，单位是脉冲
    Serial.print("OK MOVE target=");
    Serial.print(stepper.targetPosition());
    Serial.print(" speed=");
    Serial.println(speedHz, 2);
    return;
  }

  Serial.print("ERR UNKNOWN_COMMAND [");
  Serial.print(line);
  Serial.println("]");
}

void setup() {
  Serial.begin(115200);
  delay(300);

  // 共阳 + 低侧接口时，GPIO 默认不反相；若实测接口波形反相，修改上面的 STEP_INVERT/DIR_INVERT。
  stepper.setPinsInverted(DIR_INVERT, STEP_INVERT, false);
  stepper.setMinPulseWidth(MIN_PULSE_US);
  stepper.setMaxSpeed(DEFAULT_MAX_SPEED);
  stepper.setAcceleration(DEFAULT_ACCEL);
  stepper.setCurrentPosition(0);
  stepper.enableOutputs();
  emergencySoftwareStop();

  Serial.println("HBS57 Z-axis AccelStepper 1.64.0 ready");
  Serial.println("STEP=GPIO4, DIR=GPIO5, ENA/ALM unused");
  Serial.println("Units: pulses and pulses/second");
  printHelp();
}

void loop() {
  // AccelStepper 必须被高频调用，不能在 loop 中长时间 delay。
  stepper.run();

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }
}
