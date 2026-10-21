"""Exercise portable bundles, CLI mutations and actual end-to-end geometry."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image
import pytest

from brushbot.stroke_templates.bundle import build_bundle, fit_bundle, load_fitted_geometry, prepare_bundle


ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    image = tmp_path/'横.png'
    mask = np.zeros((80, 120), bool)
    mask[35:45, 10:110] = True
    Image.fromarray(np.where(mask, 0, 255).astype('uint8')).save(image)
    ann = dict(schema_version=1, role='stroke_annotation', source_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        image_size_px=[120, 80], character='一', provenance={'source_kind': 'manual_image'},
        strokes=[dict(id='s01', type='heng', variant='standard', review_status='confirmed',
            notes='safe </script><b>文字</b>', xy_px=[[12, 39.5], [20, 39.5], [100, 39.5], [107, 39.5]],
            anchors=[0, 1, 2, 3])])
    annotation = tmp_path/'annotation.json'
    annotation.write_text(json.dumps(ann, ensure_ascii=False), encoding='utf-8')
    return image, annotation, ann


def command(*args):
    return subprocess.run([sys.executable, str(ROOT/'scripts/stroke_templates.py'), *map(str, args)],
        cwd=ROOT, env=dict(os.environ, PYTHONPATH='src:.', PYTHONDONTWRITEBYTECODE='1'),
        capture_output=True, text=True)


def test_cli_build_fit_and_physical_scale_are_readable_without_v3_or_fake_targets(tmp_path):
    image, annotation, _ = fixture(tmp_path)
    built = tmp_path/'model'
    result = command('build', '--annotation', annotation, '--image', image, '--stroke-id', 's01',
                     '--style-id', 'test_style', '--output-dir', built)
    assert result.returncode == 0, result.stderr
    fitted = tmp_path/'fitted'
    result = command('fit', '--annotation', annotation, '--image', image, '--templates', built/'template.json',
                     '--image-width-mm', '60', '--output-dir', fitted)
    assert result.returncode == 0, result.stderr
    geometry = load_fitted_geometry(fitted)
    assert geometry['complete'] is True and geometry['units'] == 'mm'
    assert geometry['role'] == 'templated_character_xy'
    xy = np.asarray(geometry['strokes'][0]['xy'])
    assert xy[0] == pytest.approx([-23.75, 0.])
    assert xy[-1] == pytest.approx([23.75, 0.])
    assert geometry['strokes'][0]['arc_length'][-1] == pytest.approx(47.5)
    with np.load(fitted/'xy_paths.npz', allow_pickle=False) as data:
        assert data['offsets'][-1] == len(data['xy'])
        assert 'g_target' not in data.files and 't' not in data.files and 'format_version' not in data.files
    assert (fitted/'paths.csv').exists() and (fitted/'baseline_paths.csv').exists()
    html = (fitted/'report.html').read_text(encoding='utf-8')
    assert 'safe </script><b>' not in html


def test_preparation_is_editable_and_output_cannot_be_overwritten(tmp_path):
    image, _, _ = fixture(tmp_path)
    output = tmp_path/'draft'
    result = command('prepare', '--image', image, '--character', '一', '--no-prior', '--output-dir', output)
    assert result.returncode == 0, result.stderr
    ann = json.loads((output/'annotation.json').read_text())
    assert ann['strokes'][0]['review_status'] == 'unreviewed'
    original = (output/'manifest.json').read_bytes()
    result = command('prepare', '--image', image, '--character', '一', '--no-prior', '--output-dir', output)
    assert result.returncode != 0
    assert (output/'manifest.json').read_bytes() == original


def test_missing_template_is_reported_as_partial_not_silently_dropped(tmp_path):
    image, _, ann = fixture(tmp_path)
    built = build_bundle([(ann, image, 's01')], tmp_path/'model', style_id='test_style')
    other = dict(ann['strokes'][0], id='s02', type='shu', xy_px=[[60, 10], [60, 20], [60, 60], [60, 70]])
    ann['strokes'].append(other)
    ann['strokes'][0]['width_hint_px'] = 10.
    result = fit_bundle(ann, image, [built['template']], tmp_path/'fit')
    geometry = load_fitted_geometry(tmp_path/'fit')
    assert result['complete'] is False
    assert len(geometry['strokes']) == 2
    assert geometry['strokes'][1]['status'] == 'unsupported'
    assert geometry['strokes'][1]['reason_code'] == 'missing_template'


def test_corrupted_artifact_and_duplicate_type_models_are_rejected(tmp_path):
    image, _, ann = fixture(tmp_path)
    built = build_bundle([(ann, image, 's01')], tmp_path/'model', style_id='test_style')
    fit_bundle(ann, image, [built['template']], tmp_path/'fit')
    (tmp_path/'fit'/'paths.csv').write_text('changed')
    with pytest.raises(ValueError, match='integrity'):
        load_fitted_geometry(tmp_path/'fit')
    with pytest.raises(ValueError, match='ambiguous'):
        fit_bundle(ann, image, [built['template'], built['template']], tmp_path/'ambiguous')
    assert not (tmp_path/'ambiguous').exists()


def test_bad_image_or_render_failure_leaves_no_published_bundle(tmp_path, monkeypatch):
    image, _, ann = fixture(tmp_path)
    bad = dict(ann, source_sha256='a'*64)
    with pytest.raises(ValueError, match='source'):
        fit_bundle(bad, image, [], tmp_path/'bad')
    from brushbot.stroke_templates import report
    def fail(*args, **kwargs):
        raise RuntimeError('render failure')
    monkeypatch.setattr(report, 'write_annotation_report', fail)
    with pytest.raises(RuntimeError, match='render failure'):
        prepare_bundle(image, '一', tmp_path/'render_fail', no_prior=True)
    assert not (tmp_path/'render_fail').exists()


def test_protected_head_leaving_image_is_explicitly_flagged(tmp_path):
    image, _, ann = fixture(tmp_path)
    built = build_bundle([(ann, image, 's01')], tmp_path/'model', style_id='test_style')
    ann['strokes'][0]['xy_px'][0][0] = 0
    ann['strokes'][0]['xy_px'][1][0] = 5
    fit_bundle(ann, image, [built['template']], tmp_path/'fit')
    geometry = load_fitted_geometry(tmp_path/'fit')
    assert 'generated_path_outside_image' in geometry['strokes'][0]['review_flags']


def test_template_snapshot_cannot_copy_a_changed_reference_source(tmp_path, monkeypatch):
    image, _, ann = fixture(tmp_path)
    from brushbot.stroke_templates import bundle
    original = bundle.reference_from_annotation
    def changed(*args):
        reference = original(*args)
        im = Image.open(image).copy(); im.putpixel((0, 0), 0); im.save(image)
        return reference
    monkeypatch.setattr(bundle, 'reference_from_annotation', changed)
    with pytest.raises(ValueError, match='source'):
        build_bundle([(ann, image, 's01')], tmp_path/'model', style_id='test_style')
    assert not (tmp_path/'model').exists()
