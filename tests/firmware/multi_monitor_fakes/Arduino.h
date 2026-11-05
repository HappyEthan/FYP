#pragma once

#include <cstdint>

// The host fake declares delay before Wire.h is included by lsm6dsox.h.
// Wire.h provides the test clock-backed definition.
void delay(uint32_t ms);
