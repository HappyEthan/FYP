"""Start the packaged exhibition backend and Qt monitor as one Windows app."""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


BACKEND_COMPONENT = "BrushbotBackend"
MONITOR_COMPONENT = "BrushbotMonitor"


def component_executable(bundle_dir: str | Path, component: str) -> Path:
    """Return the executable path for the onedir PyInstaller bundle layout."""
    bundle = Path(bundle_dir)
    name = str(component)
    return bundle / name / f"{name}.exe"


def _backend_ready(base_url: str, timeout_s: float = 0.6) -> bool:
    try:
        request = urllib.request.Request(f"{base_url.rstrip('/')}/api/status")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def wait_for_backend(
    base_url: str,
    process: subprocess.Popen,
    *,
    timeout_s: float = 12.0,
    poll_s: float = 0.1,
) -> None:
    """Wait until the local backend responds or fail with a useful error."""
    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while time.monotonic() < deadline:
        if _backend_ready(base_url):
            return
        if process.poll() is not None:
            raise RuntimeError("Brushbot backend exited before becoming ready")
        time.sleep(max(0.01, float(poll_s)))
    raise TimeoutError(f"Brushbot backend did not start at {base_url}")


def _hidden_window_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _frozen_commands(bundle_dir: Path, port: int) -> tuple[list[str], list[str]]:
    backend = component_executable(bundle_dir, BACKEND_COMPONENT)
    monitor = component_executable(bundle_dir, MONITOR_COMPONENT)
    if not backend.is_file():
        raise FileNotFoundError(f"missing backend executable: {backend}")
    if not monitor.is_file():
        raise FileNotFoundError(f"missing monitor executable: {monitor}")
    base_url = f"http://127.0.0.1:{int(port)}"
    return (
        [str(backend), "--host", "127.0.0.1", "--port", str(int(port))],
        [str(monitor), "--backend-url", base_url],
    )


def _source_commands(port: int) -> tuple[list[str], list[str]]:
    base_url = f"http://127.0.0.1:{int(port)}"
    return (
        [sys.executable, "-m", "brushbot.exhibition", "--host", "127.0.0.1", "--port", str(int(port))],
        [sys.executable, "-m", "brushbot.exhibition_monitor", "--backend-url", base_url],
    )


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Launch the Brushbot Windows bundle")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    bundle_dir = Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False):
        backend_cmd, monitor_cmd = _frozen_commands(bundle_dir, args.port)
        cwd = bundle_dir
    else:
        backend_cmd, monitor_cmd = _source_commands(args.port)
        cwd = None
    backend = subprocess.Popen(
        backend_cmd,
        cwd=cwd,
        creationflags=_hidden_window_flags(),
    )
    monitor = None
    base_url = f"http://127.0.0.1:{int(args.port)}"
    try:
        wait_for_backend(base_url, backend)
        monitor = subprocess.Popen(
            monitor_cmd,
            cwd=cwd,
            creationflags=_hidden_window_flags(),
        )
        return int(monitor.wait())
    finally:
        if monitor is not None and monitor.poll() is None:
            monitor.terminate()
            try:
                monitor.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                monitor.kill()
        if backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                backend.kill()


if __name__ == "__main__":
    raise SystemExit(run())
