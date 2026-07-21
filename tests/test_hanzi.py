import json

import pytest

from brushbot.calligraphy.hanzi import (
    load_medians,
    medians_to_strokes,
    strokes_to_waypoints,
)


def _write_graphics(tmp_path, records):
    p = tmp_path / "graphics.txt"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records),
                 encoding="utf-8")
    return str(p)


def test_load_medians_returns_that_characters_medians(tmp_path):
    path = _write_graphics(tmp_path, [
        {"character": "一", "strokes": ["M0 0"], "medians": [[[1, 2], [3, 4]]]},
        {"character": "永", "strokes": ["M0 0"], "medians": [[[5, 6]], [[7, 8], [9, 10]]]},
    ])
    assert load_medians("永", path) == [[[5, 6]], [[7, 8], [9, 10]]]


def test_load_medians_raises_for_absent_character(tmp_path):
    path = _write_graphics(tmp_path, [
        {"character": "一", "strokes": ["M0 0"], "medians": [[[1, 2]]]},
    ])
    with pytest.raises(KeyError):
        load_medians("永", path)


def test_medians_to_strokes_scales_longest_side_to_size_and_centers():
    # bbox: x 0..100 (宽 100), y 0..50 (高 50) -> 按宽缩放, 中心 (50,25) 移到原点
    medians = [[[0, 0], [100, 0], [100, 50]]]
    strokes = medians_to_strokes(medians, size=0.04)
    assert len(strokes) == 1
    assert strokes[0] == pytest.approx([(-0.02, -0.01), (0.02, -0.01), (0.02, 0.01)])


def test_medians_to_strokes_preserves_stroke_count_and_point_counts():
    medians = [[[0, 0], [10, 0]], [[0, 10], [5, 5], [10, 10]]]
    strokes = medians_to_strokes(medians, size=0.03)
    assert [len(s) for s in strokes] == [2, 3]


def test_strokes_to_waypoints_lifts_pen_between_strokes():
    strokes = [[(0.0, 0.0), (0.01, 0.0)], [(0.0, 0.01), (0.01, 0.01)]]
    wp = strokes_to_waypoints(strokes, origin=(0.5, 0.1), z_down=0.196, z_up=0.23)
    # 每笔: 抬笔趋近 + 笔上各点 + 抬笔收尾
    assert len(wp) == (1 + 2 + 1) * 2
    zs = [p[2] for p in wp]
    assert zs == [0.23, 0.196, 0.196, 0.23, 0.23, 0.196, 0.196, 0.23]
    # 局部坐标被平移到 origin
    assert wp[1][:2] == pytest.approx((0.5, 0.1))
    assert wp[2][:2] == pytest.approx((0.51, 0.1))
