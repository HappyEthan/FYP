from pathlib import Path

from brushbot.platform_support import (
    adapter_root,
    default_serial_port,
    runtime_temp_path,
)


def test_windows_serial_fallback_and_detection():
    assert default_serial_port([], platform="win32") == "COM3"
    assert default_serial_port(["COM10", "COM3"], platform="win32") == "COM10"


def test_posix_serial_fallback_is_preserved():
    assert default_serial_port([], platform="linux") == "/dev/ttyACM0"


def test_runtime_temp_path_is_a_single_filename():
    path = runtime_temp_path("brushbot-test.endpoint")
    assert path.name == "brushbot-test.endpoint"
    assert path.parent.is_dir()


def test_adapter_root_prefers_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ELFIN_DHAG_ADAPTER", str(tmp_path / "adapter"))
    assert adapter_root() == (tmp_path / "adapter").resolve()
