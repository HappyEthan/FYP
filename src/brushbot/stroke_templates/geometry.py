"""Protect local ends, deform the body, and retain an explicit scaling baseline."""
from __future__ import annotations

import copy

import numpy as np

from .schema import anchors as check_anchors, landmarks as check_landmarks, fixture_kind, identifier, identity, number, points, source_hash, validate_template


PHASES = ('entry', 'body', 'exit')


def _arc(xy):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]


def _frame(xy, anchor):
    origin = xy[anchor[1]]
    delta = xy[anchor[2]]-origin
    span = float(np.linalg.norm(delta))
    if span <= 1e-8:
        raise ValueError('body must have a positive anchor span')
    axis = delta/span
    basis = np.array([axis, [-axis[1], axis[0]]])
    return origin, basis, span


def _body(xy, anchor):
    body = xy[anchor[1]:anchor[2]+1]
    if np.any(np.diff(body[:, 0]) <= 1e-8):
        raise ValueError('body projection must be strictly monotone; move the phase anchors or choose another variant')
    return body


def _resample(xy, count=65):
    arc = _arc(xy)
    # Include original vertices: uniform resampling alone would cut small corners.
    at = np.unique(np.r_[arc, np.linspace(0., arc[-1], count)])
    return np.column_stack([np.interp(at, arc, xy[:, d]) for d in (0, 1)])


def _features(xy, anchor):
    result = []
    for name, a, b in zip(PHASES, anchor[:-1], anchor[1:]):
        part = xy[a:b+1]
        result.append(dict(phase_id=name, arc_length=float(_arc(part)[-1]),
            chord_length=float(np.linalg.norm(part[-1]-part[0])),
            start_heading_rad=float(np.arctan2(*(part[1]-part[0])[::-1])),
            end_heading_rad=float(np.arctan2(*(part[-1]-part[-2])[::-1]))))
    return result


def build_template(references, *, stroke_type, variant='standard', style_id='unspecified',
                   limits=None, allow_unreviewed=False):
    """Choose a representative example; never average unaligned local features."""
    identifier(stroke_type, 'stroke type')
    identifier(variant, 'variant')
    if not isinstance(references, list) or not 1 <= len(references) <= 128:
        raise ValueError('provide 1..128 references')
    normalized, canonical, descriptors = [], [], []
    seen = set()
    for ref in references:
        ref = copy.deepcopy(ref)
        if ref.get('type') != stroke_type or ref.get('variant') != variant:
            raise ValueError('reference type or variant differs from the template')
        if ref.get('review_status') not in ('unreviewed', 'confirmed'):
            raise ValueError('reference needs a review status')
        if ref['review_status'] != 'confirmed' and not allow_unreviewed:
            raise ValueError('reference requires manual review or explicit allow_unreviewed')
        source_hash(ref.get('source_sha256'))
        rid = ref.get('reference_id')
        if not isinstance(rid, str) or not rid or rid in seen:
            raise ValueError('references need unique reference_id values')
        seen.add(rid)
        xy = points(ref.get('xy_px'))
        anchor = check_anchors(ref.get('anchors'), len(xy))
        features = check_landmarks(ref.get('landmarks'), anchor)
        width = number(ref.get('width_px'), 'reference width', positive=True)
        origin, basis, span = _frame(xy, anchor)
        local = (xy-origin) @ basis.T / width
        body = local[anchor[1]:anchor[2]+1] if features else _body(local, anchor)
        phase = _features(local, anchor)
        width_profiles = {}
        for descriptor in phase:
            measured = ref.get('phase_width_measurements', {}).get(descriptor['phase_id'])
            valid = [] if measured is None else [s['width_px']/width for s in measured['samples']
                                                if s['width_px'] is not None]
            descriptor['mean_width_reference_width'] = float(np.mean(valid)) if valid else None
            descriptor['visible_width_samples'] = len(valid)
            if measured is not None:
                width_profiles[descriptor['phase_id']] = dict(parameterization='within_phase_xy_arclength',
                    samples=[dict(u=s['u'], width_reference_width=None if s['width_px'] is None
                                  else s['width_px']/width, reason=s['reason']) for s in measured['samples']])
        middle = (np.interp(_arc(body)[-1]/2, _arc(body), body[:, 1]) if features
                  else np.interp(span/width/2, body[:, 0], body[:, 1]))
        descriptors.append([span/width, phase[0]['arc_length'], phase[2]['arc_length'], float(middle)])
        ref['xy_px'], ref['anchors'], ref['width_px'] = xy.tolist(), anchor, width
        canonical.append(ref)
        normalized.append(dict(reference_id=rid, xy=local.tolist(), anchors=anchor,
                               descriptors=phase, width_profiles=width_profiles, landmarks=features))
    names = [[p['name'] for p in p['landmarks']] for p in normalized]
    if any(n != names[0] for n in names):
        raise ValueError('reference landmark names and order must agree')
    values = np.asarray(descriptors)
    scale = np.maximum(np.median(np.abs(values-np.median(values, axis=0)), axis=0), .1)
    z = values/scale
    scores = np.linalg.norm(z[:, None]-z[None, :], axis=2).sum(axis=1)
    chosen = int(np.argmin(scores))
    aspect = descriptors[chosen][0]
    if limits is not None and (not isinstance(limits, dict)
            or set(limits)-{'body_aspect_range', 'max_bend_widths'}):
        raise ValueError('unknown design limits')
    limits = dict(body_aspect_range=[aspect*.3, aspect*3.], max_bend_widths=2.) | (limits or {})
    fixtures = {fixture_kind(p) for r in canonical for p in (r, r.get('annotation_provenance'))}
    level = ('teaching_rule_candidate' if 'teaching_reconstruction' in fixtures else
             'font_geometry_fixture' if 'font_fixture' in fixtures else
             'synthetic_geometry_fixture' if 'synthetic_fixture' in fixtures else
             'manual_geometry_reviewed' if all(r['review_status'] == 'confirmed' for r in canonical)
             else 'unreviewed_geometry')
    result = dict(schema_version=1, role='stroke_template', type=stroke_type, variant=variant,
        style_id=style_id, units='reference_width', prototype=normalized[chosen],
        adaptation='piecewise_landmarks' if names[0] else 'single_body',
        references=canonical, limits=copy.deepcopy(limits),
        observed=dict(body_aspect_range=[float(values[:, 0].min()), float(values[:, 0].max())]),
        evidence=dict(level=level, physical_validation=False,
            note='Image geometry only; width scaling and motion/magnetic transfer require paired trials.'))
    result['template_id'] = identity(result, 'template_id')
    return validate_template(result)


