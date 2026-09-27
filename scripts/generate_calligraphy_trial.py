#!/usr/bin/env python3
"""Offline 中 trial: template XY, explicitly synthetic contact, existing FF/PI."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.calligraphy.hanzi import load_medians, medians_to_strokes
from brushbot.target_strokeplan import Stroke, StrokePlan, FEATURE
from brushbot.strokeplan_compile import compile_target_plan
from brushbot.experiments.strokeplan_entry import STATIONARY_ENTRY
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_strokeplan import generate as generate_distance_law

ROOT = Path(__file__).resolve().parents[1]
GRAPHICS = ROOT/'data/makemeahanzi/graphics.txt'
SOURCE = ROOT/'runs/brush2/plans/08_短平台160到240回160_P与PI'
OUTPUT = ROOT/'runs/brush2/plans/10_中字原地进笔_快速转场'
STROKE_NAMES = ['左竖', '横折', '下横', '中竖']


def rounded_polyline(points, radius_mm=2.):
    """Trim at most 2 mm each side of a corner; quadratic tangent-continuous join.

    Endpoints and long straight spans are retained. No extrapolating spline.
    """
    points = np.asarray(points, float)
    out = [points[0]]
    for before, corner, after in zip(points, points[1:], points[2:]):
        incoming, outgoing = corner-before, after-corner
        li, lo = np.linalg.norm(incoming), np.linalg.norm(outgoing)
        trim = min(radius_mm/1000., li*.25, lo*.25)
        if trim <= 1e-12:
            raise ValueError('duplicate median vertices')
        start, end = corner-incoming/li*trim, corner+outgoing/lo*trim
        out.append(start)
        u = np.linspace(0., 1., 41)[1:, None]
        out.extend((1-u)**2*start + 2*(1-u)*u*corner + u**2*end)
    out.append(points[-1])
    return np.asarray(out)


def contact_profile(s, knots):
    """Quintic transitions in normalized arclength, with zero knot slope."""
    knots = np.asarray(knots, float)
    if np.any(np.diff(knots[:, 0]) <= 0):
        raise ValueError('contact anchors must be ordered')
    i = np.clip(np.searchsorted(knots[:, 0], s, side='right')-1, 0, len(knots)-2)
    u = np.clip((s-knots[i, 0])/(knots[i+1, 0]-knots[i, 0]), 0., 1.)
    w = u**3*(10.-15.*u+6.*u*u)
    return knots[i, 1]+(knots[i+1, 1]-knots[i, 1])*w


def generate_target(*, size_mm=180., speed_mm_s=10., graphics_path=GRAPHICS):
    if not np.isfinite(size_mm) or size_mm <= 0:
        raise ValueError('size must be positive')
    medians = load_medians('中', str(graphics_path))
    glyph = medians_to_strokes(medians, size=size_mm/1000.)
    strokes, anchors = [], []
    for index, points in enumerate(glyph):
        curve = rounded_polyline(points)
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))]
        # Reuse the existing target generator's start/stop time law.
        law = generate_distance_law(targets_uT=[160.], length_mm=arc[-1]*1000,
                                    speed_mm_s=speed_mm_s).strokes[0]
        xy = np.column_stack([np.interp(law.s*arc[-1], arc, curve[:, k]) for k in range(2)])
        measured_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        s = measured_arc/measured_arc[-1]
        if index == 0:
            knots = [(0.,160.),(.12,210.),(.30,185.),(.80,180.),(1.,130.)]
        elif index == 1:
            turn = float(s[np.argmax(xy[:, 0])])
            knots = [(0.,160.),(.10,210.),(.25,180.),
                     (turn-.12,180.),(turn,230.),(turn+.10,185.),(1.,130.)]
        elif index == 2:
            knots = [(0.,160.),(.12,205.),(.35,175.),(.72,175.),(.88,215.),(1.,140.)]
        else:
            knots = [(0.,160.),(.10,210.),(.25,185.),(.75,180.),(.87,165.),(1.,100.)]
        g = contact_profile(s, knots)
        # Paper origin is the established wait XY; the glyph centre is 140 mm to its right.
        xy += [.140, 0.]
        strokes.append(Stroke(s, xy, law.t, g))
        anchors.append(dict(stroke_index=index+1, name=STROKE_NAMES[index],
                            knots_s_uT=knots))
    plan = StrokePlan(strokes, dict(source='mixed', coordinate_frame='paper',
        feature=FEATURE, filter_definition=dict(kind='ema', alpha=.3),
        character='中', xy_source='Make Me a Hanzi medians with local quadratic corner rounding',
        stroke_order_source='Make Me a Hanzi record order',
        g_target_source='synthetic_calligraphy_heuristic',
        description='Template geometry; synthetic press/travel/turn/release targets, not measured force or width.',
        provenance=dict(path=str(Path(graphics_path).resolve()), character='中',
            median_sha256=hashlib.sha256(json.dumps(medians).encode()).hexdigest()),
        size_mm=size_mm, cruise_speed_mm_s=speed_mm_s,
        corner_trim_max_mm=2., glyph_center_paper_mm=[140.,0.], glyph_y_axis='up',
        contact_anchors=anchors))
    plan.validate()
    return plan


def generate(output: Path, *, source_dir=SOURCE, size_mm=180., speed_mm_s=10.):
    output, source_dir = Path(output), Path(source_dir)
    if output.exists():
        raise FileExistsError(f'refusing to replace trial: {output}')
    plan = generate_target(size_mm=size_mm, speed_mm_s=speed_mm_s)
    payloads = {n: (source_dir/n).read_bytes() for n in
                ('feedforward.json','settings.json','pi_profile.json')}
    table, setup, pi = [json.loads(payloads[n]) for n in payloads]
    # The source's approval was limited to its short-plateau experiment.
    # This package is an offline candidate, not a new site or hardware approval.
    table.update(approved=False, transient_approved=False,
        approval_scope=output.name+': offline candidate',
        approval_note='User requested XY direction-invariant assumption and no-slide entry; '
                      'generated and compiled offline; hardware trial not yet performed.')
    setup.update(max_xy_speed_mm_s=60., max_z_speed_mm_s=30., return_speed_mm_s=60.)
    entry = dict(STATIONARY_ENTRY, assume_direction_invariant=True,
                 transit_speed_mm_s=30., air_rotate_s=1.5,
                 angular_speed_deg_s=20., angular_accel_deg_s2=40.)
    full_poses, full_phases = compile_target_plan(plan, table, setup, assume_direction_invariant=True)
    parts, reports, compiled_parts = [], [], []
    for i, st in enumerate(plan.strokes, 1):
        part = StrokePlan([st], dict(copy.deepcopy(plan.meta), character_stroke_index=i))
        compiled = compile_recorded_plan(part, table, setup, label=f'zhong_{i:02}_pi',
                    control_mode='pi', feedback_profile=pi, entry_profile=entry)
        limits = _check_trajectory(compiled['pose_m_rad'], setup, entry)
        parts.append(part)
        compiled_parts.append(compiled)
        reports.append(dict(index=i, name=STROKE_NAMES[i-1],
            length_mm=float(np.linalg.norm(np.diff(st.xy,axis=0),axis=1).sum()*1000),
            measurement_s=float(st.t[-1]), total_trajectory_s=float(compiled['t_s'][-1]),
            g_range_uT=[float(st.g_target.min()),float(st.g_target.max())],
            nominal_z_range_mm=[float(compiled['pose_m_rad'][compiled['phase']=='measure_00',2].min()*1000),
                                float(compiled['pose_m_rad'][compiled['phase']=='measure_00',2].max()*1000)],
            compiled_limits=limits))
    report = dict(character='中', size_mm=size_mm, stroke_count=len(parts),
        assumption='same magnetic target maps to the same depth for every XY direction',
        source_calibration_support=dict(directions=table['directions'],speed_mm_s=table['speed_mm_s']),
        entry='Ry30 -> Z36 -> rotate in place to Ry15 -> load at fixed XY -> write',
        source_dir=str(source_dir), source_sha256={n:hashlib.sha256(b).hexdigest() for n,b in payloads.items()},
        wait_pose_mm_deg=[setup['origin_x_mm'],setup['origin_y_mm'],setup['wait_z_mm'],
                          *np.rad2deg(setup['vertical_rpy_rad']).tolist()],
        glyph_center_base_mm=[setup['origin_x_mm']+140.,setup['origin_y_mm']],
        validation='V3 reload and offline trajectory compilation; no hardware',
        strokes=reports,
        limitations=['Magnetic targets are heuristic, not recovered from the font or measured demonstrations.',
                     'Rounded corners approximate the sparse medians; no outline reconstruction is claimed.',
                     'Direction invariance and stationary loading are trial assumptions.',
                     'Endpoint targets stay inside the table; lift is a separate motion phase.',
                     'Each stroke is an independent recorded invocation, returning to the same wait pose.',
                     'Source approval is not inherited for this new hardware experiment.'])
    output.mkdir(parents=True)
    plan.save(output/'character.npz')
    StrokePlan.load(output/'character.npz')
    np.savez(output/'compiled_character_fixed_entry.npz', pose_m_rad=full_poses,
             phase=np.asarray(full_phases), artifact_role='offline_fixed_entry_geometry_check')
    for i, (part, compiled) in enumerate(zip(parts,compiled_parts), 1):
        part.save(output/f'stroke_{i:02}.npz')
        StrokePlan.load(output/f'stroke_{i:02}.npz')
        np.savez(output/f'compiled_stroke_{i:02}.npz', **{k:compiled[k] for k in
                 ('t_s','s','phase','pose_m_rad','g_ref_uT','depth_ff_m')},
                 artifact_role='derived_nominal_trajectory_not_feedback_commands')
    for name, value in [('feedforward.json',table),('settings.json',setup),
                        ('pi_profile.json',pi),('entry_profile.json',entry),('protocol.json',report)]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=OUTPUT)
    parser.add_argument('--size-mm',type=float,default=180.)
    parser.add_argument('--speed-mm-s',type=float,default=10.)
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir,size_mm=args.size_mm,speed_mm_s=args.speed_mm_s),
                     ensure_ascii=False,indent=2))
