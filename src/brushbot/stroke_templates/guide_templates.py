"""Promote frozen, source-bound teaching guides into phase-aware XY models."""
from __future__ import annotations

import csv
import hashlib
import html
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageFilter

from brushbot.image_geometry import simplify_path
from brushbot.xy_comparison.geometry import _distance_to_path
from .bundle import publish, read_json, write_json
from .catalog import _local_file, _verify
from .geometry import PHASES, build_template
from .schema import anchors, identifier, identity, landmarks, number, points, validate_template
from .widths import measure_widths


def _prepare(directory, manifest, descriptor):
    legacy = isinstance(descriptor, str)
    if legacy:
        variant = descriptor
        if variant not in ('long', 'short'):
            raise ValueError('unknown legacy guide descriptor')
        descriptor = dict(id='heng_'+variant, type='heng', variant=variant,
            name='长横' if variant=='long' else '短横', source_file=variant+'_source.jpg', trace_file=variant+'_trace.json',
            legacy_trace_id=variant)
    for key in ('id', 'type', 'variant'):
        identifier(descriptor.get(key), 'guide '+key)
    if not isinstance(descriptor.get('name'), str) or not descriptor['name'].strip():
        raise ValueError('guide needs a name')
    filenames = [descriptor.get('source_file'), descriptor.get('trace_file')]
    if any(not isinstance(name, str) for name in filenames):
        raise ValueError('guide source/trace filenames are missing')
    if not set(filenames) <= manifest['files'].keys():
        raise ValueError('guide source and trace must both be manifested')
    source, trace_bytes = [_local_file(directory, name).read_bytes() for name in filenames]
    for name, raw in zip(filenames, (source, trace_bytes)):
        if hashlib.sha256(raw).hexdigest() != manifest['files'][name]:
            raise ValueError('guide checksum changed during import')
    import json
    trace = json.loads(trace_bytes)
    digest = hashlib.sha256(source).hexdigest()
    if (trace.get('id') != descriptor.get('legacy_trace_id', descriptor['id']) or trace.get('source_sha256') != digest or
            trace.get('review_status') != 'unreviewed' or
            trace.get('role') != 'teaching_guide_trace_candidate_not_measured_motion' or
            trace.get('method') != 'manually_ordered_waypoints_with_white_guide_pixel_tracking' or
            any(trace.get(key, descriptor[key] if legacy else None) != descriptor[key] for key in ('type', 'variant'))):
        raise ValueError('unsupported or unbound guide trace')
    for field in ('article_url', 'source_url'):
        if urlparse(trace.get(field, '')).scheme not in ('https', 'http'):
            raise ValueError('guide sources need an HTTP(S) URL')
    with Image.open(BytesIO(source)) as image:
        if image.width*image.height > 40_000_000 or list(image.size) != trace.get('image_size_px'):
            raise ValueError('guide image size mismatch')
        grey = image.convert('L')
    size = np.array(grey.size)
    raw_xy = points(trace.get('xy_px'))
    source_xy = points(trace.get('source_points_image_px'))
    expected = source_xy.copy(); expected[:, 1] = size[1]-1-expected[:, 1]
    if raw_xy.shape != expected.shape or not np.array_equal(raw_xy, expected):
        raise ValueError('guide image/Cartesian XY mapping mismatch')
    if np.any(source_xy < 0) or np.any(source_xy > size-1):
        raise ValueError('guide coordinates outside source image')
    crop = trace.get('box')
    if not isinstance(crop, list) or len(crop) != 4:
        raise ValueError('guide needs its source image crop')
    crop = np.array([number(v, 'guide crop') for v in crop])
    if (np.any(crop[:2]<0) or np.any(crop[2:]>size) or np.any(crop[:2]>=crop[2:]) or
            np.any(source_xy<crop[:2]) or np.any(source_xy>crop[2:])):
        raise ValueError('invalid guide source crop')
    anchor = anchors(trace.get('anchors'), len(raw_xy))
    features = landmarks(trace.get('landmarks'), anchor)
    protected = sorted(set(anchor+[f['index'] for f in features]))
    chunks, mapping = [], {0: 0}
    count = 1
    for first, last in zip(protected[:-1], protected[1:]):
        chunk = simplify_path(raw_xy[first:last+1], .75)
        chunks.append(chunk if not chunks else chunk[1:])
        count += len(chunk)-1; mapping[last] = count-1
    xy = np.concatenate(chunks)
    new_anchor = [mapping[i] for i in anchor]
    new_features = [dict(name=f['name'], index=mapping[f['index']]) for f in features]
    # Fill the thin white teaching guide before scanning the diagram silhouette.
    # This is a normalization estimate, never an authored width/force profile.
    if trace.get('width_hint_px') is not None:
        width = number(trace['width_hint_px'], 'guide width hint', positive=True)
        basis = trace.get('width_hint_basis')
        if not isinstance(basis, str) or not basis.strip():
            raise ValueError('manual guide width needs its geometric basis')
        measurement = dict(width_px=width, method='manual_diagram_width_hint', basis=basis)
        width_source = 'manual_diagram_width_hint'
        width_normalization = dict(method=width_source, basis=basis, physical_scale_known=False)
    else:
        mask = Image.fromarray((np.asarray(grey)<100).astype('uint8')*255)
        mask = np.asarray(mask.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(9)))>0
        measurement = measure_widths(mask, raw_xy[anchor[1]:anchor[2]+1])
        if measurement['width_px'] is None or measurement['valid_count'] < 33:
            raise ValueError('guide diagram has insufficient visible body width')
        width_source = 'diagram_body_normal_scan_after_guide_gap_closing'
        width_normalization = dict(dark_threshold=100, close_filter_size_px=9,
            method='body_normal_scan_median_on_gap_closed_diagram', physical_scale_known=False)
    reference = dict(type=descriptor['type'], variant=descriptor['variant'], review_status='unreviewed',
        source_sha256=digest, xy_px=xy.tolist(), anchors=new_anchor,
        landmarks=new_features, width_px=measurement['width_px'], width_source=width_source,
        width_measurement=measurement, image_kind='teaching_reconstruction',
        source_kind='teaching_rule_reconstruction',
        width_definition='diagram_ink_width_normalization_candidate_not_contact_width_or_force')
    reference['reference_id'] = identity(reference, 'reference_id')
    model = build_template([reference], stroke_type=descriptor['type'], variant=descriptor['variant'],
                           style_id='kai_teaching_rules_v1', allow_unreviewed=True)
    image_points = xy.copy(); image_points[:, 1] = size[1]-1-image_points[:, 1]
    model['guide_trace'] = dict(schema_version=1, id=descriptor['id'], name=descriptor['name'],
        review_status='unreviewed', coordinate_source='ordered_white_guide_trace_simplified_per_phase',
        source_sha256=digest, source_url=trace['source_url'], article_url=trace['article_url'],
        raw_trace_sha256=hashlib.sha256(trace_bytes).hexdigest(), image_size_px=size.tolist(),
        source_crop_image_px=crop.tolist(),
        source_points_image_px=image_points.tolist(), raw_point_count=len(raw_xy),
        simplify_tolerance_px=.75,
        max_raw_point_deviation_px=float(max(_distance_to_path(raw_xy[a:b+1], xy[c:d+1]).max()
            for a, b, c, d in zip(anchor[:-1], anchor[1:], new_anchor[:-1], new_anchor[1:]))),
        stage_boundary_basis='manual_interpretation_not_measured_phase',
        width_normalization=width_normalization,
        writing_hint=trace.get('writing_hint', ''))
    model['template_id'] = identity(model, 'template_id')
    return validate_template(model), source, trace, trace_bytes


