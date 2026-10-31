"""Research-informed action order; engineering dimensions remain uncalibrated."""
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
SOURCE=ROOT/'runs/brush2/plans/heng_short_tail_contact_v11'
CONTEXT=ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT=ROOT/'runs/brush2/plans/heng_dot_retract_contact_v12'
RUN=ROOT/'runs/brush2/2026-10-23/14-28-57__heng_short_tail_contact_v11_pi__31a550'
SOURCES=[dict(url='https://www.xinhuameiyu.com/subject/getChapter.action?vo.id=f5a2c60b55a46a550155a46a55580058',
              title='新华美育：颜真卿多宝塔碑“持”笔画解析',
              support='Qualitative teaching: move right/up, turn down to make a dot, finish toward the left.',
              limitation='No robot coordinates, dwell duration, contact model or magnetic measurements.'),
         dict(url='https://jky.ntu.edu.cn/_upload/article/files/28/97/62111abb4e2bb5d0a6ac1ca82d12/358e3a16-14fa-4278-8220-3a6200c2cd76.pdf',
              title='南通大学网站：“三笔字”书写技能训练',
              support='General stroke vocabulary of a slight dot and finishing return; not a quantitative long-horizontal dataset.',
              limitation='Not used to infer millimetres, contact force or magnetic target.')]


def bezier(control):
    p=np.array(control,float);u=np.linspace(0.,1.,max(25,int(np.linalg.norm(np.diff(p,axis=0),axis=1).sum()/.04)+1))[:,None]
    return (1-u)**3*p[0]+3*(1-u)**2*u*p[1]+3*(1-u)*u**2*p[2]+u**3*p[3]


