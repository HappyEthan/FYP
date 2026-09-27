#!/usr/bin/env python3
"""Execute one StrokePlan with bounded measure-only P Z feedback.

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
TARGET_NAMES = {
    '01_gradual_press': '渐进压笔',
    '02_single_arch': '单拱',
    '03_double_wave': '双波',
    '04_smooth_levels_wide_transitions': '宽过渡',
}
PROFILE = {
    'kp': 2.0,
    'ki': 0.0,  # First-stage trial is P-only; the runner rejects nonzero ki.
    'max_correction_mm': 0.4,
    'max_correction_speed_mm_s': 5.0,
    'max_correction_accel_mm_s2': 70.0,
    'taper_ticks': 25,
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('strokeplan', type=Path, help='one target-only V3 .npz file')
    parser.add_argument('--dry-run', action='store_true', help='offline validation only')
    parser.add_argument('--record-actual-tcp', action='store_true',
                        help='record actual TCP at 10 Hz on an independent connection')
    args = parser.parse_args(argv)
    bounds = (PROFILE['max_correction_mm'], PROFILE['max_correction_speed_mm_s'],
              PROFILE['max_correction_accel_mm_s2'])
    fmt = lambda value: f'{value:g}'.replace('.', 'p')
    target_name = TARGET_NAMES.get(args.strokeplan.stem, args.strokeplan.stem)
    if bounds == (0.2, 2.0, 40.0):
        experiment_folder = '02_P反馈与增益扫描'
        folder_label = f'{target_name}_P{fmt(PROFILE["kp"])}'
        run_label = 'strokeplan_p_gain_' + args.strokeplan.stem
    elif PROFILE['kp'] == 2.0:
        experiment_folder = '03_P2修正上限'
        folder_label = (f'{target_name}_P2_修正{fmt(bounds[0])}mm_'
                        f'速度{fmt(bounds[1])}_加速度{fmt(bounds[2])}')
        run_label = 'strokeplan_p_limits_' + args.strokeplan.stem
    else:
        experiment_folder = '04_P反馈参数组合'
        folder_label = (f'{target_name}_P{fmt(PROFILE["kp"])}_修正{fmt(bounds[0])}mm_'
                        f'速度{fmt(bounds[1])}_加速度{fmt(bounds[2])}')
        run_label = 'strokeplan_p_mixed_' + args.strokeplan.stem
    return run_experiment([
        str(args.strokeplan), '--feedforward', str(FEEDFORWARD),
        '--settings', str(SETTINGS), '--serial-port', SERIAL_PORT,
        '--baud', str(BAUD), '--ip', ARM_IP, '--run-root', str(RUN_ROOT),
        '--run-label', run_label,
        '--experiment-folder', experiment_folder,
        '--run-folder-label', folder_label,
        '--control-mode', 'p',
        *(['--record-actual-tcp'] if args.record_actual_tcp else []),
        '--dry-run' if args.dry_run else '--execute',
    ], feedback_profile=PROFILE)


if __name__ == '__main__':
    raise SystemExit(main())