def _write_csv(path, model):
    ref = model['references'][0]; xy = np.array(ref['xy_px']); anchor = ref['anchors']
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['point_index', 'x_px', 'y_px', 's', 'phase_id', 'phase_u',
                         'x_reference_width', 'y_reference_width'])
        for i, point in enumerate(xy):
            phase = 0 if i<anchor[1] else 1 if i<anchor[2] else 2
            first, last = anchor[phase:phase+2]
            writer.writerow([i, *point, arc[i]/arc[-1], PHASES[phase],
                (arc[i]-arc[first])/(arc[last]-arc[first]), *model['prototype']['xy'][i]])


def import_guides(review_dir, output_dir):
    """Validate the entire review before publishing an immutable template batch."""
    directory = Path(review_dir).resolve()
    manifest = read_json(directory/'manifest.json')
    if manifest.get('role') != 'teaching_guide_review':
        raise ValueError('expected a frozen teaching guide review')
    _verify(directory, manifest)
    descriptors = manifest.get('strokes')
    if descriptors is None and manifest.get('path_count') == 2:
        descriptors = ['long', 'short']
    if (not isinstance(descriptors, list) or not 1 <= len(descriptors) <= 64 or
            manifest.get('path_count') != len(descriptors)):
        raise ValueError('guide manifest needs 1..64 matching stroke descriptors')
    prepared = [_prepare(directory, manifest, descriptor) for descriptor in descriptors]
    if (len({m['guide_trace']['id'] for m, *_ in prepared}) != len(prepared) or
            len({(m['type'], m['variant']) for m, *_ in prepared}) != len(prepared)):
        raise ValueError('duplicate guide id or type/variant')
    def write_batch(stage):
        from .guide_report import write_guide_report
        for model, source, trace, trace_bytes in prepared:
            folder = stage/'templates'/model['guide_trace']['id']
            def write_template(target):
                write_json(target/'template.json', model)
                (target/'source.jpg').write_bytes(source)
                (target/'raw_trace.json').write_bytes(trace_bytes)
                _write_csv(target/(model['type']+'_'+model['variant']+'_xy.csv'), model)
                write_guide_report(target/'report.html', model, source, trace)
                return dict(template_id=model['template_id'], evidence=model['evidence'])
            publish(folder, 'stroke_template_bundle', write_template)
        write_json(stage/'source_review_manifest.json', manifest)
        links = ''.join('<p><a href="templates/'+m['guide_trace']['id']+'/report.html">'+
            html.escape(m['guide_trace']['name'])+'：模板与原图</a></p>' for m, *_ in prepared)
        (stage/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>引导线入库</title>'
            '<h1>教学引导线笔画库</h1><p>教学图引导线候选，待人工检查。</p>'+links, encoding='utf-8')
        return dict(template_count=len(prepared), review_status='unreviewed', physical_validation=False)
    return publish(output_dir, 'teaching_guide_template_library', write_batch)
