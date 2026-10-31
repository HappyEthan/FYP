"""Preserve v7 XY; reduce tail residence and remove magnetic reloading."""
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
OUTPUT = ROOT/'runs/brush2/plans/heng_80mm_tail_unload_v8'


def main():
    original = json.loads(SOURCE.read_text())
    recipe = copy.deepcopy(original)
    recipe['name'] = '长横80mm：尾段减载与缩时'
    recipe['description'] = 'Preserve v7 compensated XY; smooth tilt direction over 16mm, remove tail reloading and reach 100uT by s=.84.'
    recipe['orientation']['smoothing_mm'] = 16.
    factor = .85
    recipe['timing'].update(speed_mm_s=4.2*factor, accel_mm_s2=10.8*factor**2,
                            angular_speed_deg_s=12.*factor, angular_accel_deg_s2=14.4*factor**2)
    recipe['timing']['speed_knots_s_mm_s'] = [[s, v*factor] for s, v in original['timing']['speed_knots_s_mm_s']]
    recipe['magnetic_target']['knots_s_uT'] = original['magnetic_target']['knots_s_uT'][:6]+[[.84, 100.], [1., 100.]]
    recipe['notes'] = ['Exact v7 recipe XY vertices, placement and compensation retained.',
                       'Orientation smoothing is 16mm; tilt remains 15 degrees. This changes orientation throughout the path.',
                       'Tail magnetic unloading is monotonic after s=.73963; 100uT is the supported contact floor, not detachment.',
                       'Separate lift phase and existing movement/feedback limits unchanged.']
    assert recipe['path'] == original['path'] and recipe['placement'] == original['placement']
    table, setup, entry, pi = [json.loads((CONTEXT/n).read_text()) for n in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    plan = build_plan(recipe)
    compiled = compile_recorded_plan(plan, table, setup, label='heng_80mm_tail_unload_v8_pi',control_mode='pi',feedback_profile=pi,entry_profile=entry)
    stroke = plan.strokes[0]
    assert np.max(np.diff(stroke.g_target[stroke.s >= .74])) <= 1e-8
    OUTPUT.mkdir(exist_ok=False)
    plan.meta['source_target'] = 'runs/brush2/plans/heng_80mm_inverse_contact_v7/strokeplan.npz'
    plan.save(OUTPUT/'strokeplan.npz')
    (OUTPUT/'recipe.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2)+'\n')
    summary = dict(source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),xy_vertices_unchanged=True,
                   orientation_smoothing_mm=16.,writing_duration_s=float(stroke.t[-1]),
                   full_duration_s=float(compiled['t_s'][-1]),
                   last20_duration_s=float(stroke.t[-1]-np.interp(.8,stroke.s,stroke.t)),
                   last10_duration_s=float(stroke.t[-1]-np.interp(.9,stroke.s,stroke.t)),
                   unloading_target_uT=100.,unloading_reached_s=.84,unloading_is_detachment=False,
                   limits=_check_trajectory(compiled['pose_m_rad'],setup,entry),control=compiled['spec_snapshot']['control'])
    (OUTPUT/'preflight.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == '__main__':
    main()
