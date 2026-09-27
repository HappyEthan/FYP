#!/usr/bin/env python3
"""Paper-shape trial: wider left stroke, shorter head and terminal overlap."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.target_strokeplan import Stroke, StrokePlan
from brushbot.feedforward import lookup_depth_m
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_directional_character_trial import directional_stroke
from scripts.generate_zhong_refined_trial import smooth

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runs/brush2/2026-09-25/11_中字连续方向姿态/raw/20-23-08_中_整字_方向姿态_pi_第3次'
OUTPUT = ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'


def arc_mm(xy):
    return np.r_[0.,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]*1000


def retime(xy, g):
    arc = arc_mm(xy)
    keep = np.r_[True,np.diff(arc)>1e-8]
    xy, g, arc = xy[keep],g[keep],arc[keep]
    return directional_stroke(Stroke(arc/arc[-1],xy,arc/10.,g))


def extend_tail(st, distance_mm=10., trim_start_mm=0.):
    arc = arc_mm(st.xy)
    d = np.linspace(trim_start_mm,arc[-1],max(2,int(np.ceil((arc[-1]-trim_start_mm)/.1))+1))
    xy = np.column_stack([np.interp(d,arc,st.xy[:,j]) for j in range(2)])
    g = np.interp(d,arc,st.g_target)
    if trim_start_mm:
        g = 100.+smooth((d-trim_start_mm)/15.)*(g-100.)
    # Avoid lifting early at the former endpoint, which lies inside the overlap.
    w = smooth((d-(arc[-1]-15.))/15.)
    g = (1.-w)*g+w*160.
    tangent = st.xy[-1]-np.array([np.interp(arc[-1]-2.,arc,st.xy[:,j]) for j in range(2)])
    tangent /= np.linalg.norm(tangent)
    extension = np.linspace(0.,distance_mm,int(np.ceil(distance_mm/.1))+1)[1:]
    xy = np.vstack([xy,xy[-1]+extension[:,None]/1000*tangent])
    g = np.r_[g,np.full(len(extension),160.)]
    return retime(xy,g)


def straighten_right_side(st):
    """Keep the upper turn, then hold X at its rightmost value through descent."""
    xy = st.xy.copy()
    turn = int(np.argmax(xy[:,0]))
    if turn == len(xy)-1 or np.any(np.diff(xy[turn:,1])>1e-9):
        raise ValueError('right side must descend after its rightmost turn')
    xy[turn:,0] = xy[turn,0]
    return retime(xy,st.g_target.copy())


def generate(output=OUTPUT, *, third_start_trim_mm=11., tail_extension_mm=15.,
             third_tail_extension_mm=30.):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'refusing to replace trial: {output}')
    original = StrokePlan.load(SOURCE/'strokeplan.npz')
    if not np.isfinite(third_start_trim_mm) or not 0. < third_start_trim_mm < arc_mm(original.strokes[2].xy)[-1]:
        raise ValueError('third start trim must be positive and shorter than the stroke')
    if not np.isfinite(tail_extension_mm) or tail_extension_mm <= 0.:
        raise ValueError('tail extension must be finite and positive')
    if not np.isfinite(third_tail_extension_mm) or third_tail_extension_mm <= 0.:
        raise ValueError('third tail extension must be finite and positive')
    plan = copy.deepcopy(original)
    table = json.loads((SOURCE/'feedforward.json').read_text())
    setup = json.loads((SOURCE/'settings.json').read_text())
    entry = json.loads((SOURCE/'entry_profile.json').read_text())
    control = json.loads((SOURCE/'resolved.json').read_text())['control']
    pi = {k:control[k] for k in ('kp','ki','max_correction_mm','max_correction_speed_mm_s',
                                'max_correction_accel_mm_s2','taper_ticks','integral_limit_mm','anti_windup')}
    pi['ki'] = .1
    first = plan.strokes[0]
    arc = arc_mm(first.xy)
    before = first.g_target.copy()
    first.g_target += 20.*smooth(arc/15.)*smooth((arc[-1]-arc)/10.)
    body = (arc>=15.)&(arc<=arc[-1]-10.)
    extra = (lookup_depth_m(table,first.g_target)-lookup_depth_m(table,before))*1000
    plan.strokes[1] = straighten_right_side(extend_tail(original.strokes[1],distance_mm=tail_extension_mm))
    plan.strokes[2] = extend_tail(original.strokes[2],distance_mm=third_tail_extension_mm,
                                 trim_start_mm=third_start_trim_mm)
    # Replace the first 20 mm of template travel by a near-vertical head.
    fourth = original.strokes[3]
    arc = arc_mm(fourth.xy)
    join = np.array([np.interp(20.,arc,fourth.xy[:,j]) for j in range(2)])
    start = np.array([join[0]-.002,fourth.xy[0,1]])
    u = np.linspace(0.,1.,151)
    head = start+(join-start)*u[:,None]
    rest = arc>20.+1e-8
    xy = np.vstack([head,fourth.xy[rest]])
    g = np.r_[np.interp(u*20.,arc,fourth.g_target),fourth.g_target[rest]]
    new_arc = arc_mm(xy)
    g = 100.+smooth(new_arc/15.)*(g-100.)
    plan.strokes[3] = retime(xy,g)
    plan.meta.update(
        source_target_sha256=hashlib.sha256((SOURCE/'strokeplan.npz').read_bytes()).hexdigest(),
        refinement_evidence_run='20260925T122308.819284Z-14ec9e',
        xy_source=f'V6 trial revision: stroke 2 holds X at rightmost turn during descent, keeping the ending Y of the {tail_extension_mm:g} mm tail extension; stroke 3 tail extends {third_tail_extension_mm:g} mm and starts {third_start_trim_mm:g} mm forward; stroke 4 replaces initial 20 mm travel with a head spanning 2 mm in X',
        g_target_source='synthetic revision: stroke 1 adds 20 uT in body; stroke 2/3 tails retain 160 uT through extensions; strokes 3/4 retain gentle 100 uT start',
    )
    table.update(approval_scope=output.name+': user-requested straight right descent and longer lower horizontal',
                 approval_note='User requested another 5 mm extension of stroke 3 after V10, bringing total extension to 30 mm relative to the source trajectory. Existing direction/pose-invariant table assumption remains experimental; no width calibration or hardware validation claimed. Operator RUN required.')
    compiled = compile_recorded_plan(plan,table,setup,label='zhong_shape_pi',control_mode='pi',
                                    feedback_profile=pi,entry_profile=entry)
    report = dict(character='中',source_run=str(SOURCE),control=pi,
        validation='offline compilation only; terminal extensions are an empirical overlap trial, not a calibrated brush-tip offset',
        duration_s=float(compiled['t_s'][-1]),compiled_limits=_check_trajectory(compiled['pose_m_rad'],setup,entry),
        first_body_extra_target_uT=20.,first_body_equivalent_extra_depth_mm_range=[float(extra[body].min()),float(extra[body].max())],
        stroke2_end_y_reference_extension_mm=tail_extension_mm,
        stroke2_right_descent_x_paper_mm=float(plan.strokes[1].xy[-1,0]*1000),
        stroke2_end_y_paper_mm=float(plan.strokes[1].xy[-1,1]*1000),
        stroke3_tail_extension_mm=third_tail_extension_mm,terminal_target_uT=160.,
        stroke3_start_trim_mm=third_start_trim_mm,stroke4_head_x_span_mm=2.,entry_policy=entry)
    output.mkdir(parents=True)
    plan.save(output/'character.npz');StrokePlan.load(output/'character.npz')
    for i,st in enumerate(plan.strokes,1):
        StrokePlan([st],dict(plan.meta,character_stroke_index=i)).save(output/f'stroke_{i:02}.npz')
    np.savez(output/'compiled_character.npz',**{k:compiled[k] for k in
             ('t_s','s','phase','pose_m_rad','g_ref_uT','depth_ff_m')},
             artifact_role='derived_nominal_trajectory_not_feedback_commands')
    for name,value in [('feedforward.json',table),('settings.json',setup),('pi_profile.json',pi),
                       ('entry_profile.json',entry),('protocol.json',report)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    print(json.dumps(generate(),ensure_ascii=False,indent=2))
