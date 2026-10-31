"""Bounded numerical inverse of the exploratory contact-center model, offline."""
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_strokeplan_from_json import build_plan

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'runs/brush2/plans/heng_80mm_html_return_v5/recipe.json'
CONTEXT = ROOT / 'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
OUTPUT = ROOT / 'runs/brush2/plans/heng_80mm_inverse_contact_v7'
PARAMETERS = dict(width_mm=6.5, aspect=1.4, center_response_mm=5.5,
                  turn_response_mm=11., max_xy_offset_mm=5.5, uncalibrated=True)


def simulate(points):
    ds = np.r_[0., np.linalg.norm(np.diff(points, axis=0), axis=1)]
    centers = np.empty_like(points)
    centers[0] = points[0]
    headings = np.empty(len(points))
    headings[0] = np.arctan2(*(points[1]-points[0])[::-1])
    for i in range(1, len(points)):
        gain = -np.expm1(-ds[i]/PARAMETERS['center_response_mm'])
        centers[i] = centers[i-1] + gain*(points[i]-centers[i-1])
        tangent = np.arctan2(*(points[i]-points[i-1])[::-1])
        delta = np.arctan2(np.sin(tangent-headings[i-1]), np.cos(tangent-headings[i-1]))
        headings[i] = headings[i-1] - np.expm1(-ds[i]/PARAMETERS['turn_response_mm'])*delta
    return centers, headings


def main():
    original = json.loads(SOURCE.read_text())
    vertices = np.array(original['path']['points_mm'])*original['placement']['scale']
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(vertices, axis=0), axis=1))]
    s = np.unique(np.r_[np.linspace(0., arc[-1], 601), arc])
    ref = np.column_stack([np.interp(s, arc, vertices[:, j]) for j in range(2)])
    start = arc[32]
    mask = s >= start
    knots = np.linspace(start, arc[-1], 16)
    # Smooth interpolation of bounded offsets. Both endpoints remain fixed.
    basis = np.zeros((len(s), len(knots)))
    for i, distance in enumerate(s):
        if distance <= start or distance >= arc[-1]:
            continue
        j = min(np.searchsorted(knots, distance)-1, len(knots)-2)
        u = (distance-knots[j])/(knots[j+1]-knots[j])
        q = u**3*(10.+u*(-15.+6.*u))
        basis[i, j], basis[i, j+1] = 1.-q, q
    basis = basis[:, 1:-1]

    def project(values):
        x = values.reshape(-1, 2)
        return (x/np.maximum(1., np.linalg.norm(x, axis=1, keepdims=True)/5.5)).ravel()

    def candidate(values):
        return ref + basis@values.reshape(-1, 2)

    def residual(values):
        centers, _ = simulate(candidate(values))
        x = np.vstack([np.zeros(2), values.reshape(-1, 2), np.zeros(2)])
        return np.r_[(centers[mask]-ref[mask]).ravel(), .25*x.ravel(), .6*np.diff(x, n=2, axis=0).ravel()]

    values = np.zeros(basis.shape[1]*2)
    initial = simulate(ref)[0]
    for iteration in range(18):
        residual0 = residual(values)
        jac = np.column_stack([(residual(values+np.eye(len(values))[j]*.01)-residual0)/.01 for j in range(len(values))])
        step = np.linalg.lstsq(jac, -residual0, rcond=None)[0]
        improved = False
        for rate in [1., .5, .25, .1]:
            proposed = project(values+rate*step)
            if np.sum(residual(proposed)**2) < np.sum(residual0**2):
                values = proposed
                improved = True
                break
        if not improved:
            break
    points = candidate(values)
    centers, headings = simulate(points)
    before = float(np.sqrt(np.mean(np.sum((initial[mask]-ref[mask])**2, axis=1))))
    after = float(np.sqrt(np.mean(np.sum((centers[mask]-ref[mask])**2, axis=1))))
    assert after < before
    assert np.array_equal(points[~mask], ref[~mask])
    assert np.array_equal(points[[0, -1]], ref[[0, -1]])
    assert np.max(np.linalg.norm(points-ref, axis=1)) <= 5.5+1e-9
    recipe = copy.deepcopy(original)
    recipe['name'] = '长横80mm：接触中心模型反求补偿'
    recipe['description'] = 'Uncalibrated bounded XY inverse; center lag 5.5mm, orientation response 11mm evaluated forward only.'
    recipe['placement']['scale'] = 1.
    recipe['path'] = dict(kind='rounded_polyline', points_mm=points.tolist(), corner_radius_mm=0.)
    new_arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    for field, key in [('magnetic_target', 'knots_s_uT'), ('timing', 'speed_knots_s_mm_s')]:
        recipe[field][key] = [[float(np.interp(q*arc[-1], s, new_arc)/new_arc[-1]), value] for q, value in original[field][key]]
    recipe['notes'] = ['Width and aspect define the hypothetical footprint, not measured force or a controller gain.',
                       'Only center error is minimized. 11mm turning response is evaluated forward, not independently controlled.',
                       'Fixed start/end, unchanged pre-tail path, offsets bounded to 5.5mm.',
                       'Magnetic levels unchanged; stages remapped by source-to-candidate arclength.']
    table, setup, entry, pi = [json.loads((CONTEXT/name).read_text()) for name in ['feedforward.json','settings.json','entry_profile.json','pi_profile.json']]
    for factor in [1., .85, .7, .55, .4, .3]:
        trial = copy.deepcopy(recipe)
        for key in ['speed_mm_s','angular_speed_deg_s']:
            trial['timing'][key] *= factor
        for key in ['accel_mm_s2','angular_accel_deg_s2']:
            trial['timing'][key] *= factor**2
        trial['timing']['speed_knots_s_mm_s'] = [[q, value*factor] for q, value in trial['timing']['speed_knots_s_mm_s']]
        plan = build_plan(trial)
        try:
            compiled = compile_recorded_plan(plan, table, setup, label='heng_80mm_inverse_contact_v7_pi', control_mode='pi', feedback_profile=pi, entry_profile=entry)
        except ValueError as exc:
            print('Retiming', factor, str(exc))
            continue
        break
    else:
        raise ValueError('No valid trajectory at existing limits')
    OUTPUT.mkdir(exist_ok=False)
    plan.meta['compensation'] = PARAMETERS
    plan.save(OUTPUT/'strokeplan.npz')
    (OUTPUT/'recipe.json').write_text(json.dumps(trial, ensure_ascii=False, indent=2)+'\n')
    np.savez(OUTPUT/'model_prediction.npz', source_distance_mm=s, reference_xy_mm=ref,
             candidate_xy_mm=points, predicted_contact_xy_mm=centers, predicted_heading_rad=headings)
    summary = dict(parameters=PARAMETERS, source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                   model_tail_center_rmse_before_mm=before, model_tail_center_rmse_after_mm=after,
                   model_final_center_error_mm=float(np.linalg.norm(centers[-1]-ref[-1])),
                   max_xy_offset_mm=float(np.max(np.linalg.norm(points-ref, axis=1))),
                   additional_retiming_factor=factor, writing_duration_s=float(plan.strokes[0].t[-1]),
                   full_duration_s=float(compiled['t_s'][-1]), limits=_check_trajectory(compiled['pose_m_rad'],setup,entry),
                   control=compiled['spec_snapshot']['control'], ink_quality_verified=False)
    (OUTPUT/'preflight.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
