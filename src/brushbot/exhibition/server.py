"""Small dependency-free HTTP/WebSocket transport for the exhibition UI."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .hanzi_preview import preview_character
from .sensor_service import SensorMonitorService


STATIC = Path(__file__).with_name("static")


class ExhibitionApp:
    def __init__(self, service, *, plan_factory=None, graphics_path=None,
                 sensor_service=None):
        self.service = service
        self.plan_factory = plan_factory
        self.graphics_path = graphics_path
        self._sensor_explicit = sensor_service is not None
        self.sensor_service = sensor_service or SensorMonitorService()

    def snapshot(self, compact=False):
        payload = self.service.snapshot()
        payload["sensor"] = self.sensor_service.snapshot(max_points=160 if compact else None)
        payload["sensor_connected"] = payload["sensor"]["connected"]
        return payload

    def close(self):
        self.sensor_service.close()

    def _reject(self, message, code=422):
        return {"status": "rejected", "error": message}, code

    def _sensor_ready_for_motion(self):
        return (not self._sensor_explicit or
                bool(self.sensor_service.snapshot().get("connected")))

    def dispatch(self, method, path, body):
        method, path = method.upper(), path.split("?", 1)[0]
        if method == "GET" and path == "/api/status":
            return self.snapshot(), 200
        if method == "GET" and path.startswith("/api/tasks/"):
            try:
                return self.service.task(path.rsplit("/", 1)[1]), 200
            except KeyError:
                return self._reject("task not found", 404)
        if method != "POST":
            return self._reject("method not allowed", 405)
        body = body if isinstance(body, dict) else {}
        if path == "/api/sensor/connect":
            if set(body) - {"port", "baud"}:
                return self._reject("connect accepts port and baud")
            try:
                return self.sensor_service.connect(body.get("port"), body.get("baud", 115200)), 200
            except (TypeError, ValueError) as exc:
                return self._reject(str(exc))
        if path == "/api/sensor/disconnect":
            if body:
                return self._reject("disconnect accepts no fields")
            return self.sensor_service.disconnect(), 200
        if path == "/api/sensor/baseline":
            if body:
                return self._reject("baseline accepts no fields")
            try:
                return self.sensor_service.start_baseline(), 202
            except RuntimeError as exc:
                return self._reject(str(exc), 409)
        if path == "/api/robot/preview":
            character = body.get("character")
            try:
                return preview_character(character, self.graphics_path), 200
            except (KeyError, ValueError) as exc:
                return self._reject(str(exc))
        if path == "/api/robot/dip":
            if set(body) - {"request_id"}:
                return self._reject("dip accepts only request_id")
            try:
                if not self._sensor_ready_for_motion():
                    return self._reject("sensor is not connected", 409)
                return self.service.dip_brush(request_id=body.get("request_id")), 202
            except (RuntimeError, ValueError) as exc:
                return self._reject(str(exc), 409)
        if path == "/api/robot/return":
            if set(body) - {"request_id"}:
                return self._reject("return accepts only request_id")
            try:
                if not self._sensor_ready_for_motion():
                    return self._reject("sensor is not connected", 409)
                return self.service.return_to_origin(request_id=body.get("request_id")), 202
            except (RuntimeError, ValueError) as exc:
                return self._reject(str(exc), 409)
        if path == "/api/robot/write":
            if set(body) - {"character", "request_id"}:
                return self._reject("write accepts character and request_id")
            if not self.plan_factory:
                return self._reject("write plan factory is not configured", 503)
            try:
                if not self._sensor_ready_for_motion():
                    return self._reject("sensor is not connected", 409)
                character = body.get("character")
                plan = self.plan_factory(character)
                return self.service.start_write(character, plan=plan,
                                                request_id=body.get("request_id")), 202
            except (RuntimeError, ValueError, KeyError) as exc:
                return self._reject(str(exc), 409)
        if path == "/api/robot/stop":
            if set(body) - {"reason"}:
                return self._reject("stop accepts only reason")
            try:
                return self.service.stop(body.get("reason", "operator_stop")), 202
            except RuntimeError as exc:
                return self._reject(str(exc), 409)
        if path == "/api/robot/pause":
            if set(body) - {"task_id"}:
                return self._reject("pause accepts only task_id")
            try:
                snapshot = (self.service.resume() if self.service.snapshot()["state"] == "PAUSED"
                            else self.service.pause())
                return {"status": "accepted", "task_id": snapshot.get("task_id"),
                        **snapshot}, 202
            except RuntimeError as exc:
                return self._reject(str(exc), 409)
        return self._reject("unknown endpoint", 404)


class _Handler(BaseHTTPRequestHandler):
    server_version = "BrushbotExhibition/1"

    def _json(self, payload, code):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 64 * 1024: raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/api/sensor/stream" and self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers.get("Sec-WebSocket-Key", "")
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101); self.send_header("Upgrade", "websocket"); self.send_header("Connection", "Upgrade"); self.send_header("Sec-WebSocket-Accept", accept); self.end_headers()
            try:
                while True:
                    payload = json.dumps(self.server.app.snapshot(compact=True), ensure_ascii=False).encode()
                    if len(payload) < 126:
                        frame = bytes([0x81, len(payload)]) + payload
                    else:
                        frame = bytes([0x81, 126]) + len(payload).to_bytes(2, "big") + payload
                    self.wfile.write(frame); self.wfile.flush()
                    threading.Event().wait(1.0 / 30.0)
            except OSError:
                pass
            return
        if self.path in ("/", "/index.html"):
            path = STATIC / "index.html"
        else:
            path = STATIC / self.path.lstrip("/")
        if path.is_file() and STATIC in path.parents:
            raw = path.read_bytes(); self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if self.path.startswith("/api/"):
            payload, code = self.server.app.dispatch("GET", self.path, None); self._json(payload, code); return
        self._json({"status": "rejected", "error": "not found"}, 404)

    def do_POST(self):
        try: body = self._body()
        except Exception as exc: self._json({"status": "rejected", "error": str(exc)}, 400); return
        payload, code = self.server.app.dispatch("POST", self.path, body); self._json(payload, code)

    def log_message(self, *_): pass


def make_server(app, host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, int(port)), _Handler); server.app = app; return server


def serve_in_thread(app, host="127.0.0.1", port=8765):
    server = make_server(app, host, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    return server, thread


def main(argv=None):
    """Serve the static exhibition UI with an offline, non-moving demo backend."""
    import argparse
    from .robot_service import RobotTaskService, SafetyConfig
    from .sensor_service import SensorMonitorService

    class DemoArm:
        pose = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
        def read_state(self): return {"available": True, "tcp_pose": self.pose}
        def move_pose(self, pose, speed_mm_s): self.pose = tuple(pose)
        def stop(self): pass

    class DemoSensor:
        connected = True

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    arm = DemoArm()
    cfg = SafetyConfig(arm.pose, 120, 220, 70, 50, 5, 5, 0, 10)
    service = RobotTaskService(arm=arm, sensor=DemoSensor(), config=cfg)
    service.start_background()
    app = ExhibitionApp(service, plan_factory=lambda _character: [arm.pose],
                        sensor_service=SensorMonitorService())
    server = make_server(app, args.host, args.port)
    print(f"Monitor exhibition UI: http://{args.host}:{server.server_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        app.close()
        service.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
