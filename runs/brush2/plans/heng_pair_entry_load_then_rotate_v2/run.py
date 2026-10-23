#!/usr/bin/env python3
"""brush2: load at 30 degrees, then rotate at the workpoint before XY/PI."""
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
    'heng': ('长横v5，80mm，起笔/终点100uT', 'heng_80mm_end100_load_then_rotate_v2_pi'),
    'short100': ('短横旧版v1，40mm，起笔/终点100uT', 'heng_short_40mm_end100_load_then_rotate_v2_pi'),
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
        parser.error('this package requires entry_order=load_then_rotate')
    print('所选目标：', description)
    print('新下笔：保持30度，经Z36继续下降到首目标对应高度，再于该高度反向5mm并转至15度。')
    print('100uT对应高度来自15度旧表；30度和接触旋转的实际响应仍待试写验证。')
    print('仅书写阶段开启原受限PI；大于500uT的排除仅用于离线统计，没有改变在线处理。')
    command = [str(PACKAGE / 'targets' / args.stroke / 'strokeplan.npz'),
        '--feedforward', str(context / 'feedforward.json'),
        '--settings', str(context / 'settings.json'),
        '--entry-profile', str(context / 'entry_profile.json'),
        '--control-mode', 'pi', '--record-actual-tcp',
        '--run-label', label, '--run-root', str(ROOT / 'runs/brush2'),
        '--serial-port', args.serial_port, '--baud', str(args.baud), '--ip', args.ip,
        '--execute' if args.execute else '--dry-run']
    return run_experiment(command,
        feedback_profile=json.loads((context / 'pi_profile.json').read_text()))


if __name__ == '__main__':
    raise SystemExit(main())
