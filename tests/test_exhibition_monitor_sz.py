import pytest
from PyQt5 import QtWidgets

from brushbot.exhibition_monitor.pressure_practice import PracticeState
from brushbot.exhibition_monitor.sz_template import (
    calligraphic_outline,
    jittered_point,
    layout_sz,
    load_sz_template,
    polyline_at_progress,
    stamp_brush,
)
from brushbot.exhibition_monitor.sz_canvas import SZCanvas


@pytest.fixture
def qtbot():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Bot:
        def addWidget(self, widget):
            widget.show()
            app.processEvents()

    return Bot()


def test_sz_template_contains_ordered_s_and_z_paths():
    template = load_sz_template()
    assert tuple(template) == ("S", "Z")
    assert template["S"] and template["Z"]
    assert len({point[1] for point in template["S"]}) == 1
    assert len({point[0] for point in template["Z"]}) == 1
    assert template["S"][0][0] == pytest.approx(0.08)
    assert template["S"][-1][0] == pytest.approx(0.92)
    assert template["Z"][0][1] == pytest.approx(0.08)
    assert template["Z"][-1][1] == pytest.approx(0.92)
    for path in template.values():
        assert all(0.0 <= value <= 1.0 for point in path for value in point)


def test_polyline_progress_splits_completed_and_active_points_by_arc_length():
    points = ((0.0, 0.0), (0.9, 0.0), (0.9, 0.1))
    completed, active = polyline_at_progress(points, 0.5)
    assert completed[0] == (0.0, 0.0)
    assert completed[1] == pytest.approx((0.5, 0.0))
    assert active[0] == pytest.approx((0.5, 0.0))
    assert active[1:] == ((0.9, 0.0), (0.9, 0.1))
    assert polyline_at_progress(points, 0.0) == ((), points)
    assert polyline_at_progress(points, 1.0) == (points, ())


def test_canvas_shows_copybook_path_and_outline_before_writing(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    assert geometry["template"] == load_sz_template()
    assert geometry["planned"]["S"]
    assert geometry["planned"]["Z"]
    assert geometry["outline"]["S"]
    assert geometry["outline"]["Z"]
    assert set(geometry["grid"]) == {"S", "Z"}
    for grid in geometry["grid"].values():
        left, top, right, bottom = grid["box"]
        assert right - left == pytest.approx(bottom - top, abs=2.0)
        assert len(grid["lines"]) == 2
    assert geometry["path_visible"] is True
    assert geometry["ink"] == {}
    assert geometry["active_letter"] == "S"
    assert geometry["colors"]["template"] != geometry["colors"]["completed"]


def test_canvas_records_only_the_jittered_ink_trace(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.5, True, 220.0, 0.0, True, True))
    geometry = canvas.visible_geometry()
    assert geometry["ink"]["S"]
    assert geometry["planned"]["S"]
    assert geometry["outline"]["S"]
    assert geometry["colors"]["completed"] == "#203f38"
    assert geometry["diffusion_width"] > geometry["ink_width"]


def test_pressure_color_palette_matches_the_exhibition_theme():
    colors = [SZCanvas.pressure_color(value) for value in (200, 300, 400, 500, 600, 700, 800, 1000)]
    assert colors[0] == "#74b8a7"
    assert colors[1] == "#54a58f"
    assert colors[3] == "#2d7d6b"
    assert colors[5] == "#b56b2f"
    assert colors[6] != colors[5]
    assert colors[7] == "#8e4329"
    assert SZCanvas.pressure_color(1400.0) == "#8e4329"
    assert len(set(colors)) == len(colors)


def test_pressure_controls_brush_width():
    assert SZCanvas.brush_width_for_pressure(200.0) == pytest.approx(16.0)
    assert SZCanvas.brush_width_for_pressure(500.0) == pytest.approx(25.75)
    assert SZCanvas.brush_width_for_pressure(1000.0) == pytest.approx(42.0)
    assert SZCanvas.brush_width_for_pressure(1400.0) == pytest.approx(42.0)


def test_calligraphic_outline_has_tapered_brush_ends():
    outline = calligraphic_outline(((0.1, 0.5), (0.9, 0.5)), width=0.24, stroke="horizontal")
    assert len(outline) >= 8
    assert min(point[1] for point in outline) < 0.5
    assert max(point[1] for point in outline) > 0.5
    assert max(point[0] for point in outline) - min(point[0] for point in outline) > 0.7


def test_horizontal_one_and_vertical_stroke_have_calligraphic_tapers():
    horizontal = calligraphic_outline(((0.1, 0.5), (0.9, 0.5)), width=0.24, stroke="horizontal")
    vertical = calligraphic_outline(((0.5, 0.1), (0.5, 0.9)), width=0.24, stroke="vertical")
    horizontal_start = abs(horizontal[0][1] - horizontal[-1][1])
    horizontal_end = abs(horizontal[3][1] - horizontal[4][1])
    vertical_start = abs(vertical[0][0] - vertical[-1][0])
    vertical_end = abs(vertical[3][0] - vertical[4][0])
    assert horizontal_start > horizontal_end
    assert vertical_start > vertical_end


