"""Simulation-first, single-owner exhibition robot task service.

The service deliberately accepts an injected arm and sensor.  It owns task
serialization and safety policy, while existing ExperimentEngine and
CartesianReturnController can be adapted behind the same boundary later.
"""

from __future__ import annotations

import copy
import math
import secrets
import threading
import time
from dataclasses import dataclass

from .contracts import RobotState, TaskState


@dataclass(frozen=True)
class SafetyConfig:
    origin_pose_m_rad: tuple[float, ...]
    ink_x_mm: float
    ink_y_mm: float
    ink_safe_z_mm: float
    ink_surface_z_mm: float
    ink_depth_mm: float
    ink_approach_speed_mm_s: float
    ink_dwell_s: float
    return_speed_mm_s: float

    @classmethod
    def from_setup(cls, setup):
        origin = setup.get("origin_pose_m_rad")
        if origin is None:
            ori = setup.get("vertical_rpy_rad", (0.0, 0.0, 0.0))
            origin = (float(setup.get("origin_x_mm", 0.0)) / 1000.0,
                      float(setup.get("origin_y_mm", 0.0)) / 1000.0,
                      float(setup.get("wait_z_mm", 0.0)) / 1000.0, *ori)
        return cls(tuple(origin), float(setup["ink_x_mm"]), float(setup["ink_y_mm"]),
                   float(setup["ink_safe_z_mm"]), float(setup["ink_surface_z_mm"]),
                   float(setup["ink_depth_mm"]), float(setup["ink_approach_speed_mm_s"]),
                   float(setup.get("ink_dwell_s", 0.0)),
                   float(setup.get("return_speed_mm_s", setup.get("ink_approach_speed_mm_s", 1.0))))

    def __post_init__(self):
        pose = tuple(float(v) for v in self.origin_pose_m_rad)
        if len(pose) != 6 or not all(math.isfinite(v) for v in pose):
            raise ValueError("origin_pose_m_rad must contain six finite values")
        if self.ink_depth_mm < 0 or self.ink_approach_speed_mm_s <= 0:
            raise ValueError("invalid ink safety parameters")
        if self.return_speed_mm_s <= 0 or self.ink_dwell_s < 0:
            raise ValueError("invalid motion safety parameters")


