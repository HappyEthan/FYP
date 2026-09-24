import pytest

from brushbot.exhibition.hanzi_preview import build_hanzi_plan, preview_character


def test_preview_contains_single_character_strokes():
    result = preview_character("永")
    assert result["character"] == "永"
    assert result["stroke_count"] > 1
    assert all(len(point) == 2 for stroke in result["strokes"] for point in stroke)


def test_plan_builder_returns_fixed_six_dimensional_waypoints():
    plan = build_hanzi_plan("永")
    assert len(plan) > 10
    assert all(len(pose) == 6 for pose in plan)
    assert all(pose[3:] == pytest.approx((3.141592653589793, 0.0, 1.5707963267948966))
               for pose in plan)
