#include <cassert>
#include <iostream>
#include <string>

#include "../../firmware/esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90/esp32s3_pico1_mlx90393_lsm6dsox_monitor_fixed90.ino"

static void sample(unsigned count = 20) {
  for (unsigned i = 0; i < count; ++i) {
    fakeUs += 3000;
    loop();
  }
}

static void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << "\nSERIAL OUTPUT:\n" << Serial.text();
    std::exit(1);
  }
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  if (scenario == "discovery") {
    Wire.connected = {0x0C, 0x0F, 0x2A};
    fakeMlxAddresses = {0x0C, 0x0F};
    setup();
    sample();
    const auto text = Serial.text();
    require(text.find("# i2c addr=0x2A") != std::string::npos,
            "Scan must report ACKs outside the former candidate list");
    require(text.find("# sensor,0x0C,") != std::string::npos,
            "The primary sensor must have an explicitly addressed stream");
    require(text.find("# sensor,0x0F,") != std::string::npos,
            "A second sensor at an unknown address must also be read");
    require(text.find(",100.000,200.000,300.000\n") != std::string::npos,
            "Primary values must remain in the output");
    require(text.find(",700.000,800.000,900.000\n") != std::string::npos,
            "Secondary values must remain separate from primary values");
    require(text.find("# sensor init failed addr=0x2A") != std::string::npos,
            "An ACK alone must not be reported as a working sensor");
    std::istringstream lines(text);
    std::string line;
    unsigned legacy = 0;
    while (std::getline(lines, line)) {
      if (line.empty() || line[0] == '#' || line[0] < '0' || line[0] > '9') continue;
      ++legacy;
      require(line.find(",100.000,200.000,300.000") != std::string::npos,
              "Legacy four-column output must never mix addresses");
    }
    require(legacy > 0, "Legacy Monitor must continue receiving primary frames");
  } else if (scenario == "fallback") {
    Wire.connected = {0x0E};
    fakeMlxAddresses = {0x0E};
    setup();
    sample();
    require(Serial.text().find("# sensor,0x0E,") != std::string::npos,
            "A working sensor must be used even without address 0x0C");
  } else if (scenario == "partial_init") {
    Wire.connected = {0x0C, 0x0F};
    fakeMlxAddresses = {0x0C};
    setup();
    Serial.clear();
    fakeMlxAddresses.insert(0x0F);
    fakeUs += 2100000;
    sample();
    require(Serial.text().find("# sensor,0x0F,") != std::string::npos,
            "An ACKed sensor must recover from a transient initialization failure");
    require(Serial.text().find("# sensor,0x0C,") != std::string::npos,
            "Retrying the secondary sensor must preserve the primary stream");
    require(fakeBegins[0x0F] == 1,
            "Initialization retry must reuse the bound transport");
  } else if (scenario == "recovery") {
    Wire.connected = {0x0C, 0x0F};
    fakeMlxAddresses = {0x0C, 0x0F};
    setup();
    Serial.clear();
    fakeReadFailures[0x0C] = true;
    fakeClearFailureOnReset[0x0C] = true;
    sample();
    require(fakeResets[0x0C] > 0, "Repeated read failures must trigger recovery");
    require(fakeBegins[0x0C] == 1 && fakeBegins[0x0F] == 1,
            "Recovery must not rebind Adafruit's I2C device");
    require(Serial.text().find("# sensor,0x0F,") != std::string::npos,
            "One sensor's recovery must not stop the other sensor");
    require(Serial.text().find("# sensor,0x0C,") != std::string::npos,
            "Recovered sensor must resume producing frames");
  } else return 2;
  return 0;
}
