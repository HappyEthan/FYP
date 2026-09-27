#!/usr/bin/env python3
"""Shared 160/240/160 plateau target: existing P versus slow anti-windup PI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from .run_strokeplan_experiment import main as run_experiment
else:
    from run_strokeplan_experiment import main as run_experiment

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT/'runs/brush2/plans/08_短平台160到240回160_P与PI'
RUN_ROOT = ROOT/'runs/brush2'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['p', 'pi'], required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        profile = json.loads((TRIAL/(args.mode+'_profile.json')).read_text())
        condition = (f'{args.mode.upper()}_Kp{profile["kp"]:g}_Ki{profile["ki"]:g}'
                     f'_总修正{profile["max_correction_mm"]:g}mm')
        if args.mode == 'pi':
            condition += f'_积分{profile["integral_limit_mm"]:g}mm_抗饱和'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return run_experiment([
        str(TRIAL/'plateau_160_240_160.npz'),
        '--feedforward', str(TRIAL/'feedforward.json'),
        '--settings', str(TRIAL/'settings.json'),
        '--entry-profile', str(TRIAL/'entry_profile.json'),
        '--control-mode', args.mode,
        '--serial-port', '/dev/ttyACM0', '--baud', '115200', '--ip', '192.168.0.10',
        '--run-root', str(RUN_ROOT), '--run-label', 'short_plateau_'+args.mode,
        '--experiment-folder', '08_短平台P与PI对比',
        '--run-folder-label', '平台160到240回160_'+condition,
        '--record-actual-tcp', '--execute' if args.execute else '--dry-run',
    ], feedback_profile=profile)


if __name__ == '__main__':
    raise SystemExit(main())
