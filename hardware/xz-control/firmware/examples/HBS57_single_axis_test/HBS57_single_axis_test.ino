#include <Arduino.h>

// 注意：若开发板是 ESP32-S3-WROOM-1-N8R8、WROOM-2-N32R16V 等 Octal
// Flash/PSRAM 变体，GPIO35/36/37 可能被内部存储占用，需改用其他 GPIO。

// ===== 首个电机测试接口 =====
constexpr int STEP_PIN = 35;  // 通过开漏/光耦控制 HBS57 PU-
constexpr int DIR_PIN  = 36;  // 通过开漏/光耦控制 HBS57 DR-
constexpr int ENA_PIN  = 37;  // 通过开漏/光耦控制 HBS57 ENA-
constexpr int ALM_PIN  = 38;  // 通过隔离/电平转换读取 HBS57 ALM

// 你的当前接线没有接 ENA- 和 ALM，因此设为 false。
// 如果以后接入，再改为 true，并确认接口极性。
constexpr bool USE_ENA = false;
constexpr bool USE_ALM = false;

// 共阳接法 + NPN/NMOS/ULN 低侧下拉时：GPIO 高电平 = 下拉导通。
// 如果你的接口板是反相的，把 HIGH 改成 LOW。
constexpr uint8_t SINK_ON_LEVEL = HIGH;
constexpr uint8_t SINK_OFF_LEVEL = (SINK_ON_LEVEL == HIGH) ? LOW : HIGH;

// 方向正向对应 DR- 下拉导通还是断开，需要实机确认。
// 若正负方向反了，把 true 改成 false。
constexpr bool POSITIVE_DIR_SINK_ON = true;

// HBS57 报警接口经隔离后通常使用低电平有效；若相反则改为 HIGH。
constexpr uint8_t ALM_ACTIVE_LEVEL = LOW;

bool armed = false;
uint32_t totalPulses = 0;

void sinkWrite(int pin, bool on) {
  digitalWrite(pin, on ? SINK_ON_LEVEL : SINK_OFF_LEVEL);
}

void setDirection(bool positive) {
  sinkWrite(DIR_PIN, positive ? POSITIVE_DIR_SINK_ON
                              : !POSITIVE_DIR_SINK_ON);
  // HBS57 要求 DIR 在脉冲前提前建立，这里留 10 us。
  delayMicroseconds(10);
}

bool alarmActive() {
  if (!USE_ALM) return false;
  return digitalRead(ALM_PIN) == ALM_ACTIVE_LEVEL;
}

void lockMotor() {
  if (!USE_ENA) return;
  // HBS57 的 ENA 有效时可能使电机进入自由状态；默认关闭 ENA。
  sinkWrite(ENA_PIN, false);
}

void freeMotor() {
  if (!USE_ENA) {
    Serial.println("INFO ENA_UNUSED");
    return;
  }
  sinkWrite(ENA_PIN, true);
}

void stopPulseOutput() {
  sinkWrite(STEP_PIN, false);
}

bool movePulses(int32_t signedPulses, uint32_t frequencyHz) {
  if (!armed) {
    Serial.println("ERR NOT_ARMED");
    return false;
  }
  if (signedPulses == 0) {
    Serial.println("OK ZERO_PULSES");
    return true;
  }
  if (frequencyHz < 1 || frequencyHz > 2000) {
    Serial.println("ERR FREQ_1_TO_2000_HZ");
    return false;
  }
  if (alarmActive()) {
    Serial.println("ERR ALARM_ACTIVE");
    return false;
  }

  bool positive = signedPulses > 0;
  uint32_t count = positive ? (uint32_t)signedPulses
                            : (uint32_t)(-(int64_t)signedPulses);
  setDirection(positive);

  const uint32_t periodUs = 1000000UL / frequencyHz;
  const uint32_t highUs = 5;  // HBS57 要求至少约 2.5 us
  if (periodUs <= highUs + 5) {
    Serial.println("ERR PERIOD_TOO_SHORT");
    return false;
  }
  const uint32_t lowUs = periodUs - highUs;

  for (uint32_t i = 0; i < count; ++i) {
    if (alarmActive()) {
      stopPulseOutput();
      Serial.println("ERR ALARM_DURING_MOVE");
      return false;
    }

    sinkWrite(STEP_PIN, true);   // PU- 下拉，产生有效脉冲
    delayMicroseconds(highUs);
    sinkWrite(STEP_PIN, false);
    delayMicroseconds(lowUs);
    ++totalPulses;
  }

  stopPulseOutput();
  Serial.print("OK MOVED ");
  Serial.println((long)signedPulses);
  return true;
}

