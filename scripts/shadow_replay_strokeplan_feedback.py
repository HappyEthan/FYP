"""Replay logged EMA observations through bounded P commands without an arm/plant.

This is a command-boundary check.  Historical observations cannot predict the
magnetic response to the counterfactual Z commands produced here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.strokeplan_feedback import StrokePlanPFeedback
from brushbot.target_strokeplan import StrokePlan


def replay_run(run_dir: Path):
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir/'manifest.json').read_text())
    if manifest['status'] != 'completed':
        raise ValueError('shadow replay requires a completed source run')
    resolved_bytes = (run_dir/'resolved.json').read_bytes()
    if hashlib.sha256(resolved_bytes).hexdigest() != manifest['sha256']['resolved.json']:
        raise ValueError('source snapshot hash differs: resolved.json')
    if json.loads(resolved_bytes)['control']['enabled']:
        raise ValueError('shadow replay requires a pure feedforward source run')
    inputs = {}
    for name in ('strokeplan.npz', 'feedforward.json', 'settings.json', 'timeline.npz'):
        data = (run_dir/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest['sha256'][name]:
            raise ValueError('source snapshot hash differs: ' + name)
        inputs[name] = data
    plan = StrokePlan.load(io.BytesIO(inputs['strokeplan.npz']))
    table = json.loads(inputs['feedforward.json'])
    setup = json.loads(inputs['settings.json'])
    current = compile_recorded_plan(plan, table, setup, label='shadow_check',
                                    control_mode='p')
    with np.load(io.BytesIO(inputs['timeline.npz']), allow_pickle=False) as stored:
        for key in ('t_s', 'pose_m_rad', 'g_ref_uT', 'depth_ff_m'):
            if not np.allclose(stored[key], current[key], atol=1e-10,
                               rtol=0, equal_nan=True):
                raise ValueError('stored timeline differs from current compiler: ' + key)
        if not np.array_equal(stored['phase'], current['phase']):
            raise ValueError('stored phases differ from current compiler')
    original = [json.loads(line) for line in (run_dir/'control.jsonl').read_text().splitlines()]
    observations = {}
    for row in original:
        tick = round(float(row['t_s'])/.02)
        if not np.isclose(row['t_s'], current['t_s'][tick], atol=1e-9, rtol=0):
            raise ValueError('logged tick is not on the 20 ms timeline')
        observations[tick] = row  # a repeated tick keeps its last recorded observation
    if 0 not in observations and current['phase'][0] == 'wait' and 1 in observations:
        # The fake runner may enter RUN on the first scheduled 20 ms tick.
        # The missing initial wait command has no feedback target.
        observations[0] = observations[1]
    if set(observations) != set(range(len(current['t_s']))):
        raise ValueError('a control observation is missing from the source timeline')
    phases = current['phase']
    total_measure = int(np.count_nonzero(phases == 'measure_00'))
    feedback = StrokePlanPFeedback(table, setup, .02, measure_ticks=total_measure)
    feedback.reset(current['pose_m_rad'][0])
    measure_tick = 0
    rows = []
    for tick, phase in enumerate(phases):
        source = observations[tick]
        target = (float(current['g_ref_uT'][tick]) if phase == 'measure_00' else None)
        if target is not None:
            if source['a_ref_uT'] is None or not np.isclose(
                    source['a_ref_uT'], target, atol=1e-9, rtol=0):
                raise ValueError('logged target differs from compiled StrokePlan')
            if not np.isclose(source['depth_ff_m'], current['depth_ff_m'][tick],
                              atol=1e-9, rtol=0):
                raise ValueError('logged feedforward differs from compiled trajectory')
        measured = float(source['a_control_uT'])
        if not np.isfinite(measured):
            raise ValueError('nonfinite recorded EMA observation')
        command, correction, limits = feedback.command(
            measure_tick if target is not None else -1,
            current['pose_m_rad'][tick],
            depth_ff_m=float(current['depth_ff_m'][tick]),
            a_ref_uT=target, a_control_uT=measured)
        if target is not None:
            measure_tick += 1
        rows.append({
            'tick': tick, 't_s': float(current['t_s'][tick]), 'phase': str(phase),
            'a_ref_uT': target, 'a_control_uT': measured,
            'e_center_uT': None if target is None else target-measured,
            'depth_ff_m': float(current['depth_ff_m'][tick]),
            'depth_fb_m': correction,
            'x_cmd_m': float(command[0]), 'y_cmd_m': float(command[1]),
            'z_ff_m': float(current['pose_m_rad'][tick, 2]),
            'z_cmd_m': float(command[2]),
            'limit_active': bool(limits), 'limit_reasons': '|'.join(limits),
        })
    nonwriting_changes = sum(
        abs(row['z_cmd_m']-row['z_ff_m']) > 1e-12
        for row in rows if row['phase'] != 'measure_00')
    if feedback.calls != total_measure or nonwriting_changes:
        raise ValueError('feedback phase gate or nonwriting command changed')
    xyz = np.asarray([[row['x_cmd_m'], row['y_cmd_m'], row['z_cmd_m']]
                      for row in rows], dtype=float)
    steps = np.diff(xyz, axis=0)
    velocities = np.diff(np.vstack([xyz[0], xyz, xyz[-1]]), axis=0) / .02
    accelerations = np.diff(velocities, axis=0) / .02
    summary = {
        'source_run': str(run_dir), 'source_run_id': manifest['run_id'],
        'status': 'boundary_valid', 'control_ticks': len(rows),
        'feedback_ticks': feedback.calls,
        'nonwriting_command_changes': nonwriting_changes,
        'limit_ticks': sum(row['limit_active'] for row in rows),
        'max_abs_feedback_mm': max(abs(row['depth_fb_m']) for row in rows)*1000.,
        'max_depth_mm': max(0., float(setup['contact_z_mm']) - min(row['z_cmd_m'] for row in rows)*1000.),
        'max_step_mm': float(np.linalg.norm(steps, axis=1).max()*1000.),
        'max_z_speed_mm_s': float(np.abs(velocities[:, 2]).max()*1000.),
        'max_accel_mm_s2': float(np.linalg.norm(accelerations, axis=1).max()*1000.),
        'min_z_cmd_mm': min(row['z_cmd_m'] for row in rows)*1000.,
        'max_z_cmd_mm': max(row['z_cmd_m'] for row in rows)*1000.,
    }
    return summary, rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_day', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    runs = sorted(p for p in args.run_day.iterdir() if (p/'manifest.json').is_file()
                  and json.loads((p/'manifest.json').read_text()).get('status') == 'completed')
    if not runs:
        parser.error('no completed runs found')
    results = [replay_run(path) for path in runs]
    args.output.mkdir(parents=True, exist_ok=False)
    for (summary, rows), path in zip(results, runs):
        with (args.output/(path.name+'.csv')).open('x', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    payload = {
        'method': 'Recorded EMA observations drive counterfactual bounded P commands '
                  'on the full 20 ms compiled timeline. Duplicate logged ticks use their '
                  'last observation; an unlogged initial wait tick uses the first '
                  'observation. No plant or sensor response is simulated.',
        'interpretation': 'Validates algorithm and command bounds only; it does not '
                          'estimate closed-loop tracking improvement.',
        'runs': [summary for summary, _ in results],
    }
    (args.output/'summary.json').write_text(json.dumps(payload, indent=2)+'\n')
    print(f'{len(results)} shadow replays: boundary valid; output: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
