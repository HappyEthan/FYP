#!/usr/bin/env python3
"""One-stroke end-75 trials; defaults to offline, with explicit Zhong PI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from scripts.run_strokeplan_experiment import main as run_experiment

PRESETS = {
    'heng75': ('长横80mm，局部回收宽约2mm，终点75uT', 'heng_80mm_tail2mm_end75_v6_pi'),
    'control75': ('几何对照：原约1.5mm小尾端，终点75uT', 'heng_80mm_tail1p5mm_end75_control_v6_pi'),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stroke', choices=PRESETS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    parser.add_argument('--serial-port', default='/dev/ttyACM0')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--ip', default='192.168.0.10')
    args = parser.parse_args(argv)
    description, label = PRESETS[args.stroke]
    context = PACKAGE / 'context'
    entry = json.loads((context / 'entry_profile.json').read_text())
    if entry.get('entry_order') != 'load_then_rotate':
        parser.error('this package requires load_then_rotate entry')
    print('所选版本：', description)
    print('起笔100uT；先30度加载至名义100对应高度，再反向5mm并转到15度；随后XY+原受限PI。')
    print('终点75uT直接在现表范围内查表；没有50版本替换、外推、目标裁剪或批准标志修改。')
    command = [str(PACKAGE / 'targets' / args.stroke / 'strokeplan.npz'),
        '--feedforward', str(context / 'feedforward.json'),
        '--settings', str(context / 'settings.json'),
        '--entry-profile', str(context / 'entry_profile.json'),
        '--control-mode', 'pi', '--record-actual-tcp', '--run-label', label,
        '--run-root', str(ROOT / 'runs/brush2'), '--serial-port', args.serial_port,
        '--baud', str(args.baud), '--ip', args.ip,
        '--execute' if args.execute else '--dry-run']
    return run_experiment(command, feedback_profile=json.loads((context / 'pi_profile.json').read_text()))


if __name__ == '__main__':
    raise SystemExit(main())
