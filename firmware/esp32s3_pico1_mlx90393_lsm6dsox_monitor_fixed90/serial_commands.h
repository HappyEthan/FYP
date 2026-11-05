#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

// A bounded line parser: a truncated/overlong line must never trigger a reset.
enum class SerialCommand : uint8_t {
  None,
  Reboot,
  ImuOn,
  ImuOff,
  ImuStatus,
};

class SerialCommandParser {
 public:
  SerialCommand feed(char ch) {
    if (ch == '\n') {
      const size_t length = used_ && line_[used_ - 1] == '\r' ? used_ - 1 : used_;
      SerialCommand command = SerialCommand::None;
      if (!overflow_ && length == 6 && memcmp(line_, "REBOOT", 6) == 0) {
        command = SerialCommand::Reboot;
      } else if (!overflow_ && length == 6 && memcmp(line_, "IMU ON", 6) == 0) {
        command = SerialCommand::ImuOn;
      } else if (!overflow_ && length == 7 && memcmp(line_, "IMU OFF", 7) == 0) {
        command = SerialCommand::ImuOff;
      } else if (!overflow_ && length == 4 && memcmp(line_, "IMU?", 4) == 0) {
        command = SerialCommand::ImuStatus;
      }
      used_ = 0;
      overflow_ = false;
      return command;
    }
    if (used_ < sizeof(line_)) line_[used_++] = ch;
    else overflow_ = true;
    return SerialCommand::None;
  }

 private:
  char line_[32];
  size_t used_ = 0;
  bool overflow_ = false;
};
