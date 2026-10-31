"""Create an independent, preflighted trial from the side-chat lead demo."""
import copy
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_strokeplan_from_json import build_plan

ROOT = Path(__file__).resolve().parents[1]
DEMO = Path('/home/serein/.codex/visualizations/2026/10/22/01a162db-ce55-7e62-8898-827adeb225b4/heng-tail-compensation.html')
SOURCE = ROOT / 'runs/brush2/plans/heng_80mm_html_return_v5/recipe.json'
CONTEXT = ROOT / 'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT = ROOT / 'runs/brush2/plans/heng_80mm_tail_lead_v6'


def main():
    text = DEMO.read_text()
    vertices = np.asarray(json.loads(re.search(r'id="heng-reference-data">(.*?)</script>', text, re.S)[1]))
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(vertices, axis=0), axis=1))]
    # Keep every original vertex as well as the demo's 601 uniform samples.
    distances = np.unique(np.r_[np.linspace(0., arc[-1], 601), arc])

    def sample(s):
        return np.column_stack([np.interp(s, arc, vertices[:, j]) for j in range(2)])

    def ease(x):
        x = np.clip(x, 0., 1.)
        return x**3 * (10. + x * (-15. + 6. * x))

    ref = sample(distances)
    direction = sample(distances + 1.) - sample(distances - 1.)
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-30)
    weight = ease((distances - arc[32]) / 4.) * ease((arc[-1] - distances) / 2.)
    candidate = ref + weight[:, None] * direction
    candidate_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(candidate, axis=0), axis=1))]
    original = json.loads(SOURCE.read_text())
    # Demo coordinates already include the 80 mm scaling, but not placement.
    source_vertices = np.asarray(original['path']['points_mm']) * original['placement']['scale']
    assert np.max(np.linalg.norm(source_vertices - vertices, axis=1)) < 1e-6
    assert np.array_equal(candidate[distances <= arc[32]], ref[distances <= arc[32]])
    assert np.array_equal(candidate[[0, -1]], ref[[0, -1]])
    recipe = copy.deepcopy(original)
    recipe['name'] = '长横80mm：尾段切线前置1mm'
    recipe['description'] = 'Side-chat geometric hypothesis: 1mm lead, 2mm tangent smoothing, endpoint taper; not calibrated contact compensation.'
    recipe['placement']['scale'] = 1.
    recipe['path'] = dict(kind='rounded_polyline', points_mm=candidate.tolist(), corner_radius_mm=0.)
    for field, key in [('magnetic_target', 'knots_s_uT'), ('timing', 'speed_knots_s_mm_s')]:
        recipe[field][key] = [[float(np.interp(s * arc[-1], distances, candidate_arc) / candidate_arc[-1]), value]
                              for s, value in original[field][key]]
    recipe['notes'] = ['Independent candidate; historical targets unchanged.',
                       'Demo algorithm preserved; original vertices added to uniform samples to preserve the unmodified prefix.',
                       'Magnetic values unchanged, phase positions mapped through corresponding source arclength.',
                       '1mm lead with 2mm centered tangent window; quintic activation over 4mm and final taper over 2mm.']
    table, setup, entry, pi = [json.loads((CONTEXT / name).read_text()) for name in
                              ['feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json']]
    for factor in [1., .85, .7, .55, .4]:
        trial = copy.deepcopy(recipe)
        for name in ['speed_mm_s', 'angular_speed_deg_s']:
            trial['timing'][name] *= factor
        for name in ['accel_mm_s2', 'angular_accel_deg_s2']:
            trial['timing'][name] *= factor**2
        trial['timing']['speed_knots_s_mm_s'] = [[s, speed * factor] for s, speed in trial['timing']['speed_knots_s_mm_s']]
        plan = build_plan(trial)
        try:
            compiled = compile_recorded_plan(plan, table, setup, label='heng_80mm_tail_lead_v6_pi',
                                            control_mode='pi', feedback_profile=pi, entry_profile=entry)
        except ValueError as exc:
            print('Retiming factor', factor, ':', exc)
            continue
        break
    else:
        raise ValueError('No candidate passed existing trajectory limits')
    OUTPUT.mkdir(exist_ok=False)
    plan.meta['compensation'] = dict(lead_mm=1., smoothing_mm=2., source_demo=str(DEMO), uncalibrated=True)
    plan.save(OUTPUT / 'strokeplan.npz')
    (OUTPUT / 'recipe.json').write_text(json.dumps(trial, ensure_ascii=False, indent=2) + '\n')
    st = plan.strokes[0]
    summary = dict(lead_mm=1., smoothing_mm=2., max_offset_mm=float(weight.max()),
                   source_demo_sha256=hashlib.sha256(DEMO.read_bytes()).hexdigest(),
                   source_recipe_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                   additional_retiming_factor=factor, writing_duration_s=float(st.t[-1]),
                   full_duration_s=float(compiled['t_s'][-1]),
                   leftward_return_mm=float((st.xy[:, 0].max() - st.xy[-1, 0]) * 1000),
                   limits=_check_trajectory(compiled['pose_m_rad'], setup, entry),
                   control=compiled['spec_snapshot']['control'], ink_quality_verified=False)
    (OUTPUT / 'preflight.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
