"""The shipped demo must disclose its priors and keep held-out characters separate."""
import json
from pathlib import Path

import pytest

from brushbot.stroke_templates.bundle import load_fitted_geometry
from brushbot.stroke_templates.examples import generate_examples


ROOT = Path(__file__).resolve().parents[1]


def test_demo_publishes_simple_characters_and_length_transfer_without_validation_claim(tmp_path):
    output = tmp_path/'examples'
    result = generate_examples(ROOT/'data/makemeahanzi/graphics.txt', output, image_size=220)
    summary = json.loads((output/'cases.json').read_text())
    assert not set(summary['reference_characters']) & set(summary['test_characters'])
    assert summary['independent_ground_truth'] is False
    assert len(summary['length_cases']) == 3
    for case in summary['length_cases']:
        geom = load_fitted_geometry(output/case['directory'])
        assert geom['complete'] and geom['physical_validation'] is False
        assert geom['strokes'][0]['parameters']['body_stretch_ratio'] == pytest.approx(case['stretch_ratio'])
    assert any(c['complete'] for c in summary['character_cases'])
    yong = next(c for c in summary['character_cases'] if c['character'] == '永')
    assert yong['complete'] is True and yong['unsupported_count'] == 0
    assert summary['demonstration_characters'] == ['永']
    assert (output/'index.html').exists()
    original = (output/'manifest.json').read_bytes()
    with pytest.raises(ValueError, match='exists'):
        generate_examples(ROOT/'data/makemeahanzi/graphics.txt', output, image_size=220)
    assert (output/'manifest.json').read_bytes() == original
