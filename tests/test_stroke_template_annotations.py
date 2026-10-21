"""Actual bitmaps exercise measurement visibility and source/annotation binding."""
import copy
import hashlib

import numpy as np
from PIL import Image
import pytest

from brushbot.stroke_templates.annotations import prepare_annotation, reference_from_annotation
from brushbot.stroke_templates.widths import measure_widths


def image(tmp_path):
    mask = np.zeros((80, 120), bool)
    mask[35:45, 10:110] = True
    path = tmp_path/'heng.png'
    Image.fromarray(np.where(mask, 0, 255).astype('uint8')).save(path)
    return path


def annotation(path):
    return dict(schema_version=1, role='stroke_annotation', source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        image_size_px=[120, 80], character='一', provenance={'source_kind': 'manual_image'},
        strokes=[dict(id='s01', type='heng', variant='standard', review_status='confirmed', notes='',
            xy_px=[[12, 39.5], [20, 39.5], [100, 39.5], [107, 39.5]], anchors=[0, 1, 2, 3])])


def test_normal_scan_measures_actual_width_instead_of_path_span():
    mask = np.zeros((60, 100), bool)
    mask[20:30, 5:95] = True
    result = measure_widths(mask, [[10, 34.5], [90, 34.5]])
    assert result['width_px'] == pytest.approx(10., abs=.6)
    assert result['valid_count'] == 65


def test_crossing_and_image_border_are_missing_width_not_zero_or_large_width():
    mask = np.zeros((60, 100), bool)
    mask[20:30, :] = True
    mask[:, 45:55] = True
    result = measure_widths(mask, [[10, 34.5], [90, 34.5]], other_paths=[[[50, 0], [50, 59]]])
    assert result['width_px'] == pytest.approx(10., abs=.6)
    assert any(p['reason'] == 'overlap' and p['width_px'] is None for p in result['samples'])
    vertical = measure_widths(mask, [[50, 10], [50, 50]])
    assert any(p['reason'] == 'image_border' for p in vertical['samples'])


def test_no_ink_and_resized_measurement_keep_explicit_units():
    result = measure_widths(np.zeros((20, 20), bool), [[3, 3], [15, 3]])
    assert result['width_px'] is None and result['valid_count'] == 0
    mask = np.zeros((30, 50), bool)
    mask[10:15, 2:48] = True
    result = measure_widths(mask, [[10, 34.5], [90, 34.5]], image_size_px=[100, 60])
    assert result['width_px'] == pytest.approx(10., abs=1.1)


def test_reference_is_bound_to_image_and_keeps_measured_width_provenance(tmp_path):
    path = image(tmp_path)
    ref = reference_from_annotation(annotation(path), path, 's01')
    assert ref['width_px'] == pytest.approx(10., abs=.6)
    assert ref['width_source'] == 'normal_scan_candidate'
    assert ref['review_status'] == 'confirmed'
    Image.new('L', (120, 80), 128).save(path)
    with pytest.raises(ValueError, match='source'):
        reference_from_annotation(annotation(path) | {'source_sha256': 'a'*64}, path, 's01')


def test_explicit_width_hint_is_distinguished_from_measurement(tmp_path):
    path = image(tmp_path)
    ann = annotation(path)
    ann['strokes'][0]['width_hint_px'] = 12.
    ref = reference_from_annotation(ann, path, 's01')
    assert ref['width_px'] == 12. and ref['width_source'] == 'manual_hint'
    assert ref['width_measurement']['width_px'] == pytest.approx(10., abs=.6)


def test_all_three_phases_keep_observed_width_profiles(tmp_path):
    path = image(tmp_path)
    ref = reference_from_annotation(annotation(path), path, 's01')
    assert set(ref['phase_width_measurements']) == {'entry', 'body', 'exit'}
    for phase in ref['phase_width_measurements'].values():
        assert phase['width_px'] == pytest.approx(10., abs=.6)
    from brushbot.stroke_templates import build_template
    template = build_template([ref], stroke_type='heng')
    assert template['prototype']['descriptors'][0]['mean_width_reference_width'] == pytest.approx(1.)
    assert len(template['prototype']['width_profiles']['exit']['samples']) == 65


def test_font_prior_draft_does_not_claim_segmentation_or_human_confirmation(tmp_path):
    path = image(tmp_path)
    record = {'character': '一', 'medians': [[[100, 200], [900, 200]]], 'strokes': []}
    ann = prepare_annotation(path, '一', font_record=record)
    assert ann['strokes'][0]['type'] == 'heng'
    assert ann['strokes'][0]['review_status'] == 'unreviewed'
    assert ann['provenance']['source_kind'] == 'font_prior'
    assert len(ann['strokes'][0]['xy_px']) >= 4
    assert 'not_image_recovered_stroke_order' in ann['review_flags']
    assert ann['image_size_px'] == [120, 80]


def test_manual_draft_is_available_without_dictionary_and_bad_character_rejected(tmp_path):
    path = image(tmp_path)
    ann = prepare_annotation(path, '字', no_prior=True)
    assert ann['strokes'][0]['type'] == 'unknown'
    with pytest.raises(ValueError, match='character'):
        prepare_annotation(path, '永', font_record={'character': '一', 'medians': [[[1, 1], [2, 1]]]})


def test_hand_edits_rebind_reference_identity_and_preserve_original_input(tmp_path):
    path = image(tmp_path)
    ann = annotation(path)
    before = copy.deepcopy(ann)
    first = reference_from_annotation(ann, path, 's01')
    ann['strokes'][0]['xy_px'][0][0] += 1
    second = reference_from_annotation(ann, path, 's01')
    assert first['reference_id'] != second['reference_id']
    assert before['strokes'][0]['xy_px'][0][0] == 12


def test_source_changing_during_preparation_is_rejected(tmp_path, monkeypatch):
    path = image(tmp_path)
    ann = annotation(path)
    from brushbot.stroke_templates import annotations
    original = annotations.prepare_image
    def changed(*args, **kwargs):
        im = Image.open(path).copy(); im.putpixel((0, 0), 0); im.save(path)
        return original(*args, **kwargs)
    monkeypatch.setattr(annotations, 'prepare_image', changed)
    with pytest.raises(ValueError, match='source'):
        reference_from_annotation(ann, path, 's01')
