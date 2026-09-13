import pytest
from PyQt5 import QtWidgets

from brushbot.exhibition_monitor.pressure_practice import PracticeState
from brushbot.exhibition_monitor.sz_template import (
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


def test_canvas_starts_with_gray_template_and_no_completed_path(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    assert geometry["template"] == load_sz_template()
    assert geometry["completed"] == {}
    assert geometry["active_letter"] == "S"
    assert geometry["colors"]["template"] != geometry["colors"]["completed"]


def test_canvas_turns_completed_prefix_black_and_keeps_future_gray(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_practice_state(PracticeState("s_writing", "S", 0.5, True, 180.0, 0.0))
    geometry = canvas.visible_geometry()
    assert geometry["completed"]["S"]
    assert geometry["active"]["S"]
    assert geometry["template"]["Z"] == load_sz_template()["Z"]
    assert geometry["colors"]["completed"] == "#203f38"


def test_canvas_empty_state_keeps_frame_and_status(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_practice_state(None)
    geometry = canvas.visible_geometry()
    assert geometry["frame"] is True
    assert geometry["status"] == "等待开始"
    assert geometry["template"] == load_sz_template()


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


def test_canvas_uses_a_nonzero_plan_band_width(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    geometry = canvas.visible_geometry()
    assert geometry["plan_width"] > 0
    assert geometry["ink_width"] > 0


def test_canvas_does_not_leave_new_ink_while_pressure_pause_is_active(qtbot):
    canvas = SZCanvas()
    qtbot.addWidget(canvas)
    canvas.set_sensor_xy(100.0, 0.0)
    canvas.set_practice_state(PracticeState("s_paused", "S", 0.4, False, 0.0, 0.0, True, True))
    geometry = canvas.visible_geometry()
    assert geometry["ink"] == {}
