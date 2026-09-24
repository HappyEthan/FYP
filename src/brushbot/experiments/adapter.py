"""Injected robot adapter; importing this module never creates a connection."""

from __future__ import annotations

import fcntl
import json
import math
import os
import time
from pathlib import Path

import numpy as np


def _pose(values) -> tuple[float, ...]:
    try:
        pose = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError("pose must contain six finite SI values") from exc
    if len(pose) != 6 or not np.isfinite(pose).all():
        raise ValueError("pose must contain six finite SI values")
    if any(abs(value) > 10.0 for value in pose[:3]):
        raise ValueError("pose XYZ must be metres, not millimetres")
    return pose


def _coord_to_vendor(values) -> tuple[float, ...]:
    pose = _pose(values)
    return (
        pose[0] * 1000.0, pose[1] * 1000.0, pose[2] * 1000.0,
        math.degrees(pose[3]), math.degrees(pose[4]), math.degrees(pose[5]),
    )


class RobotResourceLock:
    """Non-blocking process lock for one local robot address."""

    def __init__(self, path, address: str):
        self.path = Path(path)
        self.address = str(address)
        self._handle = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise RuntimeError(f"robot {self.address} is already owned") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "address": self.address}) + "\n")
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


class ElfinExperimentArm:
    """Protocol adapter around an explicitly injected ``HuayanRobot`` instance."""

    # 三次同步 HRIF 查询（TCP、关节、FSM）可能超过 20 ms；Servo 运行中禁止调用。
    realtime_state_reads = False

    def __init__(self, robot, setup: dict, *, transport_timeout_s,
                 clock_ns=time.monotonic_ns):
        if (transport_timeout_s is None or isinstance(transport_timeout_s, bool)
                or not isinstance(transport_timeout_s, (int, float))
                or not math.isfinite(transport_timeout_s)
                or transport_timeout_s <= 0):
            raise ValueError("transport_timeout_s must be explicitly verified and positive")
        if setup.get("verified") is not True:
            raise ValueError("installation must be verified")
        self.robot = robot
        self.arm = robot.arm
        self.gripper = robot.gripper
        self.setup = dict(setup)
        self.transport_timeout_s = float(transport_timeout_s)
        self.clock_ns = clock_ns
        self._verify_coordinates()

    def _verify_coordinates(self) -> None:
        if getattr(self.arm, "tcp_name", None) != self.setup.get("tcp_name"):
            raise ValueError("tcp_name does not match injected robot")
        if getattr(self.arm, "ucs_name", None) != self.setup.get("ucs_name"):
            raise ValueError("ucs_name does not match injected robot")
        for setup_key, arm_key in (
            ("tool_coord_si", "tool_coord"),
            ("user_coord_si", "user_coord"),
        ):
            expected = _coord_to_vendor(self.setup[setup_key])
            actual = np.asarray(getattr(self.arm, arm_key, ()), dtype=float)
            if actual.shape != (6,) or not np.allclose(actual, expected, atol=1e-9, rtol=0):
                raise ValueError(f"{setup_key} does not match injected robot {arm_key}")

    def read_state(self) -> dict:
        started = int(self.clock_ns())
        state = self.arm.read()
        finished = int(self.clock_ns())
        pose = _pose(state.tcp_pose)
        return {
            "tcp_pose": pose,
            "fsm": int(state.fsm),
            "available": True,
            "request_start_ns": started,
            "request_end_ns": finished,
        }

    def move_pose(self, pose: tuple, speed_mm_s: float) -> None:
        target = _pose(pose)
        speed = float(speed_mm_s)
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed_mm_s must be positive and finite")
        self.arm.move_l(target, speed_mm_s=speed, wait=False)

    def start_servo(self) -> None:
        state = self.read_state()
        if state["fsm"] != 33:
            raise RuntimeError(f"arm FSM is {state['fsm']}, expected Standby 33")
        self.arm.start_servo()

    def push_pose(self, pose: tuple) -> None:
        self.arm.push_servo_pose(_pose(pose))

    def stop(self) -> None:
        self.arm.stop()

    def configure_grip(self, width_mm: float, speed: int, force: int) -> dict:
        expected = (
            self.setup.get("gripper_width_mm"), self.setup.get("gripper_speed"),
            self.setup.get("gripper_force"),
        )
        if any(value is None for value in expected):
            raise ValueError("gripper installation fields are required")
        if (float(width_mm), int(speed), int(force)) != (
                float(expected[0]), int(expected[1]), int(expected[2])):
            raise ValueError("gripper command differs from verified installation")
        if not self.gripper.is_connected():
            raise RuntimeError("gripper is not connected")
        self.gripper.move_to_width(float(width_mm), speed=int(speed), force=int(force))
        state = self.gripper.wait_done(timeout=float(self.setup["stop_timeout_s"]))
        if not state.connected or state.moving or state.error_code not in (None, 0):
            raise RuntimeError("gripper did not reach a usable stopped state")
        return {
            "requested_width_mm": float(width_mm),
            "actual_width_mm": state.width_mm,
            "caught": state.caught,
            "catch_state": state.catch_state,
            "error_code": state.error_code,
        }
