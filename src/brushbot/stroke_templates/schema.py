"""Editable annotations and immutable template identities, independent of V3."""
from __future__ import annotations

import copy
import hashlib
import json
import re

import numpy as np


def identity(value, key):
    payload = {k: v for k, v in value.items() if k != key}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def fixture_kind(provenance):
    """Revision/confirmation cannot turn a disclosed fixture into observed data."""
    kinds = set()
    while isinstance(provenance, dict):
        kind = provenance.get('image_kind', 'unspecified')
        source = provenance.get('source_kind')
        if kind == 'font_fixture' or (source == 'font_prior' and kind == 'unspecified'):
            kinds.add('font_fixture')
        if kind == 'synthetic_fixture' or source == 'synthetic_fixture':
            kinds.add('synthetic_fixture')
        if kind == 'teaching_reconstruction' or source == 'teaching_rule_reconstruction':
            kinds.add('teaching_reconstruction')
        provenance = provenance.get('original_provenance')
    return next((k for k in ('teaching_reconstruction','font_fixture','synthetic_fixture') if k in kinds),None)


def number(value, name, *, positive=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (float, int, np.number)):
        raise ValueError(f'{name} must be a finite number')
    value = float(value)
    if not np.isfinite(value) or (positive and value <= 0):
        raise ValueError(f'{name} must be finite'+(' and positive' if positive else ''))
    return value


def identifier(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value):
        raise ValueError(f'{name} must be a lowercase identifier')
    return value


def points(value):
    try:
        raw = np.asarray(value)
        if raw.dtype.kind not in 'iuf':
            raise ValueError('non-numeric XY')
        xy = raw.astype(float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('XY must contain finite numeric pairs') from exc
    if (xy.ndim != 2 or xy.shape[1] != 2 or not 4 <= len(xy) <= 2048
            or not np.isfinite(xy).all() or np.max(np.abs(xy)) > 1e9):
        raise ValueError('XY must contain 4..2048 finite numeric pairs')
    if np.any(np.linalg.norm(np.diff(xy, axis=0), axis=1) <= 1e-10):
        raise ValueError('annotation XY contains duplicate adjacent points')
    return xy


def anchors(value, count):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) is not int for v in value)
            or not 0 == value[0] < value[1] < value[2] < value[3] == count-1):
        raise ValueError('anchors must be four ordered integer indices: first, body start, body end, last')
    return list(value)


def source_hash(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('source_sha256 must be a SHA-256 hex digest')


def landmarks(value, anchor):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError('landmarks must be a list of at most 16 features')
    result, names, last = [], set(), anchor[1]
    for item in value:
        if not isinstance(item, dict) or set(item) != {'name', 'index'}:
            raise ValueError('landmark requires name and index')
        name, index = identifier(item['name'], 'landmark name'), item['index']
        if type(index) is not int or not last < index < anchor[2] or name in names:
            raise ValueError('landmarks must be ordered, unique and inside the body anchors')
        result.append(dict(name=name, index=index)); names.add(name); last=index
    return result


def validate_annotation(annotation):
    """Canonicalize an editable annotation; every content edit gets a new ID."""
    if not isinstance(annotation, dict):
        raise ValueError('annotation must be an object')
    value = copy.deepcopy(annotation)
    if value.get('schema_version') != 1 or value.get('role') != 'stroke_annotation':
        raise ValueError('unsupported annotation schema')
    source_hash(value.get('source_sha256'))
    size = value.get('image_size_px')
    if (not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v < 3 for v in size)
            or size[0]*size[1] > 40_000_000):
        raise ValueError('invalid image_size_px')
    if not isinstance(value.get('character'), str) or len(value['character']) != 1:
        raise ValueError('character must be one character')
    if not isinstance(value.get('provenance'), dict):
        raise ValueError('annotation needs provenance')
    strokes = value.get('strokes')
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 128:
        raise ValueError('annotation needs 1..128 strokes')
    seen = set()
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise ValueError('stroke must be an object')
        sid = identifier(stroke.get('id'), 'stroke id')
        if sid in seen:
            raise ValueError('duplicate stroke id')
        seen.add(sid)
        identifier(stroke.get('type'), 'stroke type')
        identifier(stroke.get('variant'), 'variant')
        xy = points(stroke.get('xy_px'))
        if np.any(xy < -.5) or np.any(xy > np.asarray(size)-.5):
            raise ValueError('annotation coordinates lie outside the image')
        stroke['xy_px'] = xy.tolist()
        stroke['anchors'] = anchors(stroke.get('anchors'), len(xy))
        if 'landmarks' in stroke:
            stroke['landmarks'] = landmarks(stroke['landmarks'], stroke['anchors'])
        if stroke.get('path_mode', 'template') not in ('template', 'preserve'):
            raise ValueError('path_mode must be template or preserve')
        if stroke.get('review_status') not in ('unreviewed', 'confirmed'):
            raise ValueError('invalid review_status')
        if not isinstance(stroke.get('notes', ''), str):
            raise ValueError('stroke notes must be text')
        if stroke.get('width_hint_px') is not None:
            stroke['width_hint_px'] = number(stroke['width_hint_px'], 'width hint', positive=True)
    value['annotation_id'] = identity(value, 'annotation_id')
    return value


