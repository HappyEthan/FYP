"""Exercise XIAO startup and recovery without attaching sensor hardware."""
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def xiao_monitor_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("xiao-monitor") / "xiao_monitor_test"
    compiled = subprocess.run(
        [
            "g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "tests/firmware/multi_monitor_fakes"),
            str(ROOT / "tests/firmware/xiao_monitor_test.cpp"),
            "-o", str(binary),
        ], capture_output=True, text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    return binary


@pytest.mark.parametrize("scenario", [
    "init_retry", "warmup_retry", "address_change", "recovery",
])
def test_xiao_reuses_each_i2c_transport(xiao_monitor_binary, scenario):
    result = subprocess.run(
        [str(xiao_monitor_binary), scenario], capture_output=True, text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
