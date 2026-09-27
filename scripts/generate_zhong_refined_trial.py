#!/usr/bin/env python3
"""Generate connected 中 geometry and gentler entry from the recorded V5 trial."""
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

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runs/brush2/2026-09-25/11_中字连续方向姿态/raw/20-07-15_中_整字_方向姿态_pi_第2次'
OUTPUT = ROOT/'runs/brush2/plans/11_中字连接优化_柔和起笔'


def smooth(u):
    u = np.clip(u, 0., 1.)
    return u**3*(10.-15.*u+6.*u*u)


def nearest_on_polyline(point, xy):
    delta = np.diff(xy, axis=0)
    length2 = np.sum(delta*delta, axis=1)
    valid = length2 > 1e-20
    start, delta, length2 = xy[:-1][valid], delta[valid], length2[valid]
    u = np.clip(np.sum((point-start)*delta, axis=1)/length2, 0., 1.)
    projected = start+u[:,None]*delta
    return projected[np.argmin(np.linalg.norm(projected-point, axis=1))]


def generate(output=OUTPUT):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'refusing to replace trial: {output}')
    original = StrokePlan.load(SOURCE/'strokeplan.npz')
    plan = copy.deepcopy(original)
    # Centerline connectivity is explicit; no inference of ink width is needed.
    left = nearest_on_polyline(plan.strokes[2].xy[0], plan.strokes[0].xy)
    right = plan.strokes[1].xy[-1].copy()
    s = np.linspace(0., 1., 1001)
    xy = left+(right-left)*s[:,None]
    old_third = plan.strokes[2]
    third = Stroke(s, xy, s*np.linalg.norm(right-left)/.01,
                   np.interp(s, old_third.s, old_third.g_target))
    plan.strokes[2] = directional_stroke(third)
    adjustments = []
    table = json.loads((SOURCE/'feedforward.json').read_text())
    for i in (0, 2, 3):
        st = plan.strokes[i]
        arc_mm = np.r_[0., np.cumsum(np.linalg.norm(np.diff(st.xy,axis=0),axis=1))]*1000
        old_g = st.g_target.copy()
        entry_weight = smooth(arc_mm/15.)
        # Lower only the start; the target reaches the previous profile at 15 mm.
        st.g_target = 100.+entry_weight*(old_g-100.)
        boost = np.zeros_like(old_g)
        if i in (0, 3):
            boost = 12.*entry_weight*smooth((arc_mm[-1]-arc_mm)/10.)
            st.g_target += boost
        body = (arc_mm >= 15.) & (arc_mm <= arc_mm[-1]-10.)
        equivalent = (lookup_depth_m(table,old_g+boost)-lookup_depth_m(table,old_g))*1000
        adjustments.append(dict(stroke=i+1, initial_target_uT=float(st.g_target[0]),
            entry_ramp_mm=15., body_target_increase_uT=12. if i in (0,3) else 0.,
            body_nominal_extra_depth_mm_range=[float(equivalent[body].min()),float(equivalent[body].max())]))
    plan.meta.update(
        source_target_sha256=hashlib.sha256((SOURCE/'strokeplan.npz').read_bytes()).hexdigest(),
        xy_source='V5 strokes 1/2/4 retained; stroke 3 is a straight connection from nearest point on stroke 1 to stroke 2 endpoint',
        g_target_source='synthetic revision from recorded V5: strokes 1/3/4 start at 100 uT with 15 mm smooth blend; strokes 1/4 add 12 uT in body with endpoint taper',
        refinement_evidence_run='20260925T120715.997281Z-823a7e',
    )
    setup = json.loads((SOURCE/'settings.json').read_text())
    entry = json.loads((SOURCE/'entry_profile.json').read_text())
    control = json.loads((SOURCE/'resolved.json').read_text())['control']
    pi = {k:control[k] for k in ('kp','ki','max_correction_mm','max_correction_speed_mm_s',
                                'max_correction_accel_mm_s2','taper_ticks','integral_limit_mm','anti_windup')}
    pi['ki'] = 0.1  # User-selected gain for the refined character trial.
    # Preserve the existing user-authorized trial assumption with the new scope.
    table.update(approval_scope='11_中字连接优化_柔和起笔: user-requested geometry, entry and body-contact adjustment',
                 approval_note='Requested after 2026-09-25 20:07:15 run and paper photo. Existing direction/pose-invariance assumption remains experimental; no new calibration or hardware validation claimed. Operator RUN required.')
    compiled = compile_recorded_plan(plan,table,setup,label='zhong_connected_pi',
                                    control_mode='pi',feedback_profile=pi,entry_profile=entry)
    report = dict(character='中',source_run=str(SOURCE),source_run_id=plan.meta['refinement_evidence_run'],
                  validation='offline compilation only; paper appearance and actual indentation unverified',
                  duration_s=float(compiled['t_s'][-1]),
                  compiled_limits=_check_trajectory(compiled['pose_m_rad'],setup,entry),
                  stroke3_start_base_mm=(left*1000+[setup['origin_x_mm'],setup['origin_y_mm']]).tolist(),
                  stroke3_end_base_mm=(right*1000+[setup['origin_x_mm'],setup['origin_y_mm']]).tolist(),
                  contact_adjustments=adjustments,entry_policy=entry)
    output.mkdir(parents=True)
    plan.save(output/'character.npz')
    StrokePlan.load(output/'character.npz')
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
