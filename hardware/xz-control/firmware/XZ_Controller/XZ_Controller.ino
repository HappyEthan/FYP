#include <Arduino.h>
#include <AccelStepper.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

// Existing test pin assignment. X GPIO35/36 retained at user's request.
// Standard N16R8 modules reserve GPIO35-37 for PSRAM: verify the actual board.
// GPIOs require a suitable low-side interface to HBS57, not a 5 V direct connection.
constexpr uint8_t X_STEP = 35, X_DIR = 36, Z_STEP = 4, Z_DIR = 5;
// Only representational/arithmetic boundaries remain; no travel policy limits.
constexpr unsigned long HEARTBEAT_MS = 1500;
// Add explicit DIR setup time before every pulse, including direction changes.
class PulseDriver : public AccelStepper {
 public:
  PulseDriver(uint8_t step, uint8_t dir) : AccelStepper(DRIVER, step, dir) {}
 protected:
  void step1(long) override {
    setOutputPins(_direction ? 0b10 : 0b00);
    delayMicroseconds(10);
    setOutputPins(_direction ? 0b11 : 0b01);
    delayMicroseconds(20);
    setOutputPins(_direction ? 0b10 : 0b00);
  }
};
PulseDriver axisX(X_STEP, X_DIR), axisZ(Z_STEP, Z_DIR);
bool armed = false, refX = false, refZ = false;
const char *fault = "NONE";
// phase: 0 idle, 1 X first, 2 Z first, 3 final/simultaneous phase.
int phase = 0;
long finalX = 0, finalZ = 0;
unsigned long lastPing = 0, lastReport = 0;
char rx[160];
size_t rxUsed = 0;
bool rxOverflow = false;
bool jogging = false, jogReleasing = false;
unsigned long lastJog = 0;
constexpr unsigned long JOG_LEASE_MS = 350;

