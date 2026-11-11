import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import copy
import numpy as np
import pytest
from PyQt5 import QtWidgets,QtCore
from tests.test_brush_variation_model import model
from tests.test_brush_variation_responsiveness import wait_until


@pytest.fixture(scope='module')
def app():return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_controls_default_off_and_generate_uses_new_seed(model,app):
    from scripts.brush_variation_dialog import VariationDialog
    d=VariationDialog(model)
    assert not d.enabled.isChecked()
    d.enabled.setChecked(True);d.generate()
    wait_until(lambda:d.last_result is not None)
    first=copy.deepcopy(d.candidate.random_variation['batch'])
    d.generate();wait_until(lambda:d.last_result is not None);second=d.candidate.random_variation['batch']
    assert first['root_seed']!=second['root_seed']
    assert first['stroke_fields']!=second['stroke_fields']
    assert d.last_result is not None and len(d.path_after.xData)>2
    assert getattr(model,'random_variation',None) is None
    d.reject();d.close()


def test_cancel_and_child_toggle_preserve_draws(model,app):
    from scripts.brush_variation_dialog import VariationDialog
    d=VariationDialog(model);d.enabled.setChecked(True);d.generate()
    wait_until(lambda:d.last_result is not None)
    batch=copy.deepcopy(d.candidate.random_variation['batch'])
    d.xy_enabled.setChecked(False);d.preview()
    wait_until(lambda:d.last_result is not None)
    assert d.candidate.random_variation['batch']==batch
    d.xy_enabled.setChecked(True);d.preview()
    wait_until(lambda:d.last_result is not None)
    assert d.candidate.random_variation['batch']==batch
    d.reject();assert getattr(model,'random_variation',None) is None


def test_advanced_settings_action_applies_without_motion_and_supports_undo(model,app,tmp_path,monkeypatch):
    import scripts.edit_brush_path as ui
    from scripts.brush_variation_dialog import VariationDialog
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    w=ui.Editor(model);w.show()
    before=w.model.points().copy()
    advanced=next(a.menu() for a in w.menuBar().actions() if a.text()=='高级设置')
    actions=[a for a in advanced.actions() if a.text()=='随机变化…']
    assert len(actions)==1
    def apply():
        d=app.activeModalWidget();assert isinstance(d,VariationDialog)
        d.enabled.setChecked(True);d.generate();wait_until(lambda:d.last_result is not None);d.accept()
    QtCore.QTimer.singleShot(0,apply);actions[0].trigger()
    assert w.model.variation_status()['state']=='ready'
    batch=copy.deepcopy(w.model.random_variation['batch'])
    w.preflight();w.preflight()
    assert w.model.random_variation['batch']==batch
    assert np.array_equal(w.model.points(),before)
    w.undo();assert w.model.variation_status()['state']=='off'
    w.close()


def test_edit_and_undo_revalidate_fingerprint(model,app,tmp_path,monkeypatch):
    import scripts.edit_brush_path as ui
    monkeypatch.setattr(ui,'DRAFT',tmp_path/'draft.json')
    w=ui.Editor(model)
    w.model.set_variation_options(enabled=True);w.model.generate_variation(seed=101);w.remember()
    w.model.nodes[-1,0]+=.1;w.remember()
    assert w.model.variation_status()['state']=='stale'
    w.undo();assert w.model.variation_status()['state']=='ready'
    w.close()
