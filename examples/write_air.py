#!/usr/bin/env python
"""开环纸上写字 (实测 z 带版): 真实字形 -> 显式 z 定参 -> 自动到位 -> 流式伺服。

z 参数 (单位 mm, TCP 在 Base 系下的 z, 真机实测):
    --z-max  刚触纸 (只留痕)
    --z-work 正常笔画粗度 (笔画下探到的高度)
    --z-min  会损坏 (硬下限)
笔画下探 z_work, 笔画间抬到 z_max + --hover-clearance。全程 z 被安全钳在
[z_min, hover]。先用 MoveL 自动移到 (x0, y0, hover), 再开始写字。

多字横排 (左→右): 不传 --size/--gap 时按字数自动选档
    (1-2字 size120/gap30, 3字 size100/gap10, 4-5字 size60/gap15);
    不传 --x0 时整组字自动居中在 x 限制 [--x-min, --x-max] 内。
x 限制默认 [-200, 160], 布局越出会中止并提示合法 x0 区间。

用法 (brushbot conda 环境):
    python examples/write_air.py --z-work 287 --z-min 275 --z-max 296 \
        --y0 547 --char 永十
    python examples/write_air.py --z-work 287 --z-min 275 --z-max 296 \
        --x0 -90 --char 永十 --dry-run

安全: 动前确认; 急停放手边; z_min 以下是损坏区, 流式循环里钳位兜底。
"""
import argparse
import math
import os
import sys
import time

import brushbot
from brushbot import config
from brushbot.backends.huayan import HuayanBackend
from brushbot.backends.vendor.CPS import CPSClient, RbtFSM
from brushbot.calligraphy.hanzi import (
    load_medians, medians_to_strokes, strokes_to_waypoints)
from brushbot.controller import OpenLoopController
from brushbot.runtime import RealClock
from brushbot.types import Command, State

# 与 write_hanzi.DEFAULT_GRAPHICS 同一路径; 不 import 它以免连带加载 PyBullet
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(brushbot.__file__))))
DEFAULT_GRAPHICS = os.path.join(_REPO, "data", "makemeahanzi", "graphics.txt")

MAX_SIZE_MM = 120.0   # 大字框注意: 以当前 XY 为中心 ±size/2 都要在可达空间内
MAX_SPEED_MMS = 60.0
# 固定档位 (size, gap) mm, 从大到小; 未显式给 size/gap 时按字数自动选最大可装档
PRESETS = [(120.0, 20.0), (100.0, 10.0), (60.0, 15.0)]
STALL_TIMEOUT_S = 10.0
TCP_NAME, UCS_NAME = "TCP", "Base"   # 官方示例默认坐标系名


def die(msg):
    print(f"[中止] {msg}")
    sys.exit(1)


def confirm(prompt):
    """读确认输入。优先直接读 /dev/tty —— conda run 会把 stdin 吞成 EOF。"""
    try:
        with open("/dev/tty", "r") as tty:
            print(prompt, end="", flush=True)
            return tty.readline().strip().lower() == "yes"
    except OSError:
        return input(prompt).strip().lower() == "yes"


def build_waypoints(chars, size_m, origin_xy, z_up, z_down, gap_m, yaw_deg):
    """多字横排 (左→右) 路点。x0 是第一个字的中心; 中心距 = size + gap。"""
    x0, y0 = origin_xy
    wp = [(x0, y0, z_up)]
    n_strokes = 0
    for k, ch in enumerate(chars):
        cx = x0 + k * (size_m + gap_m)
        strokes = medians_to_strokes(load_medians(ch, DEFAULT_GRAPHICS),
                                     size=size_m)
        n_strokes += len(strokes)
        cwp = strokes_to_waypoints(strokes, (cx, y0), z_down, z_up,
                                   char_yaw_deg=yaw_deg)
        wp.append((cx, y0, z_up))
        wp.extend(cwp)
    return wp, n_strokes


