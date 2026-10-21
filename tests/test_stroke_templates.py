"""Hand-calculated contracts: stretching must not stretch local end features."""
import copy

import numpy as np
import pytest

from brushbot.stroke_templates import adapt_stroke, build_template, validate_annotation, validate_template


def reference(**changes):
    value = dict(reference_id='ref_a', source_sha256='a'*64, stroke_id='s01',
        type='heng', variant='standard', review_status='confirmed', source_kind='manual_image',
        xy_px=[[0, -1], [1, 0], [2, 0], [4, 0], [6, 0], [8, 0], [9, -1], [8, -2]],
        anchors=[0, 2, 5, 7], width_px=2., width_source='manual_hint')
    return value | changes


def model():
    return build_template([reference()], stroke_type='heng', style_id='test_style')


def test_length_transfer_preserves_both_end_features_and_retracing():
    result = adapt_stroke(model(), [[10, 20], [11, 21], [12, 21], [16, 21],
        [20, 21], [24, 21], [25, 20], [24, 19]], [0, 2, 5, 7], width_px=2.)
    xy = np.asarray(result['xy_px'])
    phase = np.asarray(result['phase_id'])
    entry, body, exit_ = [xy[phase == p] for p in ('entry', 'body', 'exit')]
    assert np.allclose(entry[0], [10, 20])
    assert np.allclose(body[[0, -1]], [[12, 21], [24, 21]])
    assert np.allclose(exit_[-1], [24, 19])
    assert exit_[:, 0].max() == pytest.approx(25.)
    assert np.linalg.norm(np.diff(entry, axis=0), axis=1).sum() == pytest.approx(1 + np.sqrt(2))
    assert np.linalg.norm(np.diff(exit_, axis=0), axis=1).sum() == pytest.approx(2*np.sqrt(2))
    assert result['parameters']['body_stretch_ratio'] == pytest.approx(2.)
    baseline = np.asarray(result['baseline_xy_px'])
    assert baseline[0, 0] == pytest.approx(8.)  # naive whole-stroke stretching moves the head


def test_width_scaling_is_isotropic_in_end_segments():
    result = adapt_stroke(model(), [[0, -2], [2, 0], [4, 0], [8, 0],
        [12, 0], [16, 0], [18, -2], [16, -4]], [0, 2, 5, 7], width_px=4.)
    assert np.allclose(result['xy_px'][0], [0, -2])
    assert np.allclose(result['xy_px'][-1], [16, -4])
    assert result['parameters']['body_stretch_ratio'] == pytest.approx(1.)


def test_rotated_target_keeps_direction_and_has_correct_arc_and_phase_progress():
    target = np.asarray(reference()['xy_px']) @ np.array([[0, 1], [-1, 0]]) + [20, 30]
    result = adapt_stroke(model(), target, [0, 2, 5, 7], width_px=2.)
    xy, s = np.asarray(result['xy_px']), np.asarray(result['s'])
    lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    assert np.allclose(s, lengths/lengths[-1])
    for phase in ('entry', 'body', 'exit'):
        u = np.asarray(result['phase_u'])[np.asarray(result['phase_id']) == phase]
        assert u[0] == 0 and u[-1] == 1 and np.all(np.diff(u) > 0)
    assert np.allclose(xy[0], [21, 30])
    assert np.allclose(xy[-1], [22, 38])


def test_bend_is_fitted_within_body_and_head_connects_with_equal_tangent():
    target = [[0, 0], [1, 0], [2, 0], [5, 1], [8, 0], [9, 0], [10, 0]]
    result = adapt_stroke(model(), target, [0, 2, 4, 6], width_px=2.)
    xy, phase = np.asarray(result['xy_px']), np.asarray(result['phase_id'])
    entry, body = xy[phase == 'entry'], xy[phase == 'body']
    a, b = entry[-1]-entry[-2], body[1]-body[0]
    assert np.dot(a, b)/np.linalg.norm(a)/np.linalg.norm(b) == pytest.approx(1.)
    assert result['parameters']['bend_widths'] > 0


def test_intentional_reference_join_angles_are_preserved_and_reported():
    ref = reference(xy_px=[[0, -2], [1, -1], [2, 0], [8, 0], [9, 1], [10, 2]],
                    anchors=[0, 2, 3, 5])
    template = build_template([ref], stroke_type='heng')
    result = adapt_stroke(template, [[0, 0], [2, 0], [8, 1], [14, 0], [16, 0]],
                          [0, 1, 3, 4], width_px=2.)
    xy, phase = np.asarray(result['xy_px']), np.asarray(result['phase_id'])
    head, body, tail = [xy[phase == p] for p in ('entry', 'body', 'exit')]
    vectors = [(head[-1]-head[-2], body[1]-body[0]),
               (body[-1]-body[-2], tail[1]-tail[0])]
    for before, after in vectors:
        assert np.dot(before, after)/np.linalg.norm(before)/np.linalg.norm(after) == pytest.approx(2**-.5)
    diagnostics = result['join_diagnostics']
    assert diagnostics['policy'] == 'preserve_reference_join_angles'
    assert diagnostics['reference_rad'] == pytest.approx([-np.pi/4, np.pi/4])
    assert diagnostics['adapted_rad'] == pytest.approx([-np.pi/4, np.pi/4])
    assert diagnostics['angle_change_rad'] == pytest.approx([0, 0], abs=1e-9)


