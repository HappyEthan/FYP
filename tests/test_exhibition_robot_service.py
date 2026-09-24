import time

import pytest

from brushbot.exhibition.contracts import RobotState, TaskState
from brushbot.exhibition.robot_service import RobotTaskService, SafetyConfig


class Arm:
    def __init__(self):
        self.pose = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
        self.calls = []
        self.available = True

    def read_state(self):
        return {"available": self.available, "tcp_pose": self.pose}

    def move_pose(self, pose, speed_mm_s):
        self.pose = tuple(pose)
        self.calls.append(("move_pose", self.pose, speed_mm_s))

    def stop(self):
        self.calls.append(("stop",))


class Sensor:
    connected = True


def make_service():
    arm = Arm()
    cfg = SafetyConfig(
        origin_pose_m_rad=arm.pose,
        ink_x_mm=120,
        ink_y_mm=220,
        ink_safe_z_mm=70,
        ink_surface_z_mm=50,
        ink_depth_mm=5,
        ink_approach_speed_mm_s=5,
        ink_dwell_s=0,
        return_speed_mm_s=10,
    )
    return RobotTaskService(arm=arm, sensor=Sensor(), config=cfg), arm


def test_initial_snapshot_is_ready_and_exposes_unified_state():
    service, _ = make_service()
    snap = service.snapshot()
    assert snap["state"] == RobotState.READY.value
    assert snap["sensor_connected"] is True
    assert snap["task_id"] is None


def test_dip_uses_fixed_backend_route_and_authorizes_one_write():
    service, arm = make_service()
    accepted = service.dip_brush()
    assert accepted["status"] == "accepted"
    task_id = accepted["task_id"]
    service.run_until_idle()
    task = service.task(task_id)
    assert task["state"] == TaskState.COMPLETED.value
    assert [c[0] for c in arm.calls] == ["move_pose"] * 5
    assert service.snapshot()["state"] == RobotState.READY.value
    assert service.snapshot()["dip_authorized"] is True


def test_write_requires_sensor_and_one_shot_dip_authorization():
    service, _ = make_service()
    with pytest.raises(RuntimeError, match="dip"):
        service.start_write("一", plan=[(0.1, 0.2, 0.04, 1, 2, 3)])
    service.dip_brush()
    service.run_until_idle()
    accepted = service.start_write("一", plan=[(0.1, 0.2, 0.04, 1, 2, 3)])
    assert accepted["status"] == "accepted"
    service.run_until_idle()
    assert service.snapshot()["dip_authorized"] is False
    with pytest.raises(RuntimeError, match="dip"):
        service.start_write("一", plan=[(0.1, 0.2, 0.04, 1, 2, 3)])


def test_stop_aborts_without_lift_or_return_and_pause_resumes_index():
    service, arm = make_service()
    service.dip_brush(); service.run_until_idle()
    accepted = service.start_write("一", plan=[(0.1, 0.2, 0.04, 1, 2, 3)] * 3)
    service.step()
    service.pause()
    assert service.snapshot()["state"] == RobotState.PAUSED.value
    index = service.snapshot()["plan_index"]
    service.resume()
    assert service.snapshot()["plan_index"] == index
    service.stop("operator_stop")
    task = service.task(accepted["task_id"])
    assert task["state"] == TaskState.ABORTED.value
    assert arm.calls[-1][0] == "stop"


def test_motion_tasks_are_mutually_exclusive_and_sensor_is_hard_gate():
    service, _ = make_service()
    sensor = service.sensor
    sensor.connected = False
    with pytest.raises(RuntimeError, match="sensor"):
        service.dip_brush()
    sensor.connected = True
    first = service.dip_brush()
    with pytest.raises(RuntimeError, match="active"):
        service.return_to_origin()
    assert first["task_id"]


def test_sensor_disconnect_during_task_faults_without_auto_resume():
    service, arm = make_service()
    service.dip_brush(); service.run_until_idle()
    service.start_write("一", plan=[(0.1, 0.2, 0.04, 1, 2, 3)] * 2)
    service.sensor.connected = False
    service.step()
    assert service.snapshot()["state"] == RobotState.FAULT.value
    calls = list(arm.calls)
    service.sensor.connected = True
    service.step()
    assert arm.calls == calls