def _rotate_between(points_, before, after):
    angle = np.arctan2(after[1], after[0])-np.arctan2(before[1], before[0])
    c, s = np.cos(angle), np.sin(angle)
    return points_ @ np.array([[c, s], [-s, c]])


def _join_angles(parts):
    head, body, tail = parts
    vectors = [(head[-1]-head[-2], body[1]-body[0]),
               (body[-1]-body[-2], tail[1]-tail[0])]
    return [float(np.arctan2(a[0]*b[1]-a[1]*b[0], np.dot(a, b))) for a, b in vectors]


def _finish(template, parts, baseline, parameters, join_diagnostics, feature_landmarks=()):
    xy = np.concatenate(parts)
    phase_id, phase_u, ranges = [], [], []
    offset = 0
    for name, part in zip(PHASES, parts):
        arc = _arc(part)
        phase_id.extend([name]*len(part))
        phase_u.extend((arc/arc[-1]).tolist())
        ranges.append(dict(phase_id=name, first=offset, last=offset+len(part)-1))
        offset += len(part)
    arc = _arc(xy)
    flags = ['image_geometry_candidate_not_measured_motion', 'physical_width_transfer_unverified']
    observed = template['observed']['body_aspect_range']
    if parameters['body_aspect'] < observed[0]-1e-8 or parameters['body_aspect'] > observed[1]+1e-8:
        flags.append('outside_observed_reference_aspect_range')
    features = []
    for feature in feature_landmarks:
        index = len(parts[0])+feature['body_index']
        features.append(dict(name=feature['name'], index=index, xy_px=xy[index].tolist(), s=float(arc[index]/arc[-1])))
    return dict(xy_px=xy.tolist(), baseline_xy_px=np.asarray(baseline).tolist(),
        s=(arc/arc[-1]).tolist(), arc_length_px=arc.tolist(), phase_id=phase_id,
        phase_u=phase_u, phase_parameterization='within_phase_xy_arclength', phase_ranges=ranges,
        join_diagnostics=join_diagnostics, feature_landmarks=features, parameters=parameters, review_flags=flags)


