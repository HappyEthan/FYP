"""Network-only HTTP/WebSocket gateway for the exhibition monitor.

The Qt client talks to the existing exhibition backend only.  In particular,
this module deliberately does not import serial, robot, or simulation code.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_MAX_RESPONSE_BYTES = 64 * 1024
_STREAM_PATH = "/api/sensor/stream"


class _UrllibHttp:
    def __init__(self, base_url: str, timeout_s: float):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = float(timeout_s)

    def request(self, method: str, path: str, body: dict | None = None):
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._base_url + path, data=data, headers=headers, method=method
        )
        try:
            response = urllib.request.urlopen(request, timeout=self._timeout_s)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ValueError("response too large")
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("response must be a JSON object")
            status = response.getcode()
        return int(status), payload


def _default_websocket_factory(url: str, timeout: float):
    try:
        import websocket
    except ImportError as exc:  # pragma: no cover - exercised without extra
        raise RuntimeError(
            "websocket-client is required for the exhibition monitor stream"
        ) from exc
    return websocket.create_connection(url, timeout=timeout)


class ExhibitionGateway:
    """Call exhibition backend endpoints and maintain one stream thread."""

    def __init__(
        self,
        base_url: str,
        *,
        http_timeout_s: float = 1.0,
        reconnect_delay_s: float = 0.5,
        http=None,
        websocket_factory=None,
    ):
        self.base_url = str(base_url).rstrip("/")
        self.http_timeout_s = float(http_timeout_s)
        self.reconnect_delay_s = float(reconnect_delay_s)
        self._http = http or _UrllibHttp(self.base_url, self.http_timeout_s)
        self._websocket_factory = websocket_factory or _default_websocket_factory
        self._stop = threading.Event()
        self._thread_lock = threading.RLock()
        self._socket_lock = threading.RLock()
        self._thread = None
        self._socket = None

    def get_status(self) -> tuple[int, dict]:
        return self._request("GET", "/api/status")

    def connect_sensor(self, port: str, baud: int = 115200) -> tuple[int, dict]:
        return self._request(
            "POST", "/api/sensor/connect", {"port": port, "baud": baud}
        )

    def disconnect_sensor(self) -> tuple[int, dict]:
        return self._request("POST", "/api/sensor/disconnect", {})

    def take_baseline(self) -> tuple[int, dict]:
        return self._request("POST", "/api/sensor/baseline", {})

    def _request(self, method: str, path: str, body: dict | None = None):
        # The injected seam intentionally has the same tiny protocol as the
        # concrete client, keeping tests independent of real sockets.
        return self._http.request(method, path, body)

    @property
    def stream_running(self) -> bool:
        with self._thread_lock:
            return bool(self._thread and self._thread.is_alive())

    def start_stream(self, on_snapshot: Callable[[dict], None]) -> None:
        if not callable(on_snapshot):
            raise TypeError("on_snapshot must be callable")
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._stream_worker,
                args=(on_snapshot,),
                name="exhibition-monitor-stream",
                daemon=True,
            )
            self._thread.start()

    def _stream_url(self) -> str:
        parsed = urlsplit(self.base_url)
        scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
        return urlunsplit((scheme, parsed.netloc, parsed.path.rstrip("/") + _STREAM_PATH, "", ""))

    def _stream_worker(self, on_snapshot: Callable[[dict], None]) -> None:
        while not self._stop.is_set():
            socket = None
            try:
                socket = self._websocket_factory(self._stream_url(), self.http_timeout_s)
                with self._socket_lock:
                    self._socket = socket
                while not self._stop.is_set():
                    raw = socket.recv()
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    payload: Any = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise ValueError("stream frame must be a JSON object")
                    on_snapshot(payload)
            except Exception:
                if self._stop.is_set():
                    break
            finally:
                with self._socket_lock:
                    if self._socket is socket:
                        self._socket = None
                self._close_socket(socket)

            if self._stop.wait(self.reconnect_delay_s):
                break
            try:
                _status, snapshot = self.get_status()
                if isinstance(snapshot, dict):
                    on_snapshot(snapshot)
            except Exception:
                # A failed status refresh must not bypass the prescribed
                # status-before-stream order; retry it on the next cycle.
                continue

    @staticmethod
    def _close_socket(socket) -> None:
        if socket is None:
            return
        try:
            socket.close()
        except Exception:
            pass

    def close(self) -> None:
        """Stop the stream and wait for its receiver thread (idempotently)."""
        self._stop.set()
        with self._socket_lock:
            socket = self._socket
        self._close_socket(socket)
        with self._thread_lock:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._thread_lock:
            if self._thread and not self._thread.is_alive():
                self._thread = None
