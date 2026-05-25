import json
import os
import tempfile

import pytest

from src.stroke_taxonomy.parser import (
    classify_stroke_by_median,
    parse_dictionary,
    parse_graphics,
    parse_graphics_with_medians,
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
    """Simulated graphics.txt content with medians."""
    return (
        '{"character": "一", "strokes": ["M 0 0 L 100 0"], "medians": [[[0,0],[100,0]]]}\n'
        '{"character": "永", "strokes": ["M 50 0 L 50 50", "M 0 0 L 80 0 L 80 60", "M 80 0 L 0 100", "M 50 50 L 0 100", "M 50 50 L 100 100"], "medians": [[[50,0],[50,25],[50,50]], [[0,0],[80,0],[80,60],[75,55]], [[80,0],[0,100]], [[50,50],[0,100]], [[50,50],[100,100]]]}\n'
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


class TestParseGraphicsWithMedians:
    def test_parse_returns_medians(self, graph_file):
        result = parse_graphics_with_medians(graph_file)
        assert "一" in result
        assert "永" in result

    def test_medians_are_nested_lists(self, graph_file):
        result = parse_graphics_with_medians(graph_file)
        assert isinstance(result["一"], list)
        assert isinstance(result["一"][0], list)
        assert isinstance(result["一"][0][0], list)
        assert result["一"][0][0] == [0, 0]

    def test_yong_has_five_medians(self, graph_file):
        result = parse_graphics_with_medians(graph_file)
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


class TestClassifyStrokeByMedian:
    """Tests for the median-based stroke classifier."""

    # Basic strokes
    def test_heng(self):
        median = [[0, 0], [100, 0]]
        assert classify_stroke_by_median(median) == 0  # 横

    def test_shu(self):
        median = [[50, 0], [50, 100]]
        assert classify_stroke_by_median(median) == 1  # 竖

    def test_pie(self):
        median = [[100, 0], [0, 100]]
        assert classify_stroke_by_median(median) == 2  # 撇

    def test_na(self):
        median = [[0, 0], [100, 100]]
        assert classify_stroke_by_median(median) == 3  # 捺

    def test_dian_short(self):
        median = [[50, 0], [50, 10]]
        assert classify_stroke_by_median(median) == 4  # 点

    def test_dian_single_point(self):
        median = [[50, 50]]
        assert classify_stroke_by_median(median) == 4  # 点

    def test_ti(self):
        median = [[0, 50], [80, 0]]
        assert classify_stroke_by_median(median) == 5  # 提

    # Hook strokes — hooks are small-angle turns (< 60°) at stroke end
    def test_shugou(self):
        # Vertical down, then small left hook
        median = [[50, 0], [50, 80], [45, 85]]
        assert classify_stroke_by_median(median) == 6  # 竖钩

    def test_xiegou(self):
        # Diagonal down-right, then small left hook (angle < 60°)
        median = [[0, 0], [60, 80], [59, 83]]
        assert classify_stroke_by_median(median) == 8  # 斜钩

    def test_henggou(self):
        # Horizontal right, then small downward-forward hook (angle < 60°)
        median = [[0, 0], [80, 0], [82, 2]]
        assert classify_stroke_by_median(median) == 10  # 横钩

    # Fold strokes — folds are large-angle turns (> 60°)
    def test_hengzhe(self):
        median = [[0, 0], [100, 0], [100, 100]]
        assert classify_stroke_by_median(median) == 11  # 横折

    def test_shuzhe(self):
        median = [[50, 0], [50, 80], [100, 80]]
        assert classify_stroke_by_median(median) == 12  # 竖折

    def test_piezhe(self):
        median = [[100, 0], [0, 80], [50, 80]]
        assert classify_stroke_by_median(median) == 13  # 撇折

    # Compound strokes
    def test_hengzhegou(self):
        # Horizontal, fold down, small left hook
        median = [[0, 0], [80, 0], [80, 60], [75, 68]]
        assert classify_stroke_by_median(median) == 14  # 横折钩

    def test_hengpie(self):
        # Horizontal, then large-angle diagonal (fold > 100°)
        median = [[0, 0], [60, 0], [0, 100]]
        assert classify_stroke_by_median(median) == 15  # 横撇

    def test_shuzhezhegou(self):
        # Vertical, fold right, fold down, small left hook
        median = [[50, 0], [50, 40], [80, 40], [80, 70], [75, 78]]
        assert classify_stroke_by_median(median) == 18  # 竖折折钩

    def test_hengzhezhepie(self):
        # Horizontal, fold down, fold right, diagonal end (no hook)
        median = [[0, 0], [50, 0], [50, 30], [80, 30], [0, 100]]
        assert classify_stroke_by_median(median) == 19  # 横折折撇

    def test_shuti(self):
        # Vertical down, then small right-up tick
        median = [[50, 0], [50, 70], [58, 62]]
        assert classify_stroke_by_median(median) == 20  # 竖提

    def test_piedian(self):
        # Diagonal left-down (pie), then fold to dot
        median = [[100, 0], [0, 60], [50, 100]]
        assert classify_stroke_by_median(median) == 21  # 撇点

    def test_hengzheti(self):
        # Horizontal, fold down, small right-up tick
        median = [[0, 0], [60, 0], [60, 40], [68, 32]]
        assert classify_stroke_by_median(median) == 22  # 横折提

    def test_hengzhewan(self):
        # Horizontal, fold down, then curve right (small angle turn, no hook)
        median = [[0, 0], [60, 0], [60, 30], [80, 50]]
        assert classify_stroke_by_median(median) == 23  # 横折弯

    def test_shuwan(self):
        # Vertical down, then curve right (small angle turn, no hook)
        median = [[50, 0], [50, 60], [80, 80]]
        assert classify_stroke_by_median(median) == 24  # 竖弯

    def test_shuwangou(self):
        # Vertical down, curve right, small left-up hook
        median = [[50, 0], [50, 50], [80, 70], [75, 78]]
        assert classify_stroke_by_median(median) == 25  # 竖弯钩

    def test_hengxiegou(self):
        # Horizontal, then diagonal down-right with small left hook
        median = [[0, 0], [50, 0], [80, 50], [75, 58]]
        assert classify_stroke_by_median(median) == 26  # 横斜钩

    def test_hengzhezhezhegou(self):
        # Horizontal, 3 folds, small left hook
        median = [[0, 0], [40, 0], [40, 20], [60, 20], [60, 40], [55, 48]]
        assert classify_stroke_by_median(median) == 27  # 横折折折钩

    def test_hengzhezhe(self):
        # Horizontal, fold down, fold right (no hook)
        median = [[0, 0], [40, 0], [40, 20], [60, 20], [60, 40]]
        assert classify_stroke_by_median(median) == 28  # 横折折

    # Edge cases
    def test_empty_median(self):
        assert classify_stroke_by_median([]) == 4  # 点

    def test_two_point_short(self):
        median = [[0, 0], [5, 0]]
        assert classify_stroke_by_median(median) == 4  # 点 (too short)

    def test_multi_point_heng(self):
        median = [[0, 0], [30, 2], [60, -1], [100, 0]]
        assert classify_stroke_by_median(median) == 0  # 横


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
