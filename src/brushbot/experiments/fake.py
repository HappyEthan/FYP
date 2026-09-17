"""Hardware-free experiment doubles. This module imports no robot library."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.engine import ExperimentEngine
from brushbot.experiments.recording import RunRecorder
from brushbot.z_control import ZController


class FakeArm:
    backend_kind = "synthetic"

    def __init__(self, pose=(0.1, 0.2, 0.06, 1.0, 2.0, 3.0), fsm=33, clock=None):
        self.pose = tuple(float(value) for value in pose)
        self.fsm = int(fsm)
        self.clock = clock
        self.calls = []

    def read_state(self):
        return {
            "tcp_pose": self.pose,
            "fsm": self.fsm,
            "available": True,
            "request_start_ns": 0 if self.clock is None else self.clock.now_ns(),
            "request_end_ns": 0 if self.clock is None else self.clock.now_ns(),
        }

    def move_pose(self, pose, speed_mm_s):
        self.pose = tuple(float(value) for value in pose)
        self.calls.append({
            "action": "move_pose", "pose": self.pose,
            "speed_mm_s": float(speed_mm_s),
        })

    def start_servo(self):
        if self.fsm != 33:
            raise RuntimeError("fake arm is not in Standby 33")
        self.calls.append({"action": "start_servo"})

    def push_pose(self, pose):
        self.pose = tuple(float(value) for value in pose)
        self.calls.append({"action": "push_pose", "pose": self.pose})

    def stop(self):
        self.calls.append({"action": "stop"})

    def configure_grip(self, width_mm, speed, force):
        self.calls.append({
            "action": "grip", "width_mm": float(width_mm),
            "speed": int(speed), "force": int(force),
        })
        return {
            "requested_width_mm": float(width_mm),
            "actual_width_mm": float(width_mm),
            "caught": None,
            "catch_state": None,
            "error_code": 0,
        }


class FakeClock:
    def __init__(self):
        self._ns = 0

    def now_ns(self):
        return self._ns

    def advance(self, seconds):
        self._ns += int(round(float(seconds) * 1e9))


class FakeMagneticSource:
    def __init__(self, arm, clock, contact_z_mm=40.0):
        self.arm = arm
        self.clock = clock
        self.contact_z_mm = float(contact_z_mm)
        self.enabled = True
        self._sensor_t_us = 0

    def read_frames(self):
        if not self.enabled:
            return []
        self._sensor_t_us += 20_000
        depth_mm = max(self.contact_z_mm - self.arm.pose[2] * 1000.0, 0.0)
        amplitude = depth_mm * 50.0
        return [{
            "sensor_t_us": self._sensor_t_us,
            "host_rx_ns": self.clock.now_ns(),
            "B_uT": [10.0 + amplitude, 20.0, 30.0],
            "source_kind": "synthetic",
        }]


class FakeRig:
    def __init__(self, engine, arm, hub, source, clock, spec, setup,
                 start_pose, recorder_root):
        self.engine = engine
        self.arm = arm
        self.hub = hub
        self.source = source
        self.clock = clock
        self.spec = spec
        self.setup = setup
        self.start_pose = start_pose
        self.recorder_root = Path(recorder_root)

    @property
    def feedback_calls(self):
        return self.engine.feedback_calls

    @property
    def saved_status(self):
        path = self.engine.snapshot().get("run_dir")
        if not path:
            return None
        manifest = Path(path) / "manifest.json"
        if not manifest.exists():
            return None
        return json.loads(manifest.read_text(encoding="utf-8"))["status"]

    def advance(self):
        self.clock.advance(0.02)
        if self.engine.state not in {"READY", "END_WAIT", "ABORTED", "FAULT"}:
            self.hub.poll_once()
        return self.engine.step()

    def advance_until(self, state, max_steps=1000):
        for _ in range(max_steps):
            if self.engine.state == state:
                return self.engine.snapshot()
            self.advance()
        raise AssertionError(
            f"engine did not reach {state}; snapshot={self.engine.snapshot()}")


def make_rig(*, recorder_root=None, closed_loop=False, deadband_uT=0.0):
    setup = {
        "origin_x_mm": 100.0, "origin_y_mm": 200.0,
        "wait_z_mm": 60.0, "contact_z_mm": 40.0,
        "vertical_rpy_rad": [1.0, 2.0, 3.0],
        "orientation_tolerance_rad": 0.01, "pose_tolerance_mm": 0.1,
        "workspace_min_mm": [0, 0, 0], "workspace_max_mm": [300, 400, 100],
        "max_depth_mm": 5.0, "max_xy_speed_mm_s": 25.0,
        "max_z_speed_mm_s": 10.0, "max_accel_mm_s2": 100.0,
        "max_step_mm": 1.0, "approach_speed_mm_s": 2.0,
        "return_speed_mm_s": 10.0,
        "baseline_window_s": 0.04, "baseline_timeout_s": 1.0,
        "baseline_min_samples": 3, "baseline_max_std_uT": [0.1, 0.1, 0.1],
        "baseline_max_drift_uT_s": 0.1, "sensor_max_age_s": 0.05,
        "max_tick_lateness_s": 0.005, "stop_timeout_s": 1.0,
        "filter": {"kind": "ema", "alpha": 0.3},
    }
    control = {"enabled": False}
    if closed_loop:
        control = {
            "enabled": True, "target_uT": 50.0,
            "deadband_uT": float(deadband_uT),
            "kp": 0.2, "ki": 0.01,
            "calibration_file": "measured.json",
        }
        setup["calibration"] = {"source": "measured", "approved": True}
    spec = {
        "version": 1, "name": "fake-line",
        "path": {"kind": "line", "delta_xy_mm": [4.0, 0.0]},
        "motion": {"speed_mm_s": 20.0, "accel_mm_s2": 100.0},
        "z": {"start_tcp_z_mm": 40.0, "end_tcp_z_mm": 39.0},
        "control": control,
    }
    start_pose = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
    clock = FakeClock()
    arm = FakeArm(start_pose)
    arm.clock = clock
    source = FakeMagneticSource(arm, clock)
    hub = SampleHub(source, clock.now_ns)
    root = Path(recorder_root or tempfile.mkdtemp(prefix="brushbot-fake-runs-"))
    controller = None
    if closed_loop:
        controller = ZController(
            [0, 1, 2], [0, 50, 100], dt=0.02,
            kp=control["kp"], ki=control["ki"],
            deadband_uT=control["deadband_uT"], z_surface=0,
            z_press_max=0.005, dz_step_max=0.001,
        )
    engine = ExperimentEngine(
        arm, hub, lambda snapshots: RunRecorder(str(root), snapshots),
        clock, controller=controller,
    )
    engine.prepare(spec, setup)
    return FakeRig(
        engine, arm, hub, source, clock, spec, setup, start_pose, root)
