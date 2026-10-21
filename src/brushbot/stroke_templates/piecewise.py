"""Landmark-constrained compound strokes: separate spans for turns and hooks."""
import numpy as np

from .schema import landmarks as check_landmarks
from .geometry import _arc, _finish, _frame, _join_angles, _resample, _rotate_between


def adapt_piecewise(template, target, anchor, width, landmarks):
    prototype = template['prototype']
    source = np.asarray(prototype['xy'], float)
    a = prototype['anchors']
    expected = prototype.get('landmarks', [])
    features = check_landmarks(landmarks, anchor)
    if not expected or [p['name'] for p in expected] != [p['name'] for p in features]:
        raise ValueError('compound template requires matching named landmarks')
    ref_knots = [a[1], *[p['index'] for p in expected], a[2]]
    new_knots = [anchor[1], *[p['index'] for p in features], anchor[2]]
    chunks, ratios, bends, mapped_features = [], [], [], []
    for i, (first, last, start, end) in enumerate(zip(ref_knots[:-1], ref_knots[1:], new_knots[:-1], new_knots[1:])):
        ref = source[first:last+1]
        guide = target[start:end+1]
        ref_origin, ref_basis, ref_span = _frame(ref, [0, 0, len(ref)-1, len(ref)-1])
        new_origin, new_basis, new_span = _frame(guide, [0, 0, len(guide)-1, len(guide)-1])
        ratio = new_span/(ref_span*width)
        if not .3 <= ratio <= 3.:
            raise ValueError('compound segment stretch outside preset range [.3, 3]')
        dense = _resample(ref)
        u = _arc(dense)/_arc(dense)[-1]
        local = (dense-ref_origin) @ ref_basis.T
        local[:, 0] *= new_span/ref_span
        local[:, 1] *= width
        guide_local = (guide-new_origin) @ new_basis.T
        guide_u = _arc(guide)/_arc(guide)[-1]
        bump = 4*u*(1-u)
        bend = float(np.dot(bump, np.interp(u, guide_u, guide_local[:, 1])-local[:, 1])/
                     (width*np.dot(bump, bump)))
        if abs(bend) > template['limits']['max_bend_widths']:
            raise ValueError('compound segment bend exceeds configured limit')
        local[:, 1] += width*bend*bump
        mapped = local @ new_basis+new_origin
        mapped[0], mapped[-1] = guide[0], guide[-1]
        chunks.append(mapped if i == 0 else mapped[1:])
        ratios.append(float(ratio)); bends.append(bend)
        if i < len(features):
            mapped_features.append(dict(name=features[i]['name'], body_index=sum(len(c) for c in chunks)-1))
    body = np.concatenate(chunks)
    ref_body = source[a[1]:a[2]+1]
    head = _rotate_between((source[:a[1]+1]-source[a[1]])*width,
        ref_body[1]-ref_body[0], body[1]-body[0])+body[0]
    tail = _rotate_between((source[a[2]:]-source[a[2]])*width,
        ref_body[-1]-ref_body[-2], body[-1]-body[-2])+body[-1]
    parts = [_resample(head), body, _resample(tail)]
    old_angles = _join_angles([source[:a[1]+1], ref_body, source[a[2]:]])
    new_angles = _join_angles(parts)
    joins = dict(policy='preserve_reference_join_angles', reference_rad=old_angles, adapted_rad=new_angles,
        angle_change_rad=[float((n-o+np.pi)%(2*np.pi)-np.pi) for o, n in zip(old_angles, new_angles)])
    origin, basis, span = _frame(target, anchor)
    ref_span = float(np.linalg.norm(source[a[2]]-source[a[1]]))
    aspect = span/width
    if not template['limits']['body_aspect_range'][0] <= aspect <= template['limits']['body_aspect_range'][1]:
        raise ValueError('compound body aspect outside configured range')
    baseline = source*width
    baseline[:, 0] *= span/(ref_span*width)
    baseline = baseline @ basis+origin
    result = _finish(template, parts, baseline, dict(width_px=width, body_span_px=span, body_aspect=aspect,
        body_stretch_ratio=aspect/ref_span, bend_widths=max(map(abs, bends)),
        segment_stretch_ratios=ratios, heading_rad=float(np.arctan2(basis[0, 1], basis[0, 0]))),
        joins, mapped_features)
    result['generation_method'] = 'piecewise_landmark_template'
    return result
