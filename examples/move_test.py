#!/usr/bin/env python
"""首次动臂测试: 从当前位置做一段小位移直线运动 (MoveL), 可原路返回。

用法 (brushbot conda 环境):
    python examples/move_test.py                 # 默认: 向上 (+z) 10mm
    python examples/move_test.py --dz -5         # 向下 5mm
    python examples/move_test.py --dx 10 --dy 5  # 平面位移
    python examples/move_test.py --speed 10      # 更慢 (mm/s)

安全设计:
- 位移限幅 |d| <= MAX_DISP_MM, 速度限幅 <= MAX_SPEED
- 姿态保持不变, 只平移
- 动前打印目标并要求输入 yes 确认; 急停按钮放手边
- 前提: 机械臂已在示教器上使能 (状态机应为 33 Standby)
"""
import argparse
import math
import sys
import time

from brushbot.backends.vendor.CPS import CPSClient, RbtFSM

MAX_DISP_MM = 30.0     # 单次总位移上限
MAX_SPEED = 50.0       # mm/s
STALL_TIMEOUT_S = 10.0  # 距目标距离连续这么久无进展才判失败
TCP_NAME, UCS_NAME = "TCP", "Base"   # 官方示例默认坐标系名


def die(msg: str) -> None:
    print(f"[中止] {msg}")
    sys.exit(1)


def read_pose_joints(cps: CPSClient):
    pose = cps.HRIF_ReadActTcpPos()
    joints = cps.HRIF_ReadActJointPos()
    if pose[0] != "0":
        die(f"读 TCP 位姿失败, 错误码 {pose[0]}")
    if joints[0] != "0":
        die(f"读关节角失败, 错误码 {joints[0]}")
    return [float(v) for v in pose[1:7]], [float(v) for v in joints[1:7]]


def read_override(cps: CPSClient) -> float:
    # vendor CPS.py 无此方法, 裸发协议命令 (手册 §3.5.16, 真机验证 2026-08-10)
    ret = cps.sendAndRecv("ReadOverride,0,;")
    return float(ret[1]) if ret[0] == "0" else float("nan")


def wait_until_reached(cps: CPSClient, target) -> None:
    # 完成判定用位置收敛而非 IsMotionDone: 真机实测 WayPoint 完成标志在
    # 发起运动的同一连接内长期不置位 (2026-08-10), 位置读数才是真值。
    # 超时用停滞检测而非固定时长: 速度倍率可能压得很低 (真机默认见过 1%),
    # 只要还在接近目标就继续等。
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


def move_l(cps: CPSClient, target, joints_hint, speed: float) -> None:
    # RawACSpoints 传当前关节角作为参考解; radius=0 不过渡; 不用探寻 IO
    ret = cps.HRIF_MoveL(target, joints_hint, TCP_NAME, UCS_NAME,
                         speed, speed * 2.0, 0, 0, 0, 0, "1")
    if ret[0] != "0":
        die(f"MoveL 被拒绝, 错误码 {ret[0]} "
            f"(常见原因: 未使能 / 目标不可达 / 状态机不在 Standby)")
    wait_until_reached(cps, target)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.0.10", help="控制器 IP")
    ap.add_argument("--dx", type=float, default=0.0, help="x 位移 (mm)")
    ap.add_argument("--dy", type=float, default=0.0, help="y 位移 (mm)")
    ap.add_argument("--dz", type=float, default=10.0, help="z 位移 (mm), 正=向上")
    ap.add_argument("--speed", type=float, default=20.0, help="速度 (mm/s)")
    ap.add_argument("--no-return", action="store_true", help="动完不返回起点")
    args = ap.parse_args()

    disp = math.sqrt(args.dx**2 + args.dy**2 + args.dz**2)
    if disp < 1e-6:
        die("位移为零, 没什么可动的")
    if disp > MAX_DISP_MM:
        die(f"总位移 {disp:.1f}mm 超过限幅 {MAX_DISP_MM}mm")
    speed = min(args.speed, MAX_SPEED)

    cps = CPSClient(args.ip)

    fsm = cps.HRIF_ReadCurFSM()
    if fsm[0] == "0":
        code = int(fsm[1])
        name = RbtFSM(code).name if code in set(RbtFSM) else str(code)
        print(f"状态机: {code} ({name})")
        if code != RbtFSM.enCPSState_Standy:
            die("机械臂不在 Standby(33) 就绪态, 先在示教器上使能/复位")

    start_pose, start_joints = read_pose_joints(cps)
    target = list(start_pose)
    target[0] += args.dx
    target[1] += args.dy
    target[2] += args.dz

    override = read_override(cps)
    eff_speed = speed * override if override == override else speed  # NaN 保护
    print("当前位姿: " + ", ".join(f"{v:.3f}" for v in start_pose))
    print("目标位姿: " + ", ".join(f"{v:.3f}" for v in target))
    print(f"位移 {disp:.1f}mm, 指令速度 {speed:.0f}mm/s, "
          f"速度倍率 {override:.0%} -> 实际约 {eff_speed:.1f}mm/s, "
          f"预计 {disp / max(eff_speed, 1e-6):.0f}s")
    if override == override and override < 0.05:
        print("[提示] 倍率很低, 运动会非常慢; 可在示教器上调高倍率")
    if input("确认运动? 输入 yes 执行: ").strip().lower() != "yes":
        die("已取消")

    move_l(cps, target, start_joints, speed)
    end_pose, _ = read_pose_joints(cps)
    print("到位位姿: " + ", ".join(f"{v:.3f}" for v in end_pose))
    err = [e - t for e, t in zip(end_pose[:3], target[:3])]
    print("到位误差: dx={:+.3f}  dy={:+.3f}  dz={:+.3f} (mm)".format(*err))

    if not args.no_return:
        if input("返回起点? 输入 yes 执行: ").strip().lower() == "yes":
            move_l(cps, start_pose, start_joints, speed)
            back_pose, _ = read_pose_joints(cps)
            print("返回后位姿: " + ", ".join(f"{v:.3f}" for v in back_pose))


if __name__ == "__main__":
    main()
