#!/usr/bin/env python
"""Safely exercise the DH AG-160-95: close, open, then move to 10 mm."""

import argparse
import sys

from brushbot.backends.vendor.CPS import CPSClient
from brushbot.gripper import Gripper, GripperError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", default="192.168.0.10", help="controller IP")
    parser.add_argument("--gid", type=int, default=1, help="registered gripper ID")
    parser.add_argument("--speed", type=int, default=30, help="speed percent (1-100)")
    parser.add_argument("--force", type=int, default=30, help="force percent (20-100)")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--yes", action="store_true", help="skip safety confirmation")
    args = parser.parse_args()

    if not args.yes:
        answer = input(
            "夹爪将依次全闭、全开、移动到 10mm；请清空指间区域。输入 yes 执行: "
        )
        if answer.strip().lower() != "yes":
            sys.exit("已取消")

    gripper = Gripper(CPSClient(args.ip), gid=args.gid)
    try:
        if not gripper.is_connected():
            sys.exit("夹爪未连接：请检查供电、RS485 线序和示教器插件设置")
        actions = (("全闭", gripper.close), ("全开", gripper.open),
                   ("10mm", lambda **kw: gripper.move_to_width(10, **kw)))
        for label, action in actions:
            print(f"执行 {label} ...")
            action(speed=args.speed, force=args.force)
            state = gripper.wait_done(args.timeout)
            print(f"  到位: raw={state.raw_position}, width={state.width_mm:.3f}mm, "
                  f"catch_state={state.catch_state}, error={state.error_code}")
    except GripperError as exc:
        sys.exit(f"夹爪操作失败: {exc}")


if __name__ == "__main__":
    main()
