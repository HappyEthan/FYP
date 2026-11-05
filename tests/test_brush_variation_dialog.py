"""Exercise the compact dialog's real Qt controls without hardware or a terminal."""
import copy
import json
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt5 import QtWidgets as W

from tests.test_writing_variation_integration import model_with_variation


@pytest.fixture(scope='module')
def app():
    yield W.QApplication.instance() or W.QApplication([])


def make_dialog(tmp_path):
    from scripts.brush_variation_dialog import WritingVariationDialog
    return WritingVariationDialog(model_with_variation(), profiles_path=tmp_path/'profiles.json')


def test_only_three_tuning_controls_and_preview_becomes_stale_after_edit(app, tmp_path):
    dialog = make_dialog(tmp_path)
    assert len(dialog.findChildren(W.QDoubleSpinBox)) == 2
    assert dialog.repeat_level.count() == 3
    assert dialog.preview() is True
    assert dialog.preview_data is not None
    assert dialog.xy_plot.listDataItems()
    dialog.xy_limit.setValue(.10)
    assert dialog.preview_data is None
    assert not dialog.xy_plot.listDataItems()
    assert '重新' in dialog.report.text()
    dialog.reject()


def test_cancel_does_not_modify_source_or_write_the_profile_library(app, tmp_path):
    from scripts.brush_variation_dialog import WritingVariationDialog
    source = model_with_variation()
    before = source.state()
    path = tmp_path/'profiles.json'
    dialog = WritingVariationDialog(source, profiles_path=path)
    dialog.new_profile()
    dialog.bias.setValue(10.)
    dialog.xy_limit.setValue(.1)
    dialog.preview()
    dialog.reject()
    assert source.state() == before
    assert not path.exists()


def test_saved_profile_can_be_loaded_in_a_new_dialog(app, tmp_path):
    from brushbot.experiments.writing_variation import ProfileStore
    dialog = make_dialog(tmp_path)
    dialog.new_profile()
    dialog.profile_name.setText('轻重验证配置')
    assert dialog.save_settings() is True
    assert dialog.result() == W.QDialog.Accepted
    saved = copy.deepcopy(dialog.candidate.writing_variation['profile'])
    assert saved in ProfileStore(tmp_path/'profiles.json').load()
    again = make_dialog(tmp_path)
    index = again.profile_selector.findData(saved['id'])
    assert index >= 0
    again.profile_selector.setCurrentIndex(index)
    assert again.profile_name.text() == '轻重验证配置'
    assert again.config()['profile'] == saved
    again.reject()


def test_new_repetition_keeps_fixed_style_and_reuse_locks_the_same_arrays(app, tmp_path):
    dialog = make_dialog(tmp_path)
    assert dialog.preview()
    first = copy.deepcopy(dialog.candidate.variation_snapshot)
    assert dialog.regenerate()
    second = copy.deepcopy(dialog.candidate.variation_snapshot)
    assert first['strokes'][0]['fixed_xy_mm'] == second['strokes'][0]['fixed_xy_mm']
    assert first['strokes'][0]['repeat_xy_mm'] != second['strokes'][0]['repeat_xy_mm']
    assert dialog.reuse_previous()
    assert dialog.candidate.variation_locked is True
    assert dialog.candidate.variation_snapshot == second
    dialog.reject()


def test_new_configuration_changes_style_but_keeps_the_chosen_bias(app, tmp_path):
    dialog = make_dialog(tmp_path)
    dialog.bias.setValue(0.)
    assert dialog.preview()
    original = copy.deepcopy(dialog.candidate.variation_snapshot)
    dialog.new_profile()
    assert dialog.bias.value() == 0.
    assert dialog.preview()
    changed = dialog.candidate.variation_snapshot
    assert changed['strokes'][0]['fixed_xy_mm'] != original['strokes'][0]['fixed_xy_mm']
    dialog.reject()


def test_menu_is_reachable_and_trial_preserves_preview_then_prepares_next_repeat(app, tmp_path, monkeypatch):
    import scripts.edit_brush_path as ui
    from brushbot.experiments.archive import ExperimentArchive
    monkeypatch.setattr(ui, 'DRAFT', tmp_path/'draft.json')
    monkeypatch.setattr(ui.W.QMessageBox, 'warning', lambda *a: None)
    window = ui.Editor(model_with_variation())
    window.archive = ExperimentArchive(tmp_path/'records')
    advanced = next(action.menu() for action in window.menuBar().actions() if action.text() == '高级设置')
    assert any('随机扰动' in action.text() for action in advanced.actions())
    window.model.compile_workspace()
    snapshot = copy.deepcopy(window.model.variation_snapshot)
    launched = []
    monkeypatch.setattr(ui.subprocess, 'run', lambda command, **kwargs: launched.append(command))
    window.launch_trial()
    assert len(launched) == 1
    realizations = list(window.archive.temporary.rglob('writing_variation.json'))
    assert len(realizations) == 1
    assert json.loads(realizations[0].read_text()) == snapshot
    assert window.model.variation_snapshot is None
    assert window.model.variation_repeat_seed != snapshot['repeat_seed']
    window.close()