def pick_preset(n_chars, x_min, x_max):
    """按字数在 PRESETS 里选最大可装档, 返回 (size, gap) mm。"""
    limit = x_max - x_min
    for size, gap in PRESETS:
        max_n = int((limit + gap) // (size + gap))
        if n_chars <= max_n:
            return size, gap
    die(f"{n_chars} 个字超出容量 (最大 {int((limit + PRESETS[-1][1]) // (PRESETS[-1][0] + PRESETS[-1][1]))} 字)")


def auto_x0(n_chars, size_mm, gap_mm, x_min, x_max):
    """把整组字在 [x_min, x_max] 里居中时的首字中心 x (mm)。"""
    return (x_min + x_max - (n_chars - 1) * (size_mm + gap_mm)) / 2.0


def layout_x_range(x0_mm, size_mm, gap_mm, n_chars):
    """多字横排的 x 范围 [lo, hi] (mm); x0 是首字中心。"""
    lo = x0_mm - size_mm / 2.0
    hi = x0_mm + (n_chars - 1) * (size_mm + gap_mm) + size_mm / 2.0
    return lo, hi


def check_x(x0_mm, size_mm, gap_mm, n_chars, x_min, x_max):
    """校验布局 x 范围在 [x_min, x_max] 内, 越界给出合法 x0 区间。"""
    lo, hi = layout_x_range(x0_mm, size_mm, gap_mm, n_chars)
    if lo < x_min or hi > x_max:
        ok_lo = x_min + size_mm / 2.0
        ok_hi = x_max - (n_chars - 1) * (size_mm + gap_mm) - size_mm / 2.0
        die(f"布局 x 范围 [{lo:.0f}, {hi:.0f}] 越出限制 [{x_min:.0f}, {x_max:.0f}]。"
            f"x0 (首字中心) 须在 [{ok_lo:.0f}, {ok_hi:.0f}] mm 内")
    return lo, hi


def clamp_z(pose, z_min_m, z_up_m):
    """把指令 z 钳到 [z_min, hover]。z_min 以下是损坏区, 防御兜底。"""
    x, y, z, roll, pitch, yaw = pose
    zz = min(max(z, z_min_m), z_up_m)
    if zz != z:
        print(f"[钳位] z {z * 1000:.1f}mm -> {zz * 1000:.1f}mm")
    return (x, y, zz, roll, pitch, yaw)


def read_pose_joints(cps):
    pose = cps.HRIF_ReadActTcpPos()
    joints = cps.HRIF_ReadActJointPos()
    if pose[0] != "0":
        die(f"读 TCP 位姿失败, 错误码 {pose[0]}")
    if joints[0] != "0":
        die(f"读关节角失败, 错误码 {joints[0]}")
    return [float(v) for v in pose[1:7]], [float(v) for v in joints[1:7]]


def wait_until_reached(cps, target):
    # 完成判定用位置收敛而非 IsMotionDone: 真机实测 WayPoint 完成标志不置位。
    # 超时用停滞检测而非固定时长 (倍率可能很低), 只要还在接近目标就继续等。
    stable = 0
    best = float("inf")
    last_progress = time.monotonic()
    while time.monotonic() - last_progress < STALL_TIMEOUT_S:
        pose = cps.HRIF_ReadActTcpPos()
        if pose[0] == "0":
            p = [float(v) for v in pose[1:7]]
            dist = math.dist(p[:3], target[:3])
            if dist < 0.5:
                stable += 1
                if stable >= 3:
                    print()
                    return
            else:
                stable = 0
                print(f"  ... 距目标 {dist:6.2f} mm ", end="\r", flush=True)
            if dist < best - 0.2:
                best = dist
                last_progress = time.monotonic()
        time.sleep(0.2)
    print()
    die(f"距目标 {best:.2f}mm 处停滞超过 {STALL_TIMEOUT_S:.0f}s, "
        f"请检查示教器 (暂停/报错/倍率为 0)")


def move_l(cps, target_mm, joints_hint, speed_mms):
    # RawACSpoints 传当前关节角作参考解; radius=0 不过渡; 不用探寻 IO
    ret = cps.HRIF_MoveL(target_mm, joints_hint, TCP_NAME, UCS_NAME,
                         speed_mms, speed_mms * 2.0, 0, 0, 0, 0, "1")
    if ret[0] != "0":
        die(f"MoveL 被拒绝, 错误码 {ret[0]} "
            f"(常见原因: 未使能 / 目标不可达 / 状态机不在 Standby)")
    wait_until_reached(cps, target_mm)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.0.10")
    ap.add_argument("--char", default="永", help="要写的汉字 (可多字, 横排左→右)")
    ap.add_argument("--size", type=float, default=None,
                    help="字框边长 (mm); 缺省按字数自动选档 (120/100/60)")
    ap.add_argument("--gap", type=float, default=None,
                    help="字框间留白 (mm); 缺省按字数自动选档 (30/20/15)")
    ap.add_argument("--speed", type=float, default=18.0, help="笔速 (mm/s)")
    ap.add_argument("--x0", type=float, default=None,
                    help="首字中心 x (mm, Base 系); 缺省用当前位置")
    ap.add_argument("--y0", type=float, default=None,
                    help="首字中心 y (mm, Base 系); 缺省用当前位置")
    ap.add_argument("--x-min", type=float, default=-200.0,
                    help="x 下限 (mm), 轨迹不得越出")
    ap.add_argument("--x-max", type=float, default=160.0,
                    help="x 上限 (mm), 轨迹不得越出")
    ap.add_argument("--z-work", type=float, required=True,
                    help="正常笔画粗度 z (mm)")
    ap.add_argument("--z-min", type=float, required=True,
                    help="会损坏的下限 z (mm)")
    ap.add_argument("--z-max", type=float, required=True,
                    help="刚触纸的上限 z (mm)")
    ap.add_argument("--hover-clearance", type=float, default=10.0,
                    help="抬笔比 z_max 高多少 (mm)")
    ap.add_argument("--yaw", type=float, default=0.0,
                    help="字在平面上的朝向 (度), 0 = 字的上方朝 +y")
    ap.add_argument("--dry-run", action="store_true",
                    help="只计算并打印轨迹, 不连机械臂")
    args = ap.parse_args()

    if args.size is None or args.gap is None:
        if args.size is not None or args.gap is not None:
            die("size 和 gap 要一起给, 或都缺省走自动选档")
        args.size, args.gap = pick_preset(len(args.char), args.x_min, args.x_max)
        print(f"[自动选档] {len(args.char)} 字 -> size={args.size:.0f}mm, "
              f"gap={args.gap:.0f}mm")
    if not (0 < args.size <= MAX_SIZE_MM):
        die(f"size 须在 (0, {MAX_SIZE_MM}] mm")
    if not (args.gap >= 0):
        die("gap 不能为负")
    if not (args.x_min < args.x_max):
        die("x 限制须满足 x_min < x_max")
    speed = min(args.speed, MAX_SPEED_MMS)
    if not (args.z_min < args.z_work < args.z_max):
        die(f"z 参数须满足 z_min < z_work < z_max: "
            f"{args.z_min} < {args.z_work} < {args.z_max} 不成立")
    if not (args.z_min > 0):
        die("z 须为正数 (Base 系下正值向上)")

    hover = args.z_max + args.hover_clearance
    z_min_m, z_work_m, z_max_m = args.z_min / 1000.0, args.z_work / 1000.0, args.z_max / 1000.0
    hover_m = hover / 1000.0

    if args.dry_run:
        x0 = (args.x0 if args.x0 is not None
              else auto_x0(len(args.char), args.size, args.gap,
                           args.x_min, args.x_max))
        y0 = args.y0 if args.y0 is not None else 0.0
        check_x(x0, args.size, args.gap, len(args.char), args.x_min, args.x_max)
        wp, n_strokes = build_waypoints(args.char, args.size / 1000.0,
                                        (x0 / 1000.0, y0 / 1000.0),
                                        hover_m, z_work_m,
                                        args.gap / 1000.0, args.yaw)
        ctrl = OpenLoopController(wp, speed / 1000.0, (0.0, 0.0, 0.0))
        span = args.size * len(args.char) + args.gap * (len(args.char) - 1)
        print(f"'{args.char}': {len(args.char)} 字 {n_strokes} 笔, "
              f"{len(wp)} 路点, 横排总宽 {span:.0f}mm")
        print(f"  总弧长 {ctrl.total * 1000:.0f}mm, "
              f"预计 {ctrl.total / (speed / 1000.0):.0f}s @ {speed:.0f}mm/s")
        print(f"z: 工作 {args.z_work} / 抬笔 {hover:.0f} (z_max+{args.hover_clearance:.0f}) "
              f"/ 下限 {args.z_min} mm")
        return

    cps = CPSClient(args.ip)
    fsm = cps.HRIF_ReadCurFSM()
    if fsm[0] != "0" or int(fsm[1]) != RbtFSM.enCPSState_Standy:
        die("机械臂不在 Standby(33) 就绪态, 先在示教器上使能/复位")

    backend = HuayanBackend(cps, servo_dt=config.HUAYAN_SERVO_DT,
                            lookahead=config.HUAYAN_LOOKAHEAD)
    start_pose, start_joints = read_pose_joints(cps)   # HRIF 格式: mm/度
    if not (args.x_min <= start_pose[0] <= args.x_max):
        die(f"当前位姿 x={start_pose[0]:.1f}mm 越出 x 限制 "
            f"[{args.x_min:.0f}, {args.x_max:.0f}], 先示教器移进范围")
    x0 = (args.x0 if args.x0 is not None
          else auto_x0(len(args.char), args.size, args.gap,
                       args.x_min, args.x_max))
    y0 = args.y0 if args.y0 is not None else start_pose[1]
    x_lo, x_hi = check_x(x0, args.size, args.gap, len(args.char),
                         args.x_min, args.x_max)
    ori = [math.radians(v) for v in start_pose[3:6]]   # 控制器要弧度
    start_mm = [x0, y0, hover] + start_pose[3:6]        # MoveL 要完整 6 元素 (mm/度)

    wp, n_strokes = build_waypoints(args.char, args.size / 1000.0,
                                    (x0 / 1000.0, y0 / 1000.0),
                                    hover_m, z_work_m,
                                    args.gap / 1000.0, args.yaw)
    ctrl = OpenLoopController(wp, speed / 1000.0, ori)
    dur = ctrl.total / (speed / 1000.0)
    span = args.size * len(args.char) + args.gap * (len(args.char) - 1)
    print(f"字: '{args.char}' ({len(args.char)} 字, {n_strokes} 笔), "
          f"字框 {args.size:.0f}mm, 字距 {args.gap:.0f}mm, 横排总宽 {span:.0f}mm")
    print(f"  x 范围 [{x_lo:.1f}, {x_hi:.1f}]  (限制 [{args.x_min:.0f}, "
          f"{args.x_max:.0f}], 首字中心 x={x0:.1f})")
    print(f"当前位姿: x={start_pose[0]:.1f} y={start_pose[1]:.1f} "
          f"z={start_pose[2]:.1f}mm")
    print(f"起始 (自动 MoveL): x={x0:.1f} y={y0:.1f} z={hover:.1f}mm (抬笔)")
    print(f"z 带: 写 {args.z_work} / 触纸 {args.z_max} / 损坏下限 {args.z_min} "
          f"mm, 安全钳 [{args.z_min}, {hover:.0f}]")
    print(f"总弧长 {ctrl.total * 1000:.0f}mm, 速度 {speed:.0f}mm/s, "
          f"预计 {dur:.0f}s, 伺服 {config.HUAYAN_SERVO_DT * 1000:.0f}ms/"
          f"前瞻 {config.HUAYAN_LOOKAHEAD * 1000:.0f}ms")
    if not confirm("确认到位并空中写字? 输入 yes 执行: "):
        die("已取消")

    print(f"MoveL 到起始 ({x0:.1f}, {y0:.1f}, {hover:.1f})mm ...")
    move_l(cps, start_mm, start_joints, speed)

    backend.start_servo()
    clk = RealClock(fs=1.0 / config.HUAYAN_SERVO_DT)
    overruns = 0
    n_ticks = 0
    t_wall = time.monotonic()
    n_clamp = 0
    while not ctrl.done():
        t, ov = clk.tick()
        overruns += ov
        n_ticks += 1
        cmd = ctrl.step(State(tcp_pose=(0.0,) * 6, g_meas=0.0, t=t))
        pose = clamp_z(cmd.tcp_pose, z_min_m, hover_m)
        backend.write(Command(tcp_pose=pose))
        if n_ticks % 100 == 0:
            print(f"  ... {min(100.0, 100.0 * speed / 1000.0 * t / ctrl.total):5.1f}%",
                  end="\r", flush=True)
    elapsed = time.monotonic() - t_wall
    print()

    end = backend.read()
    print(f"完成: {n_ticks} 拍 / {elapsed:.1f}s, overrun {overruns} 次")
    print(f"结束位姿 z={end.tcp_pose[2] * 1000:.1f}mm (应回抬笔 "
          f"{hover:.1f}mm 附近)")


if __name__ == "__main__":
    main()
