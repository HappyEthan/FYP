"""Drive import and order through real Qt controls, including cancel and undo."""
import copy
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
from PyQt5 import QtCore, QtTest, QtWidgets

import scripts.edit_brush_path as ui
from scripts.brush_path_editor_model import PathModel
from tests.test_brush_variation_model import model


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(model, app, tmp_path, monkeypatch):
    monkeypatch.setattr(ui, 'DRAFT', tmp_path/'draft.json')
    monkeypatch.setattr(ui.W.QMessageBox, 'warning', lambda *a: None)
    window = ui.Editor(model)
    window.show(); app.processEvents()
    yield window
    window.close()


def test_file_menu_import_adds_stroke_saves_and_undoes(win, app, monkeypatch):
    from scripts.brush_stroke_import_dialog import StrokeImportDialog
    original = win.model.points().copy()
    monkeypatch.setattr(ui.W.QFileDialog, 'getOpenFileName', lambda *a: (str(win.model.folder/'recipe.json'), ''))
    files = next(a.menu() for a in win.menuBar().actions() if a.text() == '文件')
    action = next(a for a in files.actions() if a.text() == '导入笔画…')
    def accept():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, StrokeImportDialog)
        assert dialog.stroke_list.count() == 1
        assert dialog.gap.value() == 10.
        dialog.accept()
    QtCore.QTimer.singleShot(0, accept)
    action.trigger()
    assert win.stroke_selector.count() == 2
    assert np.array_equal(win.model.points(), original)
    assert len(PathModel.restore(ui.DRAFT).stroke_order) == 2
    win.undo()
    assert win.stroke_selector.count() == 1
    assert len(PathModel.restore(ui.DRAFT).stroke_order) == 1


def test_import_dialog_cancel_and_empty_selection_do_not_mutate(win):
    from scripts.brush_stroke_import_dialog import StrokeImportDialog
    source = PathModel.from_state(win.model.portable_state())
    before = copy.deepcopy(win.model.state())
    dialog = StrokeImportDialog(win.model, source)
    dialog.stroke_list.item(0).setCheckState(QtCore.Qt.Unchecked)
    dialog.accept()
    assert dialog.result() != QtWidgets.QDialog.Accepted
    assert '选择' in dialog.error.text()
    dialog.reject()
    assert win.model.state() == before


def test_order_buttons_change_execution_numbering_save_and_undo(win):
    first = win.model.stroke_id
    win.model.add_independent_point([0., 20.]); win.model.add_independent_point([10., 20.])
    second = win.model.stroke_id
    win.rebuild_handles(); win.refresh(True); win.remember()
    before = win.model.points().copy()
    assert win.move_up_button.isEnabled()
    assert not win.move_down_button.isEnabled()
    QtTest.QTest.mouseClick(win.move_up_button, QtCore.Qt.LeftButton)
    assert win.model.stroke_order == [second, first]
    assert win.model.stroke_id == second
    assert np.array_equal(win.model.points(), before)
    assert win.test_first.value() == 0
    assert not win.move_up_button.isEnabled()
    assert win.move_down_button.isEnabled()
    assert PathModel.restore(ui.DRAFT).stroke_order == [second, first]
    win.undo()
    assert win.model.stroke_order == [first, second]
    assert win.test_first.value() == 2


def test_pending_point_disables_import_and_order_controls(win):
    win.model.add_independent_point([0., 30.]); win.refresh(True)
    assert not win.import_stroke_action.isEnabled()
    assert not win.move_up_button.isEnabled()
    assert not win.move_down_button.isEnabled()


def test_dialog_recomputes_layout_when_gap_or_side_changes(win):
    from scripts.brush_stroke_import_dialog import StrokeImportDialog
    from scripts.brush_stroke_import import paper_points
    source = PathModel.from_state(win.model.portable_state())
    dialog = StrokeImportDialog(win.model, source)
    dialog.side.setCurrentIndex(dialog.side.findData('left'))
    dialog.gap.setValue(17.)
    dialog.offset_y.setValue(5.)
    dialog.accept()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    imported = PathModel.from_state(dialog.candidate.other_strokes[-1])
    assert paper_points(imported)[:, 0].max() == pytest.approx(paper_points(win.model)[:, 0].min()-17.)
    assert paper_points(imported)[:, 1].mean() == pytest.approx(paper_points(win.model)[:, 1].mean()+5.)
    dialog.close()
