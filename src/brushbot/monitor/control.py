"""Small local control channel for an already-running Monitor window."""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
from pathlib import Path


class MonitorControlServer:
    """Unix-socket server whose requests are drained on the Qt thread."""

    def __init__(self, path="/tmp/brushbot-monitor.sock"):
        self.path = str(path)
        self._requests = queue.Queue()
        self._stop = threading.Event()
        self._socket = None
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.path)
        sock.listen(4)
        sock.settimeout(0.1)
        self._socket = sock
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._socket.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                try:
                    conn.settimeout(30.0)
                    payload = conn.recv(65536).splitlines()[0]
                    request = json.loads(payload.decode("utf-8"))
                    response_queue = queue.Queue(maxsize=1)
                    self._requests.put((request, response_queue))
                    response = response_queue.get(timeout=30.0)
                except Exception as exc:
                    response = {"status": "rejected", "error": str(exc)}
                conn.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))

    def drain(self, handler):
        """Run pending handlers on the caller's thread (the Qt GUI thread)."""
        while True:
            try:
                request, response_queue = self._requests.get_nowait()
            except queue.Empty:
                return
            try:
                response = handler(request)
                if not isinstance(response, dict):
                    response = {"status": "rejected", "error": "handler returned non-dict"}
            except Exception as exc:
                response = {"status": "rejected", "error": str(exc)}
            response_queue.put(response)

    def close(self):
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self._socket = None
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def send_command(path, action, *, timeout=5.0):
    """Send one action and return the Monitor's JSON response."""
    request = {"action": str(action)}
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(float(timeout))
    try:
        sock.connect(str(path))
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        if not data:
            raise RuntimeError("Monitor returned no response")
        return json.loads(data.splitlines()[0].decode("utf-8"))
    finally:
        sock.close()
