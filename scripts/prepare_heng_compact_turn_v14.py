"""Offline v14 compact down-right dot and inward return comparison."""
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

SOURCE = ROOT/'runs/brush2/plans/heng_dot_retract_contact_v12'
CONTEXT = ROOT/'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT = ROOT/'runs/brush2/plans/heng_compact_turn_v14'

def prepare():
    recipe = json.loads((SOURCE/'recipe.json').read_text())
    old = np.array(recipe['path']['points_mm'], dtype=float)
    old_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(old, axis=0), axis=1))]
    matches = np.flatnonzero(np.linalg.norm(old-[39., 5.15], axis=1) < 1e-8)
    if len(matches) != 1:
        raise ValueError('Source tail entry is ambiguous')
    start_dot = int(matches[0])
    old_end_dot = int(np.flatnonzero(np.linalg.norm(old-[39.6,4.65],axis=1)<1e-8)[0])
    prefix = old[:start_dot+1].copy()
    A = prefix[-1]; B = A+np.array([.9,-1.2])
    u = np.linspace(0.,1.,61)[:,None]
    controls = np.array([A,A+[.45,0.],B+[.2,.35],B])
    dot = (1-u)**3*controls[0]+3*(1-u)**2*u*controls[1]+3*(1-u)*u**2*controls[2]+u**3*controls[3]
    retract = B+np.column_stack([-1.5*np.linspace(0.,1.,61), np.zeros(61)])
    points = np.vstack([prefix,dot[1:],retract[1:]])
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    assert np.array_equal(points[:len(prefix)],prefix)
    dot_arc = arc[len(prefix)+len(dot)-2]
    trial = copy.deepcopy(recipe)
    trial['name'] = '横画v14：右下微顿 + 向内短回1.5mm'
    trial['description'] = 'Compact down-right turn then inward return; body and magnetic levels retained, tail geometry changed.'
    trial['path']['points_mm'] = points.tolist()
    # Preserve positions of all existing magnetic/speed events up to the dot.
    cut = old_arc[start_dot]
    for section,key in [('magnetic_target','knots_s_uT'),('timing','speed_knots_s_mm_s')]:
        knots = recipe[section][key]
        mapped = [[float(s*old_arc[-1]/arc[-1]),v] for s,v in knots if s*old_arc[-1]<=cut+1e-7]
        mapped += [[float(dot_arc/arc[-1]),140. if section=='magnetic_target' else 1.5],
                   [1.,100. if section=='magnetic_target' else 1.5]]
        trial[section][key] = mapped
    trial['notes'] = ['Body vertices unchanged up to (39,5.15)mm from v12.',
        'Dot endpoint displacement (+0.9,-1.2)mm; final inward return (-1.5,0)mm.',
        'Tail magnetic levels remain 130->140->100uT; local speed request remains 1.5mm/s.',
        'No early lift or stationary dwell; unchanged bounded PI; authored trial dimensions, not calibrated brush compensation.']
    table, setup, entry, pi = [json.loads((CONTEXT/name).read_text()) for name in
        ['feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json']]
    if 'tail_exit' in entry:
        raise ValueError('Early exit is excluded')
    plan = build_plan(trial)
    compiled = compile_recorded_plan(plan, table, setup, label='heng_compact_turn_v14_pi',
        control_mode='pi', feedback_profile=pi, entry_profile=entry)
    limits = _check_trajectory(compiled['pose_m_rad'], setup, entry)
    st = plan.strokes[0]
    t_dot = float(np.interp(dot_arc/arc[-1], st.s, st.t))
    summary = dict(hardware_executed=False, writing_duration_s=float(st.t[-1]),
        full_duration_s=float(compiled['t_s'][-1]), return_duration_s=float(st.t[-1]-t_dot),
        return_displacement_mm=[-1.5, 0.], dot_displacement_mm=[.9,-1.2], early_lift=False, ink_quality_verified=False,
        unchanged_prefix_vertices=len(prefix), limits=limits)
    OUTPUT.mkdir(exist_ok=False)
    plan.save(OUTPUT/'strokeplan.npz')
    for name, value in [('recipe.json',trial),('preflight.json',summary),
        ('feedforward.json',table),('settings.json',setup),('entry_profile.json',entry),('pi_profile.json',pi)]:
        (OUTPUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return OUTPUT

if __name__ == '__main__':
    prepare()
