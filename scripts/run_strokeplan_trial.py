#!/usr/bin/env python3
"""修改下方参数，选择 StrokePlan、难曲线、短平台、Ki 扫描或整字实验。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]

# ==================== 日常只需修改这一段 ====================
# 运行：python scripts/run_strokeplan_trial.py
# EXPERIMENT 选择以下六种实验之一：
#   "strokeplan_ff"：单笔纯前馈，使用 STROKEPLAN。
#   "strokeplan_p" ：单笔受限 P，使用 STROKEPLAN 和 P_PROFILE。
#   "nonlinear"   ：160–240 µT 难曲线；MODE="ff" 或 "p"。
#   "short_plateau"：160→240→160 短平台；MODE="p" 或 "pi"。
#   "ki_scan"     ：六步冻结 Ki 扫描；KI_STEP=1..6，每次只跑一步。
#   "calligraphy" ：中；MODE="feedforward" 或 "pi"，STROKE=None 为整字。
EXPERIMENT = "strokeplan_ff"

# False：离线预检，不连接硬件、不创建 run；True：预检后等待输入 RUN。
# 命令行 --dry-run / --execute 可以临时覆盖这里的设置。
EXECUTE = False

# 单笔实验的目标文件。相对路径从所选 TRIAL 目录计算，也可填写绝对路径。
# 套件可选：01_gradual_press.npz、02_single_arch.npz、03_double_wave.npz、
#           04_smooth_levels.npz、04_smooth_levels_wide_transitions.npz。
STROKEPLAN = "01_gradual_press.npz"

# None 使用所选实验的默认模式：FF、P、P、PI、PI、PI，顺序同上。
# 要切换难曲线对照可填 "ff" / "p"；短平台可填 "p" / "pi"。
MODE = None

# 中字：None 写整字；1=左竖、2=横折、3=下横、4=中竖。
STROKE = None
# Ki 扫描步骤：1..6 分别为 0.05、0.025、0.10、0.10、0.025、0.05。
# 保留原冻结顺序与公共限幅校验，逐笔手动启动。
KI_STEP = 1

# 单笔 P 的增益与边界；ki 必须为 0。距离 mm，速度 mm/s，加速度 mm/s²。
P_PROFILE = dict(kp=2.0, ki=0.0, max_correction_mm=0.4,
                 max_correction_speed_mm_s=5.0, max_correction_accel_mm_s2=70.0,
                 taper_ticks=25)  # 25 个 20 ms 节拍，即 0.5 s 渐变。

# 仅 nonlinear 的 P 模式使用。None 保留实验目录 p_profile.json 中的值。
# 例：KP=1.0、MAX_CORRECTION_MM=0.8、P_DYNAMICS="smooth" 选择平滑 P 扫描。
# P_DYNAMICS="smooth"：2 mm/s、30 mm/s²、1 s 渐变；"legacy" 保留原动态。
KP = None
MAX_CORRECTION_MM = None
P_DYNAMICS = None

# 各实验输入目录。换实验只需改 EXPERIMENT；需要时再改对应目录。
PLAN_ROOT = ROOT / "runs/brush2/plans"
TRIAL_DIRS = {
    "strokeplan_ff": PLAN_ROOT / "ry15_rz0_suite_60_200_v1",
    "strokeplan_p": PLAN_ROOT / "ry15_rz0_suite_60_200_v1",
    "nonlinear": PLAN_ROOT / "06_难曲线160到240_FF与P",
    "short_plateau": PLAN_ROOT / "08_短平台160到240回160_P与PI",
    "ki_scan": PLAN_ROOT / "09_短平台Ki扫描",
    "calligraphy": PLAN_ROOT / "12_中字朝负Y_负X为右",
}
# 以下 None 自动使用上表目录及其 feedforward.json / settings.json。
# 可填 Path("/绝对路径/...") 覆盖选中实验的目录、前馈表或现场设置。
TRIAL = None
FEEDFORWARD = None
SETTINGS = None

# 连接和输出参数。实际 TCP 采集独立于反馈，不参与 Z 修正。
SERIAL_PORT = "/dev/ttyACM0"
BAUD = 115200
ARM_IP = "192.168.0.10"
RUN_ROOT = ROOT / "runs/brush2"
# None：单笔 FF/P 默认关闭，其余实验开启；也可指定 True / False。
RECORD_ACTUAL_TCP = None
# ==================== 参数区结束 ====================

# 允许直接从仓库运行，无需手动设置 PYTHONPATH。
sys.path.insert(0, str(ROOT / "src"))
from brushbot.feedforward import require_execution_approval
from brushbot.experiments.strokeplan_execution import runtime_settings

if __package__:
    from .run_strokeplan_experiment import main as run_experiment
else:
    from run_strokeplan_experiment import main as run_experiment


_DEFAULT_MODES = dict(strokeplan_ff="feedforward", strokeplan_p="p",
                      nonlinear="p", short_plateau="pi", ki_scan="pi", calligraphy="pi")
_ALLOWED_MODES = dict(strokeplan_ff={"feedforward"}, strokeplan_p={"p"},
                      nonlinear={"feedforward", "p"}, short_plateau={"p", "pi"},
                      ki_scan={"pi"}, calligraphy={"feedforward", "pi"})
_TARGET_NAMES = {"01_gradual_press": "渐进压笔", "02_single_arch": "单拱",
                 "03_double_wave": "双波", "04_smooth_levels_wide_transitions": "宽过渡"}
_KI_SEQUENCE = (.05, .025, .1, .1, .025, .05)
_KI_FIXED_PROFILE = dict(kp=1., max_correction_mm=.8, max_correction_speed_mm_s=2.,
                         max_correction_accel_mm_s2=30., taper_ticks=50,
                         integral_limit_mm=.2, anti_windup="conditional")


def _command(args, trial, target, *, label, folder, condition, entry=False, execute=None):
    command = [str(target), "--feedforward", str(FEEDFORWARD or trial / "feedforward.json"),
               "--settings", str(SETTINGS or trial / "settings.json"),
               "--serial-port", SERIAL_PORT, "--baud", str(BAUD), "--ip", ARM_IP,
               "--run-root", str(RUN_ROOT), "--run-label", label,
               "--experiment-folder", folder, "--run-folder-label", condition,
               "--control-mode", args.mode]
    if entry:
        command += ["--entry-profile", str(trial / "entry_profile.json")]
    record_tcp = args.record_actual_tcp
    if record_tcp is None:
        record_tcp = args.experiment not in {"strokeplan_ff", "strokeplan_p"}
    if record_tcp:
        command.append("--record-actual-tcp")
    command.append("--execute" if (args.execute if execute is None else execute) else "--dry-run")
    return command


def _run_character(args, trial):
    profile = json.loads((trial / "pi_profile.json").read_text()) if args.mode == "pi" else None
    entry = json.loads((trial / "entry_profile.json").read_text())
    if entry.get("mode") == "directional_character":
        target = "character.npz" if args.stroke is None else f"stroke_{args.stroke:02}.npz"
        label = "整字" if args.stroke is None else f"第{args.stroke}笔"
        print("连续运行：一次基线采集；笔间抬笔直接转移；全部完成后回等待位。")
        return run_experiment(_command(args, trial, trial / target, label=f"zhong_{label}_{args.mode}",
            folder="11_中字连续方向姿态", condition=f"中_{label}_方向姿态_{args.mode}", entry=True),
            feedback_profile=profile)

    def command(stroke, execute):
        return _command(args, trial, trial / f"stroke_{stroke:02}.npz",
            label=f"zhong_{stroke:02}_{args.mode}", folder="10_中字原地旋转进笔",
            condition=f"中_第{stroke}笔_{args.mode}", entry=True, execute=execute)

    if args.stroke is not None:
        return run_experiment(command(args.stroke, args.execute), feedback_profile=profile)
    print("整字模式：按 1 左竖 → 2 横折 → 3 下横 → 4 中竖执行；先预检全部四笔。")
    for stroke in range(1, 5):
        status = run_experiment(command(stroke, False), feedback_profile=profile)
        if status:
            return status
    if not args.execute:
        return 0
    table = json.loads(Path(FEEDFORWARD or trial / "feedforward.json").read_text())
    setup = json.loads(Path(SETTINGS or trial / "settings.json").read_text())
    require_execution_approval(table, setup)
    runtime_settings(setup, hardware=True)
    print("整字自动执行：每笔结束返回等待位，自动开始下一笔并重新采集基线；分别保存记录。")
    print("本轮一次手动沾水，笔间不暂停补水；保持纸张位置。任一笔异常将停止整字。")
    if input("确认已沾水、处于上述等待位姿且整字路径净空足够；输入 RUN 写完整个中: ").strip() != "RUN":
        return 0
    for stroke in range(1, 5):
        print(f"开始第 {stroke}/4 笔。")
        status = run_experiment(command(stroke, True), feedback_profile=profile,
                                confirm_execution=lambda _: "RUN")
        if status:
            print(f"第 {stroke} 笔未正常完成，整字停止。")
            return status
    print("四笔均正常完成。")
    return 0


def _run_single(args, trial):
    profile = None
    entry = args.experiment not in {"strokeplan_ff", "strokeplan_p"}
    if not entry:
        target = Path(args.strokeplan if args.strokeplan is not None else STROKEPLAN)
        if args.strokeplan is None and not target.is_absolute():
            target = trial / target
        name = _TARGET_NAMES.get(target.stem, target.stem)
        if args.experiment == "strokeplan_ff":
            label, folder, condition = "strokeplan_ff_" + target.stem, "01_四目标纯前馈", name
        else:
            profile = dict(P_PROFILE)
            bounds = tuple(profile[k] for k in ("max_correction_mm", "max_correction_speed_mm_s",
                                                "max_correction_accel_mm_s2"))
            fmt = lambda value: f"{value:g}".replace(".", "p")
            if bounds == (.2, 2., 40.):
                folder, condition = "02_P反馈与增益扫描", f"{name}_P{fmt(profile['kp'])}"
                label = "strokeplan_p_gain_" + target.stem
            else:
                folder = "03_P2修正上限" if profile["kp"] == 2. else "04_P反馈参数组合"
                condition = (f"{name}_P{fmt(profile['kp'])}_修正{fmt(bounds[0])}mm_"
                             f"速度{fmt(bounds[1])}_加速度{fmt(bounds[2])}")
                label = ("strokeplan_p_limits_" if profile["kp"] == 2. else "strokeplan_p_mixed_") + target.stem
    elif args.experiment == "nonlinear":
        target = trial / "hard_160_240.npz"
        if args.mode == "p":
            profile = json.loads((trial / "p_profile.json").read_text())
            if args.p_dynamics == "smooth":
                profile.update(max_correction_speed_mm_s=2., max_correction_accel_mm_s2=30., taper_ticks=50)
            if args.kp is not None:
                profile["kp"] = args.kp
            if args.max_correction_mm is not None:
                profile["max_correction_mm"] = args.max_correction_mm
        condition = "纯前馈" if profile is None else f"前馈加P{profile['kp']:g}_修正{profile['max_correction_mm']:g}mm"
        if args.scan:
            dynamics = "平滑" if args.p_dynamics == "smooth" else "原动态"
            condition += (f"_{dynamics}_渐变{profile['taper_ticks']*.02:g}s"
                          f"_速度{profile['max_correction_speed_mm_s']:g}"
                          f"_加速度{profile['max_correction_accel_mm_s2']:g}")
        condition = "难曲线160到240_" + condition
        folder = "07_非线性前馈P参数扫描" if args.scan else "06_非线性前馈难曲线对比"
        label = "nonlinear_hard_" + ("ff" if profile is None else "p") + ("_scan" if args.scan else "")
    elif args.experiment == "short_plateau":
        target = trial / "plateau_160_240_160.npz"
        profile = json.loads((trial / (args.mode + "_profile.json")).read_text())
        condition = (f"平台160到240回160_{args.mode.upper()}_Kp{profile['kp']:g}_Ki{profile['ki']:g}"
                     f"_总修正{profile['max_correction_mm']:g}mm")
        if args.mode == "pi":
            condition += f"_积分{profile['integral_limit_mm']:g}mm_抗饱和"
        folder, label = "08_短平台P与PI对比", "short_plateau_" + args.mode
    else:
        target = trial / "plateau_160_240_160.npz"
        ki = _KI_SEQUENCE[args.step - 1]
        protocol = json.loads((trial / "protocol.json").read_text())
        if protocol["ki_sequence"] != list(_KI_SEQUENCE):
            raise ValueError("Ki scan protocol sequence differs from the frozen design")
        profile = json.loads((trial / f"pi_ki_{ki:g}.json").read_text())
        if profile != dict(_KI_FIXED_PROFILE, ki=ki):
            raise ValueError("Ki scan profile differs from the frozen gain or common limits")
        print(f"Ki 参数扫描：第 {args.step}/6 笔，Ki={ki:g}；单笔手动启动。")
        print("本批顺序：0.05 → 0.025 → 0.10 → 0.10 → 0.025 → 0.05；每笔结束重新准备。")
        folder, label = "09_短平台Ki参数扫描", f"short_ki_scan_step{args.step}_ki{ki:g}"
        condition = f"平台160到240回160_PI_Kp1_Ki{ki:g}_总修正0.8mm_积分0.2mm"
    return run_experiment(_command(args, trial, target, label=label, folder=folder,
                                   condition=condition, entry=entry), feedback_profile=profile)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strokeplan", nargs="?", help="单笔 FF/P 的 NPZ，相对当前目录；省略时使用顶部 STROKEPLAN")
    parser.add_argument("--experiment", choices=tuple(TRIAL_DIRS), default=EXPERIMENT)
    parser.add_argument("--trial-dir", type=Path, default=TRIAL)
    parser.add_argument("--mode", choices=("ff", "feedforward", "p", "pi"), default=MODE)
    parser.add_argument("--stroke", type=int, choices=range(1, 5))
    parser.add_argument("--step", type=int, choices=range(1, 7))
    parser.add_argument("--kp", type=float, default=KP)
    parser.add_argument("--max-correction-mm", type=float, default=MAX_CORRECTION_MM)
    parser.add_argument("--p-dynamics", choices=("legacy", "smooth"), default=P_DYNAMICS)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", dest="execute", action="store_false")
    action.add_argument("--execute", dest="execute", action="store_true")
    tcp = parser.add_mutually_exclusive_group()
    tcp.add_argument("--record-actual-tcp", dest="record_actual_tcp", action="store_true")
    tcp.add_argument("--no-record-actual-tcp", dest="record_actual_tcp", action="store_false")
    parser.set_defaults(execute=EXECUTE, record_actual_tcp=RECORD_ACTUAL_TCP)
    args = parser.parse_args(argv)
    if args.experiment not in TRIAL_DIRS:
        parser.error(f"unknown experiment: {args.experiment}")
    if args.stroke is not None and args.experiment != "calligraphy":
        parser.error("--stroke requires --experiment calligraphy")
    if args.step is not None and args.experiment != "ki_scan":
        parser.error("--step requires --experiment ki_scan")
    if args.stroke is None:
        args.stroke = STROKE
    if args.step is None:
        args.step = KI_STEP
    args.mode = args.mode or _DEFAULT_MODES[args.experiment]
    if args.mode == "ff":
        args.mode = "feedforward"
    if args.mode not in _ALLOWED_MODES[args.experiment]:
        parser.error(f"{args.experiment} does not support mode {args.mode}")
    # choices 只检查显式命令行选项；脚本顶部的默认值也需要相同校验。
    if args.experiment == "ki_scan" and args.step not in range(1, 7):
        parser.error("KI_STEP / --step must be an integer from 1 to 6")
    if args.experiment == "calligraphy" and args.stroke is not None and args.stroke not in range(1, 5):
        parser.error("STROKE / --stroke must be None or an integer from 1 to 4")
    if args.p_dynamics not in (None, "legacy", "smooth"):
        parser.error("P_DYNAMICS / --p-dynamics must be None, legacy or smooth")
    args.scan = any(value is not None for value in (args.kp, args.max_correction_mm, args.p_dynamics))
    if args.scan and (args.experiment != "nonlinear" or args.mode != "p"):
        parser.error("P scan options require --experiment nonlinear --mode p")
    if args.strokeplan is not None and args.experiment not in {"strokeplan_ff", "strokeplan_p"}:
        parser.error("a positional StrokePlan path requires strokeplan_ff or strokeplan_p")
    trial = Path(args.trial_dir or TRIAL_DIRS[args.experiment])
    try:
        if args.experiment == "calligraphy":
            return _run_character(args, trial)
        return _run_single(args, trial)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
