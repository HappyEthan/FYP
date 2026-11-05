from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def multi_monitor_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("multi-monitor") / "multi_monitor_test"
    result = subprocess.run(
        [
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-DCONFIG_IDF_TARGET_ESP32S3=1", "-DARDUINO_USB_CDC_ON_BOOT=1",
            "-I", str(ROOT / "tests/firmware/multi_monitor_fakes"),
            str(ROOT / "tests/firmware/multi_monitor_test.cpp"),
            "-o", str(binary),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ["discovery", "fallback", "recovery", "partial_init"])
def test_multi_address_acquisition(multi_monitor_binary, scenario):
    result = subprocess.run(
        [str(multi_monitor_binary), scenario], capture_output=True, text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
