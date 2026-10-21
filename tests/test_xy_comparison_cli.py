"""Run the real CLI against image/V3 fixtures, including failure side effects."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw
import pytest

from brushbot.target_strokeplan import FEATURE, Stroke, StrokePlan

ROOT = Path(__file__).resolve().parents[1]


def cli(*args):
    return subprocess.run([sys.executable, str(ROOT/'scripts/compare_strokeplan_xy.py'),
                           *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(ROOT/'src'),
                                   MPLCONFIGDIR='/tmp/fyp-xy-mpl', PYTHONDONTWRITEBYTECODE='1'))


def fixture(tmp_path):
    image = Image.new('L', (41, 21), 255)
    ImageDraw.Draw(image).line([(5, 10), (35, 10)], fill=0)
    source = tmp_path/'input.png'
    image.save(source)
    ref = tmp_path/'reference'
    extracted = cli('extract', '--image', source, '--mm-per-pixel', '1', '--origin-px', '5', '10',
                    '--output-dir', ref)
    assert extracted.returncode == 0, extracted.stderr
    plan = StrokePlan([Stroke(np.array([0., 1.]), np.array([[0., 0.], [.03, 0.]]),
                              np.array([0., 3.]), np.array([100., 100.]))],
                      dict(source='synthetic', coordinate_frame='paper', feature=FEATURE,
                           filter_definition={'kind': 'ema', 'alpha': .3}))
    path = tmp_path/'plan.npz'
    plan.save(path)
    return source, ref, path, plan


def test_cli_writes_portable_overlay_metrics_and_preserves_inputs(tmp_path):
    source, ref, plan, target = fixture(tmp_path)
    original = {p: p.read_bytes() for p in [source, plan, ref/'reference.csv', ref/'reference.json']}
    target.strokes[0].xy[:, 1] += .003
    shifted = tmp_path/'shifted.npz'
    target.save(shifted)
    out = tmp_path/'comparison'
    result = cli('compare', '--reference-dir', ref, '--plan', f'original={plan}',
                 '--plan', f'offset_3mm={shifted}', '--samples', '101', '--output-dir', out)
    assert result.returncode == 0, result.stderr
    report = json.loads((out/'report.json').read_text())
    assert report['alignment'] == 'fixed_image_transform_no_candidate_fit'
    assert report['reference_reviewed'] is False
    assert report['candidates'][0]['metrics']['bidirectional_mean_distance_mm'] == pytest.approx(0, abs=1e-12)
    assert report['candidates'][1]['metrics']['bidirectional_mean_distance_mm'] == pytest.approx(3)
    assert report['candidates'][0]['sha256'] == hashlib.sha256(plan.read_bytes()).hexdigest()
    assert (out/'overview.png').stat().st_size > 1000
    assert (out/'candidate_00.csv').exists()
    html = (out/'report.html').read_text()
    assert 'data:image/png;base64,' in html
    assert 'offset_3mm' in html
    assert (out/'reference_snapshot'/'image.png').exists()
    for path, data in original.items():
        assert path.read_bytes() == data
    again = cli('compare', '--reference-dir', ref, '--plan', f'A={plan}', '--output-dir', out)
    assert again.returncode != 0
    assert 'replace' in again.stderr


def test_invalid_later_plan_does_not_create_partial_report(tmp_path):
    _, ref, plan, _ = fixture(tmp_path)
    bad = tmp_path/'bad.npz'
    bad.write_bytes(b'not a V3 plan')
    out = tmp_path/'comparison'
    result = cli('compare', '--reference-dir', ref, '--plan', f'A={plan}',
                 '--plan', f'bad={bad}', '--output-dir', out)
    assert result.returncode != 0
    assert not out.exists()


def test_unmatched_coordinate_frame_and_stroke_index_are_rejected(tmp_path):
    _, ref, plan, target = fixture(tmp_path)
    bad_frame = tmp_path/'base.npz'
    target.meta['coordinate_frame'] = 'base'
    target.save(bad_frame)
    for args in [('--plan', f'base={bad_frame}'),
                 ('--plan', f'paper={plan}', '--stroke-index', '1')]:
        result = cli('compare', '--reference-dir', ref, *args, '--output-dir', tmp_path/'out')
        assert result.returncode != 0
        assert not (tmp_path/'out').exists()


def test_cli_returns_review_status_and_diagnostic_picture_for_a_branch(tmp_path):
    image = Image.new('L', (41, 41), 255)
    draw = ImageDraw.Draw(image)
    draw.line([(5, 20), (35, 20)], fill=0)
    draw.line([(20, 5), (20, 35)], fill=0)
    source = tmp_path/'cross.png'
    image.save(source)
    result = cli('extract', '--image', source, '--image-width-mm', '41', '--output-dir', tmp_path/'ref')
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'needs_review'
    assert (tmp_path/'ref'/'reference_preview.png').exists()


def test_duplicate_labels_are_rejected_and_html_labels_are_escaped(tmp_path):
    _, ref, plan, _ = fixture(tmp_path)
    duplicated = cli('compare', '--reference-dir', ref, '--plan', f'A={plan}',
                      '--plan', f'A={plan}', '--output-dir', tmp_path/'bad')
    assert duplicated.returncode != 0
    assert not (tmp_path/'bad').exists()
    result = cli('compare', '--reference-dir', ref, '--plan', f'<script>={plan}',
                 '--reference-reviewed', '--output-dir', tmp_path/'good')
    assert result.returncode == 0, result.stderr
    html = (tmp_path/'good'/'report.html').read_text()
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert json.loads((tmp_path/'good'/'report.json').read_text())['reference_reviewed'] is True
