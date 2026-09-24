"""Cross-platform serial-port defaults for the exhibition monitor."""

from __future__ import annotations

import sys
from collections.abc import Iterable


def choose_default_serial_port(devices: Iterable[str] | None, *, platform: str | None = None) -> str:
    """Return the first detected device or a platform-specific safe fallback."""
    platform_name = platform or sys.platform
    fallback = "COM3" if platform_name.startswith("win") else "/dev/ttyACM0"
    candidates = []
    for device in devices or ():
        value = str(device or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    return candidates[0] if candidates else fallback


def default_serial_port() -> str:
    """Detect a usable serial device without importing pyserial at module load."""
    try:
        from serial.tools import list_ports

        devices = [port.device for port in list_ports.comports()]
    except Exception:
        devices = []
    return choose_default_serial_port(devices)
