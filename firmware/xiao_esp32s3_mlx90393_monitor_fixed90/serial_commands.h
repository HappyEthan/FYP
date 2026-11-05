#pragma once

#include <stddef.h>
#include <string.h>

// A bounded line parser: a truncated/overlong line must never trigger a reset.
class SerialCommandParser {
 public:
  bool feed(char ch) {
    if (ch == '\n') {
      const size_t length = used_ && line_[used_ - 1] == '\r' ? used_ - 1 : used_;
      const bool reboot = !overflow_ && length == 6 && memcmp(line_, "REBOOT", 6) == 0;
      used_ = 0;
      overflow_ = false;
      return reboot;
    }
    if (used_ < sizeof(line_)) line_[used_++] = ch;
    else overflow_ = true;
    return false;
  }

 private:
  char line_[16];
  size_t used_ = 0;
  bool overflow_ = false;
};
