import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PyQt5 import QtWidgets,QtCore
from tests.test_stroke_classifier_analysis import small_config
from tests.test_stroke_classifier_training import experiments

@pytest.fixture(scope='module')
def app():return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

@pytest.fixture
def source(tmp_path):
    from brushbot.stroke_classification.training import train
    from brushbot.stroke_classification.store import ModelStore
    store=ModelStore(tmp_path/'store');task=train(experiments(tmp_path),replace(small_config(),cs=(.1,)),store.root)
    model=task['models'][0];bundle=store.load_bundle(task['id'],model['id'])
    predictions=[dict(p) for p in model['predictions']]
    # Intentionally mark a known sample as OOF error for deterministic UI assertions.
    predictions[8]['predicted']=(predictions[8]['true']+1)%7
    return bundle,predictions


def test_filter_keeps_coordinates_and_pick_links_original_sample(source,app):
    from brushbot.stroke_classification.space_ui import SpaceExplorer
    bundle,predictions=source;widget=SpaceExplorer();widget.set_source(bundle,predictions)
    points=bundle['training_projection'].copy()
    for i,check in enumerate(widget.class_checks):check.setChecked(i==1)
    assert widget.visible_indices().tolist()==[1,8,15,22]
    artist=next(a for a in widget.plot.figure.axes[0].collections if hasattr(a,'sample_indices') and len(a.sample_indices))
    assert artist.sample_indices.tolist()==[1,8,15,22]
    widget.plot.pick(SimpleNamespace(artist=artist,ind=[1]))
    assert widget.selected_index==8
    assert '第2笔' in widget.details.text() and '留出预测' in widget.details.text()
    widget.only_errors.setChecked(True)
    assert 8 in widget.visible_indices()
    np.testing.assert_array_equal(bundle['training_projection'],points)
    widget.close()


def test_three_dimensional_camera_preserved_and_supports_optional(source,app):
    from brushbot.stroke_classification.space_ui import SpaceExplorer
    bundle,predictions=source;widget=SpaceExplorer();widget.set_source(bundle,predictions)
    widget.dimension.setCurrentIndex(1)
    ax=widget.plot.figure.axes[0];ax.view_init(elev=13,azim=47)
    widget.opacity.setValue(55)
    ax=widget.plot.figure.axes[0]
    assert ax.elev==13 and ax.azim==47
    assert not any(a.get_label()=='支持向量' for a in ax.collections)
    widget.supports.setChecked(True)
    assert any(a.get_label()=='支持向量' for a in widget.plot.figure.axes[0].collections)
    widget.reset_view()
    assert widget.plot.figure.axes[0].azim==-60
    widget.close()


def test_new_sample_uses_saved_projection_without_fitting(source,app,monkeypatch):
    from brushbot.stroke_classification.space_ui import SpaceExplorer
    from brushbot.stroke_classification.predict import predict_strokes
    bundle,_=source
    result=predict_strokes(bundle,bundle['training_strokes'][:1])[0]
    def forbid(*args,**kwargs):raise AssertionError('Displaying samples must not refit PCA')
    monkeypatch.setattr(bundle['pca'],'fit',forbid)
    widget=SpaceExplorer();widget.set_source(bundle,new=result)
    widget.dimension.setCurrentIndex(1);widget.plane.setCurrentIndex(2)
    assert any(a.get_label()=='新样本' for a in widget.plot.figure.axes[0].collections)
    widget.close()


def test_new_sample_can_be_reselected_and_clears_previous_point(source,app):
    from brushbot.stroke_classification.space_ui import SpaceExplorer
    from brushbot.stroke_classification.predict import predict_strokes
    bundle,_=source;results=predict_strokes(bundle,bundle['training_strokes'][:2])
    widget=SpaceExplorer();widget.set_source(bundle,new=results[0]);widget.select_sample(8)
    widget.set_source(bundle,new=results[1])
    assert widget.selected_index is None
    assert '新样本' in widget.details.text()
    widget.select_sample(1);widget.samples.setCurrentIndex(0)
    assert widget.selected_index is None and '新样本' in widget.details.text()
    widget.close()


def test_switch_model_clears_previous_oof_details(source,app):
    from brushbot.stroke_classification.space_ui import SpaceExplorer
    bundle,predictions=source;widget=SpaceExplorer();widget.set_source(bundle,predictions)
    widget.select_sample(8)
    assert '留出预测' in widget.details.text()
    widget.set_source(dict(bundle),predictions)
    assert widget.selected_index is None
    assert '点击样本' in widget.details.text()
    assert not widget.curve.figure.axes[0].lines
    assert not widget.scores.figure.axes[0].patches
    widget.close()
