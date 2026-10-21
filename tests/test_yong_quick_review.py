"""Yong support and local edits must preserve the geometry already accepted."""
import copy
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from brushbot.stroke_templates import adapt_stroke, build_template
from brushbot.stroke_templates.annotations import load_font_record, prepare_annotation
from brushbot.stroke_templates.bundle import build_bundle, fit_bundle, load_fitted_geometry
from brushbot.stroke_templates.examples import _render_font


ROOT = Path(__file__).resolve().parents[1]


def yong_annotation(tmp_path):
    record = load_font_record('永', ROOT/'data/makemeahanzi/graphics.txt')
    image = tmp_path/'yong.png'
    transform = _render_font(record, image, 300)
    annotation = prepare_annotation(image, '永', font_record=record, font_transform=transform,
                                    image_kind='font_fixture')
    return image, annotation


def test_yong_has_five_named_strokes_and_explicit_turn_hook_landmarks(tmp_path):
    _, annotation = yong_annotation(tmp_path)
    assert [s['type'] for s in annotation['strokes']] == ['dian', 'hengzhegou', 'hengpie', 'pie', 'na']
    assert [p['name'] for p in annotation['strokes'][1]['landmarks']] == ['turn', 'hook']
    assert [p['name'] for p in annotation['strokes'][2]['landmarks']] == ['turn']
    assert all(s['review_status'] == 'unreviewed' for s in annotation['strokes'])


def test_piecewise_template_pins_turns_instead_of_forcing_one_monotone_body():
    source = [[0, 1], [1, 1], [5, 1], [5, -4], [4, -5], [2, -4], [1, -3], [0, -3]]
    landmarks = [{'name': 'turn', 'index': 2}, {'name': 'hook', 'index': 3}]
    ref = dict(reference_id='test', source_sha256='a'*64, stroke_id='s01', type='hengzhegou',
        variant='standard', review_status='unreviewed', source_kind='synthetic_fixture',
        xy_px=source, anchors=[0, 1, 6, 7], width_px=2., width_source='manual_hint', landmarks=landmarks)
    template = build_template([ref], stroke_type='hengzhegou', allow_unreviewed=True)
    target = [[0, 1], [1, 1], [9, 1], [9, -8], [8, -9], [4, -8], [1, -7], [0, -7]]
    result = adapt_stroke(template, target, [0, 1, 6, 7], width_px=2., landmarks=landmarks)
    assert template['adaptation'] == 'piecewise_landmarks'
    mapped = {p['name']: p for p in result['feature_landmarks']}
    assert mapped['turn']['xy_px'] == pytest.approx([9, 1])
    assert mapped['hook']['xy_px'] == pytest.approx([9, -8])
    xy = np.asarray(result['xy_px'])
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    assert result['s'] == pytest.approx(lengths/lengths[-1])
    with pytest.raises(ValueError, match='landmark'):
        adapt_stroke(template, target, [0, 1, 6, 7], width_px=2.)


def test_all_five_yong_templates_build_and_fit_without_user_phase_editing(tmp_path):
    image, annotation = yong_annotation(tmp_path)
    templates = [build_bundle([(annotation, image, s['id'])], tmp_path/s['type'],
        style_id='yong_font_prototype', allow_unreviewed=True)['template'] for s in annotation['strokes']]
    fit_bundle(annotation, image, templates, tmp_path/'fit')
    geometry = load_fitted_geometry(tmp_path/'fit')
    assert geometry['complete']
    assert len(geometry['strokes']) == 5
    assert all(s['status'] == 'candidate' for s in geometry['strokes'])
    assert all(s['template_evidence']['level'] == 'font_geometry_fixture' for s in geometry['strokes'])
    assert (tmp_path/'fit/review.html').is_file()


