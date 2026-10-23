#!/usr/bin/env python3
"""长横／短横单笔入口：显式加载已有 brush2 前馈、PI 和进笔配置。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]

from scripts.run_strokeplan_experiment import main as run_experiment

CONTEXT = ROOT/"runs/brush2/plans/11_中字底横延长30mm_实测第9次"
PRESETS = {
    "heng": ("heng_80mm_hidden_tail_v5/heng/strokeplan.npz", "长横80mm，收笔100uT", "heng_80mm_hidden_tail_v5_pi"),
    "short100": ("heng_short_40mm_100_193_v1/heng_short/strokeplan.npz", "短横40mm旧版，收笔100uT", "heng_short_40mm_gradual_v1_pi"),
    "short50": ("heng_short_40mm_end50_v2/heng_short/strokeplan.npz", "短横40mm新版，收笔50uT；当前表不支持", "heng_short_40mm_end50_v2_pi"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        epilog="默认只做离线预检。--execute仍须通过原入口预检并由操作者输入RUN；short50会因当前标定范围不足被拒绝。")
    parser.add_argument("stroke", choices=PRESETS,
        help="heng=长横100；short100=短横旧版100；short50=短横新版50")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true", help="预检后等待RUN，再自动回位并执行")
    action.add_argument("--dry-run", action="store_true", help="仅离线预检（默认）")
    parser.add_argument("--serial-port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--ip", default="192.168.0.10")
    args = parser.parse_args(argv)
    relative, description, label = PRESETS[args.stroke]
    target = ROOT/"runs/brush2/plans"/relative
    print("所选版本：", description)
    print("目标文件：", target)
    print("控制：前馈＋受限PI，仅书写阶段反馈；沿用独立进笔、加载和抬笔流程。")
    profile = json.loads((CONTEXT/"pi_profile.json").read_text(encoding="utf-8"))
    command = [str(target),
        "--feedforward", str(CONTEXT/"feedforward.json"),
        "--settings", str(CONTEXT/"settings.json"),
        "--entry-profile", str(CONTEXT/"entry_profile.json"),
        "--control-mode", "pi", "--record-actual-tcp",
        "--run-label", label, "--run-root", str(ROOT/"runs/brush2"),
        "--serial-port", args.serial_port, "--baud", str(args.baud), "--ip", args.ip,
        "--execute" if args.execute else "--dry-run"]
    # Preserve the existing RUN prompt, hardware checks, positioning and logs.
    return run_experiment(command, feedback_profile=profile)


if __name__ == "__main__":
    raise SystemExit(main())
