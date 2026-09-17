"""Hardware-agnostic unified open/closed-loop experiment state machine."""

from __future__ import annotations

import copy
import math

import numpy as np

from brushbot.experiments.trajectory import compile_experiment


class ExperimentEngine:
    def __init__(self, arm, hub, recorder_factory, clock, *, controller=None,
                 dt_s: float = 0.02):
        self.arm = arm
        self.hub = hub
        self.recorder_factory = recorder_factory
        self.clock = clock
        self.controller = controller
        self.dt_s = float(dt_s)
        self.state = "UNPREPARED"
        self.phase = ""
        self.last_error = ""
        self.run_id = None
        self.run_dir = None
        self.feedback_calls = 0
        self._spec = None
        self._setup = None
        self._compiled = None
        self._recorder = None
        self._sensor_cursor = 0
        self._baseline_rows = []
        self._baseline_started_ns = None
        self._approach_sent = False
        self._run_started_ns = None
        self._last_plan_index = 0
        self._last_command_pose = None
        self._stop_reason = None

    def prepare(self, spec: dict, setup: dict) -> dict:
        if self.state not in {"UNPREPARED", "READY"}:
            raise RuntimeError("cannot prepare while an operation is active")
        self._compiled = compile_experiment(spec, setup, self.dt_s)
        self._spec = copy.deepcopy(spec)
        self._setup = copy.deepcopy(setup)
        self.state = "READY"
        self.phase = "ready"
        self.last_error = ""
        return self.snapshot()

    def _now_ns(self) -> int:
        return int(self.clock.now_ns())

    def _start_pose(self):
        return (
            float(self._setup["origin_x_mm"]) / 1000.0,
            float(self._setup["origin_y_mm"]) / 1000.0,
            float(self._setup["wait_z_mm"]) / 1000.0,
            *tuple(float(v) for v in self._setup["vertical_rpy_rad"]),
        )

    def _pose_matches(self, actual, expected) -> bool:
        actual = np.asarray(actual, dtype=float)
        expected = np.asarray(expected, dtype=float)
        pos_tol = float(self._setup["pose_tolerance_mm"]) / 1000.0
        ori_tol = float(self._setup["orientation_tolerance_rad"])
        angle = np.abs((actual[3:] - expected[3:] + np.pi) % (2 * np.pi) - np.pi)
        return (np.linalg.norm(actual[:3] - expected[:3]) <= pos_tol
                and np.all(angle <= ori_tol))

    def start(self) -> None:
        if self.state != "READY" or self._compiled is None:
            raise RuntimeError("engine must be READY before start")
        state = self.arm.read_state()
        if not state.get("available") or not self._pose_matches(state["tcp_pose"], self._start_pose()):
            raise RuntimeError("arm is not at the verified wait pose; return to start first")
        snapshots = {
            "experiment": copy.deepcopy(self._compiled["spec_snapshot"]),
            "setup": copy.deepcopy(self._compiled["setup_snapshot"]),
            "filter": copy.deepcopy(self._setup.get("filter")),
            "calibration": copy.deepcopy(self._setup.get("calibration")),
            "compiled": self._compiled,
            "execution_environment": getattr(self.arm, "backend_kind", "hardware"),
        }
        self._recorder = self.recorder_factory(snapshots)
        self.run_id = self._recorder.run_id
        self.run_dir = str(self._recorder.run_dir)
        self._sensor_cursor = 0
        self._baseline_rows = []
        self._baseline_started_ns = self._now_ns()
        self._approach_sent = False
        self._stop_reason = None
        self.feedback_calls = 0
        self.state = "BASELINE"
        self.phase = "baseline"
        self._event("baseline_started")

    def _event(self, name: str, **fields) -> None:
        if self._recorder is not None:
            self._recorder.write("event", {
                "event": name, "phase": self.phase,
                "host_ns": self._now_ns(), **fields,
            })

    def _record_new_sensor(self) -> None:
        if self._recorder is None:
            return
        rows = self.hub.take_since(self._sensor_cursor)
        for row in rows:
            self._recorder.write("sensor", row)
            self._sensor_cursor = max(self._sensor_cursor, int(row["seq"]))
        if self.state == "BASELINE":
            self._baseline_rows.extend(rows)

    def request_stop(self, reason: str) -> None:
        if self.state in {"READY", "END_WAIT", "ABORTED", "FAULT"}:
            return
        self._stop_reason = str(reason)

    def _begin_abort(self, reason: str) -> None:
        self.last_error = str(reason)
        self._stop_reason = None
        self.hub.set_running(False)
        if self.state == "RUN":
            self.state = "ABORT_LIFT"
            self.phase = "abort_lift"
            return
        try:
            self.arm.stop()
        except Exception:
            self.state = "FAULT"
            self.phase = "fault"
            return
        self._finalize("aborted", reason)

    def _fault(self, reason: str) -> None:
        self.last_error = str(reason)
        self.hub.set_running(False)
        try:
            self.arm.stop()
        except Exception:
            pass
        if self._recorder is not None:
            try:
                self._recorder.finish("fault", reason)
            except Exception:
                pass
        self.state = "FAULT"
        self.phase = "fault"

    def _finalize(self, status: str, reason: str = "") -> None:
        if self._recorder is not None:
            try:
                self.run_dir = self._recorder.finish(status, reason)
            except Exception:
                self.last_error = "logger_fault"
                self.state = "FAULT"
                self.phase = "fault"
                return
            self._recorder = None
        self.state = "END_WAIT" if status == "completed" else "ABORTED"
        self.phase = "end_wait" if status == "completed" else "aborted"

    def _lift_step(self, *, completed: bool) -> None:
        current = tuple(self.arm.read_state()["tcp_pose"])
        wait_z = float(self._setup["wait_z_mm"]) / 1000.0
        if current[2] >= wait_z - 1e-12:
            self.arm.stop()
            self._event("lift_completed")
            self._finalize("completed" if completed else "aborted",
                           "" if completed else self.last_error)
            return
        dz = min(
            float(self._setup["max_z_speed_mm_s"]) * self.dt_s / 1000.0,
            float(self._setup["max_step_mm"]) / 1000.0,
            wait_z - current[2],
        )
        target = (current[0], current[1], current[2] + dz, *current[3:])
        self.arm.push_pose(target)
        self._last_command_pose = target

    def _check_pose(self, pose) -> None:
        xyz_mm = np.asarray(pose[:3], dtype=float) * 1000.0
        lower = np.asarray(self._setup["workspace_min_mm"], dtype=float)
        upper = np.asarray(self._setup["workspace_max_mm"], dtype=float)
        if np.any(xyz_mm < lower) or np.any(xyz_mm > upper):
            raise RuntimeError("workspace_limit")
        if self._last_command_pose is not None:
            step_mm = np.linalg.norm(
                np.asarray(pose[:3]) - np.asarray(self._last_command_pose[:3])) * 1000.0
            if step_mm > float(self._setup["max_step_mm"]) + 1e-9:
                raise RuntimeError("step_limit")

    def _run_step(self) -> None:
        now = self._now_ns()
        control = self.hub.latest_control(now)
        elapsed = (now - self._run_started_ns) / 1e9
        timeline = self._compiled["t_s"]
        index = min(int(np.searchsorted(timeline, elapsed, side="right") - 1), len(timeline) - 1)
        index = max(index, 0)
        lateness = elapsed - float(timeline[index])
        if index > self._last_plan_index + 1 or lateness > float(self._setup["max_tick_lateness_s"]):
            self._begin_abort("deadline_miss")
            return
        actual_pose = None
        actual_rx_ns = None
        try:
            state = self.arm.read_state()
            if state.get("available"):
                actual_pose = [float(value) for value in state["tcp_pose"]]
                actual_rx_ns = int(state.get("request_end_ns") or now)
        except Exception:
            # 单拍读位姿失败不应终止整轮扫描；该拍标记为不可用即可。
            actual_pose = None
            actual_rx_ns = None
        pose = self._compiled["pose_m_rad"][index].copy()
        depth_ff = float(self._compiled["depth_ff_m"][index])
        depth_fb = 0.0
        sample = self.hub.take_since(control["sample_seq"] - 1)[0]
        a_raw = math.hypot(float(sample["dBx_uT"]), float(sample["dBy_uT"]))
        a_control = float(control["a_control_uT"])
        a_ref = float(self._compiled["g_ref_uT"][index])
        e_center = None if not math.isfinite(a_ref) else a_ref - a_control
        e_band = None
        if self._spec["control"]["enabled"]:
            if self.controller is None:
                raise RuntimeError("closed-loop controller is unavailable")
            depth_cmd = self.controller.step_magnitude(
                a_control, a_ref, depth_ff_m=depth_ff)
            self.feedback_calls += 1
            depth_fb = float(depth_cmd - depth_ff)
            pose[2] = float(self._setup["contact_z_mm"]) / 1000.0 - depth_cmd
            deadband = float(self._spec["control"]["deadband_uT"])
            e_band = math.copysign(max(abs(e_center) - deadband, 0.0), e_center)
        self._check_pose(pose)
        self.arm.push_pose(tuple(pose))
        self._last_command_pose = tuple(pose)
        self._recorder.write("control", {
            "host_ns": now, "t_s": float(timeline[index]),
            "phase": str(self._compiled["phase"][index]),
            "sample_seq": control["sample_seq"],
            "sample_age_s": control["sample_age_s"],
            "a_raw_uT": a_raw, "a_control_uT": a_control,
            "a_ref_uT": None if not math.isfinite(a_ref) else a_ref,
            "e_center_uT": e_center, "e_band_uT": e_band,
            "depth_ff_m": depth_ff,
            "depth_fb_m": depth_fb,
            "x_cmd_m": float(pose[0]), "y_cmd_m": float(pose[1]),
            "z_cmd_m": float(pose[2]), "rx_cmd_rad": float(pose[3]),
            "ry_cmd_rad": float(pose[4]), "rz_cmd_rad": float(pose[5]),
            "actual_pose_available": actual_pose is not None,
            "actual_pose_m_rad": actual_pose,
            "actual_rx_ns": actual_rx_ns, "lateness_s": lateness,
            "limit_active": bool(getattr(self.controller, "limit_active", False)),
        })
        self._last_plan_index = index
        if index == len(timeline) - 1:
            self.state = "LIFT"
            self.phase = "lift"

    def step(self) -> dict:
        if self.state in {"READY", "END_WAIT", "ABORTED", "FAULT", "UNPREPARED"}:
            return self.snapshot()
        try:
            self._record_new_sensor()
            if self._stop_reason is not None:
                self._begin_abort(self._stop_reason)
                return self.snapshot()
            if self.state == "BASELINE":
                keys = (
                    "baseline_min_samples", "baseline_window_s",
                    "baseline_max_std_uT", "baseline_max_drift_uT_s",
                    "sensor_max_age_s", "filter",
                )
                policy = {key: copy.deepcopy(self._setup[key]) for key in keys}
                policy.update({"airborne_confirmed": True, "pose_static": True})
                try:
                    baseline = self.hub.set_baseline(self._baseline_rows, policy)
                except ValueError:
                    waited = (self._now_ns() - self._baseline_started_ns) / 1e9
                    if waited > float(self._setup["baseline_timeout_s"]):
                        self._begin_abort("baseline_failed")
                    return self.snapshot()
                self._recorder.record_baseline(baseline)
                self._event("baseline_fixed")
                self.state = "APPROACH"
                self.phase = "approach"
                return self.snapshot()
            if self.state == "APPROACH":
                target = tuple(self._compiled["pose_m_rad"][0])
                if not self._approach_sent:
                    self.arm.move_pose(target, self._setup["approach_speed_mm_s"])
                    self._approach_sent = True
                    return self.snapshot()
                state = self.arm.read_state()
                if not self._pose_matches(state["tcp_pose"], target):
                    return self.snapshot()
                self.arm.start_servo()
                if self.controller is not None:
                    self.controller.reset()
                self.hub.set_running(True)
                self._run_started_ns = self._now_ns()
                self._last_plan_index = 0
                self._last_command_pose = target
                self.state = "RUN"
                self.phase = "run"
                self._event("run_started")
                return self.snapshot()
            if self.state == "RUN":
                self._run_step()
            elif self.state == "LIFT":
                self._lift_step(completed=True)
            elif self.state == "ABORT_LIFT":
                self._lift_step(completed=False)
            return self.snapshot()
        except RuntimeError as exc:
            reason = str(exc)
            if reason.startswith("logger_fault"):
                self._fault("logger_fault")
            elif reason in {"stale control sample", "no valid post-baseline control sample"}:
                self._begin_abort("sensor_stale")
            elif reason in {"deadline_miss", "workspace_limit", "step_limit"}:
                self._begin_abort(reason)
            else:
                self._fault("communication_fault" if "source" not in reason else reason)
            return self.snapshot()
        except Exception:
            self._fault("communication_fault")
            return self.snapshot()

    def snapshot(self) -> dict:
        progress = 0.0
        if self._compiled is not None and len(self._compiled["t_s"]) > 1:
            progress = self._last_plan_index / (len(self._compiled["t_s"]) - 1)
        return {
            "state": self.state, "run_id": self.run_id, "phase": self.phase,
            "progress": float(progress), "last_error": self.last_error,
            "run_dir": self.run_dir, "spec": copy.deepcopy(self._spec),
            "setup": copy.deepcopy(self._setup),
        }
