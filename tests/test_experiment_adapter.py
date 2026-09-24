from dataclasses import dataclass
import sys

import pytest

from brushbot.experiments.adapter import ElfinExperimentArm, RobotResourceLock
from brushbot.experiments.fake import FakeArm


def _setup():
    return {
        "verified": True,
        "tcp_name": "brush-root",
        "ucs_name": "paper",
        "tool_coord_si": [0.001, 0.002, 0.003, 0.1, 0.2, 0.3],
        "user_coord_si": [0, 0, 0, 0, 0, 0],
        "vertical_rpy_rad": [1, 2, 3],
        "gripper_width_mm": 10,
        "gripper_speed": 30,
        "gripper_force": 30,
        "stop_timeout_s": 1,
    }


def test_fake_stop_never_releases_grip():
    arm = FakeArm()
    arm.configure_grip(10, 30, 30)
    arm.stop()
    assert [call["action"] for call in arm.calls] == ["grip", "stop"]


def test_fake_import_and_stop_have_no_hardware_side_effects():
    before = set(sys.modules)
    arm = FakeArm()
    arm.stop()
    imported = set(sys.modules) - before
    assert not any(name == "huayan_robot" or name.startswith("huayan_robot.") for name in imported)
    assert not any(call["action"] in {"enable", "reset", "open_gripper"} for call in arm.calls)


@dataclass
class State:
    tcp_pose: tuple = (0.1, 0.2, 0.06, 1.0, 2.0, 3.0)
    joints: tuple = (0.0,) * 6
    fsm: int = 33


class FakeVendorArm:
    def __init__(self):
        self.tcp_name = "brush-root"
        self.ucs_name = "paper"
        self.tool_coord = [1.0, 2.0, 3.0, 5.729577951, 11.459155903, 17.188733854]
        self.user_coord = [0.0] * 6
        self.calls = []

    def read(self):
        self.calls.append(("read",))
        return State()

    def move_l(self, pose, **kwargs):
        self.calls.append(("move_l", tuple(pose), kwargs))

    def start_servo(self):
        self.calls.append(("start_servo",))

    def push_servo_pose(self, pose):
        self.calls.append(("push", tuple(pose)))

    def stop(self):
        self.calls.append(("stop",))


class FakeVendorGripper:
    def __init__(self):
        self.calls = []

    def is_connected(self):
        return True

    def move_to_width(self, width, *, speed, force):
        self.calls.append(("move", width, speed, force))

    def wait_done(self, timeout):
        self.calls.append(("wait", timeout))
        return type("GripState", (), {
            "connected": True, "moving": False, "caught": True,
            "catch_state": 1, "width_mm": 12.5, "error_code": 0,
        })()


class FakeRobot:
    def __init__(self):
        self.arm = FakeVendorArm()
        self.gripper = FakeVendorGripper()


def test_adapter_maps_nonblocking_move_and_never_reads_during_push():
    robot = FakeRobot()
    adapter = ElfinExperimentArm(robot, _setup(), transport_timeout_s=0.5,
                                 clock_ns=iter([10, 20]).__next__)
    adapter.move_pose((0.1, 0.2, 0.06, 1, 2, 3), speed_mm_s=10)
    adapter.push_pose((0.101, 0.2, 0.06, 1, 2, 3))
    assert robot.arm.calls == [
        ("move_l", (0.1, 0.2, 0.06, 1.0, 2.0, 3.0),
         {"speed_mm_s": 10.0, "wait": False}),
        ("push", (0.101, 0.2, 0.06, 1.0, 2.0, 3.0)),
    ]


def test_adapter_reads_state_with_request_bounds_and_fsm():
    adapter = ElfinExperimentArm(FakeRobot(), _setup(), transport_timeout_s=0.5,
                                 clock_ns=iter([10, 20]).__next__)
    state = adapter.read_state()
    assert state["tcp_pose"] == State().tcp_pose
    assert state["fsm"] == 33
    assert state["request_start_ns"] == 10
    assert state["request_end_ns"] == 20


def test_grip_records_catch_semantics_without_claiming_requested_width():
    robot = FakeRobot()
    adapter = ElfinExperimentArm(robot, _setup(), transport_timeout_s=0.5)
    result = adapter.configure_grip(10, 30, 30)
    assert result["requested_width_mm"] == 10
    assert result["actual_width_mm"] == 12.5
    assert result["caught"] is True
    assert robot.gripper.calls == [("move", 10.0, 30, 30), ("wait", 1.0)]


def test_adapter_rejects_missing_timeout_coordinate_mismatch_and_mm_pose():
    robot = FakeRobot()
    with pytest.raises(ValueError, match="transport_timeout_s"):
        ElfinExperimentArm(robot, _setup(), transport_timeout_s=None)
    robot = FakeRobot()
    robot.arm.tcp_name = "wrong"
    with pytest.raises(ValueError, match="tcp_name"):
        ElfinExperimentArm(robot, _setup(), transport_timeout_s=0.5)


def test_robot_resource_lock_rejects_second_process_owner(tmp_path):
    first = RobotResourceLock(tmp_path / "robot.lock", "192.0.2.10")
    second = RobotResourceLock(tmp_path / "robot.lock", "192.0.2.10")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already owned"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
    adapter = ElfinExperimentArm(FakeRobot(), _setup(), transport_timeout_s=0.5)
    with pytest.raises(ValueError, match="metres"):
        adapter.push_pose((100, 200, 60, 1, 2, 3))


def test_stop_only_calls_arm_stop():
    robot = FakeRobot()
    adapter = ElfinExperimentArm(robot, _setup(), transport_timeout_s=0.5)
    adapter.stop()
    assert robot.arm.calls == [("stop",)]
    assert robot.gripper.calls == []


def test_local_robot_resource_is_exclusive(tmp_path):
    path = tmp_path / "robot.lock"
    first = RobotResourceLock(path, "192.0.2.1")
    first.acquire()
    second = RobotResourceLock(path, "192.0.2.1")
    with pytest.raises(RuntimeError, match="already owned"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()
