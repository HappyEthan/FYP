#!/usr/bin/env python3
"""Generate a continuous 中 trial with direction-following tilt, offline only."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import numpy as np

from brushbot.target_strokeplan import Stroke, StrokePlan
from brushbot.experiments.strokeplan_character import CHARACTER_ENTRY, tangent_rpy, orientation_heading
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/brush2/plans/10_中字原地进笔_快速转场'
OUTPUT=ROOT/'runs/brush2/plans/11_中字方向姿态_逆向进笔5mm'


def directional_stroke(stroke):
    """Smooth tangent over ~6 mm and retime locally for rotational dynamics."""
    old_xy=np.asarray(stroke.xy)*1000
    arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(old_xy,axis=0),axis=1))]
    keep=np.r_[True,np.diff(arc)>1e-9]
    old_xy,arc,old_g=old_xy[keep],arc[keep],np.asarray(stroke.g_target)[keep]
    d=np.linspace(0.,arc[-1],int(np.ceil(arc[-1]/.1))+1)
    xy=np.column_stack([np.interp(d,arc,old_xy[:,i]) for i in range(2)])
    deriv=np.gradient(xy,d,axis=0)
    theta=np.unwrap(np.arctan2(deriv[:,1],deriv[:,0]))
    # A 1 mm Gaussian smooths digitized tangent changes without adding axial turns.
    sigma=1./(d[1]-d[0]); radius=int(np.ceil(3*sigma))
    kernel=np.exp(-.5*(np.arange(-radius,radius+1)/sigma)**2);kernel/=kernel.sum()
    theta=np.convolve(np.pad(theta,(radius,radius),mode='edge'),kernel,mode='valid')
    rpy=tangent_rpy(theta,15.)
    dr=np.linalg.norm(np.gradient(rpy,d,axis=0),axis=1)
    ddr=np.linalg.norm(np.gradient(np.gradient(rpy,d,axis=0),d,axis=0),axis=1)
    curvature=np.linalg.norm(np.gradient(deriv,d,axis=0),axis=1)
    omega,alpha=np.deg2rad(20.),np.deg2rad(40.)
    speed=np.minimum.reduce([np.full(len(d),10.),
        .6*omega/np.maximum(dr,1e-12),np.sqrt(.3*alpha/np.maximum(ddr,1e-12)),
        np.sqrt(50./np.maximum(curvature,1e-12))])
    accel=np.minimum(30.,.3*alpha/np.maximum(dr,1e-12))
    speed[0]=speed[-1]=0.
    for i in range(1,len(d)):
        speed[i]=min(speed[i],np.sqrt(speed[i-1]**2+2*min(accel[i-1:i+1])*(d[i]-d[i-1])))
    for i in range(len(d)-2,-1,-1):
        speed[i]=min(speed[i],np.sqrt(speed[i+1]**2+2*min(accel[i:i+2])*(d[i+1]-d[i])))
    times=np.r_[0.,np.cumsum(2*np.diff(d)/(speed[:-1]+speed[1:]))]
    t=np.arange(int(np.ceil(times[-1]/.02-1e-9))+1)*.02
    distance=np.interp(t,times,d)
    target_xy=np.column_stack([np.interp(distance,d,xy[:,i]) for i in range(2)])/1000
    actual_arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(target_xy,axis=0),axis=1))]
    result=Stroke(actual_arc/actual_arc[-1],target_xy,t,np.interp(distance,arc,old_g),
                  tangent_rpy(np.interp(distance,d,theta),15.))
    result.validate()
    return result


def generate(output=OUTPUT, *, source=SOURCE, entry_reverse_mm=5.):
    output,source=Path(output),Path(source)
    if output.exists():
        raise FileExistsError(f'refusing to replace trial: {output}')
    original=StrokePlan.load(source/'character.npz')
    plan=StrokePlan([directional_stroke(st) for st in original.strokes],
        dict(copy.deepcopy(original.meta),orientation_convention='base_rpy_rad',
             orientation_source='15 degree tilt along 1 mm Gaussian-smoothed XY tangent; Rz(h) Ry(15) Rz(-h)',
             time_source='local arclength retiming for linear and angular rate/acceleration limits',
             source_target_sha256=hashlib.sha256((source/'character.npz').read_bytes()).hexdigest()))
    table,setup,pi=[json.loads((source/n).read_text()) for n in ['feedforward.json','settings.json','pi_profile.json']]
    setup.update(max_xy_speed_mm_s=80.,max_z_speed_mm_s=60.,return_speed_mm_s=80.)
    entry=dict(CHARACTER_ENTRY, entry_reverse_mm=entry_reverse_mm)
    table.update(approved=False,transient_approved=False,approval_scope=output.name+': offline candidate',
                 approval_note='Dynamic 15-degree tangent-following pose uses original +X fixed-Ry15 table as an explicit trial assumption; no dynamic-pose calibration claimed.')
    compiled=compile_recorded_plan(plan,table,setup,label='zhong_full_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
    limits=_check_trajectory(compiled['pose_m_rad'],setup,entry)
    report=dict(character='中',stroke_count=4,baseline_count=1,
        duration_s=float(compiled['t_s'][-1]),compiled_limits=limits,
        entry_policy=entry,source_dir=str(source),validation='offline compilation only; no hardware',
        table_assumption='same response-to-depth table at different writing directions and tilt azimuths',
        strokes=[dict(index=i+1,measurement_s=float(st.t[-1]),
            initial_heading_deg=float(np.rad2deg(orientation_heading(st.orientation[0]))),
            entry_rpy_deg=np.rad2deg(tangent_rpy(orientation_heading(st.orientation[0]),30.)).tolist(),
            initial_writing_rpy_deg=np.rad2deg(st.orientation[0]).tolist(),
            max_xy_speed_mm_s=float(np.max(np.linalg.norm(np.diff(st.xy,axis=0),axis=1)/np.diff(st.t))*1000)) for i,st in enumerate(plan.strokes)])
    output.mkdir(parents=True)
    plan.save(output/'character.npz');StrokePlan.load(output/'character.npz')
    for i,st in enumerate(plan.strokes,1):
        StrokePlan([st],dict(plan.meta,character_stroke_index=i)).save(output/f'stroke_{i:02}.npz')
    np.savez(output/'compiled_character.npz',**{k:compiled[k] for k in
              ['t_s','s','phase','pose_m_rad','g_ref_uT','depth_ff_m']},
              artifact_role='derived_nominal_trajectory_not_feedback_commands')
    for name,value in [('feedforward.json',table),('settings.json',setup),('pi_profile.json',pi),
                       ('entry_profile.json',entry),('protocol.json',report)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=OUTPUT)
    parser.add_argument('--entry-reverse-mm',type=float,default=5.,
                        help='reverse XY travel during contact rotation; zero keeps stationary entry')
    args=parser.parse_args()
    print(json.dumps(generate(args.output_dir,entry_reverse_mm=args.entry_reverse_mm),ensure_ascii=False,indent=2))
