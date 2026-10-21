#!/usr/bin/env python3
"""Generate editable reference-stroke targets from JSON; offline only, no Z."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

import numpy as np

from brushbot.target_strokeplan import FEATURE, Stroke, StrokePlan
from scripts.generate_calligraphy_trial import contact_profile, rounded_polyline
from scripts.generate_directional_character_trial import directional_stroke


def _fields(value, required, optional=(), *, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f'{label}: missing fields {sorted(missing)}, unknown fields {sorted(unknown)}')


def _number(value, label, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'{label} must be positive')
    if nonnegative and value < 0:
        raise ValueError(f'{label} must be nonnegative')
    return float(value)


def _pairs(value, label, *, minimum=2):
    try:
        points = np.asarray(value, float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be finite pairs') from exc
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < minimum or not np.isfinite(points).all():
        raise ValueError(f'{label} must contain at least {minimum} finite pairs')
    return points


def _knots(value, label, *, positive=False):
    knots = _pairs(value, label)
    if knots[0, 0] != 0. or knots[-1, 0] != 1.:
        raise ValueError(f'{label} must span 0 to 1')
    if np.any(np.diff(knots[:, 0]) <= 0):
        raise ValueError(f'{label} positions must strictly increase')
    if np.any(knots[:, 1] < 0) or (positive and np.any(knots[:, 1] == 0)):
        raise ValueError(f'{label} values must be {"positive" if positive else "nonnegative"}')
    return knots


def _rotation(degrees):
    a = np.deg2rad(degrees)
    return np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])


def build_plan(recipe):
    """One JSON recipe becomes one V3 target; geometric units in JSON are mm."""
    _fields(recipe, ('schema_version', 'id', 'name', 'description', 'reference',
                     'placement', 'path', 'magnetic_target', 'timing', 'orientation',
                     'filter_definition'), ('notes',), label='recipe')
    if type(recipe['schema_version']) is not int or recipe['schema_version'] != 1:
        raise ValueError('expected recipe schema_version=1')
    if not isinstance(recipe['id'], str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', recipe['id']):
        raise ValueError('id must be a lowercase filename identifier, without path separators')
    for key in ('name', 'description', 'reference'):
        if not isinstance(recipe[key], str) or not recipe[key].strip():
            raise ValueError(f'{key} must be nonempty text')
    if 'notes' in recipe and (not isinstance(recipe['notes'], list)
                             or not all(isinstance(v, str) for v in recipe['notes'])):
        raise ValueError('notes must be a list of text')

    placement = recipe['placement']
    _fields(placement, ('origin_mm', 'rotation_deg', 'scale'), label='placement')
    origin = _pairs([placement['origin_mm']], 'origin_mm', minimum=1)[0]
    rotation = _rotation(_number(placement['rotation_deg'], 'rotation_deg'))
    scale = _number(placement['scale'], 'scale', positive=True)
    path = recipe['path']
    _fields(path, ('kind', 'points_mm'), ('corner_radius_mm',), label='path')
    points = _pairs(path['points_mm'], 'points_mm')
    if path['kind'] == 'rounded_polyline':
        radius = _number(path.get('corner_radius_mm', 2.), 'corner_radius_mm', nonnegative=True)
        if np.any(np.linalg.norm(np.diff(points, axis=0), axis=1) <= 1e-9):
            raise ValueError('duplicate path vertices')
        curve = rounded_polyline(points / 1000., radius_mm=radius) * 1000. if radius > 0 else points
    elif path['kind'] == 'cubic_bezier':
        if len(points) != 4 or 'corner_radius_mm' in path:
            raise ValueError('cubic_bezier needs four control points and no corner_radius_mm')
        count = max(3, int(np.ceil(np.linalg.norm(np.diff(points, axis=0), axis=1).sum() / .1)) + 1)
        u = np.linspace(0., 1., count)[:, None]
        curve = (1-u)**3 * points[0] + 3*(1-u)**2*u*points[1] + 3*(1-u)*u**2*points[2] + u**3*points[3]
    else:
        raise ValueError('path kind must be rounded_polyline or cubic_bezier')
    xy = (scale * curve @ rotation.T + origin) / 1000.
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    if arc[-1] <= 1e-9:
        raise ValueError('path must have positive length')
    s = arc / arc[-1]

    target = recipe['magnetic_target']
    _fields(target, ('interpolation', 'knots_s_uT'), label='magnetic_target')
    knots = _knots(target['knots_s_uT'], 'magnetic target knots')
    if target['interpolation'] not in {'quintic', 'linear'}:
        raise ValueError('magnetic target interpolation must be quintic or linear')

    timing = recipe['timing']
    _fields(timing, ('speed_mm_s', 'accel_mm_s2', 'angular_speed_deg_s',
                     'angular_accel_deg_s2'), ('speed_knots_s_mm_s',), label='timing')
    timing_parameters = {key: _number(timing[key], key, positive=True) for key in timing if key != 'speed_knots_s_mm_s'}
    if 'speed_knots_s_mm_s' in timing:
        timing_parameters['speed_knots_s_mm_s'] = _knots(timing['speed_knots_s_mm_s'], 'speed knots', positive=True)
    orientation = recipe['orientation']
    _fields(orientation, ('kind', 'tilt_deg', 'smoothing_mm'), label='orientation')
    if orientation['kind'] != 'tangent_tilt':
        raise ValueError('orientation kind must be tangent_tilt')
    tilt = _number(orientation['tilt_deg'], 'tilt_deg', positive=True)
    smoothing = _number(orientation['smoothing_mm'], 'smoothing_mm', positive=True)

    filter_definition = recipe['filter_definition']
    _fields(filter_definition, ('kind', 'alpha'), label='filter_definition')
    alpha = _number(filter_definition['alpha'], 'filter alpha', positive=True)
    if filter_definition['kind'] != 'ema' or alpha > 1.:
        raise ValueError('filter_definition must be EMA with 0 < alpha <= 1')

    # Reuse the 中 trial's direction-following pose and local retiming. Evaluate
    # g on final sampled arclength so the editable knots keep their exact meaning.
    stroke = directional_stroke(Stroke(s, xy, arc / (timing_parameters['speed_mm_s'] / 1000.),
                                      np.zeros(len(s))),
                                **timing_parameters, tilt_deg=tilt, smoothing_mm=smoothing)
    stroke.g_target = (contact_profile(stroke.s, knots) if target['interpolation'] == 'quintic'
                       else np.interp(stroke.s, knots[:, 0], knots[:, 1]))
    recipe_hash = hashlib.sha256(json.dumps(recipe, ensure_ascii=False, sort_keys=True,
                                           allow_nan=False).encode('utf-8')).hexdigest()
    plan = StrokePlan([stroke], dict(source='synthetic', coordinate_frame='paper',
        feature=FEATURE, filter_definition=dict(filter_definition),
        orientation_convention='base_rpy_rad', name=recipe['name'], recipe_id=recipe['id'],
        description=recipe['description'], reference=recipe['reference'],
        xy_source='editable JSON local geometry, scale, rotation and translation',
        g_target_source='synthetic editable magnetic target knots; not measured force or width',
        orientation_source='same tangent-following tilt construction as 中 trial',
        time_source='local arclength retiming with linear/angular limits and optional speed caps',
        recipe_sha256=recipe_hash, recipe=recipe,
        validation='target-only V3; ink quality and calibration applicability untested'))
    plan.validate()
    return plan


def _preview(plan, output, *, axes=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    st = plan.strokes[0]
    recipe = plan.meta['recipe']
    view_xy = (st.xy * 1000. - recipe['placement']['origin_mm']) @ _rotation(recipe['placement']['rotation_deg'])
    if axes is None:
        fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    else:
        fig = axes[0].figure
    axes[0].plot(view_xy[:, 0], view_xy[:, 1])
    axes[0].scatter(*view_xy[0], color='green', label='start')
    axes[0].scatter(*view_xy[-1], color='red', marker='x', label='end')
    axes[0].set(xlabel='Drawing right (mm)', ylabel='Drawing up (mm)', title=recipe['id'] + ' | writing view')
    axes[0].set_aspect('equal', adjustable='datalim')
    axes[0].legend(loc='best', fontsize=8)
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(st.xy, axis=0), axis=1))] * 1000.
    axes[1].plot(arc, st.g_target)
    axes[1].scatter(np.asarray(recipe['magnetic_target']['knots_s_uT'])[:, 0] * arc[-1],
                    np.asarray(recipe['magnetic_target']['knots_s_uT'])[:, 1], s=12)
    axes[1].set(xlabel='Arclength (mm)', ylabel='Target (uT)', title='Editable magnetic target')
    axes[2].plot(st.t, st.g_target)
    axes[2].set(xlabel='Time (s)', ylabel='Target (uT)', title='Target in time')
    for ax in axes:
        ax.grid(alpha=.3)
    if output is not None:
        fig.suptitle('Synthetic reference-stroke recipe | target preview, not predicted ink')
        fig.tight_layout(rect=(0., 0., 1., .93))
        fig.savefig(output, dpi=150)
        plt.close(fig)


def generate(config_paths, output_dir, *, preview=True):
    """Validate every input before creating a new, immutable output bundle."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f'refusing to replace output: {output_dir}')
    items = []
    for path in config_paths:
        path = Path(path)
        payload = path.read_bytes()
        recipe = json.loads(payload)
        plan = build_plan(recipe)
        plan.meta.update(recipe_file=str(path.resolve()), recipe_sha256=hashlib.sha256(payload).hexdigest())
        items.append((path, payload, plan))
    if not items or len({plan.meta['recipe_id'] for _, _, plan in items}) != len(items):
        raise ValueError('provide at least one recipe, with unique id values')
    report = dict(validation='V3 reload and target previews; no hardware execution or ink validation',
                  strokes=[])
    output_dir.mkdir(parents=True, exist_ok=False)
    for path, payload, plan in items:
        folder = output_dir / plan.meta['recipe_id']
        folder.mkdir()
        (folder / 'recipe.json').write_bytes(payload)
        plan.save(folder / 'strokeplan.npz')
        loaded = StrokePlan.load(folder / 'strokeplan.npz')
        st = loaded.strokes[0]
        length = np.linalg.norm(np.diff(st.xy, axis=0), axis=1).sum() * 1000.
        speed = np.linalg.norm(np.diff(st.xy, axis=0), axis=1) / np.diff(st.t) * 1000.
        with (folder / 'target.csv').open('x', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['t_s', 's', 'x_mm', 'y_mm', 'g_target_uT', 'roll_rad', 'pitch_rad', 'yaw_rad'])
            for t, s, xy, g, rpy in zip(st.t, st.s, st.xy * 1000., st.g_target, st.orientation):
                writer.writerow([t, s, *xy, g, *rpy])
        entry = dict(id=plan.meta['recipe_id'], name=plan.meta['name'],
                     recipe_file=str(path.resolve()), recipe_sha256=plan.meta['recipe_sha256'],
                     plan=f"{plan.meta['recipe_id']}/strokeplan.npz", samples=len(st.s),
                     length_mm=float(length), duration_s=float(st.t[-1]),
                     max_xy_speed_mm_s=float(speed.max()),
                     start_end_paper_mm=(st.xy[[0, -1]] * 1000.).tolist(),
                     target_range_uT=[float(st.g_target.min()), float(st.g_target.max())])
        if preview:
            _preview(loaded, folder / 'preview.png')
        report['strokes'].append(entry)
        (folder / 'summary.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if preview:
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(len(items), 3, figsize=(13, 3.5 * len(items)), squeeze=False)
        for (_, _, plan), row in zip(items, axes):
            _preview(plan, None, axes=row)
        fig.suptitle('Reference stroke targets | synthetic initial recipes, not ink simulation')
        fig.tight_layout(rect=(0., 0., 1., .97))
        fig.savefig(output_dir / 'overview.png', dpi=150)
        plt.close(fig)
    (output_dir / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', nargs='+', required=True, type=Path, help='one or more editable JSON recipes')
    parser.add_argument('--output-dir', required=True, type=Path, help='new directory; existing output is never replaced')
    parser.add_argument('--no-preview', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = generate(args.config, args.output_dir, preview=not args.no_preview)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
