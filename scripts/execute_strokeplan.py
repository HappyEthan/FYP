#!/usr/bin/env python3
"""Human-confirmed CPS ServoP executor for a StrokePlan NPZ."""

from __future__ import annotations

import argparse
import math
import sys

from brushbot import config
from brushbot.backends.vendor.CPS import CPSClient
from brushbot.strokeplan import StrokePlan


def build_servo_poses(plan, z_surface_mm=40.0, wait_z_mm=130.0, lift_mm=10.0):
    if not plan.strokes:
        raise ValueError("StrokePlan has no strokes")
    orientation = tuple(plan.meta.get("orientation_rpy_rad", config.FIXED_ORI))
    if len(orientation) != 3 or not all(math.isfinite(float(v)) for v in orientation):
        raise ValueError("invalid orientation_rpy_rad")
    poses = []
    for stroke in plan.strokes:
        if len(stroke.s) < 2 or len(stroke.xy) != len(stroke.s) or len(stroke.z_ff) != len(stroke.s):
            raise ValueError("stroke arrays have inconsistent lengths")
        poses.extend((float(x), float(y), (z_surface_mm - float(depth) * 1000.0) / 1000.0, *orientation)
                     for (x, y), depth in zip(stroke.xy, stroke.z_ff))
        poses.append((float(stroke.xy[-1, 0]), float(stroke.xy[-1, 1]),
                      float(wait_z_mm) / 1000.0, *orientation))
    return poses


def _ok(reply, op):
    if not reply or str(reply[0]) != "0":
        raise RuntimeError(f"{op} failed: {reply[0] if reply else 'empty reply'}")
    return reply


def execute_plan(cps, plan, *, confirm, tick, z_surface_mm=40.0,
                 wait_z_mm=130.0, lift_mm=10.0, dt=0.02, lookahead=0.1):
    poses = build_servo_poses(plan, z_surface_mm, wait_z_mm, lift_mm)
    if not confirm():
        return {"status": "cancelled", "sent": 0}
    fsm = _ok(cps.HRIF_ReadCurFSM(), "read FSM")
    if len(fsm) < 2 or str(fsm[1]) != "33":
        raise RuntimeError("arm must already be in Standby (33)")
    tcp = _ok(cps.HRIF_ReadCurTCP(), "read TCP")[1:7]
    ucs = _ok(cps.HRIF_ReadCurUCS(), "read UCS")[1:7]
    started = False
    try:
        _ok(cps.HRIF_StartServo(dt, lookahead), "StartServo")
        started = True
        for pose in poses:
            tick()
            _ok(cps.HRIF_PushServoP(pose, ucs, tcp), "PushServoP")
        _ok(cps.HRIF_GrpStop(), "GroupStop")
        started = False
    except BaseException:
        if started:
            try:
                cps.HRIF_GrpStop()
            except Exception:
                pass
        raise
    return {"status": "completed", "sent": len(poses)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("--ip", default="192.168.0.10")
    parser.add_argument("--z-surface-mm", type=float, default=40.0)
    parser.add_argument("--wait-z-mm", type=float, default=130.0)
    parser.add_argument("--lift-mm", type=float, default=10.0)
    parser.add_argument("--servo-dt", type=float, default=0.02)
    parser.add_argument("--lookahead", type=float, default=0.1)
    args = parser.parse_args(argv)
    plan = StrokePlan.load(args.plan)
    poses = build_servo_poses(plan, args.z_surface_mm, args.wait_z_mm, args.lift_mm)
    print(f"Loaded {args.plan}: {len(poses)} ServoP poses")
    print("No enable/reset/TCP/UCS/gripper command will be sent.")
    input("Press Enter to start (Ctrl+C cancels): ")
    cps = CPSClient(args.ip)
    try:
        result = execute_plan(cps, plan, confirm=lambda: True,
                              tick=lambda: None, z_surface_mm=args.z_surface_mm,
                              wait_z_mm=args.wait_z_mm, lift_mm=args.lift_mm,
                              dt=args.servo_dt, lookahead=args.lookahead)
    except KeyboardInterrupt:
        print("Cancelled by Ctrl+C; GroupStop is sent only if ServoP started.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Aborted: {exc}", file=sys.stderr)
        return 2
    print(result["status"])
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
