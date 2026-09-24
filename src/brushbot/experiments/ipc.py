"""Restricted local IPC: status and return only."""

from __future__ import annotations

import json
import math
import os
import socket
import threading
from pathlib import Path


class ExperimentIPCServer:
    def __init__(self, service, path, *, max_message_bytes=4096):
        self.service = service
        self.path = Path(path)
        self.max_message_bytes = int(max_message_bytes)
        self._socket = None
        self._thread = None
        self._closed = threading.Event()

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.path))
        os.chmod(self.path, 0o600)
        server.listen(4)
        server.settimeout(0.1)
        self._socket = server
        self._thread = threading.Thread(target=self._serve, name="experiment-ipc", daemon=True)
        self._thread.start()

    def _response(self, request):
        request_id = request.get("request_id")
        action = request.get("action")
        if not isinstance(request_id, str) or not request_id:
            return {"status": "rejected", "error": "request_id is required"}
        if action == "status":
            return {"status": "completed", "request_id": request_id,
                    **self.service.snapshot()}
        if action == "return_pose":
            values = request.get("target_pose_m_rad")
            if (not isinstance(values, (list, tuple)) or len(values) != 6
                    or any(isinstance(value, bool)
                           or not isinstance(value, (int, float))
                           or not math.isfinite(float(value)) for value in values)):
                return {"status": "rejected", "request_id": request_id,
                        "error": "target_pose_m_rad must contain exactly six finite numbers"}
            frozen = [float(value) for value in values]
            service_id = self.service.submit(
                "return_pose", {"target_pose_m_rad": frozen})
            return {"status": "accepted", "request_id": request_id,
                    "service_request_id": service_id}
        return {"status": "rejected", "request_id": request_id,
                "error": "IPC permits only status and return_pose"}

    def _serve(self):
        while not self._closed.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                data = bytearray()
                while b"\n" not in data and len(data) <= self.max_message_bytes:
                    chunk = connection.recv(min(1024, self.max_message_bytes + 1))
                    if not chunk:
                        break
                    data.extend(chunk)
                try:
                    if len(data) > self.max_message_bytes:
                        raise ValueError("message too large")
                    request = json.loads(bytes(data).split(b"\n", 1)[0])
                    response = self._response(request)
                except Exception as exc:
                    response = {"status": "rejected", "error": str(exc)}
                connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode())

    def close(self):
        self._closed.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self.path.exists():
            self.path.unlink()


def send_ipc_request(path, request: dict, *, timeout_s=1.0) -> dict:
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(float(timeout_s))
        client.connect(str(path))
        client.sendall(payload)
        line = client.makefile("r", encoding="utf-8").readline()
    if not line:
        raise RuntimeError("experiment service returned no response")
    return json.loads(line)
