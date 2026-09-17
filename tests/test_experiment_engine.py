import copy

import pytest

from brushbot.experiments.fake import make_rig


def test_prepare_is_pure_and_start_requires_verified_wait_pose(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    assert rig.arm.calls == []
    rig.arm.pose = (0.2, 0.2, 0.06, 1, 2, 3)
    with pytest.raises(RuntimeError, match="return to start"):
        rig.engine.start()
    assert not any(call["action"] in {"move_pose", "push_pose"} for call in rig.arm.calls)


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
    calls_after_fault = list(rig.arm.calls)
    rig.arm.push_pose = original_push
    for _ in range(5):
        rig.advance()
    assert rig.arm.calls == calls_after_fault
