"""Thread-owned experiment request and sampling lifecycle."""

from __future__ import annotations

import copy
import queue
import secrets
import threading
import time


class ExperimentService:
    ALLOWED_ACTIONS = {"load", "start", "stop", "return_pose"}
    EXPERIMENT_ACTIVE = {"BASELINE", "APPROACH", "RUN", "LIFT", "ABORT_LIFT"}
    RETURN_ACTIVE = {"READY", "RETURNING"}

    def __init__(self, engine, return_controller):
        self.engine = engine
        self.return_controller = return_controller
        self._requests = queue.Queue()
        self._results = {}
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="experiment-service", daemon=True)
        self._thread.start()

    def submit(self, action: str, payload: dict) -> str:
        request_id = secrets.token_hex(8)
        with self._lock:
            self._results[request_id] = {"status": "pending", "action": str(action)}
        self._requests.put((request_id, str(action), copy.deepcopy(payload)))
        return request_id

    def _set_result(self, request_id, result):
        with self._lock:
            self._results[request_id] = result

    def _handle(self, request_id, action, payload):
        if action not in self.ALLOWED_ACTIONS:
            self._set_result(request_id, {
                "status": "rejected", "error": f"unsupported action: {action}"})
            return
        try:
            if action == "load":
                self.engine.prepare(payload["spec"], payload["setup"])
            elif action == "start":
                if self.return_controller.state in self.RETURN_ACTIVE:
                    raise RuntimeError("Cartesian return is active")
                self.engine.start()
            elif action == "stop":
                reason = payload.get("reason", "operator_stop")
                if self.return_controller.state in self.RETURN_ACTIVE:
                    self.return_controller.request_stop(reason)
                else:
                    self.engine.request_stop(reason)
            else:
                if self.engine.state in self.EXPERIMENT_ACTIVE:
                    raise RuntimeError("experiment is active")
                self.return_controller.prepare(payload["target_pose_m_rad"])
            self._set_result(request_id, {"status": "completed", "action": action})
        except Exception as exc:
            self._set_result(request_id, {"status": "rejected", "error": str(exc)})

    def _drive_active_operation(self):
        if self.engine.state not in self.EXPERIMENT_ACTIVE:
            if self.return_controller.state in self.RETURN_ACTIVE:
                self.return_controller.step()
            return
        if hasattr(self.engine.clock, "advance"):
            self.engine.clock.advance(self.engine.dt_s)
        self.engine.hub.poll_once()
        self.engine.step()

    def _run(self):
        while not self._closed.is_set():
            try:
                item = self._requests.get(timeout=self.engine.dt_s)
            except queue.Empty:
                item = None
            if item is not None:
                try:
                    self._handle(*item)
                finally:
                    self._requests.task_done()
            try:
                self._drive_active_operation()
            except Exception:
                self.engine._fault("source_disconnected")

    def wait_request(self, request_id: str, timeout_s: float) -> dict:
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            with self._lock:
                result = copy.deepcopy(self._results.get(request_id))
            if result is not None and result.get("status") != "pending":
                return result
            time.sleep(0.001)
        raise TimeoutError(f"request {request_id} did not finish")

    def snapshot(self) -> dict:
        snapshot = {
            "experiment": self.engine.snapshot(),
            "cartesian_return": self.return_controller.snapshot(),
        }
        with self._lock:
            snapshot["requests"] = copy.deepcopy(self._results)
        return snapshot

    def close(self) -> None:
        active = (self.engine.state in self.EXPERIMENT_ACTIVE
                  or self.return_controller.state in self.RETURN_ACTIVE)
        if active:
            request = self.submit("stop", {"reason": "service_close"})
            self.wait_request(request, 1.0)
            deadline = time.monotonic() + 3.0
            while (self.engine.state in self.EXPERIMENT_ACTIVE
                   or self.return_controller.state in self.RETURN_ACTIVE):
                if time.monotonic() >= deadline:
                    raise RuntimeError("service could not confirm bounded stop")
                time.sleep(0.005)
        self._closed.set()
        self._thread.join(timeout=1.0)
        if self._thread.is_alive():
            raise RuntimeError("experiment service worker did not stop")
