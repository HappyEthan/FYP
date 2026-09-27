#!/usr/bin/env python3
"""One shared difficult path, nonlinear FF versus bounded P. Offline by default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from .run_strokeplan_experiment import main as run_experiment
else:
    from run_strokeplan_experiment import main as run_experiment

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT/'runs/brush2/plans/06_难曲线160到240_FF与P'
RUN_ROOT = ROOT/'runs/brush2'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['ff','p'], required=True)
    parser.add_argument('--kp', type=float, help='P gain override; starts a named parameter-scan run')
    parser.add_argument('--max-correction-mm', type=float, help='symmetric P depth correction cap in mm')
    parser.add_argument('--p-dynamics', choices=['legacy','smooth'],
                        help='smooth: 2 mm/s, 30 mm/s², 1 s taper; legacy: trial JSON values')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    scan = any(value is not None for value in
               (args.kp, args.max_correction_mm, args.p_dynamics))
    if scan and args.mode != 'p':
        parser.error('P scan options require --mode p')
    profile = json.loads((TRIAL/'p_profile.json').read_text()) if args.mode == 'p' else None
    if profile is not None:
        if args.p_dynamics == 'smooth':
            profile.update(max_correction_speed_mm_s=2., max_correction_accel_mm_s2=30.,
                           taper_ticks=50)
        if args.kp is not None:
            profile['kp'] = args.kp
        if args.max_correction_mm is not None:
            profile['max_correction_mm'] = args.max_correction_mm
    condition = '纯前馈' if profile is None else f'前馈加P{profile["kp"]:g}_修正{profile["max_correction_mm"]:g}mm'
    if scan:
        dynamics = '平滑' if args.p_dynamics == 'smooth' else '原动态'
        condition += (f'_{dynamics}_渐变{profile["taper_ticks"]*.02:g}s'
                      f'_速度{profile["max_correction_speed_mm_s"]:g}'
                      f'_加速度{profile["max_correction_accel_mm_s2"]:g}')
    return run_experiment([
        str(TRIAL/'hard_160_240.npz'),
        '--feedforward',str(TRIAL/'feedforward.json'),
        '--settings',str(TRIAL/'settings.json'),
        '--entry-profile',str(TRIAL/'entry_profile.json'),
        '--control-mode','feedforward' if args.mode == 'ff' else 'p',
        '--serial-port','/dev/ttyACM0','--baud','115200','--ip','192.168.0.10',
        '--run-root',str(RUN_ROOT),
        '--run-label','nonlinear_hard_'+args.mode+('_scan' if scan else ''),
        '--experiment-folder',('07_非线性前馈P参数扫描' if scan else '06_非线性前馈难曲线对比'),
        '--run-folder-label','难曲线160到240_'+condition,
        '--record-actual-tcp',
        '--execute' if args.execute else '--dry-run',
    ], feedback_profile=profile)


if __name__ == '__main__':
    raise SystemExit(main())
