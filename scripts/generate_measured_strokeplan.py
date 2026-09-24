#!/usr/bin/env python3
"""Offline candidate feedforward from complete ladder passes; no hardware imports."""
import argparse
import json
from pathlib import Path

import numpy as np
from brushbot.strokeplan import Stroke, StrokePlan

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = [
    ROOT / 'runs/2026-09-21/19-24-32__repeat_02_part5_ry15__7f07d3',
    ROOT / 'runs/2026-09-21/19-38-37__repeat_02_part5_ry15__1cf55a',
]
OUTPUT = ROOT / 'runs/plans/ry15_reference.npz'
# 改成 [起点目标, 中间目标, 终点目标] 可生成缓变目标；None 使用实测幅值范围中点。
TARGETS_UT = None


def extract_reference(run_dirs):
    setup = None
    passes = []
    for folder in map(Path, run_dirs):
        current = json.loads((folder / 'setup.json').read_text())
        spec = json.loads((folder / 'resolved.json').read_text())
        manifest = json.loads((folder / 'manifest.json').read_text())
        if manifest['status'] not in ('completed', 'fault', 'aborted', 'interrupted'):
            raise ValueError('source run is still running')
        if spec['path']['axis'] != '+x' or spec['motion']['speed_mm_s'] != 10:
            raise ValueError('reference must be +X at 10 mm/s')
        if setup is None:
            setup = current
        for key in ('vertical_rpy_rad', 'contact_z_mm', 'filter', 'sensor_mount_id',
                    'tool_coord_si', 'user_coord_si', 'tcp_name', 'ucs_name',
                    'origin_x_mm', 'origin_y_mm'):
            if key == 'vertical_rpy_rad':
                matches = np.allclose(setup[key], current[key], atol=np.deg2rad(.1), rtol=0)
            else:
                matches = setup[key] == current[key]
            if not matches:
                raise ValueError(f'incompatible reference context: {key}')
        groups = {}
        for line in (folder / 'control.jsonl').read_text().splitlines():
            row = json.loads(line)
            if row.get('phase', '').startswith('measure_'):
                groups.setdefault(row['phase'], []).append(row)
        for phase, rows in groups.items():
            x = np.array([r['x_cmd_m'] * 1000 for r in rows])
            z = np.array([r['z_cmd_m'] * 1000 for r in rows])
            a = np.array([r['a_control_uT'] for r in rows])
            travel = float(spec['path']['travel_mm'])
            if x.max() - x.min() < .99 * travel:
                continue
            if not np.isfinite(np.r_[x, z, a]).all() or np.ptp(z) > .01:
                raise ValueError('invalid reference pass')
            age = np.array([r.get('sample_age_s', 0.) for r in rows])
            mask = ((x-x[0] >= 30) & (x-x[0] <= 170)
                    & np.isfinite(age) & (age >= 0)
                    & (age <= current.get('sensor_max_age_s', .1)))
            if mask.sum() < 50:
                continue
            passes.append(dict(run_id=manifest['run_id'], phase=phase,
                               z_mm=float(np.median(z)), amplitude_uT=float(np.median(a[mask]))))
    if not passes:
        raise ValueError('no complete reference passes')
    zs = sorted({p['z_mm'] for p in passes}, reverse=True)
    amplitudes = np.array([np.median([p['amplitude_uT'] for p in passes if p['z_mm']==z]) for z in zs])
    if len(zs) < 2 or np.any(np.diff(amplitudes) <= 0):
        raise ValueError('reference amplitudes must increase strictly with depth')
    return setup, passes, zs, amplitudes


def generate(run_dirs, targets=None):
    """Legacy V2 API. New code should use the independent V3 tools."""
    setup, passes, zs, amplitudes = extract_reference(run_dirs)
    targets = np.asarray(targets if targets is not None else [np.mean(amplitudes[[0,-1]])], float)
    if targets.ndim != 1 or not len(targets) or not np.isfinite(targets).all():
        raise ValueError('targets must be a finite nonempty list')
    if targets.min() < amplitudes[0] or targets.max() > amplitudes[-1]:
        raise ValueError('target outside measured range; extrapolation disabled')
    s = np.linspace(0, 1, 401)
    g = np.interp(s, np.linspace(0, 1, len(targets)), targets)
    depth = setup['contact_z_mm'] - np.array(zs)
    xy = np.column_stack((setup['origin_x_mm'] + s*200, np.full(len(s), setup['origin_y_mm']))) / 1000
    table = dict(depth_mm=depth.tolist(), amplitude_uT=amplitudes.tolist(),
                 approved=False, feature='filtered_dBxy_norm_uT', passes=passes,
                 stable_window_mm=[30,170], source_runs=[str(Path(p).resolve()) for p in run_dirs])
    return StrokePlan([Stroke(s, xy, g, np.interp(g, amplitudes, depth)/1000)], meta=dict(
        generation='measured_candidate_feedforward', reference_table=table, setup=setup,
        orientation_rpy_rad=setup['vertical_rpy_rad'], speed_mm_s=10.,
        stroke_durations_s=[20.], execution='open_loop', wetting='manual_before_execution'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', nargs='+', default=DEFAULT_RUNS)
    parser.add_argument('--targets-ut', nargs='+', type=float, default=TARGETS_UT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--legacy-v2', action='store_true', help='explicitly create old embedded-Z format')
    args = parser.parse_args()
    if not args.legacy_v2:
        parser.error('legacy generator: use generate_strokeplan.py + build_feedforward_table.py; or --legacy-v2')
    plan = generate(args.runs, args.targets_ut)
    if args.output.suffix != '.npz':
        parser.error('--output must end in .npz')
    if args.output.exists() or args.output.with_suffix('.json').exists():
        parser.error('output exists; choose another --output')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    plan.save(args.output)
    args.output.with_suffix('.json').write_text(json.dumps(plan.meta, ensure_ascii=False, indent=2)+'\n')
    print(f'Saved {args.output}; candidate table: {plan.meta["reference_table"]["amplitude_uT"]} uT')


if __name__ == '__main__':
    main()
