"""Small platform helpers shared by the core Windows-portable runtime.

The project still supports the existing POSIX development environment.  Keep
platform-specific defaults here so experiment scripts and the core monitor do
not each carry their own ``/dev`` or ``/tmp`` assumptions.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from collections.abc import Iterable


def is_windows(platform: str | None = None) -> bool:
    """Return whether *platform* (or the current interpreter) is Windows."""

    return (platform or sys.platform).startswith("win")


def repo_root() -> Path:
    """Return the repository root for an installed source checkout."""

    return Path(__file__).resolve().parents[2]


def runtime_temp_dir() -> Path:
    """Return a writable directory for local runtime coordination files."""

    path = Path(tempfile.gettempdir())
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_temp_path(name: str) -> Path:
    """Return a normalized path below the platform temporary directory."""

    if not name or Path(name).name != name:
        raise ValueError("runtime temp names must be a single non-empty filename")
    return runtime_temp_dir() / name


def default_serial_port(
    devices: Iterable[str] | None = None, *, platform: str | None = None
) -> str:
    """Return the first detected serial device or a safe platform fallback."""

    platform_name = platform or sys.platform
    fallback = "COM3" if is_windows(platform_name) else "/dev/ttyACM0"
    if devices is None:
        try:
            from serial.tools import list_ports

            devices = (port.device for port in list_ports.comports())
        except Exception:
            devices = ()
    seen: set[str] = set()
    for device in devices:
        value = str(device or "").strip()
        if value and value not in seen:
            return value
        seen.add(value)
    return fallback


def adapter_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the optional external Elfin/DH adapter checkout.

    ``ELFIN_DHAG_ADAPTER`` is preferred so the same script works from a
    Windows checkout and from the existing POSIX sibling checkout.
    """

    value = explicit or os.environ.get("ELFIN_DHAG_ADAPTER")
    if value:
        return Path(value).expanduser().resolve()
    return repo_root().parent / "elfin-dhag-adapter"
