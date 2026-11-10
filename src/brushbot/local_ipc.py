"""Local IPC that works with Unix sockets on POSIX and loopback TCP on Windows.

The public API intentionally keeps the existing path-like endpoint argument.
On Windows that path is a small JSON descriptor containing the dynamically
allocated loopback port; on POSIX it remains the Unix socket path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile


IS_WINDOWS = sys.platform.startswith("win")


def _endpoint_path(path: str | os.PathLike[str]) -> Path:
    raw = os.fspath(path)
    endpoint = Path(raw)
    if IS_WINDOWS and (raw.startswith("/tmp/") or raw.startswith("\\tmp\\")):
        endpoint = Path(tempfile.gettempdir()) / endpoint.name
    endpoint.parent.mkdir(parents=True, exist_ok=True)
    return endpoint


def bind_local_server(
    path: str | os.PathLike[str], *, backlog: int = 4
) -> tuple[socket.socket, Path]:
    """Bind a local server and return ``(socket, endpoint_descriptor_path)``."""

    endpoint = _endpoint_path(path)
    try:
        endpoint.unlink()
    except FileNotFoundError:
        pass

    if IS_WINDOWS:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        descriptor = {
            "kind": "tcp",
            "host": "127.0.0.1",
            "port": int(server.getsockname()[1]),
        }
        endpoint.write_text(
            json.dumps(descriptor, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    else:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(endpoint))
        os.chmod(endpoint, 0o600)

    server.listen(int(backlog))
    server.settimeout(0.1)
    return server, endpoint


def connect_local(
    path: str | os.PathLike[str], *, timeout: float = 1.0
) -> socket.socket:
    """Connect to a server created by :func:`bind_local_server`."""

    endpoint = _endpoint_path(path)
    if IS_WINDOWS:
        descriptor = json.loads(endpoint.read_text(encoding="utf-8"))
        if descriptor.get("kind") != "tcp":
            raise RuntimeError(f"unsupported local IPC descriptor: {endpoint}")
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(float(timeout))
        client.connect((str(descriptor["host"]), int(descriptor["port"])))
        return client

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(float(timeout))
    client.connect(str(endpoint))
    return client


def remove_endpoint(path: str | os.PathLike[str] | Path) -> None:
    """Remove a local endpoint descriptor/socket, ignoring missing paths."""

    endpoint = path if isinstance(path, Path) else _endpoint_path(path)
    try:
        endpoint.unlink()
    except FileNotFoundError:
        pass