void printHelp() {
  Serial.println();
  Serial.println("Commands:");
  Serial.println("  ARM                 allow motion");
  Serial.println("  DISARM              stop accepting motion");
  Serial.println("  MOVE <pulses> <Hz>  e.g. MOVE 100 200");
  Serial.println("  DIR 0|1             set direction only");
  Serial.println("  LOCK                ENA inactive, motor holds");
  Serial.println("  FREE                ENA active, motor may release");
  Serial.println("  STOP                stop pulse output");
  Serial.println("  STATUS              print pins and alarm");
  Serial.println("  HELP");
  Serial.println();
}

void printStatus() {
  Serial.print("armed=");
  Serial.print(armed ? 1 : 0);
  Serial.print(" alarm=");
  Serial.print(alarmActive() ? 1 : 0);
  Serial.print(" total_pulses=");
  Serial.println(totalPulses);
}

void handleCommand(String line) {
  line.replace("\r", "");
  line.trim();
  if (line.length() == 0) return;
  line.toUpperCase();

  int separator = line.indexOf(' ');
  String command = (separator >= 0) ? line.substring(0, separator) : line;
  String arguments = (separator >= 0) ? line.substring(separator + 1) : "";
  command.trim();
  arguments.trim();

  if (command == "ARM") {
    armed = true;
    Serial.println("OK ARM");
    return;
  }
  if (command == "DISARM") {
    armed = false;
    stopPulseOutput();
    lockMotor();
    Serial.println("OK DISARM");
    return;
  }
  if (command == "LOCK") {
    lockMotor();
    Serial.println(USE_ENA ? "OK LOCK" : "OK ENA_UNUSED");
    return;
  }
  if (command == "FREE") {
    freeMotor();
    if (USE_ENA) Serial.println("OK FREE");
    return;
  }
  if (command == "STOP") {
    stopPulseOutput();
    Serial.println("OK STOP");
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

  int32_t pulses;
  uint32_t hz;
  if (command == "MOVE" && sscanf(arguments.c_str(), "%ld %lu", &pulses, &hz) == 2) {
    movePulses(pulses, hz);
    return;
  }

  int dir;
  if (command == "DIR" && sscanf(arguments.c_str(), "%d", &dir) == 1 && (dir == 0 || dir == 1)) {
    setDirection(dir == 1);
    Serial.print("OK DIR ");
    Serial.println(dir);
    return;
  }

  Serial.print("ERR UNKNOWN_COMMAND [");
  Serial.print(line);
  Serial.println("]");
}

void setup() {
  // 如果使用 ESP32-S3 原生 USB，请在 Arduino IDE 开启 USB CDC On Boot。
  Serial.begin(115200);
  delay(300);

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  if (USE_ENA) {
    pinMode(ENA_PIN, OUTPUT);
  } else {
    pinMode(ENA_PIN, INPUT);  // ENA- 未接时保持高阻态
  }
  pinMode(ALM_PIN, USE_ALM ? INPUT_PULLUP : INPUT);

  // 上电默认：不发脉冲、保持电机、禁止软件运动。
  sinkWrite(STEP_PIN, false);
  sinkWrite(DIR_PIN, false);
  if (USE_ENA) lockMotor();
  armed = false;

  Serial.println("HBS57 single-axis test ready");
  Serial.println("Common-anode: external +5V -> PU+/DR+/ENA+");
  Serial.println("GPIO35/36/37 -> low-side PU-/DR-/ENA-");
  Serial.print("ENA input: ");
  Serial.println(USE_ENA ? "USED" : "NOT CONNECTED");
  Serial.print("ALM input: ");
  Serial.println(USE_ALM ? "USED" : "NOT CONNECTED");
  printHelp();
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }
}
