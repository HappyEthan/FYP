"""Offline continuous-contact candidate and synchronized visualization data."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_strokeplan_from_json import build_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runs/brush2/plans/heng_80mm_inverse_contact_v7/recipe.json'
CONTEXT = ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT = ROOT/'runs/brush2/plans/heng_80mm_continuous_contact_v10'
RUN = ROOT/'runs/brush2/2026-10-22/17-33-49__heng_80mm_inverse_contact_v7_pi__c7ca75'


def main():
    old = json.loads(SOURCE.read_text())
    vertices = np.array(old['path']['points_mm'])
    arc = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(vertices,axis=0),axis=1))]
    d = np.unique(np.r_[np.linspace(0.,arc[-1],1001),arc])
    xy = np.column_stack([np.interp(d,arc,vertices[:,j]) for j in range(2)])
    # Gaussian filtering on a uniform arclength grid, faded into tail only.
    grid = np.linspace(0.,arc[-1],1001)
    uniform = np.column_stack([np.interp(grid,arc,vertices[:,j]) for j in range(2)])
    radius = int(np.ceil(3*.8/(grid[1]-grid[0])))
    k = np.exp(-.5*(np.arange(-radius,radius+1)*(grid[1]-grid[0])/.8)**2);k/=k.sum()
    smooth = np.column_stack([np.convolve(np.pad(uniform[:,j],(radius,radius),mode='edge'),k,mode='valid') for j in range(2)])
    smooth = np.column_stack([np.interp(d,grid,smooth[:,j]) for j in range(2)])
    def ease(x):
        x=np.clip(x,0.,1.);return x**3*(10.+x*(-15.+6.*x))
    weight=ease((d/arc[-1]-.72)/.06)*ease((arc[-1]-d)/1.5)
    revised=xy+weight[:,None]*(smooth-xy)
    assert np.array_equal(revised[d/arc[-1]<=.72],xy[d/arc[-1]<=.72])
    assert np.array_equal(revised[[0,-1]],xy[[0,-1]])
    new_arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(revised,axis=0),axis=1))]
    def mapped(s):return float(np.interp(s*arc[-1],d,new_arc)/new_arc[-1])
    recipe=copy.deepcopy(old)
    recipe['name']='长横80mm：笔腹连续接触候选'
    recipe['description']='Keep v7 compensated geometry; smooth tail over .8mm and unload magnetic target continuously without an XYZ exit.'
    recipe['path']['points_mm']=revised.tolist()
    knots=[[0.,100.],[.039,185.],[.062,185.],[.36,125.],[.49,125.],[.65,160.],[.73,150.],[.82,115.],[.90,100.],[1.,100.]]
    recipe['magnetic_target']['knots_s_uT']=[[mapped(s),g] for s,g in knots]
    recipe['orientation']['smoothing_mm']=16.
    recipe['notes']=['No early geometric lift; P/PI remains active for the whole writing phase.',
                     'V7 XY front retained; tail-only .8mm Gaussian smoothing with fixed endpoints, no v9 contraction.',
                     'Magnetic levels are design targets, not a measured force, width or guarantee of contact.',
                     '100uT is retained as a conservative candidate floor, not a calibrated contact threshold.',
                     'Fixed 6.5mm footprint and 5.5mm lag are uncalibrated visualization hypotheses only.']
    table,setup,entry,pi=[json.loads((CONTEXT/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    assert 'tail_exit' not in entry
    for factor in [.9,.85,.8,.7,.6]:
        trial=copy.deepcopy(recipe)
        trial['timing'].update(speed_mm_s=4.2*factor,accel_mm_s2=10.8*factor**2,angular_speed_deg_s=12.*factor,angular_accel_deg_s2=14.4*factor**2)
        trial['timing']['speed_knots_s_mm_s']=[[mapped(s),v*factor] for s,v in old['timing']['speed_knots_s_mm_s']]
        plan=build_plan(trial)
        try:compiled=compile_recorded_plan(plan,table,setup,label='heng_80mm_continuous_contact_v10_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
        except ValueError as exc:print('Retiming',factor,str(exc));continue
        break
    else:raise ValueError('No valid continuous-contact trajectory')
    mask=compiled['phase']=='measure_00';st=plan.strokes[0]
    assert np.isfinite(compiled['g_ref_uT'][mask]).all()
    assert np.all(compiled['pose_m_rad'][mask,2]<setup['contact_z_mm']/1000)
    assert not np.any(np.char.startswith(compiled['phase'],'tail_exit'))
    assert np.diff(st.g_target[st.s>=mapped(.65)]).max()<=1e-8
    OUTPUT.mkdir(exist_ok=False)
    plan.save(OUTPUT/'strokeplan.npz')
    for filename,value in [('recipe.json',trial),('entry_profile.json',entry)]:
        (OUTPUT/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    summary=dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),hardware_executed=False,
                 early_lift=False,writing_feedback='pi throughout measure_00; normal final lift only',
                 actual_contact_verified=False,ink_shape_prediction_verified=False,
                 smoothing_mm=.8,max_tail_smoothing_offset_mm=float(np.linalg.norm(revised-xy,axis=1).max()),
                 writing_duration_s=float(st.t[-1]),full_duration_s=float(compiled['t_s'][-1]),
                 tail_last20_s=float(st.t[-1]-np.interp(.8,st.s,st.t)),tail_last10_s=float(st.t[-1]-np.interp(.9,st.s,st.t)),
                 magnetic_range_uT=[float(st.g_target.min()),float(st.g_target.max())],
                 nominal_writing_z_range_mm=(np.array([compiled['pose_m_rad'][mask,2].min(),compiled['pose_m_rad'][mask,2].max()])*1000).tolist(),
                 limits=_check_trajectory(compiled['pose_m_rad'],setup,entry))
    (OUTPUT/'preflight.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    # Preview data sampled by normalized candidate arclength; history retains its own timing.
    q=np.unique(np.r_[np.linspace(0.,1.,501),np.array(trial['magnetic_target']['knots_s_uT'])[:,0]])
    position=np.column_stack([np.interp(q,st.s,st.xy[:,j])*1000-([140.,0.][j]) for j in range(2)])
    old_rows=[json.loads(line) for line in (RUN/'control.jsonl').read_text().splitlines()]
    old_rows=[r for r in old_rows if r['phase']=='measure_00']
    from brushbot.target_strokeplan import StrokePlan
    old_st=StrokePlan.load(RUN/'strokeplan.npz').strokes[0]
    history=[[float(s),r['a_ref_uT'],r['a_control_uT'],r['t_s']-old_rows[0]['t_s']] for s,r in zip(old_st.s,old_rows)][::4]
    reference_recipe=json.loads((ROOT/'runs/brush2/plans/heng_80mm_html_return_v5/recipe.json').read_text())
    data=dict(summary=summary,rows=np.column_stack([q,position,np.interp(q,st.s,st.g_target),np.interp(q,st.s,st.t)]).round(5).tolist(),
              previous_xy=np.round(vertices[::2],5).tolist(),history=np.round(history,5).tolist(),
              reference_xy=(np.array(reference_recipe['path']['points_mm'])*reference_recipe['placement']['scale']).round(5).tolist(),
              knots=trial['magnetic_target']['knots_s_uT'],history_label='v7 实测 · 2026-10-22 17:33 · 不同速度/姿态条件')
    (OUTPUT/'visualization_data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
