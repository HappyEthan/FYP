#include <cassert>
#include "serial_commands.h"

static int feed(SerialCommandParser &parser, const char *text) {
  int requests = 0;
  while (*text) requests += parser.feed(*text++);
  return requests;
}

int main() {
  SerialCommandParser parser;
  assert(feed(parser, "REBO") == 0);
  assert(feed(parser, "OT\n") == 1);
  assert(feed(parser, "REBOOT\r\n") == 1);
  assert(feed(parser, "\nreboot\nXREBOOT\nREBO\rOT\nREBOOT X\n") == 0);
  assert(feed(parser, "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXREBOOT\n") == 0);
  assert(feed(parser, "REBOOT\nREBOOT\n") == 2);
}
