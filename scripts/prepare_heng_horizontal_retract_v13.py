"""Offline single-factor v12 comparison: horizontal, shorter final return."""
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
OUTPUT = ROOT/'runs/brush2/plans/heng_horizontal_retract_v13'

def prepare():
    recipe = json.loads((SOURCE/'recipe.json').read_text())
    old = np.array(recipe['path']['points_mm'], dtype=float)
    old_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(old, axis=0), axis=1))]
    matches = np.flatnonzero(np.linalg.norm(old-[39.6, 4.65], axis=1) < 1e-8)
    if len(matches) != 1:
        raise ValueError('Source dot endpoint is ambiguous')
    end_dot = int(matches[0])
    prefix = old[:end_dot+1].copy()
    # A straight return with the same Y throughout; preserve the dot and body.
    u = np.linspace(0., 1., 26)[1:]
    retract = prefix[-1]+np.column_stack([-.5*u, np.zeros_like(u)])
    points = np.vstack([prefix, retract])
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    assert np.array_equal(points[:len(prefix)], old[:len(prefix)])
    assert np.all(points[end_dot:, 1] == old[end_dot, 1])
    assert np.all(np.diff(points[end_dot:, 0]) < 0)
    trial = copy.deepcopy(recipe)
    trial['name'] = '横画v13：原微顿 + 水平短收0.5mm'
    trial['description'] = 'Single-factor tail geometry comparison to v12; same magnetic knot values and local speed settings.'
    trial['path']['points_mm'] = points.tolist()
    # Preserve positions of all existing magnetic/speed events up to the dot.
    cut = old_arc[end_dot]
    for section, key in [('magnetic_target', 'knots_s_uT'), ('timing', 'speed_knots_s_mm_s')]:
        knots = recipe[section][key]
        mapped = [[float(s*old_arc[-1]/arc[-1]), v] for s,v in knots if s*old_arc[-1] <= cut+1e-7 and s < 1]
        mapped.append([1., knots[-1][1]])
        trial[section][key] = mapped
    trial['notes'] = ['Body and dot vertices unchanged from v12.',
        'Only final return changes: (-0.8,+0.25)mm to (-0.5,0)mm.',
        'Magnetic knot values remain 130->140->100uT at the tail; not a calibrated contact threshold.',
        'PI stays enabled during writing; no early geometric lift or stationary dwell.',
        'Photo comparison required; no guaranteed ink shape prediction.']
    table, setup, entry, pi = [json.loads((CONTEXT/name).read_text()) for name in
        ['feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json']]
    if 'tail_exit' in entry:
        raise ValueError('Early exit is excluded')
    plan = build_plan(trial)
    compiled = compile_recorded_plan(plan, table, setup, label='heng_horizontal_retract_v13_pi',
        control_mode='pi', feedback_profile=pi, entry_profile=entry)
    limits = _check_trajectory(compiled['pose_m_rad'], setup, entry)
    st = plan.strokes[0]
    t_dot = float(np.interp(cut/arc[-1], st.s, st.t))
    summary = dict(hardware_executed=False, writing_duration_s=float(st.t[-1]),
        full_duration_s=float(compiled['t_s'][-1]), return_duration_s=float(st.t[-1]-t_dot),
        return_displacement_mm=[-.5, 0.], early_lift=False, ink_quality_verified=False,
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
