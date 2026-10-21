"""General guide imports must retain type, landmarks, and explicit width provenance."""
import hashlib
import json

import numpy as np
from PIL import Image, ImageDraw
import pytest

from brushbot.stroke_templates.bundle import read_json, write_json
from brushbot.stroke_templates.geometry import adapt_stroke
from tests.test_guide_stroke_templates import review_fixture, seal_review
from tests.test_stroke_template_cli import command


def compound_review(tmp_path):
    directory = review_fixture(tmp_path)
    trace = read_json(directory/'long_trace.json')
    trace.update(id='hengpie', type='hengpie', variant='short_heng_curved_pie', name='横撇',
                 landmarks=[dict(name='turn', index=20)], width_hint_px=24.,
                 width_hint_basis='测试图轮廓的人工参考宽度；仅作几何归一化。')
    write_json(directory/'long_trace.json', trace)
    seal_review(directory)
    manifest = read_json(directory/'manifest.json')
    manifest.update(path_count=1, strokes=[dict(id='hengpie', type='hengpie',
        variant='short_heng_curved_pie', name='横撇', source_file='long_source.jpg', trace_file='long_trace.json')])
    write_json(directory/'manifest.json', manifest)
    return directory


def test_cli_imports_non_horizontal_compounds_and_keeps_a_landmark_on_a_straight_span(tmp_path):
    directory = compound_review(tmp_path); output = tmp_path/'library/strokes/imported'
    result = command('import-guides', '--review-dir', directory, '--output-dir', output,
                     '--catalog-root', tmp_path/'library')
    assert result.returncode == 0, result.stderr
    model = read_json(output/'templates/hengpie/template.json')
    assert (model['type'], model['variant']) == ('hengpie', 'short_heng_curved_pie')
    assert model['adaptation'] == 'piecewise_landmarks'
    ref = model['references'][0]; feature = ref['landmarks'][0]
    assert feature['name'] == 'turn'
    assert ref['xy_px'][feature['index']] == [44., 51.8]
    assert ref['width_source'] == 'manual_diagram_width_hint'
    assert ref['width_px'] == 24
    assert model['prototype']['width_profiles'] == {}
    result = adapt_stroke(model, ref['xy_px'], ref['anchors'], width_px=24, landmarks=ref['landmarks'])
    assert result['feature_landmarks'][0]['name'] == 'turn'
    assert (output/'templates/hengpie/hengpie_short_heng_curved_pie_xy.csv').is_file()


@pytest.mark.parametrize('bad', ['duplicate', 'type_mismatch', 'missing_type', 'missing_variant',
                                 'landmark_outside_body', 'zero_width'])
def test_general_import_rejects_ambiguous_or_invalid_metadata_without_partial_publication(tmp_path, bad):
    directory = compound_review(tmp_path); manifest = read_json(directory/'manifest.json')
    trace = read_json(directory/'long_trace.json')
    if bad == 'duplicate':
        manifest['strokes'] *= 2; manifest['path_count'] = 2
    elif bad == 'type_mismatch':
        trace['type'] = 'pie'
    elif bad in ('missing_type', 'missing_variant'):
        del trace[bad.removeprefix('missing_')]
    elif bad == 'landmark_outside_body':
        trace['landmarks'][0]['index'] = 0
    else:
        trace['width_hint_px'] = 0
    write_json(directory/'long_trace.json', trace)
    manifest['files']['long_trace.json'] = hashlib.sha256((directory/'long_trace.json').read_bytes()).hexdigest()
    write_json(directory/'manifest.json', manifest)
    output = tmp_path/'output'
    result = command('import-guides', '--review-dir', directory, '--output-dir', output)
    assert result.returncode != 0
    assert not output.exists()


def test_trace_cli_follows_ordered_white_guide_and_ignores_an_arrow_side_branch(tmp_path):
    sources = tmp_path/'sources'; sources.mkdir()
    image = Image.new('RGB', (110, 80), 'white'); draw = ImageDraw.Draw(image)
    path = [(20, 35), (25, 40), (30, 35), (70, 35), (75, 30), (82, 35), (75, 39)]
    draw.line(path, fill='black', width=14, joint='curve')
    draw.line(path, fill='white', width=2)
    draw.line([(48, 35), (43, 30)], fill='white', width=1)
    image.save(sources/'heng.jpg', quality=100)
    config = dict(schema_version=1, role='teaching_guide_trace_specs',
        article_url='https://example.org/article', strokes=[dict(id='heng_long', type='heng', variant='long',
        name='长横', source=dict(filename='heng.jpg', url='https://example.org/heng.jpg',
            sha256=hashlib.sha256((sources/'heng.jpg').read_bytes()).hexdigest()),
        box=[10, 20, 95, 52], waypoints=path, body_start=2, body_end=3,
        landmarks=[], guide_mode='ink_white', writing_hint='有序白线测试。')])
    specs = tmp_path/'specs.json'; write_json(specs, config)
    review = tmp_path/'review'
    result = command('trace-guides', '--specs', specs, '--source-dir', sources, '--output-dir', review)
    assert result.returncode == 0, result.stderr
    manifest = read_json(review/'manifest.json')
    assert manifest['role'] == 'teaching_guide_review' and manifest['path_count'] == 1
    trace = read_json(review/manifest['strokes'][0]['trace_file'])
    xy = np.array(trace['source_points_image_px']); a = trace['anchors']
    assert np.max(np.abs(xy[a[1]:a[2]+1, 1]-35)) <= 1
    # The open white cap touches the background; snapping stays near that cap.
    assert xy[0] == pytest.approx([20, 35], abs=3)
    assert xy[-1] == pytest.approx([75, 39], abs=3)
    imported = command('import-guides', '--review-dir', review, '--output-dir', tmp_path/'imported')
    assert imported.returncode == 0, imported.stderr
