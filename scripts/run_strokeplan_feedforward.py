#!/usr/bin/env python3
"""Execute one StrokePlan with pure feedforward; input is only its .npz path.

Edit the site values below when the brush, calibration or connection changes.
The script validates inputs and waits for an explicit RUN before opening hardware.
"""
from __future__ import annotations

import argparse
from pathlib import Path

if __package__:
    from .run_strokeplan_experiment import main as run_experiment
else:
    from run_strokeplan_experiment import main as run_experiment


ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / 'runs/brush2/plans/ry15_rz0_suite_60_200_v1'
FEEDFORWARD = TRIAL / 'feedforward.json'
SETTINGS = TRIAL / 'settings.json'
SERIAL_PORT = '/dev/ttyACM0'
BAUD = 115200
ARM_IP = '192.168.0.10'
RUN_ROOT = ROOT / 'runs/brush2'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('strokeplan', type=Path, help='one target-only V3 .npz file')
    parser.add_argument('--dry-run', action='store_true', help='offline validation only')
    args = parser.parse_args(argv)
    return run_experiment([
        str(args.strokeplan), '--feedforward', str(FEEDFORWARD),
        '--settings', str(SETTINGS), '--serial-port', SERIAL_PORT,
        '--baud', str(BAUD), '--ip', ARM_IP, '--run-root', str(RUN_ROOT),
        '--run-label', 'strokeplan_ff_' + args.strokeplan.stem,
        '--control-mode', 'feedforward',
        '--dry-run' if args.dry_run else '--execute',
    ])


if __name__ == '__main__':
    raise SystemExit(main())
