#include <cassert>
#include <cstdlib>
#include <iostream>
#include <string>

#include "../../firmware/mlx_s3_monitor_fixed90/mlx_s3_monitor_fixed90.ino"

static void require(bool condition, const char* message) {
  if (!condition) {
    std::cerr << message << "\nSERIAL OUTPUT:\n" << Serial.text();
    std::exit(1);
  }
}

int main(int argc, char** argv) {
  assert(argc == 2);
  const std::string scenario = argv[1];
  Wire.connected = {0x0C};
  if (scenario == "init_retry") {
    // An address ACK can precede a failed MLX initialization. A failed begin
    // still binds Adafruit 2.0.5's transport and must never be repeated.
    require(!tryPinPair(PRIMARY), "A failed driver initialization must fail");
    require(Serial.text().find("probe SDA=7 SCL=8 addr=0x0C") != std::string::npos &&
                Serial.text().find("stage=driver failed") != std::string::npos,
            "Initialization failure must identify the attempted pins and stage");
    fakeMlxAddresses = {0x0C};
    require(tryPinPair(PRIMARY), "The next initialization attempt must recover");
    require(fakeBegins[0x0C] == 1, "A failed begin must not be repeated");
    require(warmupAndSeed(), "Recovered sensor must supply warmup frames");
  } else if (scenario == "warmup_retry") {
    fakeMlxAddresses = {0x0C};
    fakeReadFailures[0x0C] = true;
    require(probeAndInit(), "Driver initialization must succeed");
    require(!warmupAndSeed(), "Missing warmup frames must reject startup");
    require(Serial.text().find("stage=warmup failed collected=0/100") != std::string::npos,
            "Warmup failure must report the received frame count");
    fakeReadFailures[0x0C] = false;
    require(probeAndInit() && warmupAndSeed(), "Warmup retry must recover");
    require(fakeBegins[0x0C] == 1, "Warmup retry must not repeat begin_I2C");
  } else if (scenario == "address_change") {
    fakeMlxAddresses = {0x0C, 0x0D};
    require(tryPinPair(PRIMARY), "First candidate must initialize");
    Wire.connected = {0x0D};
    require(tryPinPair(PRIMARY), "A different candidate must initialize");
    MagFrame frame{};
    require(readSensor(frame) && frame.x == 700,
            "Reads must use the currently selected address");
    Wire.connected = {0x0C};
    require(tryPinPair(PRIMARY), "Returning to the first address must recover");
    require(readSensor(frame) && frame.x == 100,
            "The earlier transport must retain its own address");
    require(fakeBegins[0x0C] == 1 && fakeBegins[0x0D] == 1,
            "Each candidate must bind exactly once");
  } else if (scenario == "recovery") {
    fakeMlxAddresses = {0x0C};
    setup();
    Serial.clear();
    fakeReadFailures[0x0C] = true;
    fakeClearFailureOnReset[0x0C] = true;
    for (int i = 0; i < 20; ++i) {
      fakeUs += 3000;
      loop();
    }
    require(fakeResets[0x0C] > 0, "Read failures must trigger sensor reset");
    require(fakeBegins[0x0C] == 1, "Recovery must not repeat begin_I2C");
    require(Serial.text().find(",100.000,200.000,300.000\n") != std::string::npos,
            "Recovery must resume the original four-column magnetic stream");
  } else {
    return 2;
  }
  return 0;
}
