#!/usr/bin/env python3
"""Six manually started short-platform trials varying only Ki. Offline by default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from .run_strokeplan_experiment import main as run_experiment
else:
    from run_strokeplan_experiment import main as run_experiment

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT/'runs/brush2/plans/09_短平台Ki扫描'
RUN_ROOT = ROOT/'runs/brush2'
SEQUENCE = (.05, .025, .1, .1, .025, .05)
FIXED_PROFILE = dict(kp=1., max_correction_mm=.8,
    max_correction_speed_mm_s=2., max_correction_accel_mm_s2=30.,
    taper_ticks=50, integral_limit_mm=.2, anti_windup='conditional')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--step', required=True, type=int, choices=range(1,7),
                        help='1..6 selects Ki=0.05,0.025,0.1,0.1,0.025,0.05')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    ki = SEQUENCE[args.step-1]
    try:
        protocol = json.loads((TRIAL/'protocol.json').read_text())
        if protocol['ki_sequence'] != list(SEQUENCE):
            raise ValueError('Ki scan protocol sequence differs from the frozen design')
        profile = json.loads((TRIAL/f'pi_ki_{ki:g}.json').read_text())
        if profile != dict(FIXED_PROFILE, ki=ki):
            raise ValueError('Ki scan profile differs from the frozen gain or common limits')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f'Ki 参数扫描：第 {args.step}/6 笔，Ki={ki:g}；单笔手动启动。')
    print('本批顺序：0.05 → 0.025 → 0.10 → 0.10 → 0.025 → 0.05；每笔结束重新准备。')
    return run_experiment([
        str(TRIAL/'plateau_160_240_160.npz'),
        '--feedforward', str(TRIAL/'feedforward.json'),
        '--settings', str(TRIAL/'settings.json'),
        '--entry-profile', str(TRIAL/'entry_profile.json'),
        '--control-mode', 'pi',
        '--serial-port', '/dev/ttyACM0', '--baud', '115200', '--ip', '192.168.0.10',
        '--run-root', str(RUN_ROOT), '--run-label', f'short_ki_scan_step{args.step}_ki{ki:g}',
        '--experiment-folder', '09_短平台Ki参数扫描',
        '--run-folder-label', f'平台160到240回160_PI_Kp1_Ki{ki:g}_总修正0.8mm_积分0.2mm',
        '--record-actual-tcp', '--execute' if args.execute else '--dry-run',
    ], feedback_profile=profile)


if __name__ == '__main__':
    raise SystemExit(main())
