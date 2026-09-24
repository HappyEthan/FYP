#!/usr/bin/env python3
"""Record Monitor signals while writing the real ``永`` Hanzi medians at Z=25 mm."""
from __future__ import annotations

import argparse, math, os, sys

from brushbot.calligraphy.hanzi import load_medians, medians_to_strokes
from brushbot.backends.vendor.CPS import CPSClient
from brushbot.monitor.control import send_command
from brushbot.runtime import RealClock

WORK_Z_MM = 25.0
LIFT_Z_MM = 50.0
WAIT_Z_MM = 130.0
CENTER_MM = (-150.0, 500.0)
SAFE_X_MM = (-230.0, -70.0)
SAFE_Y_MM = (420.0, 580.0)
ORIENTATION_DEG = (0.0, 0.0, 0.0)
GRAPHICS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "makemeahanzi", "graphics.txt")


def build_hanzi_waypoints(character="永", *, origin_mm=CENTER_MM, size_mm=150.0,
                          char_yaw_deg=-90.0, work_z_mm=WORK_Z_MM,
                          lift_z_mm=LIFT_Z_MM):
    strokes = medians_to_strokes(load_medians(character, GRAPHICS), size=size_mm / 1000.0)
    rad = math.radians(char_yaw_deg)
    ca, sa = math.cos(rad), math.sin(rad)

    def place(point):
        x, y = point[0] * 1000.0, point[1] * 1000.0
        return (origin_mm[0] + x * ca - y * sa,
                origin_mm[1] + x * sa + y * ca)

    # 兼毫的简化提按：点/横/竖钩/撇/捺分别有不同的下压和收笔曲线。
    profiles = ((0.5, 0.8, 0.0), (0.4, 1.0, 0.3), (0.5, 1.1, 0.2),
                (0.4, 0.7, 0.0), (0.4, 1.2, 0.0))
    result = []
    for si, stroke in enumerate(strokes):
        points = [place(p) for p in stroke]
        n = len(points)
        profile = profiles[min(si, len(profiles) - 1)]
        peak = ORIENTATION_DEG
        writing = ORIENTATION_DEG
        sx, sy = points[0]
        result.extend(((sx, sy, WAIT_Z_MM, *ORIENTATION_DEG),
                       (sx, sy, WAIT_Z_MM, *peak),
                       (sx, sy, WORK_Z_MM, *peak),
                       (sx, sy, WORK_Z_MM, *writing)))
        for pi in range(n):
            frac = pi / max(1, n - 1)
            depth = profile[0] + (profile[1] - profile[0]) * min(frac * 1.5, 1.0)
            if frac > 0.85:
                depth *= max(0.0, (1.0 - frac) / 0.15)
            x, y = points[pi]
            if pi == 0:
                result.append((x, y, work_z_mm - depth, *writing))
            result.append((x, y, work_z_mm - depth, *writing))
        ex, ey = points[-1]
        result.extend(((ex, ey, WAIT_Z_MM, *writing),
                       (ex, ey, WAIT_Z_MM, *ORIENTATION_DEG)))
    for p in result:
        if not (SAFE_X_MM[0] <= p[0] <= SAFE_X_MM[1] and SAFE_Y_MM[0] <= p[1] <= SAFE_Y_MM[1]):
            raise ValueError("generated Hanzi path exceeds safe XY range")
    return result


def densify_waypoints(waypoints, *, max_step_mm=0.5, max_z_step_mm=0.25,
                      max_angle_step_deg=0.1):
    if max_step_mm <= 0 or max_z_step_mm <= 0 or max_angle_step_deg <= 0:
        raise ValueError("step limits must be positive")
    out = [tuple(float(v) for v in waypoints[0])]
    for target in waypoints[1:]:
        target = tuple(float(v) for v in target)
        start = out[-1]
        distance = math.dist(start[:3], target[:3])
        n = max(1, math.ceil(distance / max_step_mm),
                math.ceil(abs(target[2] - start[2]) / max_z_step_mm),
                *(math.ceil(abs(target[j] - start[j]) / max_angle_step_deg)
                  for j in range(3, 6)))
        out.extend(tuple(start[j] + (target[j] - start[j]) * i / n for j in range(6))
                   for i in range(1, n + 1))
    return out


def build_servo_waypoints(*, max_step_mm=0.5, max_z_step_mm=0.25):
    drawing = build_hanzi_waypoints()
    first = drawing[0]
    raw = [(*CENTER_MM, WAIT_Z_MM, *ORIENTATION_DEG),
           (first[0], first[1], WAIT_Z_MM, *ORIENTATION_DEG)] + drawing
    return densify_waypoints(raw, max_step_mm=max_step_mm,
                             max_z_step_mm=max_z_step_mm)


