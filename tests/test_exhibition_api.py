import json
import socket
import threading
import time
import urllib.request

import pytest

from brushbot.exhibition.robot_service import RobotTaskService, SafetyConfig
from brushbot.exhibition.server import ExhibitionApp, serve_in_thread
from brushbot.exhibition.sensor_service import SensorMonitorService


class Arm:
    def __init__(self):
        self.pose = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
        self.calls = []

    def read_state(self):
        return {"available": True, "tcp_pose": self.pose}

    def move_pose(self, pose, speed_mm_s):
        self.pose = tuple(pose); self.calls.append(("move", self.pose))

    def stop(self): self.calls.append(("stop",))


class Sensor:
    connected = True


def make_app():
    arm = Arm()
    cfg = SafetyConfig(arm.pose, 120, 220, 70, 50, 5, 5, 0, 10)
    service = RobotTaskService(arm=arm, sensor=Sensor(), config=cfg)
    app = ExhibitionApp(service, plan_factory=lambda ch: [arm.pose])
    return app, service


def test_status_and_task_query_are_read_only_and_have_task_contract():
    app, _ = make_app()
    status, code = app.dispatch("GET", "/api/status", None)
    assert code == 200 and status["state"] == "READY"
    response, code = app.dispatch("GET", "/api/tasks/missing", None)
    assert code == 404 and response["status"] == "rejected"


def test_preview_rejects_multiple_characters_and_returns_strokes_for_one():
    app, _ = make_app()
    result, code = app.dispatch("POST", "/api/robot/preview", {"character": "一"})
    assert code == 200 and result["stroke_count"] >= 1
    result, code = app.dispatch("POST", "/api/robot/preview", {"character": "一二"})
    assert code == 422 and result["status"] == "rejected"


def test_write_returns_task_id_and_repeat_request_id_is_idempotent():
    app, service = make_app()
    service.dip_brush(request_id="dip"); service.run_until_idle()
    one, code = app.dispatch("POST", "/api/robot/write",
                             {"character": "一", "request_id": "w1"})
    two, code2 = app.dispatch("POST", "/api/robot/write",
                              {"character": "一", "request_id": "w1"})
    assert code == code2 == 202 and one["task_id"] == two["task_id"]


def test_return_endpoint_does_not_accept_arbitrary_pose():
    app, _ = make_app()
    result, code = app.dispatch("POST", "/api/robot/return", {"x": 1})
    assert code == 422 and result["status"] == "rejected"


def test_http_server_serves_static_index_and_json_status():
    app, _ = make_app()
    server, thread = serve_in_thread(app, "127.0.0.1", 0)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/status") as response:
            assert json.loads(response.read())["state"] == "READY"
        with urllib.request.urlopen(base + "/") as response:
            assert b"Monitor" in response.read()
    finally:
        server.shutdown(); thread.join(timeout=2)


def test_sensor_websocket_handshake_returns_status_frame():
    app, _ = make_app()
    server, thread = serve_in_thread(app, "127.0.0.1", 0)
    try:
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=2) as sock:
            request = ("GET /api/sensor/stream HTTP/1.1\r\n"
                       "Host: localhost\r\nUpgrade: websocket\r\n"
                       "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                       "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n")
            sock.sendall(request.encode())
            response = sock.recv(4096)
            assert b"101 Switching Protocols" in response
            assert b"Sec-WebSocket-Accept" in response
    finally:
        server.shutdown(); thread.join(timeout=2)


def test_sensor_connect_baseline_and_disconnect_endpoints():
    class Source:
        bad_lines = 0
        info = {"nominal_rate_hz": 100.0}
        def start(self): pass
        def stop(self): pass
        def read_frames(self):
            return [{"sensor_t_us": 1, "B_uT": [1.0, 2.0, 3.0], "source_kind": "serial"}]

    arm = Arm(); cfg = SafetyConfig(arm.pose, 120, 220, 70, 50, 5, 5, 0, 10)
    robot = RobotTaskService(arm=arm, sensor=Sensor(), config=cfg)
    sensors = SensorMonitorService(source_factory=lambda p, b: Source(),
                                   poll_interval=0.001, baseline_duration_s=0.01)
    app = ExhibitionApp(robot, sensor_service=sensors)
    try:
        payload, code = app.dispatch("POST", "/api/sensor/connect",
                                     {"port": "fake", "baud": 115200})
        assert code == 200 and payload["connected"] is True
        for _ in range(50):
            if app.dispatch("GET", "/api/status", None)[0]["sensor"]["series"]["x"]:
                break
            time.sleep(0.002)
        status = app.dispatch("GET", "/api/status", None)[0]
        assert status["sensor"]["pressure_bxy_uT"] == pytest.approx(5.0 ** 0.5)
        payload, code = app.dispatch("POST", "/api/sensor/baseline", {})
        assert code == 202 and payload["baseline_running"] is True
        payload, code = app.dispatch("POST", "/api/sensor/disconnect", {})
        assert code == 200 and payload["connected"] is False
    finally:
        sensors.close()


def test_explicit_sensor_disconnect_blocks_motion_requests():
    arm = Arm(); cfg = SafetyConfig(arm.pose, 120, 220, 70, 50, 5, 5, 0, 10)
    robot = RobotTaskService(arm=arm, sensor=Sensor(), config=cfg)
    sensors = SensorMonitorService(source_factory=lambda p, b: (_ for _ in ()).throw(OSError("offline")))
    app = ExhibitionApp(robot, plan_factory=lambda _ch: [arm.pose], sensor_service=sensors)
    try:
        result, code = app.dispatch("POST", "/api/robot/dip", {})
        assert code == 409 and result["status"] == "rejected"
    finally:
        sensors.close()


def test_compact_status_is_bounded_for_realtime_websocket_frames():
    app, _ = make_app()
    payload = app.snapshot(compact=True)
    assert len(payload["sensor"]["series"]["x"]) <= 160
