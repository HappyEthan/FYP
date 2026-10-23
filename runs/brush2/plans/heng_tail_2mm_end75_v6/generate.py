#!/usr/bin/env python3
"""Offline local-tail variants: identical magnetic/time/pose references, end 75 uT."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / 'runs/brush2/plans/heng_80mm_hidden_tail_v5/heng/strokeplan.npz'
CONTEXT = ROOT / 'runs/brush2/plans/heng_pair_entry_load_then_rotate_v2/context'
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from brushbot.target_strokeplan import Stroke, StrokePlan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.strokeplan_character import orientation_heading
from brushbot.experiments.z_identification import _check_trajectory
from brushbot.feedforward import lookup_depth_m, require_execution_approval

PREVIEW = str(ROOT / 'scripts/preview_strokeplan.py')
VARIANTS = {'control75': 1., 'heng75': 4. / 3.}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def write_csv(path, rows):
    with Path(path).open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def arc(xy_mm):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy_mm, axis=0), axis=1))]


def smooth(u):
    u = np.clip(u, 0., 1.)
    return u**3 * (10. - 15.*u + 6.*u*u)


def build_variant(base, factor):
    old = base.strokes[0]
    old_xy = old.xy * 1000.
    old_arc = arc(old_xy)
    old_rows = base.meta['phase_control_points']
    transition_start = float(old_rows[-3]['distance_mm'])
    tail_start = float(old_rows[-2]['distance_mm'])
    anchor = np.array([180., 5.])
    weight = smooth((old_arc - transition_start) / (tail_start - transition_start))
    xy = old_xy.copy()
    changed = weight > 0.
    if factor != 1.:
        xy[changed] = anchor + (old_xy[changed] - anchor) * (
            1. + (factor - 1.) * weight[changed, None])
    # Freeze the entire earlier magnetic curve; only the final L2-to-end
    # transition changes. Both geometry variants have exactly the same G(t).
    tail = old_arc >= tail_start
    g = old.g_target.copy()
    g[tail] = old_rows[-2]['g_target_uT'] + (
        75. - old_rows[-2]['g_target_uT']) * smooth(
            (old_arc[tail] - tail_start) / (old_arc[-1] - tail_start))
    d = arc(xy)
    st = Stroke(d / d[-1], xy / 1000., old.t.copy(), g, old.orientation.copy())
    rows = []
    for index, original in enumerate(old_rows):
        t = float(np.interp(original['s'], old.s, old.t))
        distance = float(np.interp(t, st.t, d))
        row = copy.deepcopy(original)
        row.update(distance_mm=distance, s=distance / d[-1], writing_t_s=t)
        if index == len(old_rows) - 1:
            row.update(action='局部回收结束，75uT收束，随后抬笔', g_target_uT=75.)
        rows.append(row)
    recipe = dict(schema='heng-local-tail-affine-v1', source_target=str(SOURCE.relative_to(ROOT)),
        source_sha256=digest(SOURCE), tail_scale_factor=factor,
        affine_anchor_paper_mm=anchor.tolist(), terminal_target_uT=75., start_target_uT=100.,
        geometry_transition_start_t_s=float(np.interp(transition_start, old_arc, old.t)),
        tail_start_t_s=float(np.interp(tail_start, old_arc, old.t)),
        geometry_policy='quintic blend after body peak; full affine scale only in local finishing region',
        time_policy='copy all source times exactly',
        orientation_policy='copy body-derived source RPY exactly; do not follow enlarged return tangent')
    meta = copy.deepcopy(base.meta)
    meta.update(name='长横80mm：局部回收调整，末端75uT',
        description='主体不变；仅末端局部几何及终点磁目标调整，实写效果待验证。',
        source_target=str(SOURCE.relative_to(ROOT)), source_target_sha256=digest(SOURCE),
        previous_target_sha256=digest(SOURCE), generation_recipe=recipe,
        phase_control_points=rows,
        xy_source=recipe['geometry_policy'], time_source=recipe['time_policy'],
        orientation_source=recipe['orientation_policy'],
        g_target_source='user-requested synthetic terminal 75uT; earlier targets copied unchanged',
        validation='offline candidate; not measured force, width or verified ink coverage')
    plan = StrokePlan([st], meta)
    plan.validate()
    assert np.array_equal(st.xy[~changed], old.xy[~changed])
    assert np.array_equal(st.g_target[~tail], old.g_target[~tail])
    assert np.array_equal(st.t, old.t) and np.array_equal(st.orientation, old.orientation)
    assert st.g_target[0] == 100. and st.g_target[-1] == 75.
    assert st.t[-1] <= 20. and abs(np.ptp(st.xy[:, 0])*1000. - 80.) < .02
    return plan, rows, recipe


def main():
    if any(p.name not in {'generate.py', 'run.py', '__pycache__'} for p in OUT.iterdir()):
        raise FileExistsError('choose a new directory; never overwrite a candidate bundle')
    sources = [SOURCE] + [CONTEXT / name for name in (
        'feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json')]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    (OUT / 'context').mkdir()
    (OUT / 'preflight').mkdir()
    for p in sources[1:]:
        shutil.copy2(p, OUT / 'context' / p.name)
    table, setup, entry, pi = [json.loads((OUT / 'context' / name).read_text()) for name in (
        'feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json')]
    assert entry['entry_order'] == 'load_then_rotate'
    require_execution_approval(table, setup)
    base = StrokePlan.load(SOURCE)
    variants = {}
    summary = {}
    for name, factor in VARIANTS.items():
        plan, rows, recipe = build_variant(base, factor)
        folder = OUT / 'targets' / name
        folder.mkdir(parents=True)
        plan.save(folder / 'strokeplan.npz')
        plan = StrokePlan.load(folder / 'strokeplan.npz')
        st = plan.strokes[0]
        variants[name] = st
        write_json(folder / 'recipe.json', recipe)
        write_csv(folder / 'phase_table.csv', rows)
        c = compile_recorded_plan(plan, table, setup, label=name + '_tail_end75_v6_pi',
            control_mode='pi', feedback_profile=pi, entry_profile=entry)
        limits = _check_trajectory(c['pose_m_rad'], setup, entry)
        np.savez_compressed(OUT / 'preflight' / ('compiled_' + name + '_pi.npz'),
            **{key: c[key] for key in ('t_s', 's', 'phase', 'pose_m_rad', 'g_ref_uT', 'depth_ff_m')},
            artifact_role='derived_nominal_trajectory_not_measured_response_or_PI_commands')
        phases, poses = c['phase'], c['pose_m_rad']
        bounds = np.r_[0, np.flatnonzero(phases[1:] != phases[:-1]) + 1, len(phases)]
        stages = []
        for begin, end in zip(bounds[:-1], bounds[1:]):
            start = max(0, begin - 1)
            stages.append(dict(phase=str(phases[begin]), first_command_t_s=float(c['t_s'][begin]),
                last_command_t_s=float(c['t_s'][end-1]),
                elapsed_from_previous_phase_s=float(c['t_s'][end-1]-c['t_s'][start]),
                z_start_mm=float(poses[start, 2]*1000), z_end_mm=float(poses[end-1, 2]*1000),
                xy_travel_mm=float(np.linalg.norm(np.diff(poses[start:end, :2], axis=0), axis=1).sum()*1000),
                feedback_enabled=bool(phases[begin] == 'measure_00')))
        write_csv(folder / 'full_motion_phase_table.csv', stages)
        start_t = recipe['tail_start_t_s']
        xy = st.xy * 1000.
        local = np.vstack([[np.interp(start_t, st.t, xy[:, j]) for j in range(2)], xy[st.t > start_t]])
        length = float(arc(local)[-1])
        bbox = np.ptp(local, axis=0)
        assert length < 5. and np.all(bbox < 5.)
        heading = np.unwrap([orientation_heading(p) for p in st.orientation[st.t >= start_t]])
        speed = np.linalg.norm(np.diff(st.xy, axis=0), axis=1)/np.diff(st.t)*1000.
        summary[name] = dict(tail_scale_factor=factor, writing_duration_s=float(st.t[-1]),
            nominal_full_motion_duration_s=float(c['t_s'][-1]),
            target_range_uT=[float(st.g_target.min()), float(st.g_target.max())],
            start_target_uT=float(st.g_target[0]), terminal_target_uT=float(st.g_target[-1]),
            bbox_mm=np.ptp(xy, axis=0).tolist(), peak_xy_speed_mm_s=float(speed.max()),
            finishing=dict(start_t_s=start_t, duration_s=float(st.t[-1]-start_t), path_length_mm=length,
                bbox_mm=bbox.tolist(), x_return_mm=float(xy[:, 0].max()-xy[-1, 0]),
                tilt_azimuth_span_deg=float(np.rad2deg(np.ptp(heading)))),
            control=c['spec_snapshot']['control'], compiled_limits=limits,
            terminal_nominal_z_mm=float(poses[phases == 'measure_00'][-1, 2]*1000))
        result = subprocess.run([sys.executable, PREVIEW, str(folder / 'strokeplan.npz'),
            '--repo', str(ROOT), '--output-dir', str(folder / 'preview')], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        result = subprocess.run([sys.executable, str(OUT / 'run.py'), name, '--dry-run'],
            capture_output=True, text=True)
        (OUT / 'preflight' / (name + '_cli.txt')).write_text(result.stdout + '\n' + result.stderr)
        assert result.returncode == 0, result.stderr
    assert np.array_equal(variants['control75'].g_target, variants['heng75'].g_target)
    assert np.array_equal(variants['control75'].t, variants['heng75'].t)
    assert np.array_equal(variants['control75'].orientation, variants['heng75'].orientation)
    write_json(OUT / 'preflight_report.json', dict(variants=summary,
        source_sha256=hashes, entry_profile=entry,
        measured_feedforward_range_uT=[min(table['amplitude_uT']), max(table['amplitude_uT'])],
        terminal_margin_above_measured_lower_bound_uT=75.-min(table['amplitude_uT']),
        terminal_lookup_depth_mm=float(lookup_depth_m(table, np.array([75.]))[0]*1000),
        no_extrapolation_or_clipping=True, hardware_connected=False, execute_called=False,
        comparison='control75 and heng75 share exact G(t), time, RPY, entry and PI; only terminal XY differs'))
    assert hashes == {str(p.relative_to(ROOT)): digest(p) for p in sources}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
