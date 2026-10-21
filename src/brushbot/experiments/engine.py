"""Hardware-agnostic unified open/closed-loop experiment state machine."""

from __future__ import annotations

import copy
import math

import numpy as np

from brushbot.experiments.trajectory import compile_experiment


def height_deadline_policy(setup, min_z_mm=20.):
    """Opt in to ordered timing recovery above a checked command-height floor."""
    floor = max(float(setup['workspace_min_mm'][2]),
                float(setup['contact_z_mm'])-float(setup['max_depth_mm']))
    if not math.isfinite(min_z_mm) or min_z_mm < floor:
        raise ValueError('timing continuation height is below the installation Z limit')
    return dict(mode='continue_above_z', min_z_mm=float(min_z_mm))


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
        self._baseline_diagnostic = None
        self._baseline_started_ns = None
        self._approach_sent = False
        self._run_started_ns = None
        self._last_plan_index = 0
        self._last_command_pose = None
        self._stop_reason = None
        self._pause_cursor = 0
        self._automatic_rebaseline_cursor = 0
        self._pause_started_ns = None
        self._pending_next_visit = None
        self._telemetry = None
        self._last_push_started_ns = None
        self._last_push_finished_ns = None
        self._deadline_diagnostic = None
        self._deadline_recovery_count = 0
        self._last_deadline_recovery = None

    def prepare(self, spec: dict, setup: dict) -> dict:
        if self.state not in {"UNPREPARED", "READY"}:
            raise RuntimeError("cannot prepare while an operation is active")
        self._compiled = compile_experiment(spec, setup, self.dt_s)
        self._spec = copy.deepcopy(spec)
        self._setup = copy.deepcopy(setup)
        self.state = "READY"
        self.phase = "ready"
        self.last_error = ""
        self._telemetry = None
        return self.snapshot()

    def _now_ns(self) -> int:
        return int(self.clock.now_ns())

    def _push_pose(self, pose) -> None:
        self._last_push_started_ns = self._now_ns()
        self._last_push_finished_ns = None
        try:
            self.arm.push_pose(pose)
        finally:
            self._last_push_finished_ns = self._now_ns()

    def _command_timing(self):
        start, end = self._last_push_started_ns, self._last_push_finished_ns
        return dict(command_started_ns=start, command_finished_ns=end,
                    command_duration_s=None if start is None or end is None else (end-start)/1e9)

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

    def start(self, *, require_wait_position: bool = True) -> None:
        if self.state != "READY" or self._compiled is None:
            raise RuntimeError("engine must be READY before start")
        state = self.arm.read_state()
        if not state.get("available"):
            raise RuntimeError("arm state is unavailable")
        if require_wait_position and not self._pose_matches(
                state["tcp_pose"], self._start_pose()):
            raise RuntimeError("arm is not at the verified wait pose; return to start first")
        if not require_wait_position:
            actual = np.asarray(state["tcp_pose"], dtype=float)
            expected = np.asarray(self._start_pose(), dtype=float)
            if actual.shape != (6,) or not np.isfinite(actual).all():
                raise RuntimeError("arm pose is unavailable or invalid")
            angle = np.abs((actual[3:] - expected[3:] + np.pi) % (2 * np.pi) - np.pi)
            if np.any(angle > float(self._setup["orientation_tolerance_rad"])):
                raise RuntimeError("arm orientation differs from experiment setup")
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
        self._baseline_diagnostic = None
        self._baseline_started_ns = self._now_ns()
        self._approach_sent = False
        self._stop_reason = None
        self._pause_cursor = 0
        self._automatic_rebaseline_cursor = 0
        self._pause_started_ns = None
        self._pending_next_visit = None
        self.feedback_calls = 0
        self._telemetry = None
        self._last_push_started_ns = self._last_push_finished_ns = None
        self._deadline_diagnostic = None
        self._deadline_recovery_count = 0
        self._last_deadline_recovery = None
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
        if self.state in {"BASELINE", "REBASELINE"}:
            self._baseline_rows.extend(rows)

    def resume_after_operator(self) -> None:
        """Acknowledge an intentional ladder pause and start a fresh baseline."""
        if self.state != "WAIT_OPERATOR":
            raise RuntimeError("engine is not waiting for the operator")
        self._begin_rebaseline("rebaseline_started")

    def _begin_rebaseline(self, event_name: str) -> None:
        """Stop using the previous offset and collect a fresh stationary baseline."""
        self._baseline_rows = []
        self._baseline_started_ns = self._now_ns()
        self.hub.begin_baseline()
        self.state = "REBASELINE"
        self.phase = "rebaseline"
        self._event(event_name, effective_visit=self._pending_next_visit)

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
        if self._last_command_pose is not None:
            current = tuple(self._last_command_pose)
        else:
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
        self._push_pose(target)
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

    def _control_diagnostics(self):
        return {}

    def _command_for_tick(self, index, phase, pose, depth_ff, a_control, a_ref):
        """Return the TCP command, feedback depth, band error and active limits."""
        depth_fb = 0.0
        e_band = None
        limits = []
        if self._spec["control"]["enabled"]:
            if self.controller is None:
                raise RuntimeError("closed-loop controller is unavailable")
            depth_cmd = self.controller.step_magnitude(
                a_control, a_ref, depth_ff_m=depth_ff)
            self.feedback_calls += 1
            depth_fb = float(depth_cmd - depth_ff)
            pose[2] = float(self._setup["contact_z_mm"]) / 1000.0 - depth_cmd
            deadband = float(self._spec["control"]["deadband_uT"])
            error = a_ref - a_control
            e_band = math.copysign(max(abs(error) - deadband, 0.0), error)
            if self.controller.limit_active:
                limits.append("controller")
        return pose, depth_fb, e_band, limits

    def _reset_feedback_state(self, pose):
        """Adapter hook for segment-local command history."""

    def _select_run_index(self, elapsed):
        timeline = self._compiled["t_s"]
        # The nanosecond clock can land exactly on a tick while the floating
        # timeline stores that tick one ulp above it (e.g. 0.7 vs 0.7000000000000001).
        index = min(int(np.searchsorted(timeline, elapsed + 1e-9, side="right") - 1), len(timeline) - 1)
        return max(index, 0)

    def _run_deadline(self, index, now, *, checkpoint):
        timeline = self._compiled['t_s']
        # The clock is integral nanoseconds. Quantize each timeline timestamp
        # before subtraction so an exact 100 ms interval stays at the boundary.
        target_ns = int(round(float(timeline[index])*1e9))
        previous_ns = int(round(float(timeline[self._last_plan_index])*1e9))
        elapsed_ns = now-self._run_started_ns
        lateness_ns = elapsed_ns-target_ns
        ahead_ns = target_ns-previous_ns
        allowed_ns = int(round(float(self._setup['max_tick_lateness_s'])*1e9))
        allowed_advance_ns = max(int(round(2.5*self.dt_s*1e9)), allowed_ns)
        if ahead_ns > allowed_advance_ns or lateness_ns > allowed_ns:
            diagnostic = dict(checkpoint=checkpoint,
                trajectory_phase=str(self._compiled['phase'][index]),
                timeline_policy=self._spec.get('timeline_policy', 'wall_clock'),
                last_plan_index=self._last_plan_index, next_plan_index=index,
                last_plan_t_s=previous_ns/1e9, next_plan_t_s=target_ns/1e9,
                elapsed_s=elapsed_ns/1e9, lateness_s=lateness_ns/1e9,
                planned_advance_s=ahead_ns/1e9, allowed_lateness_s=allowed_ns/1e9,
                allowed_plan_advance_s=allowed_advance_ns/1e9, **self._command_timing())
            policy = self._spec.get('deadline_policy', {})
            if (policy.get('mode') == 'continue_above_z'
                    and self._spec.get('timeline_policy') == 'sequential_20ms'
                    and not self._spec['control']['enabled']
                    and self._last_command_pose is not None):
                current_z = float(self._last_command_pose[2])*1000
                next_z = float(self._compiled['pose_m_rad'][index, 2])*1000
                if min(current_z, next_z) > policy['min_z_mm']:
                    diagnostic.update(min_z_mm=policy['min_z_mm'], current_z_mm=current_z,
                                      next_z_mm=next_z, action='continue_in_order')
                    # Keep the next unsent point, and remove only the observed
                    # scheduling gap from the nominal execution clock.
                    self._run_started_ns += max(0, lateness_ns)
                    self._deadline_recovery_count += 1
                    self._last_deadline_recovery = diagnostic
                    self._event('deadline_recovered', **diagnostic)
                    return 0.
            self._deadline_diagnostic = diagnostic
            self._event('deadline_miss', **diagnostic)
            self._begin_abort('deadline_miss')
            return None
        return lateness_ns/1e9

    def _run_step(self) -> None:
        now = self._now_ns()
        control = self.hub.latest_control(now)
        elapsed = (now - self._run_started_ns) / 1e9
        timeline = self._compiled["t_s"]
        index = self._select_run_index(elapsed)
        if index is None:
            return
        pause_indices = self._compiled.get("pause_after_indices", [])
        pause_index = None
        if self._pause_cursor < len(pause_indices):
            candidate = int(pause_indices[self._pause_cursor])
            if index >= candidate:
                index = candidate
                pause_index = candidate
        automatic_indices = self._compiled.get(
            "automatic_rebaseline_after_indices", [])
        automatic_index = None
        if self._automatic_rebaseline_cursor < len(automatic_indices):
            candidate = int(automatic_indices[self._automatic_rebaseline_cursor])
            if index >= candidate:
                index = candidate
                automatic_index = candidate
        # 判据看"计划时间推进了多少"，而不是索引差值，并且至少容忍两个样本。
        # 时间轴的采样时刻与引擎的 elapsed 各自带浮点误差：梯子的样本落在精确的 0.02 网格上，
        # 但整体与 elapsed 的 k*0.02 网格有约 1e-15 的偏移。于是一拍之内可能同时跨过两个样本
        # ——索引差 2、计划时间推进 2*dt，而对齐偏移只有 1e-15 量级。用索引判（或按 1.5*dt 判
        # 计划时间）都会把这种噪声当成掉队，实测在 27389 个样本上误判 228 次，整轮扫描被误杀。
        # 2.5*dt 是避免对齐伪影的下限；若 installation 明确允许更大的调度抖动，则计划推进判据
        # 必须使用同一容差，否则 max_tick_lateness_s 放宽后仍会被这里的固定 50 ms 提前中止。
        lateness = self._run_deadline(index, now, checkpoint='before_preparation')
        if lateness is None:
            return
        actual_pose = None
        actual_rx_ns = None
        if getattr(self.arm, "realtime_state_reads", False):
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
        sample = self.hub.take_since(control["sample_seq"] - 1)[0]
        a_raw = math.hypot(float(sample["dBx_uT"]), float(sample["dBy_uT"]))
        a_control = float(control["a_control_uT"])
        a_ref = float(self._compiled["g_ref_uT"][index])
        e_center = None if not math.isfinite(a_ref) else a_ref - a_control
        phase = str(self._compiled["phase"][index])
        pose, depth_fb, e_band, limits = self._command_for_tick(
            index, phase, pose, depth_ff, a_control, a_ref)
        self._check_pose(pose)
        # Preparation/state reads may themselves block. Recheck before sending;
        # an expired deadline must either meet the height policy or abort.
        if self._run_deadline(index, self._now_ns(), checkpoint='before_push') is None:
            return
        self._push_pose(tuple(pose))
        self._last_command_pose = tuple(pose)
        self._telemetry = {
            "host_ns": now,
            "phase": str(self._compiled["phase"][index]),
            "z_cmd_mm": float(pose[2]) * 1000.0,
            "depth_cmd_mm": (float(self._setup["contact_z_mm"])/1000. - pose[2]) * 1000.,
            "B_uT": [
                float(sample["Bx_uT"]), float(sample["By_uT"]),
                float(sample["Bz_uT"]),
            ],
            "dBxy_uT": a_raw,
            "dBxy_filtered_uT": a_control,
            "baseline_id": sample.get("baseline_id"),
        }
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
            "depth_cmd_m": float(self._setup["contact_z_mm"])/1000. - float(pose[2]),
            "x_cmd_m": float(pose[0]), "y_cmd_m": float(pose[1]),
            "z_cmd_m": float(pose[2]), "rx_cmd_rad": float(pose[3]),
            "ry_cmd_rad": float(pose[4]), "rz_cmd_rad": float(pose[5]),
            "actual_pose_available": actual_pose is not None,
            "actual_pose_m_rad": actual_pose,
            "actual_rx_ns": actual_rx_ns, "lateness_s": lateness,
            **self._command_timing(),
            "deadline_recovery_count": self._deadline_recovery_count,
            "limit_active": bool(limits), "limit_reasons": limits,
            **self._control_diagnostics(),
        })
        self._last_plan_index = index
        if pause_index is not None:
            self.hub.set_running(False)
            self.arm.stop()
            self._pause_started_ns = now
            self._pending_next_visit = int(
                self._compiled["pause_next_visits"][self._pause_cursor])
            self._pause_cursor += 1
            self.state = "WAIT_OPERATOR"
            self.phase = "wait_operator"
            self._event(
                "operator_pause_started",
                effective_visit=self._pending_next_visit,
                completed_passes=self._pending_next_visit,
            )
            return
        if automatic_index is not None:
            self.hub.set_running(False)
            self.arm.stop()
            self._pause_started_ns = now
            self._pending_next_visit = int(
                self._compiled["automatic_rebaseline_next_visits"][
                    self._automatic_rebaseline_cursor])
            self._automatic_rebaseline_cursor += 1
            self._begin_rebaseline("automatic_rebaseline_started")
            return
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
            if self.state in {"BASELINE", "REBASELINE"}:
                rebaseline = self.state == "REBASELINE"
                keys = (
                    "baseline_min_samples", "baseline_window_s",
                    "baseline_max_std_uT", "baseline_max_drift_uT_s",
                    "sensor_max_age_s", "filter",
                )
                policy = {key: copy.deepcopy(self._setup[key]) for key in keys}
                policy.update({"airborne_confirmed": True, "pose_static": True})
                try:
                    baseline = self.hub.set_baseline(
                        self._baseline_rows, policy,
                        enforce_quality=(
                            self._spec["path"].get("pause_every_passes") is None
                            and self._spec["path"].get("wetting") is None),
                    )
                except ValueError as exc:
                    waited = (self._now_ns() - self._baseline_started_ns) / 1e9
                    if waited > float(self._setup["baseline_timeout_s"]):
                        diagnostics = {
                            "error": str(exc),
                            "samples": len(self._baseline_rows),
                            "valid_samples": sum(
                                bool(row.get("valid")) for row in self._baseline_rows),
                        }
                        source_diagnostics = getattr(
                            self.hub.source, "diagnostics", None)
                        if isinstance(source_diagnostics, dict):
                            diagnostics["source"] = source_diagnostics
                        self._baseline_diagnostic = diagnostics
                        self._event("baseline_failed", **diagnostics)
                        self._begin_abort("baseline_failed")
                    return self.snapshot()
                baseline["effective_visit"] = (
                    int(self._pending_next_visit) if rebaseline else 0)
                self._recorder.record_baseline(baseline)
                self._event(
                    "baseline_fixed", baseline_id=baseline["baseline_id"],
                    effective_visit=baseline["effective_visit"])
                if rebaseline:
                    self.arm.start_servo()
                    if self.controller is not None:
                        self.controller.reset()
                    self._reset_feedback_state(self._last_command_pose)
                    self.hub.set_running(True)
                    # All stopped preparation, including synchronous StartServo,
                    # belongs to the pause, not to the next command's deadline.
                    self._run_started_ns += self._now_ns()-int(self._pause_started_ns)
                    self.state = "RUN"
                    self.phase = "run"
                    self._event(
                        "run_resumed", baseline_id=baseline["baseline_id"],
                        effective_visit=baseline["effective_visit"])
                    return self.snapshot()
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
                if (not self._pose_matches(state["tcp_pose"], target)
                        or int(state.get("fsm", -1)) != 33):
                    return self.snapshot()
                self.arm.start_servo()
                if self.controller is not None:
                    self.controller.reset()
                self.hub.set_running(True)
                self._run_started_ns = self._now_ns()
                self._last_plan_index = 0
                self._last_command_pose = target
                self._reset_feedback_state(target)
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
            elif reason == "sample_buffer_overflow":
                self._fault(reason)
            elif reason in {"stale control sample", "no valid post-baseline control sample"}:
                self._begin_abort("sensor_stale")
            elif reason in {"deadline_miss", "workspace_limit", "step_limit",
                            "sensor_invalid", "depth_limit", "speed_limit",
                            "z_speed_limit", "acceleration_limit",
                            "feedback_envelope_limit", "feedback_phase_invalid"}:
                self._begin_abort(reason)
            else:
                self._fault(
                    reason if "source" in reason else
                    "communication_fault: {}: {}".format(
                        type(exc).__name__, reason))
            return self.snapshot()
        except Exception as exc:
            self._fault("communication_fault: {}: {}".format(
                type(exc).__name__, exc))
            return self.snapshot()

    def snapshot(self) -> dict:
        progress = 0.0
        if self._compiled is not None and len(self._compiled["t_s"]) > 1:
            progress = self._last_plan_index / (len(self._compiled["t_s"]) - 1)
        return {
            "state": self.state, "run_id": self.run_id, "phase": self.phase,
            "progress": float(progress), "last_error": self.last_error,
            "baseline_diagnostic": copy.deepcopy(self._baseline_diagnostic),
            "run_dir": self.run_dir, "spec": copy.deepcopy(self._spec),
            "setup": copy.deepcopy(self._setup),
            "telemetry": copy.deepcopy(self._telemetry),
            "deadline_diagnostic": copy.deepcopy(self._deadline_diagnostic),
            "deadline_recovery_count": self._deadline_recovery_count,
            "last_deadline_recovery": copy.deepcopy(self._last_deadline_recovery),
        }
