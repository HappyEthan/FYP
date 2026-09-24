import copy
import json
from collections import deque
from pathlib import Path

import pytest

from brushbot.experiments.fake import make_ladder_rig, make_rig


def _control_rows(run_dir):
    path = Path(run_dir) / "control.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_prepare_is_pure_and_start_requires_verified_wait_pose(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    assert rig.arm.calls == []
    rig.arm.pose = (0.2, 0.2, 0.06, 1, 2, 3)
    with pytest.raises(RuntimeError, match="return to start"):
        rig.engine.start()
    assert not any(call["action"] in {"move_pose", "push_pose"} for call in rig.arm.calls)


def test_explicit_start_from_other_xyz_still_uses_original_approach(tmp_path):
    rig = make_ladder_rig(recorder_root=tmp_path)
    original = rig.arm.pose
    rig.arm.pose = (original[0] + 0.01, original[1], original[2], *original[3:])

    rig.engine.start(require_wait_position=False)
    assert rig.engine.state == "BASELINE"
    assert not any(call["action"] == "move_pose" for call in rig.arm.calls)
    rig.advance_until("APPROACH")
    rig.advance()

    approach = [call for call in rig.arm.calls if call["action"] == "move_pose"]
    assert len(approach) == 1
    assert approach[0]["pose"] == pytest.approx(
        tuple(rig.engine._compiled["pose_m_rad"][0]))


def test_explicit_start_from_other_xyz_keeps_orientation_check(tmp_path):
    rig = make_ladder_rig(recorder_root=tmp_path)
    pose = rig.arm.pose
    rig.arm.pose = (*pose[:3], pose[3] + 0.2, *pose[4:])

    with pytest.raises(RuntimeError, match="orientation"):
        rig.engine.start(require_wait_position=False)
    assert not any(call["action"] == "move_pose" for call in rig.arm.calls)


