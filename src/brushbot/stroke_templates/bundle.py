"""Offline template workflow with source binding and manifest-last publication."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

from brushbot.xy_comparison.geometry import compare_paths
from .annotations import load_bound_image, measure_annotation, prepare_annotation, reference_from_annotation
from .geometry import adapt_stroke, build_template, preserve_stroke
from .schema import identity, number, validate_annotation, validate_template
from . import report
from .quick_review import write_quick_review


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 20_000_000:
        raise ValueError('JSON input exceeds 20 MB')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, RecursionError) as exc:
        raise ValueError(f'invalid JSON input: {path.name}') from exc


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def publish(output_dir, role, writer):
    output = Path(output_dir).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f'output directory already exists: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{output.name}-', dir=output.parent) as temporary:
        stage = Path(temporary)
        summary = writer(stage)
        files = sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*') if p.is_file())
        manifest = dict(schema_version=1, role=role, **summary,
            files={name: hashlib.sha256((stage/name).read_bytes()).hexdigest() for name in files})
        write_json(stage/'manifest.json', manifest)
        try:
            output.mkdir()
        except FileExistsError as exc:
            raise ValueError(f'output directory already exists: {output}') from exc
        try:
            for path in sorted(stage.iterdir()):
                if path.name != 'manifest.json':
                    path.rename(output/path.name)
            (stage/'manifest.json').rename(output/'manifest.json')
        except BaseException:
            shutil.rmtree(output)
            raise
    return dict(manifest, output_dir=str(output), report_html=str(output/'report.html'))


def prepare_bundle(image_path, character, output_dir, *, font_record=None, no_prior=False, font_transform=None,
                   image_kind='user_supplied'):
    annotation = prepare_annotation(image_path, character, font_record=font_record,
        no_prior=no_prior, font_transform=font_transform, image_kind=image_kind)
    annotation, prepared = load_bound_image(annotation, image_path)
    def write(stage):
        write_json(stage/'annotation.json', annotation)
        (stage/'source_image.bin').write_bytes(prepared['source_bytes'])
        prepared['image'].save(stage/'image.png')
        report.write_annotation_report(annotation, prepared, stage/'report.html')
        return dict(annotation_id=annotation['annotation_id'], character=character,
                    review_status='needs_review', source_sha256=annotation['source_sha256'])
    return publish(output_dir, 'stroke_annotation_bundle', write)


def build_bundle(references, output_dir, *, style_id, limits=None, allow_unreviewed=False):
    """References are (editable annotation, original image path, stroke id) tuples."""
    if not references:
        raise ValueError('provide at least one reference')
    measured = [reference_from_annotation(*reference) for reference in references]
    sources = [Path(image).read_bytes() for _, image, _ in references]
    if any(hashlib.sha256(raw).hexdigest() != reference['source_sha256']
           for raw, reference in zip(sources, measured)):
        raise ValueError('reference source changed before snapshot publication')
    template = build_template(measured, stroke_type=measured[0]['type'],
        variant=measured[0]['variant'], style_id=style_id, limits=limits, allow_unreviewed=allow_unreviewed)
    def write(stage):
        write_json(stage/'template.json', template)
        # Freeze the exact annotation and source bytes behind every model reference.
        for i, (annotation, image_path, _) in enumerate(references):
            write_json(stage/f'reference_{i:03}_annotation.json', validate_annotation(annotation))
            (stage/f'reference_{i:03}_source.bin').write_bytes(sources[i])
        report.write_template_report(template, stage/'report.html')
        return dict(template_id=template['template_id'], evidence=template['evidence'])
    result = publish(output_dir, 'stroke_template_bundle', write)
    return dict(result, template=template, template_json=str(Path(result['output_dir'])/'template.json'))


def _metrics(reference, candidate, factor, unit, width):
    measured = compare_paths(reference*factor, candidate*factor, samples=201)['metrics']
    metrics = {key.replace('_mm', '_'+unit): value for key, value in measured.items()}
    metrics['mean_distance_over_width'] = measured['bidirectional_mean_distance_mm']/(width*factor) if width else None
    return metrics


def fit_character(annotation, prepared, templates, *, image_width_mm=None):
    annotation = validate_annotation(annotation)
    by_type = {}
    for template in templates:
        template = validate_template(template)
        key = (template['type'], template['variant'])
        if key in by_type:
            raise ValueError(f'ambiguous templates for type/variant: {key}')
        by_type[key] = template
    if image_width_mm is None:
        factor, units = 1., 'px'
    else:
        factor, units = number(image_width_mm, 'image width mm', positive=True)/annotation['image_size_px'][0], 'mm'
    centre = (np.asarray(annotation['image_size_px'])-1)/2
    measurements = measure_annotation(annotation, prepared)
    strokes = []
    for stroke in annotation['strokes']:
        result = {key: stroke[key] for key in ('id', 'type', 'variant', 'review_status')}
        template = by_type.get((stroke['type'], stroke['variant']))
        preserving = stroke.get('path_mode') == 'preserve'
        if template is None and not preserving:
            strokes.append(dict(result, status='unsupported', reason_code='missing_template',
                reason='No template for this type/variant; review the annotation or supply a matching model.'))
            continue
        width = measurements[stroke['id']]
        if width['width_px'] is None and not preserving:
            strokes.append(dict(result, status='unsupported', reason_code='width_unavailable',
                reason='No visible body width; review overlap or set an explicit width hint.'))
            continue
        try:
            adapted = preserve_stroke(stroke['xy_px'], stroke['anchors'], landmarks=stroke.get('landmarks')) if preserving else adapt_stroke(
                template, stroke['xy_px'], stroke['anchors'], width_px=width['width_px'], landmarks=stroke.get('landmarks'))
        except ValueError as exc:
            strokes.append(dict(result, status='unsupported', reason_code='adaptation_rejected', reason=str(exc)))
            continue
        xy_px = np.asarray(adapted['xy_px'])
        base_px = np.asarray(adapted['baseline_xy_px'])
        ref_px = np.asarray(stroke['xy_px'])
        metrics = dict(proposed=_metrics(ref_px, xy_px, factor, units, width['width_px']),
                       baseline=_metrics(ref_px, base_px, factor, units, width['width_px']))
        flags = adapted['review_flags']
        from .image_consistency import ink_consistency
        consistency = ink_consistency(prepared['mask'], xy_px, annotation['image_size_px'])
        if consistency['outside_fraction'] > 0 or consistency['outside_vertex_count']:
            flags.append('generated_path_outside_reference_ink')
        if np.any(xy_px < -.5) or np.any(xy_px > np.asarray(annotation['image_size_px'])-.5):
            flags.append('generated_path_outside_image')
        if stroke['review_status'] != 'confirmed':
            flags.append('target_annotation_unreviewed')
        if template is not None and template['evidence']['level'] != 'manual_geometry_reviewed':
            flags.append('template_not_manual_calligraphy_reference')
        strokes.append(dict(result, status='candidate', template_id=template['template_id'] if template else None,
            template_evidence=template['evidence'] if template else dict(level='manual_geometry', physical_validation=False), **adapted,
            xy=((xy_px-centre)*factor).tolist(), baseline_xy=((base_px-centre)*factor).tolist(),
            reference_xy=((ref_px-centre)*factor).tolist(),
            arc_length=(np.asarray(adapted['arc_length_px'])*factor).tolist(),
            width=width['width_px']*factor if width['width_px'] is not None else None, width_source=width['width_source'],
            image_consistency=consistency,
            width_measurement=width['width_measurement'], phase_width_measurements=width['phase_width_measurements'],
            metrics=metrics))
    complete = all(stroke['status'] == 'candidate' for stroke in strokes)
    result = dict(schema_version=1, role='templated_character_xy', character=annotation['character'],
        annotation_id=annotation['annotation_id'], source_sha256=annotation['source_sha256'],
        template_ids=[template['template_id'] for template in by_type.values()],
        units=units, image_size_px=annotation['image_size_px'],
        transform=dict(origin_original_cartesian_px=centre.tolist(), units_per_pixel=factor),
        complete=complete, review_status='annotation_reviewed' if complete and all(
            s['review_status'] == 'confirmed' for s in strokes) else 'needs_review',
        physical_validation=False, strokes=strokes,
        reference_role='editable_image_geometry_candidate_not_independent_motion_ground_truth',
        provenance=annotation['provenance'],
        dynamic_attachment_contract=dict(required=['geometry_id', 'stroke_id', 'run_id', 'time',
            'coordinate_role', 'feature_definition', 'calibration_reference'],
            phase_u='within_phase_xy_arclength_not_time', no_motion_or_magnetic_data_inferred=True))
    result['geometry_id'] = identity(result, 'geometry_id')
    return result


def _exports(stage, geometry):
    supported = [s for s in geometry['strokes'] if s['status'] == 'candidate']
    for filename, key in [('paths.csv', 'xy'), ('baseline_paths.csv', 'baseline_xy')]:
        with (stage/filename).open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            if key == 'xy':
                writer.writerow(['stroke_id', 'point_index', 'x', 'y', 'arc_length', 's', 'phase_id', 'phase_u'])
                for stroke in supported:
                    writer.writerows([stroke['id'], i, *xy, arc, s, phase, u]
                        for i, (xy, arc, s, phase, u) in enumerate(zip(stroke['xy'], stroke['arc_length'],
                            stroke['s'], stroke['phase_id'], stroke['phase_u'])))
            else:
                writer.writerow(['stroke_id', 'point_index', 'x', 'y'])
                for stroke in supported:
                    writer.writerows([stroke['id'], i, *xy] for i, xy in enumerate(stroke[key]))
    arrays = {}
    for out, key in [('xy', 'xy'), ('s', 's'), ('arc_length', 'arc_length'),
                     ('phase_u', 'phase_u'), ('phase_id', 'phase_id')]:
        arrays[out] = np.concatenate([np.asarray(s[key]) for s in supported]) if supported else np.empty(
            (0, 2) if out == 'xy' else (0,), dtype=str if out == 'phase_id' else float)
    np.savez_compressed(stage/'xy_paths.npz', **arrays,
        offsets=np.r_[0, np.cumsum([len(s['xy']) for s in supported])].astype(np.int64),
        stroke_ids=np.asarray([s['id'] for s in supported], dtype=str), units=geometry['units'],
        geometry_id=geometry['geometry_id'], role=geometry['role'])


def fit_bundle(annotation, image_path, templates, output_dir, *, image_width_mm=None):
    annotation, prepared = load_bound_image(annotation, image_path)
    geometry = fit_character(annotation, prepared, templates, image_width_mm=image_width_mm)
    def write(stage):
        write_json(stage/'geometry.json', geometry)
        write_json(stage/'annotation.json', annotation)
        write_json(stage/'templates.json', templates)
        (stage/'source_image.bin').write_bytes(prepared['source_bytes'])
        prepared['image'].save(stage/'image.png')
        _exports(stage, geometry)
        report.write_annotation_report(annotation, prepared, stage/'report.html', geometry=geometry)
        write_quick_review(annotation, prepared, geometry, stage/'review.html')
        return dict(geometry_id=geometry['geometry_id'], source_sha256=annotation['source_sha256'],
            complete=geometry['complete'], review_status=geometry['review_status'], units=geometry['units'])
    return publish(output_dir, 'templated_character_xy_bundle', write)


def load_fitted_geometry(bundle_dir):
    directory = Path(bundle_dir)
    expected = {'geometry.json', 'annotation.json', 'templates.json', 'source_image.bin',
                'image.png', 'paths.csv', 'baseline_paths.csv', 'xy_paths.npz', 'report.html'}
    try:
        manifest = read_json(directory/'manifest.json')
        if manifest['schema_version'] != 1 or manifest['role'] != 'templated_character_xy_bundle':
            raise ValueError('unsupported fitted bundle')
        if set(manifest['files']) not in (expected, expected | {'review.html'}):
            raise ValueError('integrity: unexpected artifact list')
        for name, digest in manifest['files'].items():
            if hashlib.sha256((directory/name).read_bytes()).hexdigest() != digest:
                raise ValueError(f'integrity: artifact checksum mismatch: {name}')
        geometry = read_json(directory/'geometry.json')
        if geometry['geometry_id'] != identity(geometry, 'geometry_id') or geometry['geometry_id'] != manifest['geometry_id']:
            raise ValueError('integrity: geometry identity mismatch')
        annotation = validate_annotation(read_json(directory/'annotation.json'))
        templates = [validate_template(t) for t in read_json(directory/'templates.json')]
        if (geometry['annotation_id'] != annotation['annotation_id']
                or geometry['source_sha256'] != manifest['files']['source_image.bin']
                or geometry['source_sha256'] != annotation['source_sha256']
                or geometry['template_ids'] != [t['template_id'] for t in templates]):
            raise ValueError('integrity: source/annotation/template binding mismatch')
        return geometry
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError(f'bundle integrity error: {exc}') from exc
