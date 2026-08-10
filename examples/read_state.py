#!/usr/bin/env python
"""读取机械臂当前状态: 状态机 / 关节角 / TCP 位姿。

用法 (brushbot conda 环境):
    python examples/read_state.py                # 读一次
    python examples/read_state.py --watch        # 0.5s 轮询, Ctrl-C 退出
    python examples/read_state.py --ip 192.168.0.10

单位与示教器一致: 毫米 / 度。
"""
import argparse
import time

from brushbot.backends.vendor.CPS import CPSClient, RbtFSM


def fsm_name(code: str) -> str:
    try:
        return RbtFSM(int(code)).name
    except (ValueError, KeyError):
        return f"未知状态({code})"


def read_once(cps: CPSClient) -> None:
    fsm = cps.HRIF_ReadCurFSM()
    joints = cps.HRIF_ReadActJointPos()
    pose = cps.HRIF_ReadActTcpPos()

    if fsm[0] == "0":
        print(f"状态机   : {fsm[1]} ({fsm_name(fsm[1])})")
    else:
        print(f"状态机   : 读取失败, 错误码 {fsm[0]}")

    if joints[0] == "0":
        j = [float(v) for v in joints[1:7]]
        print("关节角(°): J1={:8.3f}  J2={:8.3f}  J3={:8.3f}\n"
              "           J4={:8.3f}  J5={:8.3f}  J6={:8.3f}".format(*j))
    else:
        print(f"关节角   : 读取失败, 错误码 {joints[0]}")

    if pose[0] == "0":
        p = [float(v) for v in pose[1:7]]
        print("TCP 位姿 : x={:8.3f}mm  y={:8.3f}mm  z={:8.3f}mm\n"
              "           Rx={:7.3f}°   Ry={:7.3f}°   Rz={:7.3f}°".format(*p))
    else:
        print(f"TCP 位姿 : 读取失败, 错误码 {pose[0]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.0.10", help="控制器 IP")
    ap.add_argument("--watch", action="store_true", help="0.5s 轮询直到 Ctrl-C")
    args = ap.parse_args()

    cps = CPSClient(args.ip)
    if args.watch:
        try:
            while True:
                print("\033[2J\033[H", end="")  # 清屏, 顶部开始
                print(time.strftime("%H:%M:%S"))
                read_once(cps)
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    else:
        read_once(cps)


if __name__ == "__main__":
    main()