bool busy() { return phase != 0; }
void emit(const char *line) {
  // Never let a disconnected/full USB transmit buffer block pulse generation.
  size_t n = strlen(line);
  if (Serial && Serial.availableForWrite() >= (int)(n + 1)) {
    Serial.write((const uint8_t *)line, n);
    Serial.write('\n');
  }
}
void status() {
  char out[384];
  snprintf(out, sizeof(out),
    "{\"type\":\"status\",\"protocol\":\"XZ1\",\"armed\":%d,\"busy\":%d,\"phase\":%d,"
    "\"x\":%ld,\"z\":%ld,\"tx\":%ld,\"tz\":%ld,\"vx\":%.2f,\"vz\":%.2f,"
    "\"refx\":%d,\"refz\":%d,\"fault\":\"%s\"}",
    armed, busy(), phase, axisX.currentPosition(), axisZ.currentPosition(),
    finalX, finalZ, axisX.speed(), axisZ.speed(), refX, refZ, fault);
  emit(out);
}
void ack(const char *cmd) {
  char out[80]; snprintf(out, sizeof(out), "{\"type\":\"ack\",\"cmd\":\"%s\"}", cmd);
  emit(out); status();
}
void error(const char *code) {
  char out[96]; snprintf(out, sizeof(out), "{\"type\":\"error\",\"code\":\"%s\"}", code);
  emit(out); status();
}
void halt(bool invalidate) {
  // Immediate software pulse stop. Does not disconnect power or release ENA.
  bool moving = busy();
  axisX.setCurrentPosition(axisX.currentPosition());
  axisZ.setCurrentPosition(axisZ.currentPosition());
  finalX = axisX.currentPosition(); finalZ = axisZ.currentPosition();
  phase = 0; armed = false;
  jogging = jogReleasing = false;
  if (invalidate && moving) refX = refZ = false;
}
bool integer(const char *s, long &v) {
  if (!s || !*s) return false;
  errno = 0; char *end = nullptr;
  v = strtol(s, &end, 10);
  return errno != ERANGE && end != s && *end == '\0' && v >= INT32_MIN && v <= INT32_MAX;
}
long jogTarget(long current, long direction) {
  // A rolling target prevents target-current overflow when traversing across zero.
  int64_t target = (int64_t)current + direction * (int64_t)INT32_MAX;
  if (target > INT32_MAX) target = INT32_MAX;
  if (target < INT32_MIN) target = INT32_MIN;
  return (long)target;
}
void handle(char *line) {
  char *t[9]; int n = 0; char *save = nullptr;
  for (char *p = strtok_r(line, " \t\r", &save); p; p = strtok_r(nullptr, " \t\r", &save)) {
    if (n == 9) { error("BAD_COMMAND"); return; }
    t[n++] = p;
  }
  if (!n) return;
  if (!strcmp(t[0], "HELLO") && n == 1) {
    emit("{\"type\":\"hello\",\"protocol\":\"XZ1\",\"firmware\":\"1.4.0\",\"move_accel\":true,\"jog\":true,\"jog_continuous\":true,\"numeric_ranges\":true}");
    status(); return;
  }
  if (!strcmp(t[0], "PING") && n == 1) { lastPing = millis(); return; }
  if (!strcmp(t[0], "JKEEP") && n == 1) {
    if (jogging && !jogReleasing) lastJog = millis();
    return;
  }
  if (!strcmp(t[0], "JEND") && n == 1) {
    if (jogging && !jogReleasing) {
      // Controlled deceleration, never extending the original bounded target.
      for (AccelStepper *axis : {static_cast<AccelStepper *>(&axisX), static_cast<AccelStepper *>(&axisZ)}) {
        long remaining = axis->distanceToGo();
        double braking = (double)axis->speed() * axis->speed() / (2.0 * axis->acceleration()) + 1.0;
        long steps = braking >= labs(remaining) ? labs(remaining) : (long)braking;
        axis->moveTo(axis->currentPosition() + (remaining < 0 ? -steps : steps));
      }
      finalX = axisX.targetPosition(); finalZ = axisZ.targetPosition();
      jogReleasing = true;
    }
    ack("JEND"); return;
  }
  if (!strcmp(t[0], "STATUS") && n == 1) { status(); return; }
  if ((!strcmp(t[0], "STOP") || !strcmp(t[0], "DISARM")) && n == 1) {
    halt(true); ack(t[0]); return;
  }
  if (!strcmp(t[0], "CLEAR") && n == 1) {
    halt(true); fault = "NONE"; ack("CLEAR"); return;
  }
  if (!strcmp(fault, "NONE")) {
    // One held axis at a time. Fresh JKEEP is required independently of PING.
    if (!strcmp(t[0], "JOG") && n == 5) {
      if (!armed) { error("NOT_ARMED"); return; }
      if (busy()) { error("BUSY"); return; }
      bool x = !strcmp(t[1], "X");
      if (!x && strcmp(t[1], "Z")) { error("BAD_AXIS"); return; }
      long dir, speed, accel;
      if (!integer(t[2], dir) || !integer(t[3], speed) || !integer(t[4], accel)) { error("BAD_NUMBER"); return; }
      if (dir != 1 && dir != -1) { error("BAD_NUMBER"); return; }
      if (speed < 1) { error("BAD_SPEED"); return; }
      if (accel < 1) { error("BAD_ACCEL"); return; }
      AccelStepper &axis = x ? static_cast<AccelStepper &>(axisX) : static_cast<AccelStepper &>(axisZ);
      long dest = jogTarget(axis.currentPosition(), dir);
      if (dest == axis.currentPosition()) { error("NUMERIC_RANGE"); return; }
      axis.setAcceleration(accel); axis.setMaxSpeed(speed); axis.moveTo(dest);
      finalX = axisX.targetPosition(); finalZ = axisZ.targetPosition();
      phase = 3; jogging = true; jogReleasing = false; lastJog = millis();
      ack("JOG"); return;
    }
    if (!strcmp(t[0], "ZERO") && n == 2) {
      if (busy()) { error("BUSY"); return; }
      bool x = !strcmp(t[1], "X") || !strcmp(t[1], "ALL");
      bool z = !strcmp(t[1], "Z") || !strcmp(t[1], "ALL");
      if (!x && !z) { error("BAD_AXIS"); return; }
      if (x) { axisX.setCurrentPosition(0); finalX = 0; refX = true; }
      if (z) { axisZ.setCurrentPosition(0); finalZ = 0; refZ = true; }
      ack("ZERO"); return;
    }
    if (!strcmp(t[0], "ARM") && n == 1) {
      if (millis() - lastPing >= HEARTBEAT_MS) { error("NO_HEARTBEAT"); return; }
      if (!refX || !refZ) { error("ZERO_REQUIRED"); return; }
      armed = true; ack("ARM"); return;
    }
    // MOVE ABS|REL XZ|ZX|SIM x z vx vz [ax az], integer pulses/s and pulses/s^2.
    // Legacy seven-token commands keep the original 50 pulses/s^2 behaviour.
    if (!strcmp(t[0], "MOVE") && (n == 7 || n == 9)) {
      if (!armed) { error("NOT_ARMED"); return; }
      if (busy()) { error("BUSY"); return; }
      bool relative = !strcmp(t[1], "REL");
      if (!relative && strcmp(t[1], "ABS")) { error("BAD_MODE"); return; }
      int order = !strcmp(t[2], "XZ") ? 1 : !strcmp(t[2], "ZX") ? 2 : !strcmp(t[2], "SIM") ? 3 : 0;
      if (!order) { error("BAD_ORDER"); return; }
      long x, z, vx, vz, ax = 50, az = 50;
      if (!integer(t[3], x) || !integer(t[4], z) || !integer(t[5], vx) || !integer(t[6], vz)) {
        error("BAD_NUMBER"); return;
      }
      if (n == 9 && (!integer(t[7], ax) || !integer(t[8], az))) {
        error("BAD_NUMBER"); return;
      }
      int64_t tx = (int64_t)x + (relative ? axisX.currentPosition() : 0);
      int64_t tz = (int64_t)z + (relative ? axisZ.currentPosition() : 0);
      if (vx < 1 || vz < 1) { error("BAD_SPEED"); return; }
      if (ax < 1 || az < 1) { error("BAD_ACCEL"); return; }
      // AccelStepper subtracts target-current in signed long (32-bit on ESP32).
      if (tx < INT32_MIN || tx > INT32_MAX || tz < INT32_MIN || tz > INT32_MAX ||
          llabs(tx - axisX.currentPosition()) > INT32_MAX || llabs(tz - axisZ.currentPosition()) > INT32_MAX) {
        error("NUMERIC_RANGE"); return;
      }
      finalX = (long)tx; finalZ = (long)tz;
      axisX.setAcceleration(ax); axisZ.setAcceleration(az);
      axisX.setMaxSpeed(vx); axisZ.setMaxSpeed(vz);
      phase = order;
      if (order != 2) axisX.moveTo(finalX);
      if (order != 1) axisZ.moveTo(finalZ);
      ack("MOVE"); return;
    }
    error("BAD_COMMAND"); return;
  }
  error("FAULT_LOCKED");
}
void serviceMotion() {
  if (!armed) return;
  if (jogging && !jogReleasing) {
    for (AccelStepper *axis : {static_cast<AccelStepper *>(&axisX), static_cast<AccelStepper *>(&axisZ)}) {
      long remaining = axis->distanceToGo();
      if (remaining && labs(remaining) < INT32_MAX / 2)
        axis->moveTo(jogTarget(axis->currentPosition(), remaining > 0 ? 1 : -1));
    }
    finalX = axisX.targetPosition(); finalZ = axisZ.targetPosition();
  }
  axisX.run(); axisZ.run();
  if (phase == 1 && axisX.distanceToGo() == 0) { axisZ.moveTo(finalZ); phase = 3; }
  else if (phase == 2 && axisZ.distanceToGo() == 0) { axisX.moveTo(finalX); phase = 3; }
  if (phase == 3 && axisX.distanceToGo() == 0 && axisZ.distanceToGo() == 0) {
    jogging = jogReleasing = false;
    phase = 0; emit("{\"type\":\"done\"}"); status();
  }
}
void setup() {
  Serial.begin(115200);
#if defined(ARDUINO_ARCH_ESP32) && ARDUINO_USB_CDC_ON_BOOT && ARDUINO_USB_MODE
  Serial.setTxBufferSize(1024);
  Serial.setTxTimeoutMs(0);
#endif
  axisX.setPinsInverted(false, false, false);
  axisZ.setPinsInverted(false, false, false);
  axisX.setAcceleration(50); axisZ.setAcceleration(50);
  axisX.setMaxSpeed(10); axisZ.setMaxSpeed(10);
  axisX.setCurrentPosition(0); axisZ.setCurrentPosition(0);
  lastPing = millis();
}
void loop() {
  if (jogging && !jogReleasing && millis() - lastJog >= JOG_LEASE_MS) {
    halt(true); fault = "JOG_TIMEOUT"; status();
  }
  if (armed && millis() - lastPing >= HEARTBEAT_MS) {
    halt(true); fault = "LINK_TIMEOUT"; status();
  }
  serviceMotion();
  // Fixed memory and bounded receive work; no readStringUntil or blocking motion loop.
  for (int i = 0; i < 48 && Serial.available(); ++i) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (rxOverflow) error("LINE_TOO_LONG");
      else { rx[rxUsed] = '\0'; handle(rx); }
      rxUsed = 0; rxOverflow = false;
    } else if (c != '\r') {
      if (rxUsed < sizeof(rx) - 1) rx[rxUsed++] = c;
      else rxOverflow = true;
    }
    serviceMotion();
  }
  if (millis() - lastReport >= 200) { lastReport = millis(); status(); }
}