def main():
    original=json.loads((SOURCE/'recipe.json').read_text());old=np.array(original['path']['points_mm'])
    arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(old,axis=0),axis=1))]
    old_st=StrokePlan.load(SOURCE/'strokeplan.npz').strokes[0]
    cut=.84*arc[-1];join=np.array([np.interp(cut,arc,old[:,j]) for j in range(2)])
    before=np.array([np.interp(cut-.8,arc,old[:,j]) for j in range(2)]);direction=join-before;direction/=np.linalg.norm(direction)
    extension=bezier([join,join+direction*2.,[38.6,5.15],[39.,5.15]])
    dot=bezier([[39.,5.15],[39.3,5.15],[39.8,4.55],[39.6,4.65]])
    retract=bezier([[39.6,4.65],[39.4,4.75],[39.,4.90],[38.8,4.90]])
    prefix=np.vstack([old[arc<cut],join])
    points=np.vstack([prefix,extension[1:],dot[1:],retract[1:]])
    lengths=[np.linalg.norm(np.diff(segment,axis=0),axis=1).sum() for segment in [prefix,extension,dot,retract]]
    distances=np.cumsum(lengths);total=distances[-1]
    recipe=copy.deepcopy(original)
    recipe['name']='长横：微顿短收，不补缺'
    recipe['description']='Retain v11 prefix, replace its loop with a body continuation, a small down/right dot and 0.8mm inward retraction; continuous magnetic tracking.'
    recipe['path']['points_mm']=points.tolist()
    g_join=float(np.interp(.84,old_st.s,old_st.g_target))
    knots=[[s*arc[-1]/total,g] for s,g in original['magnetic_target']['knots_s_uT'] if s<.84]
    knots += [[distances[0]/total,g_join],[distances[1]/total,130.],[distances[2]/total,140.],[1.,100.]]
    recipe['magnetic_target']['knots_s_uT']=knots
    # Dot means a local speed reduction and modest loading, not a stationary dwell.
    recipe['timing']['speed_knots_s_mm_s']=[[0.,1.89],[.04,3.78],[(distances[1]-2.)/total,3.78],
                                                         [distances[1]/total,1.5],[distances[2]/total,1.5],[1.,1.5]]
    recipe['notes']=['No loop, no gap-filling path and no early geometric lift. Normal final lift only after writing.',
                     'Qualitative teaching sources support action order only; dimensions and magnetic levels are authored test hypotheses.',
                     'Dot displacement +0.6mm X/-0.5mm Y; short retraction -0.8mm X/+0.25mm Y.',
                     '130->140->100uT is a small experimental magnetic nod, not measured contact force.',
                     'No stationary dot dwell; actual time and shape depend on retiming and uncalibrated brush response.']
    table,setup,entry,pi=[json.loads((CONTEXT/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    assert 'tail_exit' not in entry
    for factor in [1.,.9,.8,.7,.6]:
        trial=copy.deepcopy(recipe)
        for key in ['speed_mm_s','angular_speed_deg_s']:trial['timing'][key]*=factor
        for key in ['accel_mm_s2','angular_accel_deg_s2']:trial['timing'][key]*=factor**2
        trial['timing']['speed_knots_s_mm_s']=[[s,v*factor] for s,v in recipe['timing']['speed_knots_s_mm_s']]
        plan=build_plan(trial)
        try:compiled=compile_recorded_plan(plan,table,setup,label='heng_dot_retract_contact_v12_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
        except ValueError as exc:print('Retiming',factor,str(exc));continue
        break
    else:raise ValueError('No candidate meets existing motion limits')
    st=plan.strokes[0];stage_s=distances/total;stage_t=np.interp(stage_s,st.s,st.t)
    summary=dict(source_sha256=hashlib.sha256((SOURCE/'recipe.json').read_bytes()).hexdigest(),
                 reference_sources=SOURCES,quantitative_dimensions_source='authored engineering choices, not measured web data',
                 hardware_executed=False,early_lift=False,writing_feedback='pi throughout writing',
                 stationary_dwell_s=0.,writing_duration_s=float(st.t[-1]),full_duration_s=float(compiled['t_s'][-1]),
                 retained_prefix_source_s=.84,body_extension_length_mm=float(lengths[1]),
                 dot_path_length_mm=float(lengths[2]),retract_path_length_mm=float(lengths[3]),
                 dot_duration_s=float(stage_t[2]-stage_t[1]),retract_duration_s=float(stage_t[3]-stage_t[2]),
                 dot_displacement_mm=[.6,-.5],retract_displacement_mm=[-.8,.25],
                 retiming_factor=factor,nominal_bbox_mm=np.ptp(st.xy*1000,axis=0).tolist(),
                 limits=_check_trajectory(compiled['pose_m_rad'],setup,entry),ink_prediction_verified=False)
    mask=compiled['phase']=='measure_00'
    assert np.isfinite(compiled['g_ref_uT'][mask]).all()
    assert np.all(compiled['pose_m_rad'][mask,2]<setup['contact_z_mm']/1000)
    OUTPUT.mkdir(exist_ok=False)
    plan.save(OUTPUT/'strokeplan.npz')
    for name,value in [('recipe.json',trial),('entry_profile.json',entry),('preflight.json',summary),('sources.json',SOURCES)]:
        (OUTPUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    q=np.unique(np.r_[np.linspace(0.,1.,501),stage_s,np.array(knots)[:,0]])
    xy=np.column_stack([np.interp(q,st.s,st.xy[:,j])*1000-[140.,0.][j] for j in range(2)])
    rows=[json.loads(l) for l in (RUN/'control.jsonl').read_text().splitlines()];rows=[r for r in rows if r['phase']=='measure_00']
    history=[[float(s),r['a_ref_uT'],r['a_control_uT'],r['t_s']-rows[0]['t_s']] for s,r in zip(old_st.s,rows)][::4]
    ref=json.loads((ROOT/'runs/brush2/plans/heng_80mm_html_return_v5/recipe.json').read_text())
    data=dict(summary=summary,rows=np.column_stack([q,xy,np.interp(q,st.s,st.g_target),np.interp(q,st.s,st.t)]).round(5).tolist(),
              previous_xy=old[::2].round(5).tolist(),history=np.round(history,5).tolist(),
              reference_xy=(np.array(ref['path']['points_mm'])*ref['placement']['scale']).round(5).tolist(),knots=knots,
              stages=[dict(label=label,s=float(s),time_s=float(t)) for label,s,t in zip(['进入末段','开始微顿','开始短收','结束'],stage_s,stage_t)])
    (OUTPUT/'visualization_data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
