#!/usr/bin/env python3
"""Safely return the robot to the code-defined Cartesian origin pose."""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ADAPTER_ROOT = Path(__file__).resolve().parents[2] / "elfin-dhag-adapter"

# 零参数真机配置：需要改连接或回位目标时，只改这里。
ROBOT_IP = "192.168.0.10"
GRIPPER_GID = 1
TCP_NAME = "TCP_brush"

# 目标位置：mm；目标姿态：degree。
ORIGIN_X_MM = -370.0
ORIGIN_Y_MM = 500.0
ORIGIN_Z_MM = 130.0
ORIGIN_RX_DEG = 0.0
ORIGIN_RY_DEG = 15.0
ORIGIN_RZ_DEG = 0.0

# 回位安全边界与速度。目标和当前位置都必须位于此范围内。
RETURN_SPEED_MM_S = 30.0
RETURN_SETUP = {
    "workspace_min_mm": [-400.0, 400.0, 17.0],
    "workspace_max_mm": [100.0, 600.0, 150.0],
    "return_speed_mm_s": RETURN_SPEED_MM_S,
    "max_xy_speed_mm_s": RETURN_SPEED_MM_S,
    "max_z_speed_mm_s": RETURN_SPEED_MM_S,
    "pose_tolerance_mm": 0.5,
    "orientation_tolerance_rad": math.radians(1.0),
}


def _preset_origin_pose() -> tuple[float, ...]:
    return (
        ORIGIN_X_MM / 1000.0,
        ORIGIN_Y_MM / 1000.0,
        ORIGIN_Z_MM / 1000.0,
        math.radians(ORIGIN_RX_DEG),
        math.radians(ORIGIN_RY_DEG),
        math.radians(ORIGIN_RZ_DEG),
    )


def _format_pose(pose) -> str:
    values = tuple(float(value) for value in pose)
    xyz = tuple(value * 1000.0 for value in values[:3])
    rpy = tuple(math.degrees(value) for value in values[3:])
    return ("XYZ[mm]=({:.3f}, {:.3f}, {:.3f}), "
            "RPY[deg]=({:.3f}, {:.3f}, {:.3f})").format(*xyz, *rpy)


def execute_return(arm, setup: dict, *, input_fn=input, output_fn=print,
                   sleep=time.sleep, poll_s: float = 0.02) -> int:
    """Confirm and execute one direct MoveL to the preset origin."""
    target = _preset_origin_pose()
    state = arm.read_state()
    if not state.get("available") or state.get("tcp_pose") is None:
        output_fn("无法读取机械臂当前位置；没有发送运动命令。")
        return 2
    current = tuple(float(value) for value in state["tcp_pose"])
    lower = tuple(float(value) for value in setup["workspace_min_mm"])
    upper = tuple(float(value) for value in setup["workspace_max_mm"])
    for pose in (current, target):
        xyz_mm = tuple(value * 1000.0 for value in pose[:3])
        if any(value < lo or value > hi
               for value, lo, hi in zip(xyz_mm, lower, upper)):
            output_fn("当前位置或目标超出代码预设工作空间；没有发送运动命令。")
            return 2

    output_fn("当前位置: " + _format_pose(current))
    output_fn("代码预设原点: " + _format_pose(target))

    answer = input_fn("确认直线路径与周围环境安全后，按 Enter 回到实验原点：").strip()
    if answer:
        output_fn("已取消；没有发送运动命令。")
        return 1

    try:
        arm.move_pose(target, float(setup["return_speed_mm_s"]))
    except KeyboardInterrupt:
        try:
            arm.stop()
        except Exception:
            pass
        output_fn("已收到 Ctrl+C；机械臂停止，回原点操作中止。")
        return 130
    except Exception as exc:
        try:
            arm.stop()
        except Exception:
            pass
        output_fn("回原点失败: {}".format(exc))
        return 2

    output_fn("return_state=COMPLETED")
    return 0


class _HuayanReturnArm:
    """Minimal arm interface used by CartesianReturnController."""

    def __init__(self, robot):
        self.arm = robot.arm

    def read_state(self) -> dict:
        state = self.arm.read()
        return {
            "tcp_pose": tuple(float(value) for value in state.tcp_pose),
            "fsm": int(state.fsm),
            "available": True,
        }

    def move_pose(self, pose, speed_mm_s: float) -> None:
        self.arm.move_l(tuple(float(value) for value in pose),
                        speed_mm_s=float(speed_mm_s), wait=True)

    def stop(self) -> None:
        self.arm.stop()


def _connect_arm(ip: str, gid: int, tcp_name: str):
    if ADAPTER_ROOT.is_dir() and str(ADAPTER_ROOT) not in sys.path:
        sys.path.insert(0, str(ADAPTER_ROOT))
    try:
        from huayan_robot import HuayanRobot
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "找不到 elfin-dhag-adapter；请使用其 Python 环境，或设置 "
            "PYTHONPATH={}".format(ADAPTER_ROOT)) from exc
    return _HuayanReturnArm(HuayanRobot(
        ip, gripper_gid=gid, tcp_name=tcp_name))


def main(*, input_fn=input, output_fn=print, sleep=time.sleep,
         connect_arm=None) -> int:
    connector = connect_arm or _connect_arm

    try:
        arm = connector(ROBOT_IP, GRIPPER_GID, TCP_NAME)
        return execute_return(
            arm, RETURN_SETUP, input_fn=input_fn, output_fn=output_fn,
            sleep=sleep)
    except (RuntimeError, ValueError) as exc:
        print("回原点失败: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
