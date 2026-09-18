#!/usr/bin/env python3
"""真机执行梯子标定实验：拼装实验栈、按 50 Hz 节拍推进、产出 run 目录。

与 `scripts/*_scan.py` 那一套不同：本脚本走 `experiments/` 平台（ExperimentEngine），
产物是 `control.jsonl` + `sensor.csv` + `manifest.json`，也就是 `summarize_ladder` 能读的格式，
并能用 `scripts/split_ladder_run.py` 分趟查看。

本脚本**不做**任何配置推断：installation 必须已实测并置 `verified: true`，否则适配器会拒绝。

Ctrl+C 走引擎的中止路径（ABORT_LIFT 抬笔）而不是让进程直接退出——梯子扫描途中刷子可能
正压在纸面下，直接退出会把它留在那儿。
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

from brushbot.experiments.acquisition import SampleHub
from brushbot.experiments.adapter import ElfinExperimentArm
from brushbot.experiments.config import (
    load_experiment,
    validate_experiment,
    validate_installation,
)
from brushbot.experiments.engine import ExperimentEngine
from brushbot.experiments.recording import RunRecorder
from brushbot.monitor.sources import SerialSource

# 引擎的终态：走到这三个之一即不再推进。
TERMINAL = {"END_WAIT", "ABORTED", "FAULT"}
# 这些状态下引擎不消费传感器样本（与 fake.FakeRig.advance 一致）。
IDLE = {"READY", "END_WAIT", "ABORTED", "FAULT"}

ADAPTER_ROOT = Path(__file__).resolve().parents[2] / "elfin-dhag-adapter"


class MonotonicClock:
    """引擎、臂适配器与采样中枢**必须**共用同一个时钟实例。

    三者都用单调钟纳秒；若臂适配器用默认的 `time.monotonic_ns` 而引擎用别的时基，
    `control.jsonl` 里 `actual_rx_ns - host_ns` 就没有意义了。
    """

    def now_ns(self) -> int:
        return time.monotonic_ns()


def build_experiment_stack(*, spec, setup, arm, source, root, clock, dt_s=0.02):
    """拼装采样中枢与引擎并 prepare。不连接任何硬件，便于用假设备驱动测试。"""
    hub = SampleHub(source, clock.now_ns)
    engine = ExperimentEngine(
        arm, hub, lambda snapshots: RunRecorder(str(root), snapshots), clock, dt_s=dt_s)
    engine.prepare(spec, setup)
    return engine, hub


def _pace(clock, tick_started_ns, tick, dt_s, sleep) -> None:
    """把这一拍对齐到绝对节拍边界。

    绝对边界而非相对 sleep(dt)：每拍干活的耗时不累积成漂移。假时钟没有挂钟可对齐，
    直接推进自身（与 `ExperimentService._drive_active_operation` 一致）。
    """
    if hasattr(clock, "advance"):
        clock.advance(dt_s)
        return
    target_ns = tick_started_ns + int(round(tick * dt_s * 1e9))
    remaining = (target_ns - clock.now_ns()) / 1e9
    if remaining > 0:
        sleep(remaining)


def _advance_loop(engine, hub, *, clock, dt_s, sleep) -> None:
    started_ns = clock.now_ns()
    tick = 0
    while engine.state not in TERMINAL:
        if engine.state not in IDLE:
            hub.poll_once()
            engine.step()
        tick += 1
        _pace(clock, started_ns, tick, dt_s, sleep)


def run_experiment(engine, hub, *, clock, dt_s=0.02, sleep=time.sleep) -> dict:
    """start 后推进到终态，返回 snapshot。

    Ctrl+C 不直接退出：先 `request_stop` 让引擎走 ABORT_LIFT 把笔抬起来，再重新推进到
    终态，然后才把 KeyboardInterrupt 抛给调用方。
    """
    engine.start()
    try:
        _advance_loop(engine, hub, clock=clock, dt_s=dt_s, sleep=sleep)
    except KeyboardInterrupt:
        engine.request_stop("operator_stop")
        print("已中断：正在让引擎抬笔（ABORT_LIFT）…", file=sys.stderr)
        _advance_loop(engine, hub, clock=clock, dt_s=dt_s, sleep=sleep)
        raise
    return engine.snapshot()


def _report(snapshot: dict) -> None:
    print("状态: %s" % snapshot.get("state"))
    if snapshot.get("run_id"):
        print("run_id: %s" % snapshot["run_id"])
    if snapshot.get("run_dir"):
        print("run 目录: %s" % snapshot["run_dir"])
    print("进度: %.1f%%" % (100.0 * float(snapshot.get("progress") or 0.0)))
    if snapshot.get("last_error"):
        print("最后错误: %s" % snapshot["last_error"])


def _parse(argv):
    parser = argparse.ArgumentParser(
        description="按真机 installation 执行一个实验定义，产出可分析的 run 目录")
    parser.add_argument("--installation", required=True,
                        help="configs/installations/<id>.json（必须 verified: true）")
    parser.add_argument("--experiment", required=True,
                        help="实验定义 JSON，如 configs/experiments/z_ladder_x.json")
    parser.add_argument("--ip", required=True, help="控制器 IP")
    parser.add_argument("--gid", type=int, default=1, help="夹爪 GID")
    parser.add_argument("--serial-port", default="/dev/ttyUSB0", help="磁传感器串口")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--transport-timeout-s", type=float, required=True,
                        help="单次 HRIF 调用的超时；须已实测（见 installation README）")
    parser.add_argument("--socket", help="可选：同时开实验服务 socket，供 monitor GUI 驱动")
    parser.add_argument("--max-depth-mm", type=float,
                        help="本次只跑到该压深（首次上机建议先用小值试跑）")
    parser.add_argument("--run-root", default="runs",
                        help="run 目录的父目录，每个 run 一个子目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="不连任何硬件：只编译并报告计划，用于上机前预检")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)

    spec = load_experiment(args.experiment)
    if args.max_depth_mm is not None:
        spec = copy.deepcopy(spec)
        requested = float(spec["path"]["depth_to_mm"])
        spec["path"]["depth_to_mm"] = min(requested, float(args.max_depth_mm))
        spec = validate_experiment(spec)
        print("本次压深上限: %g mm（实验定义里是 %g mm）"
              % (spec["path"]["depth_to_mm"], requested))

    setup_path = Path(args.installation)
    setup = validate_installation(
        json.loads(setup_path.read_text(encoding="utf-8")), hardware=True)

    if args.dry_run:
        from brushbot.experiments.trajectory import compile_experiment
        compiled = compile_experiment(spec, setup, dt_s=0.02)
        print("预检通过（未连接任何硬件）")
        print("计划: %d 个样本, %.1f 秒 (%.1f 分钟)"
              % (len(compiled["t_s"]), compiled["t_s"][-1], compiled["t_s"][-1] / 60.0))
        phases = sorted(set(compiled["phase"]))
        print("相位: %d 种，%s … %s" % (len(phases), phases[0], phases[-1]))
        return 0

    if ADAPTER_ROOT.is_dir() and str(ADAPTER_ROOT) not in sys.path:
        sys.path.insert(0, str(ADAPTER_ROOT))
    try:
        from huayan_robot import HuayanRobot
    except ModuleNotFoundError:
        print("找不到 elfin-dhag-adapter；请用其 Python 环境，或设置 "
              "PYTHONPATH=%s" % ADAPTER_ROOT, file=sys.stderr)
        return 2

    clock = MonotonicClock()
    source = SerialSource(args.serial_port, args.baud)
    source.start()
    try:
        robot = HuayanRobot(args.ip, gripper_gid=args.gid)
        # 适配器在这里自检 tcp_name / ucs_name / tool_coord / user_coord 是否与机器人一致，
        # 不一致直接抛——这是防呆，不是本脚本的职责。
        arm = ElfinExperimentArm(
            robot, setup, transport_timeout_s=args.transport_timeout_s,
            clock_ns=clock.now_ns)
        engine, hub = build_experiment_stack(
            spec=spec, setup=setup, arm=arm, source=source,
            root=Path(args.run_root), clock=clock)
        print("已就绪。请确认机器人停在 wait 位姿；Ctrl+C 会走抬笔中止。")
        try:
            snapshot = run_experiment(engine, hub, clock=clock)
        except RuntimeError as exc:
            # start() 在机器人不在 wait 位姿时抛这个；给出可操作的提示而不是栈回溯。
            print("无法开始: %s" % exc, file=sys.stderr)
            print("请先把机器人移动到 installation 里的 wait 位姿再重试。", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            _report(engine.snapshot())
            print("实验已中止并抬笔。", file=sys.stderr)
            return 130
        _report(snapshot)
        if snapshot.get("state") != "END_WAIT":
            print("实验未正常结束，请检查 run 目录里的 manifest.json。", file=sys.stderr)
            return 2
        print("完成。下一步：summarize_ladder / split_ladder_run.py 对该 run 目录。")
        return 0
    finally:
        source.stop()


if __name__ == "__main__":
    raise SystemExit(main())
