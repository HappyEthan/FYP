#!/usr/bin/env python
"""DHAG-95 夹爪通信最小验证: 只读状态 + 可选一次温和绝对移动。

链路: 笔记本 --TCP(10003)--> Elfin 控制柜(HYGripper 插件)
      --ModbusRTU(115200/8N1)--> DH AG-160-95 (GID=1)

单位 (见 AG-160-95 手册 表2.2):
    位置 0-1000 千分比 = 0..95mm  (每计数 95um)
    力值 20-100 % (AG95 最大 160N -> 30% ≈ 48N)

用法 (brushbot conda):
    python examples/gripper_probe.py                # 每秒读状态, Ctrl-C 退出
    python examples/gripper_probe.py --once         # 只读一次
    python examples/gripper_probe.py --move 30      # 绝对移到 ~30mm (需 y 确认)
    python examples/gripper_probe.py --move 30 --yes
"""
import argparse
import sys
import time

from brushbot.backends.vendor.CPS import CPSClient

GID = 1                       # 真机探测: 插件注册的夹爪有效编号为 1, GID=0 报 60000 无效参数
MM_PER_COUNT = 0.095          # 95um/计数
POS_MIN_MM, POS_MAX_MM = 0.0, 95.0
SPEED_PCT, FORCE_PCT = 30, 30
POLL_S = 1.0
TIMEOUT_S = 20.0


def hr(cps, cmd):
    """发 HRApp 命令, 打印完整原始回复, 非 0 错误码即中止."""
    ret = cps.HRApp("hr_gri_plugins", cmd)
    print(f"  HRApp({cmd!r}) -> {ret!r}")
    if ret[0] != "0":
        print(f"[中止] 命令返回错误码 {ret[0]}: {ret!r}")
        sys.exit(1)
    return ret


def read_state(cps):
    moving = hr(cps, f"IsMoving,{GID}")
    catch = hr(cps, f"GetCatchState,{GID}")
    pos = hr(cps, f"GetCatchPosition,{GID}")
    v = lambda r: r[2] if len(r) >= 3 else "?"
    raw = v(pos)
    mm = f"{int(raw) * MM_PER_COUNT:.1f}mm" if raw.isdigit() else raw
    print(f"  -> 状态: IsMoving={v(moving)}  CatchState={v(catch)}"
          f"  Position={raw}(raw)≈{mm}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.0.10")
    ap.add_argument("--move", type=float, default=None, help="绝对移动到 mm (0-95)")
    ap.add_argument("--yes", action="store_true", help="跳过 --move 确认")
    ap.add_argument("--once", action="store_true", help="只读一次并退出")
    args = ap.parse_args()

    cps = CPSClient(args.ip)

    if args.move is not None:
        if not POS_MIN_MM <= args.move <= POS_MAX_MM:
            sys.exit(f"[中止] --move 超出量程 {POS_MIN_MM}-{POS_MAX_MM}mm")
        raw = int(round(args.move / MM_PER_COUNT))
        if not args.yes and input(
                f"夹爪绝对移动到约 {args.move}mm (raw={raw}, "
                f"speed={SPEED_PCT}, force={FORCE_PCT})? [y/N] "
        ).strip().lower() != "y":
            sys.exit("已取消")
        hr(cps, f"GripperAbsCatchMove,{GID},{raw},{SPEED_PCT},{FORCE_PCT}")
        print("移动已发起, 轮询 IsMoving 直到停止...")
        t0 = time.time()
        while True:
            r = hr(cps, f"IsMoving,{GID}")
            if len(r) >= 3 and r[2] == "0":
                break
            if time.time() - t0 > TIMEOUT_S:
                print("[警告] 超时未停, 发 GripperStop")
                hr(cps, f"GripperStop,{GID}")
                break
            time.sleep(POLL_S)
        read_state(cps)
        return

    if args.once:
        read_state(cps)
        return
    try:
        while True:
            read_state(cps)
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
