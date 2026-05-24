import json
import os

import pytest

from src.stroke_taxonomy.taxonomy import StrokeTaxonomy


@pytest.fixture
def sample_taxonomy_file(tmp_path):
    """Create a sample stroke taxonomy JSON file."""
    data = {
        "strokes": [
            {"id": 0, "name": "横", "name_pinyin": "heng", "stroke_type": "basic", "description": "Horizontal stroke"},
            {"id": 1, "name": "竖", "name_pinyin": "shu", "stroke_type": "basic", "description": "Vertical stroke"},
            {"id": 14, "name": "横折钩", "name_pinyin": "hengzhegou", "stroke_type": "compound", "description": "Horizontal fold with hook"},
        ],
        "char_to_strokes": {
            "一": [0],
            "二": [0, 0],
        },
    }
    path = os.path.join(str(tmp_path), "stroke_taxonomy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return path


class TestStrokeTaxonomy:
    def test_load_taxonomy(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.num_strokes() == 3

    def test_get_stroke_info(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        info = tax.get_stroke(0)
        assert info["name"] == "横"
        assert info["stroke_type"] == "basic"

    def test_get_strokes_by_type(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        basic = tax.get_strokes_by_type("basic")
        assert len(basic) == 2
        compound = tax.get_strokes_by_type("compound")
        assert len(compound) == 1

    def test_get_char_strokes(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        strokes = tax.get_char_strokes("一")
        assert strokes == [0]

    def test_get_char_strokes_with_names(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        names = tax.get_char_strokes_with_names("一")
        assert names == ["横"]

    def test_char_not_found_returns_none(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_char_strokes("nonexistent") is None

    def test_get_stroke_name(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_stroke_name(0) == "横"
        assert tax.get_stroke_name(14) == "横折钩"

    def test_get_stroke_name_invalid_id(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_stroke_name(999) is None

    def test_get_all_chars(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        chars = tax.get_all_chars()
        assert "一" in chars
        assert "二" in chars

    def test_get_stroke_count(self, sample_taxonomy_file):
        tax = StrokeTaxonomy(sample_taxonomy_file)
        assert tax.get_stroke_count("一") == 1
        assert tax.get_stroke_count("二") == 2
        assert tax.get_stroke_count("nonexistent") is None
