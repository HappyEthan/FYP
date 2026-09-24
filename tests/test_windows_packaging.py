from pathlib import Path

from brushbot.exhibition_monitor.serial_port import choose_default_serial_port
from brushbot.exhibition.windows_launcher import component_executable


def test_windows_serial_fallback_uses_com3():
    assert choose_default_serial_port([], platform="win32") == "COM3"


def test_linux_serial_fallback_keeps_acm0():
    assert choose_default_serial_port([], platform="linux") == "/dev/ttyACM0"


def test_detected_serial_port_wins_over_platform_fallback():
    assert choose_default_serial_port(["COM7", "COM3"], platform="win32") == "COM7"


def test_component_executable_uses_windows_bundle_layout(tmp_path: Path):
    path = component_executable(tmp_path, "BrushbotBackend")
    assert path == tmp_path / "BrushbotBackend" / "BrushbotBackend.exe"
