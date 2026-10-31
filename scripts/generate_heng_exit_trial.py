"""Prepare a smaller return and explicit XYZ exit; never connect hardware."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_strokeplan_from_json import build_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'runs/brush2/plans/heng_80mm_tail_unload_v8/recipe.json'
CONTEXT = ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT = ROOT/'runs/brush2/plans/heng_80mm_lift_return_v9'


def main():
    original = json.loads(SOURCE.read_text())
    points = np.array(original['path']['points_mm'])
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    pivot_distance = .74*arc[-1]
    pivot = np.array([np.interp(pivot_distance, arc, points[:, j]) for j in range(2)])
    q = np.clip((arc-pivot_distance)/3.,0.,1.)
    weight = q**3*(10.+q*(-15.+6.*q))
    revised = points + weight[:,None]*(points-pivot)*np.array([-.2,-.3])
    assert np.array_equal(revised[arc<=pivot_distance],points[arc<=pivot_distance])
    new_arc = np.r_[0.,np.cumsum(np.linalg.norm(np.diff(revised,axis=0),axis=1))]
    def mapped(s):
        return float(np.interp(s*arc[-1],arc,new_arc)/new_arc[-1])
    recipe = copy.deepcopy(original)
    recipe['name'] = '长横80mm：收紧回锋并同步抬笔'
    recipe['description'] = 'Local tail X/Y contraction to 80%/70%; explicit open-loop lift is in entry_profile, not target data.'
    recipe['path']['points_mm'] = revised.tolist()
    for section, key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
        recipe[section][key] = [[mapped(s),v] for s,v in original[section][key]]
    recipe['notes'] = ['Before source s=.74, XY remains unchanged.',
                       'After a 3mm smooth transition, tail offsets from pivot are scaled X=.8, Y=.7.',
                       'Explicit lift lives in the separate execution entry profile; PI ends before the lift starts.',
                       '42mm clearance assumes the existing 40mm contact reference; actual detachment is not measured.']
    table,setup,entry,pi = [json.loads((CONTEXT/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    plan = build_plan(recipe)
    stroke = plan.strokes[0]
    start_s = mapped(.76)
    start_t = float(np.interp(start_s,stroke.s,stroke.t))
    end_s = float(np.interp(start_t+2.4,stroke.t,stroke.s))
    entry['tail_exit'] = dict(start_s=start_s,end_s=end_s,end_z_mm=42.)
    compiled = compile_recorded_plan(plan,table,setup,label='heng_80mm_lift_return_v9_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
    phases,poses=compiled['phase'],compiled['pose_m_rad']
    exit_mask=phases=='tail_exit_00'
    assert np.isnan(compiled['g_ref_uT'][exit_mask]).all()
    assert np.diff(poses[exit_mask,2]).min()>=-1e-12
    assert poses[exit_mask][-1,2] == .042
    OUTPUT.mkdir(exist_ok=False)
    plan.save(OUTPUT/'strokeplan.npz')
    for filename,value in [('recipe.json',recipe),('entry_profile.json',entry)]:
        (OUTPUT/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    np.savez(OUTPUT/'compiled_preview.npz',**{key:compiled[key] for key in ['t_s','phase','pose_m_rad','g_ref_uT']},artifact_role='offline_nominal_preview_not_actual_commands')
    times=compiled['t_s'][exit_mask]
    above=np.flatnonzero(poses[exit_mask,2]>=.040)
    summary=dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                 geometry_change=dict(source_tail_start_s=.74,local_scale_x=.8,local_scale_y=.7,transition_mm=3.),
                 tail_exit=entry['tail_exit'],writing_and_exit_duration_s=float(plan.strokes[0].t[-1]),
                 full_duration_s=float(compiled['t_s'][-1]),tail_exit_duration_s=float(times[-1]-times[0]),
                 clearance_40_reached_after_exit_s=float(times[above[0]]-times[0]),
                 nominal_exit_start_xyz_mm=(poses[exit_mask][0,:3]*1000).tolist(),
                 nominal_exit_end_xyz_mm=(poses[exit_mask][-1,:3]*1000).tolist(),
                 limits=_check_trajectory(poses,setup,entry),feedback_on_exit=False,
                 hardware_executed=False,ink_quality_verified=False)
    (OUTPUT/'preflight.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