def validate_initial_pose(pose, *, position_tol_mm=5.0, orientation_tol_deg=2.0):
    pose = tuple(float(v) for v in pose)
    if len(pose) != 6 or not all(math.isfinite(v) for v in pose):
        raise RuntimeError("invalid initial TCP pose")
    if math.dist(pose[:2], CENTER_MM) > position_tol_mm or abs(pose[2] - WAIT_Z_MM) > position_tol_mm:
        raise RuntimeError("move TCP to (-150,500,130) mm before starting; "
                           f"current=({pose[0]:.2f},{pose[1]:.2f},{pose[2]:.2f})")
    def angle_diff(a, b):
        return abs((a - b + 180.0) % 360.0 - 180.0)
    if any(angle_diff(pose[i + 3], ORIENTATION_DEG[i]) > orientation_tol_deg for i in range(3)):
        raise RuntimeError("initial TCP orientation must be (0,0,0) deg ±2; "
                           f"current=({pose[3]:.2f},{pose[4]:.2f},{pose[5]:.2f})")
    return pose


def stream_poses(cps, poses, ucs, tcp, *, tick):
    for pose in poses:
        tick()
        _ok(cps.HRIF_PushServoP(pose, ucs, tcp), "PushServoP")


def _ok(reply, name):
    if not reply or str(reply[0]) != "0":
        raise RuntimeError(f"{name} failed: {reply[0] if reply else 'empty reply'}")
    return reply


def signal_monitor(path, action):
    if not os.path.exists(path):
        raise RuntimeError(
            f"Monitor socket not found: {path}; start `python -m brushbot.monitor`, "
            "connect the serial source, take a baseline, then retry")
    try:
        response = send_command(path, action)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Monitor socket not found: {path}; start Monitor and enable its control server") from exc
    except OSError as exc:
        raise RuntimeError(f"Monitor socket unavailable: {path}: {exc}") from exc
    if response.get("status") not in {"recording", "stopped"}:
        raise RuntimeError(f"Monitor rejected {action}: {response}")
    return response


def execute(cps, poses, *, monitor_socket, confirm=True, dt=0.02, lookahead=0.05):
    if not confirm:
        return {"status": "cancelled", "sent": 0}
    fsm = _ok(cps.HRIF_ReadCurFSM(), "read FSM")
    if len(fsm) < 2 or str(fsm[1]) != "33":
        raise RuntimeError("arm must already be in Standby (33)")
    current = validate_initial_pose(_ok(cps.HRIF_ReadActTcpPos(), "read TCP")[1:7])
    poses = densify_waypoints([current, *poses], max_step_mm=0.5,
                              max_z_step_mm=0.25)
    tcp = _ok(cps.HRIF_ReadCurTCP(), "read active TCP")[1:7]
    ucs = _ok(cps.HRIF_ReadCurUCS(), "read active UCS")[1:7]
    started = False
    try:
        signal_monitor(monitor_socket, "start_record")
        _ok(cps.HRIF_StartServo(dt, lookahead), "StartServo"); started = True
        stream_poses(cps, poses, ucs, tcp, tick=RealClock(fs=1.0 / dt).tick)
        _ok(cps.HRIF_GrpStop(), "GroupStop"); started = False
        signal_monitor(monitor_socket, "stop_record")
    except BaseException:
        if started:
            try: cps.HRIF_GrpStop()
            except Exception: pass
        raise
    return {"status": "completed", "sent": len(poses)}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ip", default="192.168.0.10")
    p.add_argument("--monitor-socket", default="/tmp/brushbot-monitor.sock")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    drawing = build_hanzi_waypoints()
    poses = build_servo_waypoints()
    print(f"永: {len(drawing)} waypoints, {len(poses)} ServoP poses, work Z={WORK_Z_MM:g} mm")
    if args.dry_run:
        return 0
    input("确认 TCP 已在 (-150,500,130) mm 且 Monitor 正在运行后按 Enter 执行：")
    try:
        print(execute(CPSClient(args.ip), poses, monitor_socket=args.monitor_socket))
    except KeyboardInterrupt:
        print("Cancelled; GroupStop is sent only after ServoP starts.", file=sys.stderr); return 130
    except Exception as exc:
        print(f"Aborted: {exc}", file=sys.stderr); return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
