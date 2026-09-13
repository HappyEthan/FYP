"""Contract tests for the exhibition monitor's network-only gateway."""

from __future__ import annotations

import json
import threading
import time
from collections import deque

import pytest

pytest.importorskip("PyQt5")

from brushbot.exhibition_monitor.gateway import ExhibitionGateway
from brushbot.exhibition_monitor.state_store import ExhibitionStateStore


class FakeHttp:
    def __init__(self, responses=()):
        self.responses = deque(responses)
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.responses.popleft()


class FakeWebSocket:
    def __init__(self, frames, events=None):
        self.frames = deque(frames)
        self.events = events
        self.closed = False

    def recv(self):
        item = self.frames.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self):
        self.closed = True


class BlockingFakeWebSocket:
    def __init__(self):
        self.closed = threading.Event()

    def recv(self):
        self.closed.wait()
        raise OSError("closed")

    def close(self):
        self.closed.set()


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_state_store_emits_and_keeps_only_a_deep_copied_latest_snapshot():
    store = ExhibitionStateStore()
    changes = []
    store.changed.connect(lambda: changes.append(store.snapshot()))
    first = {"sensor": {"series": {"x": [1.0]}}}
    second = {"sensor": {"series": {"x": [2.0]}}}

    store.update_snapshot(first)
    first["sensor"]["series"]["x"].append(99.0)
    returned = store.snapshot()
    returned["sensor"]["series"]["x"].append(88.0)
    store.update_snapshot(second)

    assert changes == [
        {"sensor": {"series": {"x": [1.0]}}},
        {"sensor": {"series": {"x": [2.0]}}},
    ]
    assert store.snapshot() == {"sensor": {"series": {"x": [2.0]}}}


def test_gateway_uses_only_existing_status_and_sensor_endpoints():
    http = FakeHttp(
        [
            (200, {"state": "READY"}),
            (200, {"connected": True}),
            (200, {"connected": False}),
            (202, {"baseline_running": True}),
        ]
    )
    gateway = ExhibitionGateway("http://127.0.0.1:8765/", http=http)

    assert gateway.get_status() == (200, {"state": "READY"})
    assert gateway.connect_sensor("/dev/ttyACM0", 9600) == (
        200,
        {"connected": True},
    )
    assert gateway.disconnect_sensor() == (200, {"connected": False})
    assert gateway.take_baseline() == (202, {"baseline_running": True})
    assert http.calls == [
        ("GET", "/api/status", None),
        ("POST", "/api/sensor/connect", {"port": "/dev/ttyACM0", "baud": 9600}),
        ("POST", "/api/sensor/disconnect", {}),
        ("POST", "/api/sensor/baseline", {}),
    ]


def test_stream_delivers_each_frame_once_and_refreshes_status_before_reconnect():
    events = []
    http = FakeHttp([(200, {"sequence": "status"})])
    first = FakeWebSocket(
        [json.dumps({"sequence": "first"}), OSError("disconnected")]
    )
    second = FakeWebSocket([json.dumps({"sequence": "second"})])
    sockets = deque([first, second])

    def open_websocket(url, timeout):
        events.append(("stream", url, timeout))
        return sockets.popleft()

    original_request = http.request

    def traced_request(method, path, body=None):
        events.append(("http", method, path))
        return original_request(method, path, body)

    http.request = traced_request
    gateway = ExhibitionGateway(
        "http://monitor.local:8765",
        http_timeout_s=0.2,
        reconnect_delay_s=0.001,
        http=http,
        websocket_factory=open_websocket,
    )
    received = []

    def on_snapshot(snapshot):
        received.append(snapshot)
        events.append(("snapshot", snapshot["sequence"]))

    gateway.start_stream(on_snapshot)
    try:
        wait_until(lambda: len(received) >= 3)
    finally:
        gateway.close()

    assert received == [
        {"sequence": "first"},
        {"sequence": "status"},
        {"sequence": "second"},
    ]
    assert events[:5] == [
        ("stream", "ws://monitor.local:8765/api/sensor/stream", 0.2),
        ("snapshot", "first"),
        ("http", "GET", "/api/status"),
        ("snapshot", "status"),
        ("stream", "ws://monitor.local:8765/api/sensor/stream", 0.2),
    ]


def test_close_is_idempotent_and_unblocks_receiver_within_one_second():
    socket = BlockingFakeWebSocket()
    gateway = ExhibitionGateway(
        "https://monitor.local/base",
        websocket_factory=lambda url, timeout: socket,
    )
    gateway.start_stream(lambda _snapshot: None)
    wait_until(lambda: gateway.stream_running)

    started = time.monotonic()
    gateway.close()
    gateway.close()

    assert time.monotonic() - started < 1.0
    assert socket.closed.is_set()
    assert gateway.stream_running is False


def test_reconnect_does_not_open_stream_until_status_refresh_succeeds():
    first = FakeWebSocket([OSError("disconnected")])
    opened = []

    class FailingHttp:
        def request(self, method, path, body=None):
            raise OSError("status unavailable")

    def open_websocket(url, timeout):
        opened.append((url, timeout))
        return first

    gateway = ExhibitionGateway(
        "http://monitor.local:8765",
        reconnect_delay_s=0.001,
        http=FailingHttp(),
        websocket_factory=open_websocket,
    )
    gateway.start_stream(lambda _snapshot: None)
    try:
        wait_until(lambda: len(opened) == 1)
        time.sleep(0.03)
        assert len(opened) == 1
    finally:
        gateway.close()
