"""Image-bound editable stroke candidates and measured reference records."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from brushbot.character_xy.processing import prepare_image, processed_to_original
from brushbot.xy_comparison.geometry import resample_path
from .schema import identity, validate_annotation
from .widths import measure_widths
from .hints import YONG_MEDIANS_SHA256, YONG_STROKES


def load_font_record(character, graphics_path):
    with Path(graphics_path).open(encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get('character') == character:
                return record
    raise ValueError(f'character {character!r} is absent from the dictionary; use --no-prior for manual tracing')


def _classify(xy):
    delta = np.abs(xy[-1]-xy[0])
    length = np.linalg.norm(np.diff(xy, axis=0), axis=1).sum()
    chord = np.linalg.norm(delta)
    if chord <= 1e-8 or length/chord > 1.35:
        return 'unknown'
    if delta[0] >= 2.5*delta[1]:
        return 'heng'
    if delta[1] >= 2.5*delta[0]:
        return 'shu'
    return 'unknown'


def prepare_annotation(image_path, character, *, font_record=None, no_prior=False, font_transform=None,
                       image_kind='user_supplied'):
    """Register a known glyph prior, or initialize a manually traceable draft."""
    if not isinstance(character, str) or len(character) != 1:
        raise ValueError('character must be a single character')
    prepared = prepare_image(image_path)
    size = prepared['preprocessing']['exif_image_size_px']
    rows, cols = np.nonzero(prepared['mask'])
    box = processed_to_original([[cols.min(), rows.max()], [cols.max(), rows.min()]], prepared['preprocessing'])
    box[:, 1] = size[1]-1-box[:, 1]
    low, high = box
    strokes = []
    if no_prior:
        centre = (low+high)/2
        start, end = centre.copy(), centre.copy()
        axis = int(np.argmax(high-low))
        start[axis], end[axis] = low[axis], high[axis]
        if np.linalg.norm(end-start) < 1:
            raise ValueError('ink region too small for manual path initialization')
        paths = [np.linspace(start, end, 21)]
        source_kind = 'manual_image'
        prior = None
    else:
        if (not isinstance(font_record, dict) or font_record.get('character') != character
                or not isinstance(font_record.get('medians'), list) or not font_record['medians']):
            raise ValueError('font prior must match the character and contain ordered medians')
        medians = [np.asarray(path, float) for path in font_record['medians']]
        combined = np.concatenate(medians)
        if combined.ndim != 2 or combined.shape[1] != 2 or not np.isfinite(combined).all():
            raise ValueError('invalid font prior coordinates')
        if character == '永' and hashlib.sha256(json.dumps(font_record['medians'], separators=(',', ':')).encode()).hexdigest() != YONG_MEDIANS_SHA256:
            raise ValueError('Yong landmark hints do not match this dictionary median version; use --no-prior or the bundled dictionary')
        font_low, font_high = combined.min(axis=0), combined.max(axis=0)
        if font_transform is None:
            extent = font_high-font_low
            active = extent > 1e-8
            if not active.any():
                raise ValueError('font prior has no positive length')
            scale = float(np.min((high-low)[active]/extent[active]))
            offset = (low+high)/2-scale*(font_low+font_high)/2
            registration = 'uniform_median_bbox_initialization_requires_review'
        else:
            scale = float(font_transform['scale'])
            offset = np.asarray(font_transform['offset_xy_px'], float)
            if not np.isfinite(scale) or scale <= 0 or offset.shape != (2,) or not np.isfinite(offset).all():
                raise ValueError('invalid font transform')
            registration = 'explicit_font_fixture_transform_not_image_registration'
        paths = [resample_path(path*scale+offset, 21) for path in medians]
        if character == '永' and len(medians) == len(YONG_STROKES):
            paths = []
            for path in medians:
                arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
                at = np.unique(np.r_[arc, np.linspace(0., arc[-1], 21)])
                paths.append(np.column_stack([np.interp(at, arc, path[:, d]) for d in (0, 1)])*scale+offset)
        source_kind = 'font_prior'
        prior = dict(record_sha256=identity(font_record, 'unused'),
            source_url='https://github.com/skishore/makemeahanzi', registration=registration,
            scale=scale, offset_xy_px=offset.tolist())
        if character == '永' and len(paths) == len(YONG_STROKES):
            prior['stroke_hint_source'] = 'explicit_yong_structure_v1_not_font_type_labels'
            prior['stroke_hint_medians_sha256'] = YONG_MEDIANS_SHA256
    for i, xy in enumerate(paths):
        a = [0, 3, 17, 20]
        stroke_type, display_name, features = ('unknown' if no_prior else _classify(xy)), '', []
        if not no_prior and character == '永' and len(paths) == len(YONG_STROKES):
            stroke_type, display_name, hints = YONG_STROKES[i]
            arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
            a = [0, max(1, int(np.argmin(abs(arc-.1*arc[-1])))),
                 min(len(xy)-2, int(np.argmin(abs(arc-.9*arc[-1])))), len(xy)-1]
            features = [dict(name=name, index=int(np.argmin(np.linalg.norm(
                xy-(medians[i][index]*scale+offset), axis=1)))) for name, index in hints]
        strokes.append(dict(id=f's{i+1:02}', type=stroke_type, display_name=display_name,
            variant='standard', xy_px=xy.tolist(), anchors=a, landmarks=features,
            review_status='unreviewed', notes='几何候选：可保留正确路径，仅修正局部。'))
    return validate_annotation(dict(schema_version=1, role='stroke_annotation',
        source_sha256=prepared['source_sha256'], image_size_px=size, character=character,
        provenance=dict(source_kind=source_kind, image_kind=image_kind, prior=prior), strokes=strokes,
        review_flags=['not_image_recovered_stroke_order', 'manual_phase_and_stroke_review_required']))


def load_bound_image(annotation, image_path):
    annotation = validate_annotation(annotation)
    if hashlib.sha256(Path(image_path).read_bytes()).hexdigest() != annotation['source_sha256']:
        raise ValueError('image source SHA-256 differs from annotation')
    prepared = prepare_image(image_path)
    if prepared['source_sha256'] != annotation['source_sha256']:
        raise ValueError('image source changed during preparation')
    if prepared['preprocessing']['exif_image_size_px'] != annotation['image_size_px']:
        raise ValueError('image size differs from annotation')
    return annotation, prepared


def measure_annotation(annotation, prepared):
    result = {}
    for stroke in annotation['strokes']:
        a = stroke['anchors']
        other_paths = [s['xy_px'] for s in annotation['strokes'] if s['id'] != stroke['id']]
        phases = {name: measure_widths(prepared['mask'], stroke['xy_px'][first:last+1],
            other_paths=other_paths, image_size_px=annotation['image_size_px'])
            for name, first, last in zip(('entry', 'body', 'exit'), a[:-1], a[1:])}
        measurement = phases['body']
        hint = stroke.get('width_hint_px')
        result[stroke['id']] = dict(width_px=hint if hint is not None else measurement['width_px'],
            width_source='manual_hint' if hint is not None else 'normal_scan_candidate',
            width_measurement=measurement, phase_width_measurements=phases)
    return result


def reference_from_annotation(annotation, image_path, stroke_id):
    annotation, prepared = load_bound_image(annotation, image_path)
    selected = [s for s in annotation['strokes'] if s['id'] == stroke_id]
    if not selected:
        raise ValueError(f'unknown stroke id: {stroke_id}')
    stroke = selected[0]
    width = measure_annotation(annotation, prepared)[stroke_id]
    if width['width_px'] is None:
        raise ValueError('no visible body width; provide an explicit width_hint_px after review')
    value = dict(annotation_id=annotation['annotation_id'], source_sha256=annotation['source_sha256'],
        stroke_id=stroke_id, type=stroke['type'], variant=stroke['variant'], xy_px=stroke['xy_px'],
        anchors=stroke['anchors'], review_status=stroke['review_status'],
        landmarks=stroke.get('landmarks', []),
        source_kind=annotation['provenance']['source_kind'], character=annotation['character'],
        image_kind=annotation['provenance'].get('image_kind', 'unspecified'),
        annotation_provenance=annotation['provenance'], **width)
    value['reference_id'] = identity(value, 'reference_id')
    return value
