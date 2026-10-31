"""Shorten v10 tail geometry, retain continuous magnetic tracking; offline only."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from brushbot.target_strokeplan import StrokePlan
from scripts.generate_strokeplan_from_json import build_plan

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/brush2/plans/heng_80mm_continuous_contact_v10'
CONTEXT=ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT=ROOT/'runs/brush2/plans/heng_short_tail_contact_v11'
RUN=ROOT/'runs/brush2/2026-10-23/14-17-51__heng_80mm_continuous_contact_v10_pi_wetted_repeat__c5ed6a'


def main():
    original=json.loads((SOURCE/'recipe.json').read_text())
    points=np.array(original['path']['points_mm'])
    arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    join=.72*arc[-1]
    pivot=np.array([np.interp(join,arc,points[:,j]) for j in range(2)])
    q=np.clip((arc-join)/2.,0.,1.)
    w=q**3*(10.+q*(-15.+6.*q))
    shortened=points-.5*w[:,None]*(points-pivot)
    assert np.array_equal(shortened[arc<=join],points[arc<=join])
    new_arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(shortened,axis=0),axis=1))]
    def mapped(s):return float(np.interp(s*arc[-1],arc,new_arc)/new_arc[-1])
    recipe=copy.deepcopy(original)
    recipe['name']='笔腹横：尾端各段约减半，连续磁反馈'
    recipe['description']='Keep the v10 prefix; scale tail about source arclength .72 pivot by .5 with a 2mm smooth transition. No early lift.'
    recipe['path']['points_mm']=shortened.tolist()
    for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
        recipe[section][key]=[[mapped(s),v] for s,v in original[section][key]]
    recipe['notes']=['Tail shortening is an experimental geometric choice, not a calibrated sensor-offset transform.',
                     'After the 2mm transition, each original tail segment has half its former length.',
                     'Prefix and magnetic target values retained; stage positions remapped to corresponding shortened geometry.',
                     'End position and overall footprint change; do not call this an unchanged 80mm target.',
                     'Whole writing phase retains PI, no geometric exit; actual continuous paper contact unverified.']
    table,setup,entry,pi=[json.loads((CONTEXT/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    assert 'tail_exit' not in entry
    plan=build_plan(recipe)
    compiled=compile_recorded_plan(plan,table,setup,label='heng_short_tail_contact_v11_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
    st=plan.strokes[0];old_st=StrokePlan.load(SOURCE/'strokeplan.npz').strokes[0]
    old_join_t=float(np.interp(.72,old_st.s,old_st.t));new_join_t=float(np.interp(mapped(.72),st.s,st.t))
    segments=[]
    for lo,hi in zip([.72,.8,.86,.92],[.8,.86,.92,1.]):
        segments.append(dict(source_start_s=lo,source_end_s=hi,old_length_mm=(hi-lo)*arc[-1],
                             new_length_mm=float(np.interp(hi*arc[-1],arc,new_arc)-np.interp(lo*arc[-1],arc,new_arc))))
    summary=dict(source_sha256=hashlib.sha256((SOURCE/'recipe.json').read_bytes()).hexdigest(),
                 prefix_end_source_s=.72,tail_scale=.5,transition_mm=2.,
                 old_tail_length_mm=float(arc[-1]-join),new_tail_length_mm=float(new_arc[-1]-np.interp(join,arc,new_arc)),
                 old_tail_duration_s=float(old_st.t[-1]-old_join_t),new_tail_duration_s=float(st.t[-1]-new_join_t),
                 old_writing_duration_s=float(old_st.t[-1]),writing_duration_s=float(st.t[-1]),full_duration_s=float(compiled['t_s'][-1]),
                 new_bbox_mm=np.ptp(st.xy*1000,axis=0).tolist(),segments=segments,
                 magnetic_values_unchanged=True,early_lift=False,writing_feedback='pi throughout measure_00',
                 hardware_executed=False,actual_contact_verified=False,limits=_check_trajectory(compiled['pose_m_rad'],setup,entry))
    mask=compiled['phase']=='measure_00'
    assert np.isfinite(compiled['g_ref_uT'][mask]).all()
    assert np.all(compiled['pose_m_rad'][mask,2]<setup['contact_z_mm']/1000)
    OUTPUT.mkdir(exist_ok=False)
    plan.save(OUTPUT/'strokeplan.npz')
    for name,value in [('recipe.json',recipe),('entry_profile.json',entry),('preflight.json',summary)]:
        (OUTPUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    progress=np.unique(np.r_[np.linspace(0.,1.,501),np.array(recipe['magnetic_target']['knots_s_uT'])[:,0]])
    position=np.column_stack([np.interp(progress,st.s,st.xy[:,j])*1000-[140.,0.][j] for j in range(2)])
    rows=[json.loads(l) for l in (RUN/'control.jsonl').read_text().splitlines()]
    rows=[r for r in rows if r['phase']=='measure_00']
    history=[[float(s),r['a_ref_uT'],r['a_control_uT'],r['t_s']-rows[0]['t_s']] for s,r in zip(old_st.s,rows)][::4]
    old_reference=json.loads((ROOT/'runs/brush2/plans/heng_80mm_html_return_v5/recipe.json').read_text())
    data=dict(summary=summary,rows=np.column_stack([progress,position,np.interp(progress,st.s,st.g_target),np.interp(progress,st.s,st.t)]).round(5).tolist(),
              previous_xy=points[::2].round(5).tolist(),history=np.round(history,5).tolist(),
              reference_xy=(np.array(old_reference['path']['points_mm'])*old_reference['placement']['scale']).round(5).tolist(),
              knots=recipe['magnetic_target']['knots_s_uT'],history_label='v10 蘸水实测 · 2026-10-23 14:17 · 各自归一化进度')
    (OUTPUT/'visualization_data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
