#!/usr/bin/env python3
"""人工确认后只把夹爪夹到指定开口宽度；不移动机械臂，也不自动松爪。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ADAPTER_ROOT = Path(__file__).resolve().parents[2] / "elfin-dhag-adapter"
if ADAPTER_ROOT.is_dir() and str(ADAPTER_ROOT) not in sys.path:
    sys.path.insert(0, str(ADAPTER_ROOT))

try:
    from huayan_robot import GripperError, HuayanRobot
except ModuleNotFoundError as exc:  # pragma: no cover - depends on external adapter
    raise SystemExit(
        "找不到 elfin-dhag-adapter；请使用其 Python 环境，或设置 "
        "PYTHONPATH=/home/ethan/elfin-dhag-adapter") from exc


DEFAULT_WIDTH_MM = 14.0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width-mm", type=float, default=DEFAULT_WIDTH_MM,
                        help="目标夹爪开口宽度，默认 14 mm")
    parser.add_argument("--ip", default="192.168.0.10")
    parser.add_argument("--gid", type=int, default=1)
    parser.add_argument("--speed", type=int, default=30)
    parser.add_argument("--force", type=int, default=30)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--yes", action="store_true",
                        help="跳过人工 Enter 确认；仅适合已检查清空夹持区域的情况")
    args = parser.parse_args(argv)

    if not 0.0 <= args.width_mm <= 95.0:
        parser.error("width_mm must be within [0, 95]")
    if args.speed <= 0 or args.force <= 0 or args.timeout_s <= 0:
        parser.error("speed, force and timeout-s must be positive")

    robot = HuayanRobot(args.ip, gripper_gid=args.gid)
    moving = False
    try:
        before = robot.gripper.read()
        print("当前夹爪状态:", before)
        if not before.connected:
            print(f"中止：夹爪未连接，错误码={before.error_code}", file=sys.stderr)
            return 2
        if not args.yes:
            input(
                f"夹爪将移动到开口 {args.width_mm:g} mm；请确认毛笔已放好、夹持区域清空。"
                "按 Enter 执行: "
            )

        robot.gripper.move_to_width(
            args.width_mm, speed=args.speed, force=args.force)
        moving = True
        after = robot.gripper.wait_done(timeout=args.timeout_s)
        moving = False
        print("夹爪已到位:", after)
        print("本脚本不会自动松爪；请由操作者另行决定后续操作。")
        return 0
    except KeyboardInterrupt:
        if moving:
            try:
                robot.gripper.stop()
            except Exception:
                pass
        print("已由 Ctrl+C 中断；没有发送松爪命令。", file=sys.stderr)
        return 130
    except (GripperError, ValueError) as exc:
        print(f"夹爪操作失败: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
