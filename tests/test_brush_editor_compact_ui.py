"""Exercise daily edits through the compact editor's actual Qt controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PyQt5 import QtCore, QtTest, QtWidgets

import scripts.edit_brush_path as ui
from scripts.brush_path_editor_model import PathModel


@pytest.fixture(scope='module')
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, 'DRAFT', tmp_path / 'draft.json')
    monkeypatch.setattr(ui.W.QMessageBox, 'warning', lambda *args: None)
    window = ui.Editor(PathModel())
    window.show()
    window.activateWindow()
    app.processEvents()
    yield window
    window.close()


def type_value(field, text):
    field.setFocus()
    QtTest.QTest.keyClick(field, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
    if text:
        QtTest.QTest.keyClicks(field, text)
    else:
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Backspace)


def test_canvas_selects_segment_and_first_node_coordinates_round_trip(win, app):
    win.choose_segment(5)
    midpoint = (win.model.nodes[0] + win.model.nodes[1]) / 2
    scene = win.path_view.mapViewToScene(QtCore.QPointF(*midpoint))
    position = win.plot.mapFromScene(scene)
    QtTest.QTest.mouseClick(win.plot.viewport(), QtCore.Qt.LeftButton, pos=position)
    assert win.table.currentRow() == 0
    assert win.inspector.currentWidget() is win.segment_panel

    win.model.nodes[0, 1] += .00001234
    win.refresh(True)
    win.remember()
    before = win.model.nodes.copy()
    win.click_path_point(0)
    assert win.inspector.currentWidget() is win.point_panel
    type_value(win.point_x, str(round(before[0, 0] + .2, 4)))
    QtTest.QTest.keyClick(win.point_x, QtCore.Qt.Key_Return)
    assert win.model.nodes[0, 0] == pytest.approx(round(before[0, 0] + .2, 4))
    assert win.model.nodes[0, 1] == before[0, 1]  # Preserve the untouched axis's precision.
    assert np.array_equal(PathModel.restore(ui.DRAFT).nodes, win.model.nodes)
    win.undo()
    assert np.array_equal(win.model.nodes, before)


def test_magnetic_inheritance_and_shared_angle_edit_from_inspector(win):
    win.choose_segment(3)
    assert win.magnetic_inherit.isChecked()
    win.magnetic_inherit.setChecked(False)
    type_value(win.segment_fields[5], '150.125')
    QtTest.QTest.keyClick(win.segment_fields[5], QtCore.Qt.Key_Return)
    assert win.model.segment_magnetic[3] == 150.125
    type_value(win.segment_fields[7], '12.25')
    QtTest.QTest.keyClick(win.segment_fields[7], QtCore.Qt.Key_Return)
    assert win.model.node_angles[4, 0] == 12.25
    assert win.table.item(4, 6).text() == '12.25'
    type_value(win.segment_fields[7], '')
    QtTest.QTest.keyClick(win.segment_fields[7], QtCore.Qt.Key_Return)
    assert win.model.node_angles[4, 0] is None
    win.magnetic_inherit.setChecked(True)
    assert win.model.segment_magnetic[3] is None
    assert not win.segment_fields[5].isEnabled()


def test_save_shortcut_commits_focused_field(win):
    win.choose_segment(2)
    type_value(win.segment_fields[6], '13.456')
    # No Return or focus change before the shortcut.
    QtTest.QTest.keyClick(win.segment_fields[6], QtCore.Qt.Key_S, QtCore.Qt.ControlModifier)
    assert PathModel.restore(ui.DRAFT).node_angles[2, 0] == 13.456


def test_export_commits_editor_and_invalid_edit_aborts_export(win, tmp_path, monkeypatch):
    exports = []

    def export():
        exports.append(win.model.node_angles[2, 0])
        return tmp_path, dict(retiming_factor=1., writing_duration_s=1., execution_order=[], local_speed_iterations=0)

    monkeypatch.setattr(win.model, 'export', export)
    win.choose_segment(2)
    type_value(win.segment_fields[6], '14')
    assert win.export_version() == tmp_path
    assert exports == [14.]
    type_value(win.segment_fields[6], '35')
    assert win.export_version() is None
    assert exports == [14.]
    assert win.model.node_angles[2, 0] == 14.


def test_delete_key_edits_text_but_deletes_nodes_only_in_canvas(win, app):
    count = len(win.model.nodes)
    win.click_path_point(3)
    win.point_x.setFocus()
    QtTest.QTest.keyClick(win.point_x, QtCore.Qt.Key_Delete)
    assert len(win.model.nodes) == count
    win.plot.setFocus()
    app.processEvents()
    QtTest.QTest.keyClick(win.plot, QtCore.Qt.Key_Delete)
    assert len(win.model.nodes) == count - 1
    win.undo()
    assert len(win.model.nodes) == count


def test_add_menu_mode_allows_clicking_on_existing_path(win, app):
    count = len(win.model.nodes)
    midpoint = (win.model.nodes[0] + win.model.nodes[1]) / 2
    win.show_add_points(True)
    app.processEvents()
    win.insert_order.setValue(1)
    scene = win.path_view.mapViewToScene(QtCore.QPointF(*midpoint))
    position = win.plot.mapFromScene(scene)
    QtTest.QTest.mouseClick(win.plot.viewport(), QtCore.Qt.LeftButton, pos=position)
    assert len(win.model.nodes) == count + 1
    assert np.allclose(win.model.nodes[1], midpoint, atol=.15)
    win.finish_adding()
    assert not win.click_insert_button.isChecked()
    assert win.add_panel.isHidden()


def test_test_panel_lists_each_strokes_effective_execution_range(win):
    win.model.add_independent_point([10., 10.])
    win.model.add_independent_point([20., 10.])
    win.rebuild_handles()
    win.refresh(True)
    win.show_test_ranges()
    assert '点 0 → 20' in win.execution_ranges.text()
    assert '点 21 → 22' in win.execution_ranges.text()
    assert win.test_first.value() == 21
    assert win.test_last.value() == 22
