"""Reduce paper-plane tail rise; preserve dot/retraction and magnetic levels."""
import copy
import json
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from scripts.generate_strokeplan_from_json import build_plan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
SOURCE=ROOT/'runs/brush2/plans/heng_early_dot_v15'
OUTPUT=ROOT/'runs/brush2/plans/heng_flat_tail_v16'

def prepare():
    recipe=json.loads((SOURCE/'recipe.json').read_text())
    old=np.array(recipe['path']['points_mm'],float)
    A=np.array([34.298506104290965,4.568526162397012])
    match=np.flatnonzero(np.linalg.norm(old-A,axis=1)<1e-8)
    if len(match)!=1:raise ValueError('Source tail entry ambiguous')
    a=int(match[0]);start=int(np.flatnonzero(old[:a,0]>=15.)[0])
    points=old.copy()
    # Smoothly change the slope multiplier over X=15..20 mm, then retain 30%.
    midx=(old[start:a,0]+old[start+1:a+1,0])/2
    u=np.clip((midx-15.)/5.,0.,1.)
    weight=6*u**5-15*u**4+10*u**3
    dy=np.diff(old[start:a+1,1])*(1.-.7*weight)
    points[start:a+1,1]=old[start,1]+np.r_[0.,np.cumsum(dy)]
    points[a+1:,1]+=points[a,1]-old[a,1]
    assert np.array_equal(points[:start],old[:start])
    assert np.array_equal(points[:,0],old[:,0])
    assert np.allclose(np.diff(points[a:],axis=0),np.diff(old[a:],axis=0))
    old_arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(old,axis=0),axis=1))]
    arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    trial=copy.deepcopy(recipe)
    trial['name']='横画v16：压低后半段上扬，保留顿笔内收'
    trial['description']='Reduce only the paper-plane Y rise from local X15mm, smoothly transitioning to a 30% slope multiplier by X20mm; translate the existing dot/return without changing their relative geometry.'
    trial['path']['points_mm']=points.tolist()
    for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
        trial[section][key]=[[float(np.interp(s*old_arc[-1],old_arc,arc)/arc[-1]),v] for s,v in recipe[section][key]]
    trial['notes']=['XY paper-plane rise reduction only, not a change to final Z clearance.',
        'X coordinates unchanged; Y slope transitions over local X15..20mm, retaining 30% thereafter.',
        'Existing dot (+0.9,-1.2)mm and return (-1.5,0)mm translated as a rigid local shape.',
        'Magnetic levels, local speed requests, PI limits, and normal final lift unchanged.',
        'No early lift, stationary dwell, or validated prediction of ink shape.']
    table,setup,entry,pi=[json.loads((SOURCE/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    assert 'tail_exit' not in entry
    plan=build_plan(trial)
    compiled=compile_recorded_plan(plan,table,setup,label='heng_flat_tail_v16_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
    limits=_check_trajectory(compiled['pose_m_rad'],setup,entry)
    st=plan.strokes[0]
    summary=dict(hardware_executed=False,early_lift=False,ink_quality_verified=False,
        modification='paper-plane Y rise; final Z clearance unchanged',
        rise_start_local_mm=old[start].tolist(),old_rise_mm=float(old[a,1]-old[start,1]),
        new_rise_mm=float(points[a,1]-points[start,1]),
        old_dot_entry_mm=old[a].tolist(),new_dot_entry_mm=points[a].tolist(),
        writing_duration_s=float(st.t[-1]),full_duration_s=float(compiled['t_s'][-1]),limits=limits)
    OUTPUT.mkdir(exist_ok=False);plan.save(OUTPUT/'strokeplan.npz')
    for name,value in [('recipe.json',trial),('preflight.json',summary),('feedforward.json',table),('settings.json',setup),('entry_profile.json',entry),('pi_profile.json',pi)]:
        (OUTPUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':prepare()