def adapt_stroke(template, target_xy_px, target_anchors, *, width_px, landmarks=None):
    """Fit body span and one bounded bend; ends receive only similarity transforms."""
    template = validate_template(template)
    target = points(target_xy_px)
    anchor = check_anchors(target_anchors, len(target))
    width = number(width_px, 'target width', positive=True)
    if template.get('adaptation') == 'piecewise_landmarks':
        from .piecewise import adapt_piecewise
        return adapt_piecewise(template, target, anchor, width, landmarks)
    origin, basis, span = _frame(target, anchor)
    guide = (target-origin) @ basis.T
    target_body = _body(guide, anchor)
    prototype = template['prototype']
    local = np.asarray(prototype['xy'], float)
    a = prototype['anchors']
    body = _body(local, a)
    original_span = body[-1, 0]-body[0, 0]
    aspect = span/width
    low, high = template['limits']['body_aspect_range']
    if not low <= aspect <= high:
        raise ValueError(f'body aspect {aspect:.4g} outside configured range [{low:.4g}, {high:.4g}]')
    # Equal-progress samples avoid dependence on how densely a user clicked.
    u = np.linspace(0., 1., 65)
    base_y = np.interp(u, body[:, 0]/original_span, body[:, 1])
    guide_y = np.interp(u*span, target_body[:, 0], target_body[:, 1])/width
    bump = 4*u*(1-u)
    bend = float(np.dot(bump, guide_y-base_y)/np.dot(bump, bump))
    if abs(bend) > template['limits']['max_bend_widths']:
        raise ValueError(f'body bend {bend:.4g} exceeds configured bend limit')
    at = np.unique(np.r_[u, body[:, 0]/original_span])
    adapted_body = np.column_stack([at*span,
        (np.interp(at, body[:, 0]/original_span, body[:, 1])+bend*4*at*(1-at))*width])
    head = _rotate_between((local[:a[1]+1]-local[a[1]])*width,
        body[1]-body[0], adapted_body[1]-adapted_body[0])+adapted_body[0]
    tail = _rotate_between((local[a[2]:]-local[a[2]])*width,
        body[-1]-body[-2], adapted_body[-1]-adapted_body[-2])+adapted_body[-1]
    parts = [_resample(part) @ basis+origin for part in (head, adapted_body, tail)]
    reference_joins = _join_angles([local[:a[1]+1], body, local[a[2]:]])
    adapted_joins = _join_angles(parts)
    join_diagnostics = dict(policy='preserve_reference_join_angles', reference_rad=reference_joins,
        adapted_rad=adapted_joins, angle_change_rad=[float((new-old+np.pi)%(2*np.pi)-np.pi)
            for old, new in zip(reference_joins, adapted_joins)])
    baseline_local = local*width
    baseline_local[:, 0] *= span/(original_span*width)
    baseline = baseline_local @ basis+origin
    return _finish(template, parts, baseline, dict(width_px=width, body_span_px=span, body_aspect=aspect,
            body_stretch_ratio=aspect/original_span, bend_widths=bend,
            heading_rad=float(np.arctan2(basis[0, 1], basis[0, 0]))), join_diagnostics)


def preserve_stroke(xy_px, anchor, *, landmarks=None):
    """An explicit manual result is authoritative geometry, not re-templated data."""
    xy = points(xy_px)
    anchor = check_anchors(anchor, len(xy))
    features = check_landmarks(landmarks, anchor)
    arc = _arc(xy)
    phase_id, phase_u, ranges = [], np.zeros(len(xy)), []
    for phase, first, last in zip(PHASES, anchor[:-1], anchor[1:]):
        length = arc[last]-arc[first]
        if length <= 0:
            raise ValueError('manual phase must have positive length')
        phase_u[first:last+1] = (arc[first:last+1]-arc[first])/length
        ranges.append(dict(phase_id=phase, first=first, last=last))
    for i in range(len(xy)):
        phase_id.append('entry' if i < anchor[1] else 'body' if i < anchor[2] else 'exit')
    return dict(xy_px=xy.tolist(), baseline_xy_px=xy.tolist(), s=(arc/arc[-1]).tolist(),
        arc_length_px=arc.tolist(), phase_id=phase_id, phase_u=phase_u.tolist(), phase_ranges=ranges,
        feature_landmarks=[dict(name=p['name'], index=p['index'], xy_px=xy[p['index']].tolist(),
            s=float(arc[p['index']]/arc[-1])) for p in features],
        phase_parameterization='within_phase_xy_arclength_following_phase_owns_boundary',
        parameters=dict(body_stretch_ratio=1., bend_widths=0.),
        generation_method='manual_geometry_preserved', review_flags=['manual_geometry_revision',
            'image_geometry_candidate_not_measured_motion'])