def test_reference_contours_keep_many_samples_and_sharp_needle_finish():
    horizontal = calligraphic_outline(((0.1, 0.5), (0.9, 0.5)), width=0.24, stroke="horizontal")
    vertical = calligraphic_outline(((0.5, 0.1), (0.5, 0.9)), width=0.24, stroke="vertical")
    assert len(horizontal) >= 16
    assert len(vertical) >= 16
    horizontal_tip_width = abs(horizontal[len(horizontal) // 2 - 1][1] - horizontal[len(horizontal) // 2][1])
    vertical_tip_width = abs(vertical[len(vertical) // 2 - 1][0] - vertical[len(vertical) // 2][0])
    assert horizontal_tip_width <= 0.1 * 0.24
    assert vertical_tip_width <= 0.05 * 0.24


def test_canvas_keeps_pressure_per_ink_sample_and_uses_thicker_brush(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.5, True, 700.0, 0.0, True, True))
    geometry = canvas.visible_geometry()
    assert geometry["ink_pressure"]["S"]
    assert set(geometry["ink_pressure"]["S"]) == {700.0}
    assert geometry["ink_width"] >= 24.0
    assert geometry["point_color"] == SZCanvas.pressure_color(700.0)
    assert geometry["ink_widths"]["S"]
    assert set(geometry["ink_widths"]["S"]) == {SZCanvas.brush_width_for_pressure(700.0)}
    assert geometry["point_width"] == SZCanvas.brush_width_for_pressure(700.0)


def test_canvas_empty_state_keeps_frame_and_status(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_practice_state(None)
    geometry = canvas.visible_geometry()
    assert geometry["frame"] is True
    assert geometry["status"] == "等待开始"
    assert geometry["template"] == load_sz_template()


def test_canvas_does_not_add_sz_prompt_to_canvas_header(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    assert not canvas.visible_geometry()["status"].startswith("SZ")


def test_layout_puts_s_and_z_in_separate_left_to_right_boxes():
    boxes = layout_sz(load_sz_template(), (0.0, 0.0, 1000.0, 400.0), gutter=80.0)
    assert boxes["S"][2] > 0
    assert boxes["Z"][0] > boxes["S"][2]
    assert boxes["S"][1] == pytest.approx(boxes["Z"][1])


def test_xy_jitter_uses_plot_orientation_and_is_clamped():
    point = jittered_point((100.0, 100.0), (100.0, 0.0), jitter_gain=1.0, max_offset=12.0)
    assert point == pytest.approx((112.0, 100.0))
    point = jittered_point((100.0, 100.0), (0.0, 100.0), jitter_gain=1.0, max_offset=12.0)
    assert point == pytest.approx((100.0, 88.0))


def test_stamp_brush_interpolates_a_thick_path():
    points = stamp_brush((0.0, 0.0), (30.0, 0.0), brush_width=18.0)
    assert points[0] == (0.0, 0.0)
    assert points[-1] == (30.0, 0.0)
    assert len(points) >= 3


def test_canvas_uses_a_tighter_hidden_jitter_limit(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    assert geometry["jitter_limit"] == 0.0
    assert geometry["ink_width"] > 0


def test_canvas_does_not_leave_new_ink_while_pressure_pause_is_active(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_sensor_xy(100.0, 0.0)
    canvas.set_practice_state(PracticeState("s_paused", "S", 0.4, False, 0.0, 0.0, True, True))
    geometry = canvas.visible_geometry()
    assert geometry["ink"] == {}


def test_canvas_freezes_brush_point_during_pressure_pause(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_sensor_xy(0.0, 0.0)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.4, True, 150.0, 0.0, True, True))
    writing_point = canvas.visible_geometry()["point"]
    canvas.set_sensor_xy(100.0, 0.0)
    canvas.set_practice_state(PracticeState("s_paused", "S", 0.4, False, 0.0, 0.0, True, True))
    assert canvas.visible_geometry()["point"] == writing_point


def test_canvas_brush_point_stays_on_centerline_when_xy_changes(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_sensor_xy(0.0, 0.0)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.4, True, 500.0, 0.0, True, True))
    first = canvas.visible_geometry()["point"]
    canvas.set_sensor_xy(400.0, -400.0)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.4, True, 500.0, 0.0, True, True))
    assert canvas.visible_geometry()["point"] == first


def test_canvas_outline_is_a_polygon_separate_from_centerline(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    assert len(geometry["outline"]["S"]) >= 8
    assert len(geometry["outline"]["S"]) > len(geometry["planned"]["S"])


def test_copybook_strokes_fill_most_of_each_tianzige(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    for letter, axis in (("S", 0), ("Z", 1)):
        path = geometry["template"][letter]
        start = path[0][axis]
        end = path[-1][axis]
        assert end - start >= 0.84


def test_canvas_does_not_bridge_ink_between_s_and_z_boxes(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.9, True, 150.0, 0.0, True, True))
    canvas.set_practice_state(PracticeState("z_writing", "Z", 0.1, True, 150.0, 0.0, True, True))
    geometry = canvas.visible_geometry()
    assert geometry["ink"]["Z"][0][0] >= geometry["boxes"]["Z"][0]


def test_canvas_keeps_hidden_letter_boxes_inside_the_frame(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    frame = canvas._plot_rect()
    assert geometry["boxes"]["S"][1] >= frame.top()
    assert geometry["boxes"]["S"][3] <= frame.bottom()
