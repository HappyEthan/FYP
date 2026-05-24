import json
import os
import tempfile

import pytest

from src.stroke_taxonomy.parser import (
    classify_stroke_by_svg,
    parse_dictionary,
    parse_graphics,
    build_taxonomy,
    _extract_points,
    _count_direction_changes,
)


@pytest.fixture
def sample_dictionary_content():
    """Simulated dictionary.txt content."""
    return (
        '{"character": "一", "decomposition": "？", "definition": "one"}\n'
        '{"character": "永", "decomposition": "？", "definition": "forever"}\n'
    )


@pytest.fixture
def sample_graphics_content():
    """Simulated graphics.txt content with SVG paths."""
    return (
        '{"character": "一", "strokes": ["M 0 0 L 100 0"], "medians": [[[0,0],[100,0]]]}\n'
        '{"character": "永", "strokes": ["M 50 0 Q 50 25 50 50", "M 0 0 L 80 0 L 80 60 L 75 55", "M 80 0 L 0 100", "M 50 50 L 0 100", "M 50 50 L 100 100"], "medians": []}\n'
    )


@pytest.fixture
def dict_file(sample_dictionary_content, tmp_path):
    p = tmp_path / "dictionary.txt"
    p.write_text(sample_dictionary_content, encoding="utf-8")
    return str(p)


@pytest.fixture
def graph_file(sample_graphics_content, tmp_path):
    p = tmp_path / "graphics.txt"
    p.write_text(sample_graphics_content, encoding="utf-8")
    return str(p)


class TestParseDictionary:
    def test_parse_returns_char_data(self, dict_file):
        result = parse_dictionary(dict_file)
        assert "一" in result
        assert "永" in result

    def test_parse_includes_decomposition(self, dict_file):
        result = parse_dictionary(dict_file)
        assert "decomposition" in result["一"]

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        result = parse_dictionary(str(p))
        assert result == {}


class TestParseGraphics:
    def test_parse_returns_svg_paths(self, graph_file):
        result = parse_graphics(graph_file)
        assert "一" in result
        assert "永" in result

    def test_svg_paths_are_lists(self, graph_file):
        result = parse_graphics(graph_file)
        assert isinstance(result["一"], list)
        assert len(result["一"]) == 1

    def test_yong_has_five_strokes(self, graph_file):
        result = parse_graphics(graph_file)
        assert len(result["永"]) == 5


class TestExtractPoints:
    def test_simple_line(self):
        svg = "M 0 0 L 100 0"
        points = _extract_points(svg)
        assert len(points) == 2
        assert points[0] == (0, 0)
        assert points[1] == (100, 0)

    def test_quadratic_curve(self):
        svg = "M 0 0 Q 50 50 100 0"
        points = _extract_points(svg)
        assert len(points) >= 2


class TestCountDirectionChanges:
    def test_straight_line_no_changes(self):
        points = [(0, 0), (50, 0), (100, 0)]
        assert _count_direction_changes(points) == 0

    def test_right_angle_turn(self):
        points = [(0, 0), (100, 0), (100, 100)]
        changes = _count_direction_changes(points)
        assert changes >= 1


class TestClassifyStroke:
    def test_heng_classified(self):
        svg = "M 0 0 L 100 0"
        result = classify_stroke_by_svg(svg)
        assert result == 0  # 横

    def test_shu_classified(self):
        svg = "M 50 0 L 50 100"
        result = classify_stroke_by_svg(svg)
        assert result == 1  # 竖

    def test_pie_classified(self):
        svg = "M 100 0 L 0 100"
        result = classify_stroke_by_svg(svg)
        assert result == 2  # 撇

    def test_na_classified(self):
        svg = "M 0 0 L 100 100"
        result = classify_stroke_by_svg(svg)
        assert result == 3  # 捺

    def test_short_stroke_is_dian(self):
        svg = "M 50 0 L 50 10"
        result = classify_stroke_by_svg(svg)
        assert result == 4  # 点

    def test_hengzhe_classified(self):
        svg = "M 0 0 L 100 0 L 100 100"
        result = classify_stroke_by_svg(svg)
        assert result == 11  # 横折


class TestBuildTaxonomy:
    def test_build_taxonomy_json(self, dict_file, graph_file):
        output_path = os.path.join(tempfile.mkdtemp(), "stroke_taxonomy.json")
        result = build_taxonomy(dict_file, graph_file, output_path)

        assert os.path.exists(output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "strokes" in data
        assert "char_to_strokes" in data
        assert len(data["strokes"]) == 29

        # "一" should have 1 stroke
        assert len(data["char_to_strokes"]["一"]) == 1