def test_manual_preserve_mode_keeps_all_points_exactly_even_without_a_template(tmp_path):
    from brushbot.stroke_templates.quick_review import review_annotation
    image, annotation = yong_annotation(tmp_path)
    edited = copy.deepcopy(annotation)
    for stroke in edited['strokes']:
        stroke['path_mode'] = 'preserve'
    edited['provenance']['source_kind'] = 'manual_geometry_revision'
    edited['strokes'][0]['xy_px'][3][0] += 1
    first = edited['strokes'][0]['xy_px'][0]
    edited['strokes'][0]['xy_px'][1] = [first[0]+5e-10, first[1]]
    fit_bundle(edited, image, [], tmp_path/'kept')
    geometry = load_fitted_geometry(tmp_path/'kept')
    assert geometry['complete']
    for expected, actual in zip(edited['strokes'], geometry['strokes']):
        assert actual['xy_px'] == expected['xy_px']
        assert actual['generation_method'] == 'manual_geometry_preserved'
        assert [dict(name=p['name'], index=p['index']) for p in actual.get('feature_landmarks', [])] == expected['landmarks']
        for feature in actual.get('feature_landmarks', []):
            assert feature['xy_px'] == expected['xy_px'][feature['index']]
            assert feature['s'] == pytest.approx(actual['s'][feature['index']])
    reopened = review_annotation(edited, geometry)
    for expected, actual in zip(edited['strokes'], reopened['strokes']):
        assert actual['xy_px'] == expected['xy_px']
        assert actual['landmarks'] == expected['landmarks']
    fit_bundle(reopened, image, [], tmp_path/'kept_again')
    for expected, actual in zip(geometry['strokes'], load_fitted_geometry(tmp_path/'kept_again')['strokes']):
        assert actual['xy_px'] == expected['xy_px']
        assert actual.get('feature_landmarks') == expected.get('feature_landmarks')
    assert geometry['physical_validation'] is False


def test_yong_cli_publishes_a_direct_quick_review_entry(tmp_path):
    result = subprocess.run([sys.executable, 'scripts/stroke_templates.py', 'yong',
        '--image-size', '300', '--output-dir', str(tmp_path/'yong')], cwd=ROOT,
        env=dict(os.environ, PYTHONPATH='src:.', PYTHONDONTWRITEBYTECODE='1'), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'yong/fit/review.html').exists()
    assert load_fitted_geometry(tmp_path/'yong/fit')['complete']


@pytest.mark.parametrize('change', ['truncate', 'insert_same_polyline_vertex'])
def test_incompatible_yong_dictionary_hint_is_an_actionable_error(tmp_path, change):
    image, _ = yong_annotation(tmp_path)
    record = load_font_record('永', ROOT/'data/makemeahanzi/graphics.txt')
    if change == 'truncate':
        record['medians'][1] = record['medians'][1][:2]
    else:
        a, b = record['medians'][1][:2]
        record['medians'][1].insert(1, [(x+y)/2 for x, y in zip(a, b)])
    with pytest.raises(ValueError, match='dictionary'):
        prepare_annotation(image, '永', font_record=record)


@pytest.mark.parametrize('provenance,expected', [
    ({'source_kind': 'synthetic_fixture'}, 'synthetic_geometry_fixture'),
    ({'source_kind': 'manual_geometry_revision', 'image_kind': 'synthetic_fixture'}, 'synthetic_geometry_fixture'),
    ({'source_kind': 'font_prior'}, 'font_geometry_fixture'),
    ({'source_kind': 'font_prior', 'image_kind': 'user_supplied'}, 'manual_geometry_reviewed'),
])
def test_quick_confirmation_never_promotes_fixture_evidence(tmp_path, provenance, expected):
    from PIL import Image, ImageDraw
    from brushbot.stroke_templates.annotations import load_bound_image, reference_from_annotation
    from brushbot.stroke_templates.bundle import fit_character
    from brushbot.stroke_templates.quick_review import review_annotation
    image = tmp_path/'line.png'
    bitmap = Image.new('RGB', (120, 80), 'white')
    ImageDraw.Draw(bitmap).rectangle([5, 34, 115, 45], fill='black'); bitmap.save(image)
    annotation = prepare_annotation(image, '一', no_prior=True)
    annotation['provenance'] = provenance
    annotation['strokes'][0].update(type='heng', path_mode='preserve', review_status='confirmed', width_hint_px=10.)
    for _ in range(2):
        annotation, prepared = load_bound_image(annotation, image)
        geometry = fit_character(annotation, prepared, [])
        annotation = review_annotation(annotation, geometry)
    reference = reference_from_annotation(annotation, image, 's01')
    template = build_template([reference], stroke_type='heng')
    assert template['evidence']['level'] == expected
    assert template['evidence']['physical_validation'] is False
