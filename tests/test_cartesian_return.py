import math

import numpy as np
import pytest

from brushbot.experiments.cartesian_return import (
    CartesianReturnController,
    build_return_route,
    target_pose_si,
)
from brushbot.experiments.fake import FakeArm


def _setup():
    return {
        "workspace_min_mm": [0.0, 0.0, 0.0],
        "workspace_max_mm": [500.0, 500.0, 200.0],
        "return_speed_mm_s": 10.0,
        "max_xy_speed_mm_s": 25.0,
        "max_z_speed_mm_s": 10.0,
    }


def test_target_pose_converts_mm_degrees_to_si():
    pose = target_pose_si(100, 200, 60, 90, 0, -180)
    assert pose == pytest.approx((0.1, 0.2, 0.06, np.pi / 2, 0, -np.pi))


def test_route_is_independent_of_strokeplan_and_orders_safe_segments():
    current = (0.3, 0.2, 0.02, 0.1, 0.2, 0.3)
    target = (0.1, 0.4, 0.06, 1.0, 2.0, 3.0)
    assert build_return_route(current, target, _setup()) == [
        (0.3, 0.2, 0.06, 0.1, 0.2, 0.3),
        (0.1, 0.4, 0.06, 0.1, 0.2, 0.3),
        (0.1, 0.4, 0.06, 1.0, 2.0, 3.0),
    ]


def test_route_descends_only_after_xy_and_orientation_when_current_is_higher():
    current = (0.3, 0.2, 0.10, 0.1, 0.2, 0.3)
    target = (0.1, 0.4, 0.06, 1.0, 2.0, 3.0)
    assert build_return_route(current, target, _setup()) == [
        (0.1, 0.4, 0.10, 0.1, 0.2, 0.3),
        (0.1, 0.4, 0.10, 1.0, 2.0, 3.0),
        (0.1, 0.4, 0.06, 1.0, 2.0, 3.0),
    ]


def test_route_removes_duplicate_points():
    pose = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
    assert build_return_route(pose, pose, _setup()) == []


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_target_and_route_reject_nonfinite_values(bad):
    with pytest.raises(ValueError, match="finite"):
        target_pose_si(100, 200, 60, 0, bad, 0)
    with pytest.raises(ValueError, match="finite"):
        build_return_route((0.1, 0.2, 0.06, 0, 0, 0),
                           (0.1, bad, 0.06, 0, 0, 0), _setup())


def test_prepare_rejects_workspace_before_sending_motion():
    arm = FakeArm()
    controller = CartesianReturnController(arm, _setup())
    with pytest.raises(ValueError, match="workspace"):
        controller.prepare((0.6, 0.2, 0.06, 0, 0, 0))
    assert not any(call["action"] == "move_pose" for call in arm.calls)


def test_controller_completes_route_one_command_per_step_without_control_calls():
    arm = FakeArm((0.3, 0.2, 0.02, 0.1, 0.2, 0.3))
    target = (0.1, 0.4, 0.06, 1.0, 2.0, 3.0)
    controller = CartesianReturnController(arm, _setup())
    controller.prepare(target)
    assert controller.snapshot()["state"] == "READY"
    assert arm.calls == []
    for _ in range(10):
        before = len(arm.calls)
        controller.step()
        assert len(arm.calls) - before <= 1
        if controller.snapshot()["state"] == "COMPLETED":
            break
    assert controller.snapshot()["state"] == "COMPLETED"
    assert arm.pose == target
    assert not any(call["action"] in {"enable", "reset", "grip", "open_gripper"}
                   for call in arm.calls)


def test_duplicate_prepare_is_idempotent_but_different_target_is_rejected():
    arm = FakeArm()
    controller = CartesianReturnController(arm, _setup())
    target = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
    first = controller.prepare(target)
    assert controller.prepare(target)["operation_id"] == first["operation_id"]
    with pytest.raises(RuntimeError, match="active"):
        controller.prepare((0.2, 0.2, 0.06, 1.0, 2.0, 3.0))


def test_stop_calls_only_arm_stop_and_never_resumes():
    arm = FakeArm((0.3, 0.2, 0.02, 0.1, 0.2, 0.3))
    controller = CartesianReturnController(arm, _setup())
    controller.prepare((0.1, 0.4, 0.06, 1.0, 2.0, 3.0))
    controller.step()
    controller.request_stop("operator_stop")
    calls = list(arm.calls)
    assert calls[-1]["action"] == "stop"
    assert controller.snapshot()["state"] == "ABORTED"
    for _ in range(3):
        controller.step()
    assert arm.calls == calls


def test_unavailable_state_faults_before_motion_and_does_not_retry():
    class UnavailableArm(FakeArm):
        def read_state(self):
            return {"available": False}

    arm = UnavailableArm()
    controller = CartesianReturnController(arm, _setup())
    controller.prepare((0.1, 0.2, 0.06, 1.0, 2.0, 3.0))
    controller.step()
    assert controller.snapshot()["state"] == "FAULT"
    calls = list(arm.calls)
    controller.step()
    assert arm.calls == calls
    assert not any(call["action"] == "move_pose" for call in calls)