@pytest.mark.parametrize('anchors', [[0, 0, 5, 7], [0, 5, 2, 7], [0, 2, 5, 6], [0, 2.0, 5, 7]])
def test_invalid_anchors_are_rejected(anchors):
    with pytest.raises(ValueError, match='anchor'):
        build_template([reference(anchors=anchors)], stroke_type='heng')


def test_out_of_range_body_and_bend_are_rejected_instead_of_clipped():
    with pytest.raises(ValueError, match='range'):
        adapt_stroke(model(), [[0, 0], [1, 0], [2, 0], [100, 0], [101, 0]],
                     [0, 1, 3, 4], width_px=2.)
    with pytest.raises(ValueError, match='bend'):
        adapt_stroke(model(), [[0, 0], [1, 0], [2, 0], [5, 20], [8, 0], [9, 0]],
                     [0, 2, 4, 5], width_px=2.)


def test_prototype_selection_uses_all_references_and_records_observed_support():
    refs = [reference(reference_id=f'ref_{i}', xy_px=(np.asarray(reference()['xy_px'])*[k, 1]).tolist())
            for i, k in enumerate((.8, 1., 2.))]
    template = build_template(refs, stroke_type='heng', style_id='test_style')
    assert template['prototype']['reference_id'] == 'ref_1'
    assert template['observed']['body_aspect_range'] == pytest.approx([2.4, 6.])
    assert len(template['references']) == 3


def test_tampered_template_cannot_keep_old_identity():
    template = model()
    template['prototype']['xy'][0][0] += .2
    with pytest.raises(ValueError, match='identity'):
        validate_template(template)


def test_unreviewed_reference_requires_explicit_opt_in_and_never_becomes_measured():
    ref = reference(review_status='unreviewed', source_kind='font_prior')
    with pytest.raises(ValueError, match='review'):
        build_template([ref], stroke_type='heng')
    template = build_template([ref], stroke_type='heng', allow_unreviewed=True)
    assert template['evidence']['level'] == 'font_geometry_fixture'
    assert template['evidence']['physical_validation'] is False


def test_type_mismatch_and_nonmonotone_body_are_rejected():
    with pytest.raises(ValueError, match='type'):
        build_template([reference(type='shu')], stroke_type='heng')
    ref = reference()
    ref['xy_px'][3] = [7, 0]
    with pytest.raises(ValueError, match='monotone'):
        build_template([ref], stroke_type='heng')


def test_partial_design_limits_are_applied_and_synthetic_evidence_stays_explicit():
    template = build_template([reference(source_kind='synthetic_fixture')], stroke_type='heng',
                              limits={'max_bend_widths': .25})
    assert template['limits']['max_bend_widths'] == .25
    assert template['evidence']['level'] == 'synthetic_geometry_fixture'


def test_reviewed_user_image_can_promote_geometry_but_font_fixture_cannot():
    user = reference(source_kind='font_prior', image_kind='user_supplied')
    assert build_template([user], stroke_type='heng')['evidence']['level'] == 'manual_geometry_reviewed'
    fixture = user | {'image_kind': 'font_fixture'}
    assert build_template([fixture], stroke_type='heng')['evidence']['level'] == 'font_geometry_fixture'


def test_annotation_edits_get_new_identity_and_invalid_coordinates_fail():
    annotation = dict(schema_version=1, role='stroke_annotation', source_sha256='a'*64,
        image_size_px=[30, 30], character='一', provenance={'source_kind': 'manual_image'},
        strokes=[dict(id='s01', type='heng', variant='standard',
            xy_px=[[1, 10], [2, 10], [20, 10], [21, 10]], anchors=[0, 1, 2, 3],
            review_status='unreviewed', notes='')])
    first = validate_annotation(annotation)
    changed = copy.deepcopy(first)
    changed['strokes'][0]['xy_px'][1][1] += 1
    assert validate_annotation(changed)['annotation_id'] != first['annotation_id']
    changed['strokes'][0]['xy_px'][0][0] = -3
    with pytest.raises(ValueError, match='image'):
        validate_annotation(changed)