def validate_template(template):
    """Reject stale/tampered immutable models before any adaptation."""
    if not isinstance(template, dict):
        raise ValueError('template must be an object')
    value = copy.deepcopy(template)
    if value.get('schema_version') != 1 or value.get('role') != 'stroke_template':
        raise ValueError('unsupported template schema')
    if value.get('template_id') != identity(value, 'template_id'):
        raise ValueError('template identity mismatch')
    identifier(value.get('type'), 'template type')
    identifier(value.get('variant'), 'variant')
    if not isinstance(value.get('style_id'), str) or not value['style_id'].strip():
        raise ValueError('template needs style_id')
    prototype = value.get('prototype', {})
    xy = points(prototype.get('xy'))
    anchors(prototype.get('anchors'), len(xy))
    landmarks(prototype.get('landmarks'), prototype['anchors'])
    if value.get('adaptation', 'single_body') not in ('single_body', 'piecewise_landmarks'):
        raise ValueError('unsupported template adaptation')
    if value.get('units') != 'reference_width':
        raise ValueError('template units must be reference_width')
    limits = value.get('limits', {})
    interval = limits.get('body_aspect_range')
    if not isinstance(interval, list) or len(interval) != 2:
        raise ValueError('template needs a body aspect range')
    low, high = [number(v, 'aspect limit', positive=True) for v in interval]
    if low >= high:
        raise ValueError('invalid body aspect range')
    number(limits.get('max_bend_widths'), 'bend limit', positive=True)
    if not isinstance(value.get('references'), list) or not value['references']:
        raise ValueError('template needs references')
    if 'guide_trace' in value:
        guide = value['guide_trace']
        if (not isinstance(guide, dict) or guide.get('schema_version') != 1 or
                guide.get('coordinate_source') != 'ordered_white_guide_trace_simplified_per_phase' or
                guide.get('review_status') != 'unreviewed' or len(value['references']) != 1):
            raise ValueError('invalid guide trace metadata')
        source_hash(guide.get('source_sha256')); source_hash(guide.get('raw_trace_sha256'))
        size = guide.get('image_size_px')
        if (not isinstance(size, list) or len(size) != 2 or
                any(type(n) is not int or n<3 for n in size) or size[0]*size[1]>40_000_000):
            raise ValueError('invalid guide image size')
        source_xy = points(guide.get('source_points_image_px'))
        ref = value['references'][0]; ref_xy = points(ref.get('xy_px'))
        expected = source_xy.copy(); expected[:, 1] = size[1]-1-expected[:, 1]
        if (np.any(source_xy<0) or np.any(source_xy>np.array(size)-1) or
                expected.shape != ref_xy.shape or not np.array_equal(expected, ref_xy) or
                ref.get('source_sha256') != guide['source_sha256'] or
                ref.get('reference_id') != prototype.get('reference_id') or
                ref.get('anchors') != prototype['anchors']):
            raise ValueError('guide/reference image coordinate binding mismatch')
        a = anchors(ref.get('anchors'), len(ref_xy))
        delta = ref_xy[a[2]]-ref_xy[a[1]]; span = np.linalg.norm(delta)
        if span <= 1e-8:
            raise ValueError('guide body span is zero')
        axis = delta/span
        normalized = (ref_xy-ref_xy[a[1]]) @ np.array([axis, [-axis[1], axis[0]]]).T / number(ref.get('width_px'), 'guide width', positive=True)
        if normalized.shape != xy.shape or not np.allclose(normalized, xy, rtol=0, atol=1e-8):
            raise ValueError('guide prototype does not match source reference')
        tolerance = number(guide.get('simplify_tolerance_px'), 'guide simplify tolerance', positive=True)
        deviation = number(guide.get('max_raw_point_deviation_px'), 'guide deviation')
        if (not 0 <= deviation <= tolerance+1e-8 or type(guide.get('raw_point_count')) is not int or
                not len(xy) <= guide['raw_point_count'] <= 2048):
            raise ValueError('invalid guide simplification metadata')
        if value.get('evidence', {}).get('level') != 'teaching_rule_candidate' or value['evidence'].get('physical_validation') is not False:
            raise ValueError('guide must remain a provisional teaching candidate')
    if 'teaching' in value:
        teaching=value['teaching']
        if (not isinstance(teaching,dict) or teaching.get('schema_version')!=1 or
                teaching.get('coordinate_source')!='manually_authored_rule_based_curves' or
                teaching.get('review_status') not in ('unreviewed','confirmed')):
            raise ValueError('invalid teaching reconstruction metadata')
        widths=teaching.get('relative_width')
        if not isinstance(widths,list) or len(widths)!=len(xy):
            raise ValueError('teaching relative width must match prototype points')
        if any(not 0 <= number(w,'relative width') <= 4 for w in widths) or max(widths)<=0:
            raise ValueError('invalid teaching relative width')
        events=teaching.get('events')
        if not isinstance(events,list) or not 4 <= len(events) <= 64:
            raise ValueError('teaching needs 4..64 events')
        names=set();previous=-1
        arc=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
        phase_anchors=prototype['anchors']
        for event in events:
            if not isinstance(event,dict):
                raise ValueError('teaching event must be an object')
            name=identifier(event.get('name'),'event name');index=event.get('index')
            if name in names or type(index) is not int or not 0 <= index < len(xy) or index < previous:
                raise ValueError('invalid teaching event index or name')
            names.add(name);previous=index
            phase=0 if index<phase_anchors[1] else 1 if index<phase_anchors[2] else 2
            first,last=phase_anchors[phase:phase+2]
            position=np.asarray(event.get('xy'),float)
            if (event.get('phase_id') != ('entry','body','exit')[phase] or
                    abs(number(event.get('s'),'event s')-arc[index]/arc[-1])>1e-8 or
                    abs(number(event.get('phase_u'),'event phase u')-(arc[index]-arc[first])/(arc[last]-arc[first]))>1e-8 or
                    position.shape!=(2,) or not np.isfinite(position).all() or
                    not np.allclose(position,xy[index],rtol=0,atol=1e-8)):
                raise ValueError('invalid teaching event position')
        source_hash(teaching.get('source_illustration_sha256'))
    return value
