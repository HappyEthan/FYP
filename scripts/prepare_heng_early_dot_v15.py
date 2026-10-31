"""Compress v14's pre-dot extension to 35%; translate dot/return unchanged."""
import copy
import json
import sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'src')]
from scripts.generate_strokeplan_from_json import build_plan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
SOURCE = ROOT/'runs/brush2/plans/heng_compact_turn_v14'
OUTPUT = ROOT/'runs/brush2/plans/heng_early_dot_v15'

def prepare():
    recipe = json.loads((SOURCE/'recipe.json').read_text())
    old = np.array(recipe['path']['points_mm'],float)
    join = np.array([31.76693246813994,4.255424865226171])
    matches = [np.flatnonzero(np.linalg.norm(old-target,axis=1)<1e-8) for target in [join,np.array([39.,5.15]),np.array([39.9,3.95])]]
    if any(len(x)!=1 for x in matches):raise ValueError('Ambiguous source stage points')
    j,a,b = [int(x[0]) for x in matches]
    points = old.copy()
    points[j:a+1] = join+.35*(old[j:a+1]-join)
    points[a+1:] = old[a+1:]+points[a]-old[a]
    old_arc = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(old,axis=0),axis=1))]
    arc = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    assert np.array_equal(points[:j+1],old[:j+1])
    assert np.allclose(np.diff(points[a:],axis=0),np.diff(old[a:],axis=0))
    assert np.isclose(arc[a]-arc[j],.35*(old_arc[a]-old_arc[j]))
    trial=copy.deepcopy(recipe)
    trial['name']='横画v15：提前微顿，延伸缩短65%'
    trial['description']='Compress only the pre-dot extension to 35%; translate the existing dot and inward return; preserve magnetic knot values and local speed requests.'
    trial['path']['points_mm']=points.tolist()
    for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
        trial[section][key]=[[float(np.interp(s*old_arc[-1],old_arc,arc)/arc[-1]),v] for s,v in recipe[section][key]]
    trial['notes']=['Prefix through the pre-dot join retained exactly from v14.',
        'Pre-dot extension compressed to 35%; complete stroke becomes shorter, no compensating body extension.',
        'Dot (+0.9,-1.2)mm and inward return (-1.5,0)mm unchanged except translation.',
        'Tail magnetic levels 130->140->100uT unchanged; bounded PI and normal final lift unchanged.',
        'No stationary dwell or early lift; authored trial hypothesis; ink shape not verified.']
    table,setup,entry,pi=[json.loads((SOURCE/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    assert 'tail_exit' not in entry
    plan=build_plan(trial)
    compiled=compile_recorded_plan(plan,table,setup,label='heng_early_dot_v15_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
    limits=_check_trajectory(compiled['pose_m_rad'],setup,entry)
    st=plan.strokes[0];ts=np.interp(arc[[j,a,b,-1]]/arc[-1],st.s,st.t)
    summary=dict(hardware_executed=False,early_lift=False,ink_quality_verified=False,
        extension_length_mm=float(arc[a]-arc[j]),previous_extension_length_mm=float(old_arc[a]-old_arc[j]),
        stage_duration_s=dict(zip(['extension','dot','return'],np.diff(ts).tolist())),
        writing_duration_s=float(st.t[-1]),full_duration_s=float(compiled['t_s'][-1]),
        tail_local_points_mm=points[[j,a,b,-1]].tolist(),limits=limits)
    OUTPUT.mkdir(exist_ok=False);plan.save(OUTPUT/'strokeplan.npz')
    for n,value in [('recipe.json',trial),('preflight.json',summary),('feedforward.json',table),('settings.json',setup),('entry_profile.json',entry),('pi_profile.json',pi)]:
        (OUTPUT/n).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':prepare()