class RobotTaskService:
    """Own one exhibition task at a time; no browser request moves an arm."""

    def __init__(self, *, arm, sensor, config: SafetyConfig, clock=None,
                 plan_factory=None, preview_factory=None):
        self.arm = arm
        self.sensor = sensor
        if isinstance(config, dict):
            config = SafetyConfig.from_setup(config)
        self.config = config
        self.plan_factory = plan_factory
        self.preview_factory = preview_factory
        self.clock = clock or time
        self._lock = threading.RLock()
        self._tasks = {}
        self._active = None
        self._state = RobotState.READY if self._sensor_connected() and self._arm_connected() else RobotState.OFFLINE
        self._phase = "ready"
        self._plan = []
        self._plan_index = 0
        self._dip_authorized = False
        self._paused_from = None
        self._worker = None
        self._closed = threading.Event()

    def _now(self):
        now = getattr(self.clock, "time", None)
        return float(now() if callable(now) else time.time())

    def _sensor_connected(self):
        value = getattr(self.sensor, "connected", None)
        if value is None:
            value = getattr(self.sensor, "is_connected", False)
            value = value() if callable(value) else value
        return bool(value)

    def _arm_connected(self):
        try:
            state = self.arm.read_state()
        except Exception:
            return False
        return bool(state.get("available")) and state.get("tcp_pose") is not None

    def _require_ready_motion(self):
        if self._active is not None:
            raise RuntimeError("another task is active")
        if not self._sensor_connected():
            raise RuntimeError("sensor is disconnected")
        if not self._arm_connected():
            self._state = RobotState.OFFLINE
            raise RuntimeError("arm is disconnected")
        if self._state == RobotState.FAULT:
            raise RuntimeError("fault requires reconnection and confirmation")

    def _new_task(self, kind, *, request_id=None, character=None):
        if request_id:
            for task in self._tasks.values():
                if task.get("request_id") == request_id:
                    return task, False
        task_id = secrets.token_hex(12)
        now = self._now()
        task = {
            "task_id": task_id, "kind": kind,
            "state": TaskState.ACCEPTED.value, "phase": "accepted",
            "started_at": now, "ended_at": None, "last_error": None,
            "result": None, "plan_index": 0, "character": character,
            "request_id": request_id,
        }
        self._tasks[task_id] = task
        self._active = task_id
        return task, True

    def _repeat(self, request_id):
        if request_id:
            for task in self._tasks.values():
                if task.get("request_id") == request_id:
                    return self._accepted(task)
        return None

    def _accepted(self, task):
        return {"status": "accepted", "task_id": task["task_id"]}

    def _finish(self, state, *, result=None, error=None):
        task = self._tasks[self._active]
        task["state"] = state.value
        task["ended_at"] = self._now()
        task["result"] = copy.deepcopy(result)
        task["last_error"] = error
        self._active = None
        self._plan = []
        self._paused_from = None
        if state == TaskState.COMPLETED:
            self._state = RobotState.COMPLETED
            self._phase = "completed"
        elif state == TaskState.ABORTED:
            self._state = RobotState.ABORTED
            self._phase = "aborted"
        else:
            self._state = RobotState.FAULT
            self._phase = "fault"

    def dip_brush(self, *, request_id=None):
        with self._lock:
            repeated = self._repeat(request_id)
            if repeated is not None:
                return repeated
            self._require_ready_motion()
            task, created = self._new_task("dip", request_id=request_id)
            if not created:
                return self._accepted(task)
            self._state = RobotState.DIPPING
            self._phase = "dip"
            current = tuple(self.arm.read_state()["tcp_pose"])
            c = self.config
            ink_safe = (c.ink_x_mm / 1000, c.ink_y_mm / 1000,
                        c.ink_safe_z_mm / 1000, *current[3:])
            ink_surface = (c.ink_x_mm / 1000, c.ink_y_mm / 1000,
                            (c.ink_surface_z_mm - c.ink_depth_mm) / 1000,
                            *current[3:])
            self._plan = [ink_safe, ink_surface, ink_surface, ink_safe,
                          tuple(c.origin_pose_m_rad)]
            self._plan_index = 0
            task["state"] = TaskState.RUNNING.value
            task["phase"] = "dip"
            return self._accepted(task)

    def start_write(self, character, *, plan=None, request_id=None):
        with self._lock:
            repeated = self._repeat(request_id)
            if repeated is not None:
                return repeated
            self._require_ready_motion()
            if not self._dip_authorized:
                raise RuntimeError("successful dip is required before writing")
            if not isinstance(character, str) or len(character) != 1:
                raise ValueError("exactly one character is required")
            if plan is None:
                if self.plan_factory is None:
                    raise RuntimeError("write plan factory is not configured")
                plan = self.plan_factory(character)
            poses = [tuple(float(v) for v in pose) for pose in plan]
            if not poses or any(len(p) != 6 or not all(math.isfinite(v) for v in p)
                                for p in poses):
                raise ValueError("plan must contain finite six-dimensional poses")
            task, created = self._new_task("write", request_id=request_id,
                                           character=character)
            if not created:
                return self._accepted(task)
            self._state = RobotState.PREPARING
            self._phase = "preparing"
            self._plan = poses
            self._plan_index = 0
            task["state"] = TaskState.RUNNING.value
            task["phase"] = "writing"
            self._state = RobotState.WRITING
            self._phase = "writing"
            self._dip_authorized = False
            return self._accepted(task)

    def preview(self, character):
        if self.preview_factory is None:
            raise RuntimeError("preview factory is not configured")
        return copy.deepcopy(self.preview_factory(character))

    def return_to_origin(self, *, request_id=None):
        with self._lock:
            repeated = self._repeat(request_id)
            if repeated is not None:
                return repeated
            self._require_ready_motion()
            task, created = self._new_task("return", request_id=request_id)
            if not created:
                return self._accepted(task)
            task["state"] = TaskState.RUNNING.value
            task["phase"] = "return"
            self._state = RobotState.RETURNING
            self._phase = "return"
            self._plan = [tuple(self.config.origin_pose_m_rad)]
            self._plan_index = 0
            return self._accepted(task)

    def step(self):
        with self._lock:
            if self._active is None or self._state in {RobotState.PAUSED,
                                                         RobotState.FAULT}:
                return self.snapshot()
            task = self._tasks[self._active]
            try:
                if not self._sensor_connected():
                    try:
                        self.arm.stop()
                    finally:
                        self._finish(TaskState.FAULT, error="sensor_disconnected")
                    return self.snapshot()
                if self._state == RobotState.DIPPING:
                    self.arm.move_pose(self._plan[self._plan_index],
                                       self.config.ink_approach_speed_mm_s)
                elif self._state == RobotState.RETURNING:
                    self.arm.move_pose(self._plan[self._plan_index],
                                       self.config.return_speed_mm_s)
                else:
                    self.arm.move_pose(self._plan[self._plan_index],
                                       self.config.return_speed_mm_s)
                self._plan_index += 1
                task["plan_index"] = self._plan_index
                if self._plan_index >= len(self._plan):
                    kind = task["kind"]
                    result = {"plan_index": self._plan_index}
                    self._finish(TaskState.COMPLETED, result=result)
                    if kind == "dip":
                        self._dip_authorized = True
                        self._state = RobotState.READY
                        self._phase = "ready"
                    elif kind == "return":
                        self._state = RobotState.READY
                        self._phase = "ready"
            except Exception as exc:
                self._finish(TaskState.FAULT, error="communication_fault: " + str(exc))
            return self.snapshot()

    def run_until_idle(self, max_steps=1000):
        for _ in range(max_steps):
            if self._active is None:
                return self.snapshot()
            self.step()
        raise RuntimeError("task did not finish within max_steps")

    def start_background(self, period_s=0.02):
        if self._worker is not None and self._worker.is_alive():
            return
        self._closed.clear()
        def loop():
            while not self._closed.is_set():
                self.step()
                time.sleep(float(period_s))
        self._worker = threading.Thread(target=loop, name="exhibition-robot", daemon=True)
        self._worker.start()

    def close(self):
        self._closed.set()
        if self._worker is not None:
            self._worker.join(timeout=1.0)

    def pause(self):
        with self._lock:
            if self._active is None or self._state != RobotState.WRITING:
                raise RuntimeError("only writing can be paused")
            task = self._tasks[self._active]
            task["state"] = TaskState.PAUSED.value
            task["phase"] = "paused"
            self._paused_from = self._plan_index
            self._state = RobotState.PAUSED
            self._phase = "paused"
            return self.snapshot()

    def resume(self):
        with self._lock:
            if self._active is None or self._state != RobotState.PAUSED:
                raise RuntimeError("no paused writing task")
            task = self._tasks[self._active]
            task["state"] = TaskState.RUNNING.value
            task["phase"] = "writing"
            self._state = RobotState.WRITING
            self._phase = "writing"
            return self.snapshot()

    def stop(self, reason="operator_stop"):
        with self._lock:
            if self._active is None:
                raise RuntimeError("no active task")
            try:
                self.arm.stop()
            except Exception as exc:
                self._finish(TaskState.FAULT, error="communication_fault: " + str(exc))
                return self.snapshot()
            self._finish(TaskState.ABORTED, error=str(reason))
            self._dip_authorized = False
            return self.snapshot()

    def task(self, task_id):
        with self._lock:
            if task_id not in self._tasks:
                raise KeyError(task_id)
            return copy.deepcopy(self._tasks[task_id])

    def snapshot(self):
        with self._lock:
            active = self._tasks.get(self._active)
            sensor_snapshot = getattr(self.sensor, "snapshot", None)
            sensor_data = sensor_snapshot() if callable(sensor_snapshot) else None
            return {
                "state": self._state.value,
                "phase": self._phase,
                "task_id": self._active,
                "plan_index": self._plan_index,
                "sensor_connected": self._sensor_connected(),
                "arm_connected": self._arm_connected(),
                "last_error": active.get("last_error") if active else None,
                "dip_authorized": self._dip_authorized,
                "sensor": copy.deepcopy(sensor_data),
            }
