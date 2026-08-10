#!/usr/bin/env python
"""伺服周期扫描实验: StartServo + 定频 PushServoP 推正弦轨迹, 量化跟踪性能。

用法 (brushbot conda 环境, 一次跑一个配置, 换参数多跑几轮对比):
    python examples/servo_scan.py                          # dt=20ms lookahead=0.1
    python examples/servo_scan.py --dt 0.033 --lookahead 0.2
    python examples/servo_scan.py --amp 3 --freq 1.0 --duration 8

动作: 保持 XY 和姿态不变, z 在当前高度 ±amp(mm) 正弦振荡 duration 秒,
结束后 1s 线性引导回起始高度。每拍同时读实际位姿, 结果存 CSV 并打印:
- 跟踪滞后 (互相关估计, ms)
- 滞后补偿后的 RMS 跟踪误差 (mm)
- overrun 计数与每拍耗时统计

安全: 动前确认; 请先把机械臂移到空中, 上下各留 >= amp+20mm 净空;
急停放手边。速度倍率会缩放运动指令, 实验前先确认倍率 (脚本会打印)。
"""
import argparse
import csv
import math
import statistics
import sys
import time

from brushbot.backends.vendor.CPS import CPSClient, RbtFSM
from brushbot.runtime import RealClock

MAX_AMP_MM = 10.0
MAX_FREQ_HZ = 2.0
RAMP_BACK_S = 1.0


def die(msg: str) -> None:
    print(f"[中止] {msg}")
    sys.exit(1)


def read_pose(cps: CPSClient):
    ret = cps.HRIF_ReadActTcpPos()
    if ret[0] != "0":
        die(f"读位姿失败, 错误码 {ret[0]}")
    return [float(v) for v in ret[1:7]]


def estimate_lag_ticks(cmd, act) -> int:
    """互相关找滞后: act 相对 cmd 平移多少拍最相似。O(n*maxlag) 够用。"""
    n = len(cmd)
    mc = sum(cmd) / n
    ma = sum(act) / n
    c = [v - mc for v in cmd]
    a = [v - ma for v in act]
    max_lag = min(n // 2, 100)
    best_lag, best_score = 0, float("-inf")
    for lag in range(max_lag):
        score = sum(c[i] * a[i + lag] for i in range(n - lag))
        if score > best_score:
            best_lag, best_score = lag, score
    return best_lag


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.0.10")
    ap.add_argument("--dt", type=float, default=0.02, help="伺服周期 (s)")
    ap.add_argument("--lookahead", type=float, default=0.1, help="前瞻时间 (s)")
    ap.add_argument("--amp", type=float, default=5.0, help="z 振幅 (mm)")
    ap.add_argument("--freq", type=float, default=0.5, help="正弦频率 (Hz)")
    ap.add_argument("--duration", type=float, default=10.0, help="振荡时长 (s)")
    ap.add_argument("--out", default=None, help="CSV 输出路径")
    args = ap.parse_args()

    if not (0 < args.amp <= MAX_AMP_MM):
        die(f"振幅须在 (0, {MAX_AMP_MM}] mm")
    if not (0 < args.freq <= MAX_FREQ_HZ):
        die(f"频率须在 (0, {MAX_FREQ_HZ}] Hz")
    vmax = args.amp * 2 * math.pi * args.freq
    out = args.out or f"servo_scan_dt{args.dt * 1000:.0f}ms_la{args.lookahead * 1000:.0f}ms.csv"

    cps = CPSClient(args.ip)

    fsm = cps.HRIF_ReadCurFSM()
    if fsm[0] != "0" or int(fsm[1]) != RbtFSM.enCPSState_Standy:
        die("机械臂不在 Standby(33) 就绪态, 先在示教器上使能/复位")
    ovr = cps.sendAndRecv("ReadOverride,0,;")
    override = float(ovr[1]) if ovr[0] == "0" else float("nan")

    start = read_pose(cps)
    print(f"起始位姿: " + ", ".join(f"{v:.3f}" for v in start))
    print(f"配置: 周期 {args.dt * 1000:.0f}ms, 前瞻 {args.lookahead * 1000:.0f}ms, "
          f"z 振幅 ±{args.amp}mm @ {args.freq}Hz, 时长 {args.duration}s")
    print(f"峰值速度 {vmax:.1f}mm/s, 速度倍率 {override:.0%}")
    if override == override and override < 0.2:
        print("[提示] 倍率较低, 若跟踪严重滞后请先调高倍率再对比")
    if input("确认开始伺服振荡? 输入 yes 执行: ").strip().lower() != "yes":
        die("已取消")

    ret = cps.HRIF_StartServo(args.dt, args.lookahead)
    if ret[0] != "0":
        die(f"StartServo 被拒绝, 错误码 {ret[0]}")

    n_sine = int(args.duration / args.dt)
    n_ramp = int(RAMP_BACK_S / args.dt)
    ucs = [0.0] * 6
    tcp = [0.0] * 6
    clk = RealClock(fs=1.0 / args.dt)
    rows = []          # t, z_cmd, z_act, overrun, work_ms
    total_overrun = 0

    for i in range(n_sine + n_ramp):
        t, ov = clk.tick()
        total_overrun += ov
        w0 = time.perf_counter()
        if i < n_sine:
            dz = args.amp * math.sin(2 * math.pi * args.freq * i * args.dt)
        else:  # 从正弦末值线性回到 0
            z_end = args.amp * math.sin(2 * math.pi * args.freq * args.duration)
            frac = (i - n_sine + 1) / n_ramp
            dz = z_end * (1.0 - frac)
        pose = list(start)
        pose[2] = start[2] + dz
        ret = cps.HRIF_PushServoP(pose, ucs, tcp)
        if ret[0] != "0":
            print(f"\n[中止] 第 {i} 拍 PushServoP 错误码 {ret[0]}")
            break
        act = cps.HRIF_ReadActTcpPos()
        z_act = float(act[3]) if act[0] == "0" else float("nan")
        rows.append((t, pose[2], z_act, ov, (time.perf_counter() - w0) * 1000))

    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "z_cmd_mm", "z_act_mm", "overrun", "work_ms"])
        w.writerows(rows)

    n = len(rows)
    if n < 20:
        die(f"有效数据只有 {n} 拍, 不足以分析 (CSV 已存 {out})")
    cmd = [r[1] for r in rows[:n_sine]]
    act = [r[2] for r in rows[:n_sine] if r[2] == r[2]]
    lag = estimate_lag_ticks(cmd[:len(act)], act)
    rms = math.sqrt(statistics.fmean(
        (cmd[i] - act[i + lag]) ** 2 for i in range(len(act) - lag)))
    works = sorted(r[4] for r in rows)
    p99 = works[min(n - 1, int(0.99 * n))]
    print(f"\n== 结果 (共 {n} 拍, CSV: {out}) ==")
    print(f"跟踪滞后 : {lag} 拍 = {lag * args.dt * 1000:.0f}ms")
    print(f"RMS 误差 : {rms:.3f}mm (滞后补偿后)")
    print(f"overrun  : {total_overrun} 次")
    print(f"每拍耗时 : 中位 {statistics.median(works):.2f}ms, p99 {p99:.2f}ms "
          f"(预算 {args.dt * 1000:.0f}ms)")
    end = read_pose(cps)
    print(f"结束位姿 z={end[2]:.3f}mm (起始 {start[2]:.3f}mm)")


if __name__ == "__main__":
    main()