def test_completed_run_remains_at_end_wait_without_automatic_return(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("END_WAIT")
    end_xy = rig.arm.read_state()["tcp_pose"][:2]
    assert end_xy != rig.start_pose[:2]
    assert rig.saved_status == "completed"
    calls_before_wait = len(rig.arm.calls)
    for _ in range(5):
        rig.advance()
    assert len(rig.arm.calls) == calls_before_wait
    assert rig.engine.snapshot()["state"] == "END_WAIT"
    assert not hasattr(rig.engine, "request_return")
    assert not any(call["action"] == "open_gripper" for call in rig.arm.calls)


def test_open_loop_never_calls_feedback(tmp_path):
    rig = make_rig(recorder_root=tmp_path, closed_loop=False)
    rig.engine.start()
    rig.advance_until("END_WAIT")
    assert rig.feedback_calls == 0


def test_prepared_parameters_are_frozen_against_caller_mutation(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    original = copy.deepcopy(rig.engine.snapshot()["spec"])
    rig.spec["path"]["delta_xy_mm"][0] = 999
    assert rig.engine.snapshot()["spec"] == original


def test_stale_sensor_aborts_before_next_servo_command(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("RUN")
    rig.source.enabled = False
    pushed_before = len([c for c in rig.arm.calls if c["action"] == "push_pose"])
    rig.clock.advance(rig.setup["sensor_max_age_s"] + 0.001)
    rig.engine.step()
    pushed_after = len([c for c in rig.arm.calls if c["action"] == "push_pose"])
    assert pushed_after == pushed_before
    assert rig.engine.snapshot()["state"] == "ABORT_LIFT"
    rig.advance_until("ABORTED")


def test_true_sensor_history_lag_reports_buffer_overflow(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.hub._rows = deque(maxlen=3)
    read_one = rig.source.read_frames
    rig.source.read_frames = lambda: [read_one()[0] for _ in range(5)]
    rig.engine.start()

    rig.hub.poll_once()
    snapshot = rig.engine.step()

    assert snapshot["state"] == "FAULT"
    assert snapshot["last_error"] == "sample_buffer_overflow"
    assert not any(call["action"] in {"move_pose", "push_pose"}
                   for call in rig.arm.calls)


def test_baseline_timeout_records_sample_diagnostics(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.source.enabled = False
    rig.engine.start()
    rig.advance_until("ABORTED")

    assert rig.engine.snapshot()["last_error"] == "baseline_failed"
    events = [json.loads(line) for line in
              (Path(rig.engine.run_dir) / "events.jsonl").read_text(
                  encoding="utf-8").splitlines()]
    failure = next(event for event in events if event["event"] == "baseline_failed")
    assert failure["error"] == "insufficient baseline samples"
    assert failure["samples"] == 0
    assert failure["valid_samples"] == 0
    assert rig.engine.snapshot()["baseline_diagnostic"] == {
        "error": "insufficient baseline samples", "samples": 0,
        "valid_samples": 0,
    }
    assert not any(call["action"] == "move_pose" for call in rig.arm.calls)


def test_deadline_miss_does_not_catch_up_or_send_a_late_pose(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("RUN")
    pushed_before = len([c for c in rig.arm.calls if c["action"] == "push_pose"])
    rig.clock.advance(rig.setup["max_tick_lateness_s"] + 0.2)
    rig.hub.poll_once()
    rig.engine.step()
    pushed_after = len([c for c in rig.arm.calls if c["action"] == "push_pose"])
    assert pushed_after == pushed_before
    assert rig.engine.snapshot()["last_error"] == "deadline_miss"
    rig.advance_until("ABORTED")


def test_configured_deadline_tolerance_allows_an_80_ms_scheduler_stall(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine._setup["max_tick_lateness_s"] = 0.1
    rig.engine.start()
    rig.advance_until("RUN")
    pushed_before = len([c for c in rig.arm.calls if c["action"] == "push_pose"])

    rig.clock.advance(0.08)
    rig.hub.poll_once()
    rig.engine.step()

    pushed_after = len([c for c in rig.arm.calls if c["action"] == "push_pose"])
    assert pushed_after == pushed_before + 1
    assert rig.engine.snapshot()["state"] == "RUN"
    assert rig.engine.snapshot()["last_error"] == ""


def test_operator_stop_never_releases_grip(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("RUN")
    rig.engine.request_stop("operator_stop")
    rig.advance_until("ABORTED")
    assert not any(call["action"] in {"open_gripper", "reset", "enable"}
                   for call in rig.arm.calls)
    assert rig.saved_status == "aborted"


def test_logger_failure_is_not_misreported_as_communication_fault(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("RUN")
    rig.engine._recorder._writer_error = "OSError: disk unavailable"
    rig.advance()
    assert rig.engine.snapshot()["state"] == "FAULT"
    assert rig.engine.snapshot()["last_error"] == "logger_fault"


def test_communication_fault_never_sends_automatic_lift_or_resumes(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("RUN")
    original_push = rig.arm.push_pose

    def fail_push(_pose):
        raise RuntimeError("link down")

    rig.arm.push_pose = fail_push
    rig.advance()
    assert rig.engine.snapshot()["state"] == "FAULT"
    assert rig.engine.snapshot()["last_error"] == (
        "communication_fault: RuntimeError: link down")
    calls_after_fault = list(rig.arm.calls)
    rig.arm.push_pose = original_push
    for _ in range(5):
        rig.advance()
    assert rig.arm.calls == calls_after_fault


def test_approach_waits_for_standby_after_pose_arrives(tmp_path):
    """到位读数可能先于控制器 FSM 回到 Standby，不能立刻启动 Servo。"""
    rig = make_rig(recorder_root=tmp_path)
    original_move = rig.arm.move_pose

    def arrive_while_motion_fsm_is_settling(pose, speed_mm_s):
        original_move(pose, speed_mm_s)
        rig.arm.fsm = 25  # Huayan enCPSState_Moving

    rig.arm.move_pose = arrive_while_motion_fsm_is_settling
    rig.engine.start()
    rig.advance_until("APPROACH")
    rig.advance()  # 发送 MoveL；位姿已到，但 FSM 仍不是 Standby。
    rig.advance()

    assert rig.engine.snapshot()["state"] == "APPROACH"
    assert not any(call["action"] == "start_servo" for call in rig.arm.calls)

    rig.arm.fsm = 33
    rig.advance()
    assert rig.engine.snapshot()["state"] == "RUN"


def test_hardware_servo_loop_pushes_without_synchronous_state_reads(tmp_path):
    """真机 Servo 每拍只下发命令，不能让三次 HRIF 状态查询破坏 20 ms 节拍。"""
    rig = make_rig(recorder_root=tmp_path)
    rig.arm.realtime_state_reads = False
    original_read = rig.arm.read_state
    reads = {"count": 0}

    def counted_read():
        reads["count"] += 1
        return original_read()

    rig.arm.read_state = counted_read
    rig.engine.start()
    rig.advance_until("RUN")
    reads_before = reads["count"]
    pushes_before = len([
        call for call in rig.arm.calls if call["action"] == "push_pose"])

    for _ in range(5):
        rig.advance()

    pushes_after = len([
        call for call in rig.arm.calls if call["action"] == "push_pose"])
    assert pushes_after == pushes_before + 5
    assert reads["count"] == reads_before


def test_hardware_servo_lift_uses_last_command_without_state_reads(tmp_path):
    """测量后的固定节拍抬笔也必须沿用最后命令，不能逐拍查询 HRIF。"""
    rig = make_rig(recorder_root=tmp_path)
    rig.arm.realtime_state_reads = False
    original_read = rig.arm.read_state
    reads = {"count": 0}

    def counted_read():
        reads["count"] += 1
        return original_read()

    rig.arm.read_state = counted_read
    rig.engine.start()
    rig.advance_until("LIFT")
    reads_before = reads["count"]
    pushes_before = len([
        call for call in rig.arm.calls if call["action"] == "push_pose"])

    rig.advance()

    pushes_after = len([
        call for call in rig.arm.calls if call["action"] == "push_pose"])
    assert pushes_after == pushes_before + 1
    assert reads["count"] == reads_before


def test_snapshot_exposes_latest_local_magnetic_telemetry(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.start()
    rig.advance_until("RUN")
    rig.advance()

    telemetry = rig.engine.snapshot()["telemetry"]
    assert telemetry["phase"] == "ramp_up"
    assert telemetry["z_cmd_mm"] == pytest.approx(39.995)
    assert telemetry["depth_cmd_mm"] == pytest.approx(0.005)
    assert telemetry["B_uT"] == pytest.approx([10.0, 20.0, 30.0])
    assert telemetry["dBxy_uT"] == pytest.approx(0.0)
    assert telemetry["baseline_id"] == 0


def test_control_rows_record_actual_pose(tmp_path):
    rig = make_rig(recorder_root=str(tmp_path))
    rig.engine.start()
    rig.advance_until("END_WAIT")
    rows = _control_rows(rig.engine.snapshot()["run_dir"])
    assert rows, "expected at least one control row"
    assert all(row["actual_pose_available"] is True for row in rows)
    assert all(row["actual_pose_m_rad"] is not None for row in rows)
    assert all(row["actual_rx_ns"] is not None for row in rows)


def test_actual_pose_is_the_pose_commanded_on_the_previous_tick(tmp_path):
    # 引擎每拍先读实际位姿、再下发命令，所以第 i 拍记录的是第 i-1 拍下发的位置。
    rig = make_rig(recorder_root=str(tmp_path))
    rig.engine.start()
    rig.advance_until("END_WAIT")
    rows = _control_rows(rig.engine.snapshot()["run_dir"])
    for previous, row in zip(rows, rows[1:]):
        expected = [
            previous["x_cmd_m"], previous["y_cmd_m"], previous["z_cmd_m"],
            previous["rx_cmd_rad"], previous["ry_cmd_rad"], previous["rz_cmd_rad"],
        ]
        assert row["actual_pose_m_rad"] == pytest.approx(expected)


def test_pose_read_failure_does_not_abort_the_run(tmp_path, monkeypatch):
    rig = make_rig(recorder_root=str(tmp_path))
    rig.engine.start()
    original = rig.arm.read_state
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        # 只在 RUN 阶段注入故障：APPROACH 阶段的读取没有保护，
        # 打在那里会触发 FAULT，验不到"运行中读失败不中止"。
        if rig.engine.state == "RUN" and calls["n"] % 2 == 0:
            raise RuntimeError("network hiccup")
        return original()

    monkeypatch.setattr(rig.arm, "read_state", flaky)
    rig.advance_until("END_WAIT")
    rows = _control_rows(rig.engine.snapshot()["run_dir"])
    assert any(row["actual_pose_available"] is False for row in rows)
    assert any(row["actual_pose_available"] is True for row in rows)
    assert rig.saved_status == "completed"


def test_ladder_pause_stops_at_origin_rebaselines_and_continues_same_run(tmp_path):
    rig = make_ladder_rig(recorder_root=tmp_path, steps=4, pause_every_passes=4)
    rig.engine.start()
    rig.advance_until("WAIT_OPERATOR", max_steps=5000)

    run_id = rig.engine.run_id
    assert rig.arm.pose[:3] == pytest.approx((0.1, 0.2, 0.05))
    assert rig.arm.calls[-1]["action"] == "stop"
    calls_at_pause = list(rig.arm.calls)
    for _ in range(5):
        rig.advance()
    assert rig.arm.calls == calls_at_pause

    rig.engine.resume_after_operator()
    assert rig.engine.state == "REBASELINE"
    rig.advance_until("END_WAIT", max_steps=5000)

    assert rig.engine.run_id == run_id
    manifest = json.loads(
        (Path(rig.engine.run_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert [item["effective_visit"] for item in manifest["baselines"]] == [0, 4]
    assert rig.saved_status == "completed"
