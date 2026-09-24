#!/usr/bin/env python3
"""真机执行梯子标定实验：拼装实验栈、按 50 Hz 节拍推进、产出 run 目录。

与 `scripts/*_scan.py` 那一套不同：本脚本走 `experiments/` 平台（ExperimentEngine），
产物是 `control.jsonl` + `sensor.csv` + `manifest.json`，也就是 `summarize_ladder` 能读的格式，
并能用 `scripts/split_ladder_run.py` 分趟查看。

直接运行时使用本文件内的当前装配配置；仍可用可选参数覆盖，便于 dry-run 和调试。

Ctrl+C 走引擎的中止路径（ABORT_LIFT 抬笔）而不是让进程直接退出——梯子扫描途中刷子可能
正压在纸面下，直接退出会把它留在那儿。
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
IDLE = {"READY", "WAIT_OPERATOR", "END_WAIT", "ABORTED", "FAULT"}

ADAPTER_ROOT = Path(__file__).resolve().parents[2] / "elfin-dhag-adapter"
REPO_ROOT = Path(__file__).resolve().parents[1]

# 零参数真机配置。日常执行只需：python scripts/run_ladder_experiment.py
ROBOT_IP = "192.168.0.10"
GRIPPER_GID = 1
TCP_NAME = "TCP_brush"
UCS_NAME = "Base"
SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200
TRANSPORT_TIMEOUT_S = 0.5
DEFAULT_EXPERIMENT = REPO_ROOT / "configs" / "experiments" / "z_ladder_x.json"
BRUSH_ID = "brush2"
DEFAULT_RUN_ROOT = REPO_ROOT / "runs" / BRUSH_ID

# brush2：离线预检默认 Ry15/Rz0；真机轨迹采用启动时读取的 TCP 姿态。
# 接触零点 40 mm，本批按用户设置跑 Z=36→24 mm、8 档。
EXPERIMENT_RY_DEG = 15.0
Z_START_MM = 36.0
RUN_LABEL = "brush2_full_rx-15_rz270"
Z_END_MM = 24.0
Z_LEVEL_COUNT = 8
TRAVEL_MM = 200.0
# 自动沾水：1 表示每条路径前沾水，2 表示每两条，None 表示关闭。
AUTO_WET_EVERY_PATHS = 1
WET_X_MM = -300.0
WET_Y_MM = 500.0
WET_CUP_RIM_Z_MM = 100.0
WET_SAFE_Z_MM = 120.0
WET_DIP_Z_MM = 50.0
WET_DWELL_S = 1.0
BASELINE_SETTLE_S = 0.5


def _hardcoded_setup() -> dict:
    """当前毛笔装配的零参数实验配置。

    TCP/UCS 的六维坐标在连接后按名称从控制器读取并写回；这里的零值只是连接前
    编译轨迹所需的占位值，不会用来切换或修改控制器里的 TCP。
    """
    return validate_installation({
        "installation_id": "brush2-z-ladder",
        "verified": True,
        "tcp_name": TCP_NAME,
        "ucs_name": UCS_NAME,
        "tool_coord_si": [0.0] * 6,
        "user_coord_si": [0.0] * 6,
        "vertical_rpy_rad": [0.0, math.radians(EXPERIMENT_RY_DEG), 0.0],
        "sensor_mount_id": "brush2-mount",
        "origin_x_mm": -200.0,
        "origin_y_mm": 500.0,
        "wait_z_mm": 130.0,
        "contact_z_mm": 40.0,
        "workspace_min_mm": [-400.0, 400.0, 17.0],
        "workspace_max_mm": [100.0, 600.0, 130.0],
        "max_depth_mm": 20.0,
        "max_xy_speed_mm_s": 30.0,
        "max_z_speed_mm_s": 13.0,
        "max_accel_mm_s2": 200.0,
        "max_step_mm": 2.0,
        "approach_speed_mm_s": 13.0,
        "return_speed_mm_s": 20.0,
        "pose_tolerance_mm": 0.5,
        "orientation_tolerance_rad": math.radians(1.0),
        "baseline_window_s": 0.04,
        "baseline_timeout_s": 2.0,
        "baseline_min_samples": 3,
        "baseline_max_std_uT": [0.1, 0.1, 0.1],
        "baseline_max_drift_uT_s": 0.1,
        "sensor_max_age_s": 0.1,
        "max_tick_lateness_s": 0.10,
        "stop_timeout_s": 10.0,
        "gripper_width_mm": 14.0,
        "gripper_speed": 30,
        "gripper_force": 30,
        "filter": {"kind": "ema", "alpha": 0.3},
    }, hardware=True)


def _capture_runtime_orientation(setup: dict, arm) -> tuple[float, float, float]:
    """Record the current finite TCP RPY without restricting its orientation."""
    state = arm.read_state()
    pose = state.get("tcp_pose") if state.get("available") else None
    if pose is None:
        raise RuntimeError("无法读取当前 TCP 姿态")
    try:
        values = tuple(float(value) for value in pose)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("当前 TCP 位姿不是有效数字") from exc
    if len(values) != 6 or not all(math.isfinite(value) for value in values):
        raise RuntimeError("当前 TCP 位姿必须包含六个有限数值")
    orientation = values[3:]
    setup["vertical_rpy_rad"] = list(orientation)
    return orientation


def _read_named_coordinate(client, method_name: str, name: str) -> tuple[float, ...]:
    """Read one named controller coordinate without activating or changing it."""
    reply = getattr(client, method_name)(name)
    if not isinstance(reply, (list, tuple)) or len(reply) < 7 or str(reply[0]) != "0":
        raise RuntimeError("读取 {} 失败: {}".format(name, reply))
    try:
        values = tuple(float(value) for value in reply[1:7])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("{} 坐标不是有效数字".format(name)) from exc
    if not all(math.isfinite(value) for value in values):
        raise RuntimeError("{} 坐标包含非有限值".format(name))
    return values


def _vendor_coord_to_si(values) -> list[float]:
    return [
        float(values[0]) / 1000.0,
        float(values[1]) / 1000.0,
        float(values[2]) / 1000.0,
        math.radians(float(values[3])),
        math.radians(float(values[4])),
        math.radians(float(values[5])),
    ]


def _configure_batch_spec(
        template: dict, setup: dict, *, z_start_mm=Z_START_MM,
        z_end_mm=Z_END_MM, z_level_count=Z_LEVEL_COUNT,
        run_label=RUN_LABEL) -> dict:
    """Resolve editable absolute-Z batch parameters into a one-way ladder spec."""
    try:
        z_start = float(z_start_mm)
        z_end = float(z_end_mm)
    except (TypeError, ValueError) as exc:
        raise ValueError("Z_START_MM and Z_END_MM must be finite numbers") from exc
    if not math.isfinite(z_start) or not math.isfinite(z_end):
        raise ValueError("Z_START_MM and Z_END_MM must be finite numbers")
    if z_start <= z_end:
        raise ValueError("Z_START_MM must be above Z_END_MM for a downward one-way batch")
    if (isinstance(z_level_count, bool) or not isinstance(z_level_count, int)
            or z_level_count < 2):
        raise ValueError("Z_LEVEL_COUNT must be an integer >= 2")
    if not isinstance(run_label, str) or not run_label.strip():
        raise ValueError("RUN_LABEL must be a non-empty string")

    lower = float(setup["workspace_min_mm"][2])
    upper = min(float(setup["workspace_max_mm"][2]), float(setup["contact_z_mm"]))
    if z_start > upper + 1e-9:
        raise ValueError("Z_START_MM is above the contact/workspace limit")
    if z_end < lower - 1e-9:
        raise ValueError("Z_END_MM is below the workspace limit")
    depth_from = float(setup["contact_z_mm"]) - z_start
    depth_to = float(setup["contact_z_mm"]) - z_end
    if depth_to > float(setup["max_depth_mm"]) + 1e-9:
        raise ValueError("Z_END_MM exceeds max_depth_mm")

    spec = copy.deepcopy(template)
    spec["name"] = "z_batch_{}_to_{}".format(
        format(z_start, "g").replace(".", "p"),
        format(z_end, "g").replace(".", "p"))
    spec["run_label"] = run_label.strip()
    path = spec["path"]
    path.update({
        "axis": "+x",
        "travel_mm": float(TRAVEL_MM),
        "depth_from_mm": depth_from,
        "depth_to_mm": depth_to,
        "steps": int(z_level_count),
        "order": "one_way",
    })
    path.pop("pause_every_passes", None)
    path.pop("pause_z_mm", None)
    path.pop("wetting", None)
    if AUTO_WET_EVERY_PATHS is not None:
        if (isinstance(AUTO_WET_EVERY_PATHS, bool)
                or not isinstance(AUTO_WET_EVERY_PATHS, int)
                or AUTO_WET_EVERY_PATHS < 1):
            raise ValueError(
                "AUTO_WET_EVERY_PATHS must be None or an integer >= 1")
        path["wetting"] = {
            "every_paths": int(AUTO_WET_EVERY_PATHS),
            "x_mm": float(WET_X_MM),
            "y_mm": float(WET_Y_MM),
            "cup_rim_z_mm": float(WET_CUP_RIM_Z_MM),
            "safe_z_mm": float(WET_SAFE_Z_MM),
            "dip_z_mm": float(WET_DIP_Z_MM),
            "dwell_s": float(WET_DWELL_S),
            "settle_s": float(BASELINE_SETTLE_S),
        }
    return validate_experiment(spec)


def _batch_z_values(spec: dict, setup: dict) -> list[float]:
    path = spec["path"]
    count = int(path["steps"])
    depth_start = float(path["depth_from_mm"])
    depth_end = float(path["depth_to_mm"])
    contact_z = float(setup["contact_z_mm"])
    return [
        contact_z - (depth_start + (depth_end - depth_start) * index / (count - 1))
        for index in range(count)
    ]


class MonotonicClock:
    """引擎、臂适配器与采样中枢**必须**共用同一个时钟实例。

    三者都用单调钟纳秒；若臂适配器用默认的 `time.monotonic_ns` 而引擎用别的时基，
    `control.jsonl` 里 `actual_rx_ns - host_ns` 就没有意义了。
    """

    def now_ns(self) -> int:
        return time.monotonic_ns()


class DatedLadderRecorder(RunRecorder):
    """Write a run directly in Shanghai-date/HH-MM-SS__label__short-id."""

    def __init__(self, root: Path, snapshots: dict):
        snapshots = {**snapshots, "brush_id": BRUSH_ID}
        started_at = datetime.now(timezone.utc)
        local_start = started_at.astimezone(ZoneInfo("Asia/Shanghai"))
        resolved = snapshots.get("resolved", snapshots.get("experiment", {}))
        label = str(resolved.get("run_label") or resolved.get("name") or "run")
        label = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", label.strip())
        label = re.sub(r"\s+", "-", label)
        self._brief = re.sub(r"-+", "-", label).strip("-._")[:80] or "run"
        self._local_start = local_start
        super().__init__(str(Path(root) / f"{local_start:%Y-%m-%d}"),
                         snapshots, started_at=started_at)

    def _create_run_dir(self):
        stamp = self._started_at.astimezone(timezone.utc).strftime(
            "%Y%m%dT%H%M%S.%fZ")
        for _ in range(100):
            short = secrets.token_hex(3)
            run_id = f"{stamp}-{short}"
            folder = self.root / f"{self._local_start:%H-%M-%S}__{self._brief}__{short}"
            try:
                folder.mkdir()
            except FileExistsError:
                continue
            return run_id, folder
        raise RuntimeError("could not allocate unique experiment run_id")


def build_experiment_stack(*, spec, setup, arm, source, root, clock, dt_s=0.02):
    """拼装采样中枢与引擎并 prepare。不连接任何硬件，便于用假设备驱动测试。"""
    hub = SampleHub(source, clock.now_ns)
    engine = ExperimentEngine(
        arm, hub, lambda snapshots: DatedLadderRecorder(root, snapshots),
        clock, dt_s=dt_s)
    engine.prepare(spec, setup)
    return engine, hub


def _pace(clock, tick_started_ns, tick, dt_s, sleep) -> None:
    """把这一拍对齐到绝对节拍边界。

    绝对边界而非相对 sleep(dt)：每拍干活的耗时不累积成漂移。假时钟没有挂钟可对齐，
    直接推进自身（与 `ExperimentService._drive_active_operation` 一致）。
    """
    if hasattr(clock, "advance"):
        clock.advance(dt_s)
        # 合成时钟不会像真实的 20 ms sleep 那样自然让出 GIL；显式 yield，
        # 否则长计划会让后台 recorder 线程饿死并把有界队列写满。
        sleep(0)
        return
    target_ns = tick_started_ns + int(round(tick * dt_s * 1e9))
    remaining = (target_ns - clock.now_ns()) / 1e9
    if remaining > 0:
        sleep(remaining)


def _format_live_status(telemetry: dict, progress: float) -> tuple[str, ...]:
    b = telemetry["B_uT"]
    return (
        "Z Ladder  {progress:5.1f}%".format(progress=100.0 * float(progress)),
        "phase={}".format(telemetry["phase"]),
        "Zcmd={:6.2f}mm  depth={:5.2f}mm".format(
            float(telemetry["z_cmd_mm"]), float(telemetry["depth_cmd_mm"])),
        "Bx={:8.2f}  By={:8.2f}  Bz={:8.2f} uT".format(
            float(b[0]), float(b[1]), float(b[2])),
        "|ΔBxy|={:7.2f}uT  baseline={}".format(
            float(telemetry["dBxy_uT"]), telemetry["baseline_id"]),
    )


class LiveStatusPanel:
    """TTY 中原位刷新五行状态；重定向输出时退化为普通日志。"""

    def __init__(self, stream):
        self.stream = stream
        self._tty = bool(getattr(stream, "isatty", lambda: False)())
        self._line_count = 0
        self._active = False

    def update(self, lines) -> None:
        lines = tuple(str(line) for line in lines)
        if not self._tty:
            self.stream.write(" | ".join(lines) + "\n")
            self.stream.flush()
            return
        if not self._active:
            self.stream.write("\x1b[?25l")
        elif self._line_count:
            self.stream.write("\x1b[{}A".format(self._line_count))
        for line in lines:
            self.stream.write("\x1b[2K\r" + line + "\n")
        self.stream.flush()
        self._line_count = len(lines)
        self._active = True

    def pause(self) -> None:
        if not self._active:
            return
        if self._tty:
            self.stream.write("\x1b[?25h\n")
            self.stream.flush()
        self._active = False
        self._line_count = 0

    close = pause


def _advance_loop(engine, hub, *, clock, dt_s, sleep, input_fn=input,
                  live_output_fn=None, live_break_fn=None,
                  live_interval_s=0.2) -> None:
    started_ns = clock.now_ns()
    tick = 0
    last_live_ns = None
    live_interval_ns = int(round(float(live_interval_s) * 1e9))
    while engine.state not in TERMINAL:
        if engine.state == "WAIT_OPERATOR":
            if live_break_fn is not None:
                live_break_fn()
            input_fn("已回到高位原点；请沾水，按 Enter 后重新取基线并继续：")
            engine.resume_after_operator()
            started_ns = clock.now_ns()
            tick = 0
            continue
        if engine.state not in IDLE:
            hub.poll_once()
            snapshot = engine.step()
            telemetry = snapshot.get("telemetry")
            now_ns = clock.now_ns()
            if (live_output_fn is not None and engine.state == "RUN"
                    and telemetry is not None
                    and (last_live_ns is None
                         or now_ns - last_live_ns >= live_interval_ns)):
                live_output_fn(_format_live_status(
                    telemetry, float(snapshot.get("progress") or 0.0)))
                last_live_ns = now_ns
        tick += 1
        _pace(clock, started_ns, tick, dt_s, sleep)


def run_experiment(engine, hub, *, clock, dt_s=0.02, sleep=time.sleep,
                   input_fn=input, live_output_fn=None, live_break_fn=None,
                   live_interval_s=0.2,
                   require_wait_position=True) -> dict:
    """start 后推进到终态，返回 snapshot。

    Ctrl+C 不直接退出：先 `request_stop` 让引擎走 ABORT_LIFT 把笔抬起来，再重新推进到
    终态，然后才把 KeyboardInterrupt 抛给调用方。
    """
    engine.start(require_wait_position=require_wait_position)
    try:
        _advance_loop(
            engine, hub, clock=clock, dt_s=dt_s, sleep=sleep,
            input_fn=input_fn, live_output_fn=live_output_fn,
            live_break_fn=live_break_fn, live_interval_s=live_interval_s)
    except KeyboardInterrupt:
        engine.request_stop("operator_stop")
        engine.step()
        print("已中断：正在让引擎抬笔（ABORT_LIFT）…", file=sys.stderr)
        _advance_loop(
            engine, hub, clock=clock, dt_s=dt_s, sleep=sleep,
            input_fn=input_fn, live_output_fn=live_output_fn,
            live_break_fn=live_break_fn, live_interval_s=live_interval_s)
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
    diagnostic = snapshot.get("baseline_diagnostic")
    if diagnostic:
        print("baseline 诊断: {}；有效帧 {}/{}".format(
            diagnostic["error"], diagnostic["valid_samples"],
            diagnostic["samples"]))
        source = diagnostic.get("source")
        if source:
            print("串口统计: 收到 {} 字节、{} 行，其中 {} 行无法解析".format(
                source["bytes_received"], source["lines_seen"],
                source["bad_lines"]))


def _parse(argv):
    parser = argparse.ArgumentParser(
        description="执行 Z 梯子实验；不传参数即使用脚本内的当前毛笔装配")
    parser.add_argument("--installation",
                        help="可选：用 verified installation JSON 覆盖脚本内配置")
    parser.add_argument("--experiment", default=str(DEFAULT_EXPERIMENT),
                        help="实验定义 JSON，如 configs/experiments/z_ladder_x.json")
    parser.add_argument("--ip", default=ROBOT_IP, help="控制器 IP")
    parser.add_argument("--gid", type=int, default=GRIPPER_GID, help="夹爪 GID")
    parser.add_argument("--serial-port", default=SERIAL_PORT, help="磁传感器串口")
    parser.add_argument("--baud", type=int, default=SERIAL_BAUD)
    parser.add_argument("--transport-timeout-s", type=float,
                        default=TRANSPORT_TIMEOUT_S, help="单次 HRIF 调用超时")
    parser.add_argument("--socket", help="可选：同时开实验服务 socket，供 monitor GUI 驱动")
    parser.add_argument("--max-depth-mm", type=float,
                        help="本次只跑到该压深（首次上机建议先用小值试跑）")
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT),
                        help="run 目录的父目录，每个 run 一个子目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="不连任何硬件：只编译并报告计划，用于上机前预检")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv)

    spec = load_experiment(args.experiment)

    if args.installation:
        setup_path = Path(args.installation)
        setup = validate_installation(
            json.loads(setup_path.read_text(encoding="utf-8")), hardware=True)
    else:
        setup = _hardcoded_setup()
        print("使用脚本内配置: IP={}, TCP={}, 串口={}".format(
            args.ip, setup["tcp_name"], args.serial_port))
        print("实验原点 XYZ = ({:.1f}, {:.1f}, {:.1f}) mm；接触 Z = {:.1f} mm".format(
            setup["origin_x_mm"], setup["origin_y_mm"], setup["wait_z_mm"],
            setup["contact_z_mm"]))
    spec = _configure_batch_spec(spec, setup)
    if args.max_depth_mm is not None:
        requested = float(spec["path"]["depth_to_mm"])
        capped = min(requested, float(args.max_depth_mm))
        if capped <= float(spec["path"]["depth_from_mm"]):
            raise ValueError("--max-depth-mm must remain deeper than Z_START_MM")
        spec["path"]["depth_to_mm"] = capped
        spec = validate_experiment(spec)
        print("本次压深上限: %g mm（批次定义为 %g mm）" % (capped, requested))
    z_values = _batch_z_values(spec, setup)
    print("批次: {}；单向 Z 路径 {} 条：{} mm".format(
        spec["run_label"], len(z_values),
        ", ".join("{:.3f}".format(value).rstrip("0").rstrip(".") for value in z_values)))
    print("速度: 非接触 Z/XY 回程 {:.1f} mm/s；XY 测量 {:.1f} mm/s".format(
        setup["approach_speed_mm_s"], spec["motion"]["speed_mm_s"]))

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
        robot = HuayanRobot(
            args.ip, gripper_gid=args.gid,
            tcp_name=setup["tcp_name"], ucs_name=setup["ucs_name"])
        if args.installation is None:
            # 只读取已存在的 TCP_brush/Base；不调用 SetTCP/SetUCS，也不切换 TCP。
            tool_coord = _read_named_coordinate(
                robot.client, "HRIF_ReadTCPByName", setup["tcp_name"])
            user_coord = _read_named_coordinate(
                robot.client, "HRIF_ReadUCSByName", setup["ucs_name"])
            robot.arm.tool_coord = list(tool_coord)
            robot.arm.user_coord = list(user_coord)
            setup["tool_coord_si"] = _vendor_coord_to_si(tool_coord)
            setup["user_coord_si"] = _vendor_coord_to_si(user_coord)
        # 适配器在这里自检 tcp_name / ucs_name / tool_coord / user_coord 是否与机器人一致，
        # 不一致直接抛——这是防呆，不是本脚本的职责。
        arm = ElfinExperimentArm(
            robot, setup, transport_timeout_s=args.transport_timeout_s,
            clock_ns=clock.now_ns)
        try:
            captured_rpy = _capture_runtime_orientation(setup, arm)
        except RuntimeError as exc:
            print("无法开始: %s" % exc, file=sys.stderr)
            print("没有发送运动命令。", file=sys.stderr)
            return 2
        print("已记录当前 TCP 姿态 RPY = ({:.3f}, {:.3f}, {:.3f})°；"
              "本次所有轨迹保持该姿态。".format(
                  *(math.degrees(value) for value in captured_rpy)))
        engine, hub = build_experiment_stack(
            spec=spec, setup=setup, arm=arm, source=source,
            root=Path(args.run_root), clock=clock)
        print("已就绪。启动位置不限；取 baseline 时请保持笔尖离纸静止。"
              "随后将从当前位置直接 MoveL 到第一段轨迹起点，请确认直线路径无遮挡。"
              "Ctrl+C 会走抬笔中止。")
        panel = LiveStatusPanel(sys.stdout)
        try:
            snapshot = run_experiment(
                engine, hub, clock=clock,
                live_output_fn=panel.update,
                live_break_fn=panel.pause,
                require_wait_position=False)
        except RuntimeError as exc:
            print("无法开始: %s" % exc, file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            panel.close()
            _report(engine.snapshot())
            print("实验已中止并抬笔。", file=sys.stderr)
            return 130
        finally:
            panel.close()
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
