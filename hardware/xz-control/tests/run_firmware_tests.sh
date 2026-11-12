#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
accel_source="${ACCELSTEPPER_SRC:-$HOME/Documents/Arduino/libraries/AccelStepper/src}"
test_binary=$(mktemp /tmp/xz-firmware-test.XXXXXX)
trap 'rm -f "$test_binary"' EXIT
c++ -std=c++17 -DARDUINO=10800 -Itests -I"$accel_source" tests/firmware_test.cpp "$accel_source/AccelStepper.cpp" -o "$test_binary"
"$test_binary"
