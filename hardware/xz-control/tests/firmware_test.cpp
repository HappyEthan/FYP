#include "Arduino.h"
#include <cassert>
#include <iostream>
unsigned long fakeMicros = 100000;
FakeSerial Serial;
#include "../firmware/XZ_Controller/XZ_Controller.ino"

void cmd(const char *s) {
  char line[200]; snprintf(line, sizeof(line), "%s", s); handle(line);
}
void fresh() {
  halt(false); cmd("CLEAR"); cmd("ZERO ALL"); cmd("PING"); cmd("ARM");
  Serial.output.clear(); assert(armed);
}
void advance(int ms, bool heartbeat = true) {
  for (int i=0; i<ms*10; ++i) {
    fakeMicros += 100;
    if (heartbeat && i % 1000 == 0) cmd("PING");
    loop();
  }
}
int main() {
  setup(); cmd("ARM"); assert(!armed); assert(Serial.output.find("ZERO_REQUIRED") != std::string::npos);
  cmd("HELLO"); assert(Serial.output.find("\"move_accel\":true") != std::string::npos);
  fresh(); cmd("JOG X 1 500 5000");
  for (int i=0;i<5;i++) { cmd("JKEEP"); advance(100); }
  assert(jogging && axisX.currentPosition()>0 && axisZ.currentPosition()==0);
  cmd("JOG Z -1 500 5000"); assert(axisZ.targetPosition()==0);
  long releasePosition=axisX.currentPosition(); cmd("JEND"); advance(500);
  assert(!busy() && !jogging && armed && refX && refZ);
  assert(axisX.currentPosition()>=releasePosition && axisX.currentPosition()<10000);
  cmd("JOG Z -1 500 5000"); advance(100); assert(axisZ.currentPosition()<0);
  advance(400); assert(!armed && !busy() && !refX && !strcmp(fault,"JOG_TIMEOUT"));
  long stopped=axisZ.currentPosition(); cmd("JKEEP"); advance(200); assert(axisZ.currentPosition()==stopped);
  std::cout << "PASS jog cruise, release deceleration, second-axis exclusion and independent deadman timeout\n";
  fresh(); axisX.setCurrentPosition(INT32_MAX-10); cmd("JOG X 1 100 1000");
  for (int i=0;i<10;i++) { cmd("JKEEP"); advance(100); }
  assert(axisX.currentPosition()==INT32_MAX && !busy());
  cmd("JOG X 1 100 1000"); assert(!busy());
  fresh(); cmd("JOG X 0 100 1000"); assert(!busy());
  cmd("JOG X 1 0 1000"); assert(!busy());
  cmd("JOG X 1 100 -1"); assert(!busy());
  cmd("JOG Z -1 100 1000"); advance(100); cmd("STOP");
  assert(!armed && !busy() && !jogging && !refZ);
  std::cout << "PASS jog boundary, validation and immediate STOP\n";
  fresh(); cmd("JOG X 1 2000 10000");
  for (int i=0;i<70;i++) { cmd("JKEEP"); advance(100); }
  assert(busy() && jogging && axisX.currentPosition()>10000);
  cmd("JEND"); advance(1000); assert(!busy() && armed && refX);
  std::cout << "PASS continuous jog exceeds 10000 pulses and releases normally\n";
  fresh(); cmd("MOVE REL SIM 1000 -600 500 300 5000 3000");
  assert(axisX.acceleration()==5000 && axisZ.acceleration()==3000);
  advance(200);
  assert(busy() && axisX.speed()==500 && axisZ.speed()==-300);
  advance(500);
  assert(axisX.speed()==500 && axisZ.speed()==-300);
  advance(3000);
  assert(!busy() && axisX.currentPosition()==1000 && axisZ.currentPosition()==-600);
  std::cout << "PASS independent acceleration, target cruise speeds and exact endpoints\n";
  fresh();
  for (const char *line : {"MOVE REL SIM 10 10 100 100 0 1000",
                          "MOVE REL SIM 10 10 100 100 1000 -1",
                          "MOVE REL SIM 10 10 100 100 2147483648 1000",
                          "MOVE REL SIM 10 10 100 100 1000",
                          "MOVE REL SIM 10 10 100 100 1000 1000 EXTRA"}) {
    cmd(line); assert(!busy() && axisX.currentPosition()==0 && axisZ.currentPosition()==0);
  }
  std::cout << "PASS invalid acceleration commands rejected atomically\n";
  fresh(); cmd("MOVE REL XZ 20 30 100 100");
  bool zStarted = false;
  for (int i=0; busy() && i<10000; ++i) {
    advance(1);
    if (axisZ.currentPosition() != 0) { zStarted=true; assert(axisX.currentPosition()==20); }
  }
  assert(zStarted && !busy() && axisX.currentPosition()==20 && axisZ.currentPosition()==30);
  std::cout << "PASS X then Z, exact final counts\n";
  fresh(); cmd("MOVE REL ZX -20 30 100 100");
  for (int i=0; busy() && i<10000; ++i) {
    advance(1); if (axisX.currentPosition()!=0) assert(axisZ.currentPosition()==30);
  }
  assert(!busy() && axisX.currentPosition()==-20 && axisZ.currentPosition()==30);
  std::cout << "PASS Z then X, negative direction\n";
  fresh(); cmd("MOVE ABS SIM 50 -50 100 100"); advance(400);
  assert(axisX.currentPosition()>0 && axisZ.currentPosition()<0 && busy());
  cmd("ZERO ALL"); assert(busy() && Serial.output.find("BUSY")!=std::string::npos);
  cmd("STOP"); long x=axisX.currentPosition(), z=axisZ.currentPosition();
  advance(2000); assert(!armed && !busy() && axisX.currentPosition()==x && axisZ.currentPosition()==z && !refX && !refZ);
  std::cout << "PASS simultaneous motion, busy zero rejected, STOP cancels both\n";
  fresh(); cmd("MOVE REL XZ 100 100 100 100"); advance(300); cmd("DISARM"); advance(5000);
  assert(axisZ.currentPosition()==0 && !busy() && !armed);
  std::cout << "PASS DISARM cancels queued second axis\n";
  fresh(); cmd("MOVE REL SIM 1000 1000 100 100"); advance(1700, false);
  assert(!armed && !busy() && !strcmp(fault,"LINK_TIMEOUT"));
  cmd("PING"); cmd("ARM"); assert(!armed);
  cmd("CLEAR"); cmd("ARM"); assert(!armed); // stopping invalidated the reference
  std::cout << "PASS heartbeat fault lock, no automatic resume, zero required\n";
  fresh(); cmd("MOVE REL XZ 10001 0 10 10"); assert(busy()); fresh();
  cmd("MOVE REL XZ 10 0 0 10"); assert(!busy());
  cmd("MOVE REL XZ 10 0 -1 10"); assert(!busy());
  cmd("MOVE REL XZ 10 0 2147483648 10"); assert(!busy());
  cmd("MOVE REL XZ 10junk 0 10 10"); assert(!busy());
  cmd("MOVE REL XZ 99999999999999999999999 0 10 10"); assert(!busy());
  cmd("MOVE REL XZ 10 0 10 10 EXTRA"); assert(!busy());
  assert(axisX.currentPosition()==0 && axisZ.currentPosition()==0);
  std::cout << "PASS limits, malformed numbers and extra arguments rejected\n";
  fresh(); cmd("MOVE REL SIM 10 10 5000 12000");
  assert(busy() && axisX.maxSpeed()==5000 && axisZ.maxSpeed()==12000);
  advance(5000); assert(!busy() && axisX.currentPosition()==10 && axisZ.currentPosition()==10);
  std::cout << "PASS speeds above former 1000 cap accepted and motion completes\n";
  fresh(); cmd("MOVE ABS SIM 2000000 -2000000 200000 150000 1000 1000");
  assert(busy() && finalX==2000000 && finalZ==-2000000 && axisX.maxSpeed()==200000);
  fresh(); axisX.setCurrentPosition(INT32_MAX-5); cmd("MOVE REL SIM 10 0 10 10");
  assert(!busy() && Serial.output.find("NUMERIC_RANGE")!=std::string::npos);
  fresh(); axisX.setCurrentPosition(-1); cmd("MOVE ABS SIM 2147483647 0 10 10"); assert(!busy());
  fresh(); axisX.setCurrentPosition(INT32_MIN+10); cmd("JOG X -1 100 1000");
  for (int i=0;i<10;i++) { cmd("JKEEP"); advance(100); }
  assert(!busy() && axisX.currentPosition()==INT32_MIN);
  cmd("JOG X 1 100 1000"); assert(busy() && axisX.distanceToGo()==INT32_MAX);
  cmd("STOP");
  std::cout << "PASS large motion, numeric overflow rejection and full-range jog arithmetic\n";
  fresh(); Serial.input="MOVE REL XZ 10"; advance(100); assert(!busy());
  Serial.input=" 10 10 10\n"; advance(100); assert(busy());
  Serial.input="STOP\n"; advance(10); assert(!busy() && !armed);
  Serial.input=std::string(200,'A')+"\nPING\n"; advance(10);
  assert(Serial.output.find("LINE_TOO_LONG")!=std::string::npos);
  std::cout << "PASS split serial line, buffered STOP, overflow recovery\n";
  fresh(); cmd("MOVE REL SIM 10 10 10 10"); Serial.capacity=0; advance(5000);
  assert(!busy() && axisX.currentPosition()==10 && axisZ.currentPosition()==10);
  std::cout << "PASS full serial TX buffer does not block motion\n";
}
