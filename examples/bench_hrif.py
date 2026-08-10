#!/usr/bin/env python
"""HRIF 协议往返延迟 benchmark: 为选定伺服周期提供时间预算数据。

用法 (brushbot conda 环境):
    python examples/bench_hrif.py                # 1000 次读位姿 RTT 统计
    python examples/bench_hrif.py --loop-sim     # 附加: 模拟定频循环测 overrun
    python examples/bench_hrif.py -n 5000

纯读操作, 机械臂不会动。关注 p99 而非均值: 写字时一次超时顿挫就是一个墨点。
"""
import argparse
import statistics
import time

from brushbot.backends.vendor.CPS import CPSClient
from brushbot.runtime import RealClock


def stats_ms(samples_s):
    ss = sorted(samples_s)
    n = len(ss)
    pick = lambda q: ss[min(n - 1, int(q * n))] * 1000
    return (statistics.median(ss) * 1000, pick(0.95), pick(0.99), ss[-1] * 1000)


def bench_rtt(cps: CPSClient, n: int) -> None:
    print(f"== 读位姿 RTT × {n} (ReadActPos 完整往返) ==")
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        ret = cps.HRIF_ReadActTcpPos()
        ts.append(time.perf_counter() - t0)
        if ret[0] != "0":
            print(f"[警告] 读失败, 错误码 {ret[0]}")
    med, p95, p99, mx = stats_ms(ts)
    print(f"中位数 {med:.2f}ms  p95 {p95:.2f}ms  p99 {p99:.2f}ms  最大 {mx:.2f}ms")
    print(f"预算参考: 每拍读一次+写一次 ≈ 2×RTT, p99 口径 {2*p99:.2f}ms")


def bench_loop(cps: CPSClient, fs: float, ticks: int) -> None:
    dt_ms = 1000.0 / fs
    clk = RealClock(fs=fs)
    overruns = 0
    work = []
    for _ in range(ticks):
        _, ov = clk.tick()
        overruns += ov
        t0 = time.perf_counter()
        cps.HRIF_ReadActTcpPos()   # 代表每拍的 read; write 成本同量级
        work.append(time.perf_counter() - t0)
    med, p95, p99, mx = stats_ms(work)
    verdict = "充裕" if p99 < 0.5 * dt_ms else ("紧张" if p99 < dt_ms else "塞不下")
    print(f"fs={fs:5.1f}Hz (周期 {dt_ms:.1f}ms): overrun {overruns}/{ticks}, "
          f"每拍活 p99 {p99:.2f}ms -> 预算{verdict}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.0.10")
    ap.add_argument("-n", type=int, default=1000, help="RTT 采样次数")
    ap.add_argument("--loop-sim", action="store_true",
                    help="模拟定频循环: 各候选频率跑 200 拍统计 overrun")
    args = ap.parse_args()

    cps = CPSClient(args.ip)
    bench_rtt(cps, args.n)
    if args.loop_sim:
        print("\n== 定频循环模拟 (RealClock + 每拍一次读) ==")
        for fs in (20.0, 30.0, 50.0, 100.0):
            bench_loop(cps, fs, ticks=200)


if __name__ == "__main__":
    main()
