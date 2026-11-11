import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from dataclasses import replace
import pytest
from PyQt5 import QtWidgets,QtCore,QtTest
from tests.test_stroke_classifier_training import experiments
from tests.test_stroke_classifier_analysis import small_config

@pytest.fixture(scope='module')
def app():return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

@pytest.fixture
def source(tmp_path):
    from brushbot.stroke_classification.training import train
    from brushbot.stroke_classification.store import ModelStore
    store=ModelStore(tmp_path/'store')
    task=train(experiments(tmp_path),replace(small_config(),cs=(.1,)),store.root)
    model=task['models'][0]
    return store,task,model,store.load_bundle(task['id'],model['id'])


def test_analysis_tabs_preview_and_independent_advanced_weights(tmp_path,app):
    from brushbot.stroke_classification.ui import TrainerWindow,AdvancedDialog
    from brushbot.stroke_classification.training import TrainConfig
    window=TrainerWindow(tmp_path/'store')
    labels=[window.results_tabs.tabText(i) for i in range(window.results_tabs.count())]
    assert '学习曲线' in labels and '参数验证' in labels
    dialog=AdvancedDialog(TrainConfig(weights=(.5,)))
    assert dialog.fields['difference_weights'].text()=='0.5'
    assert dialog.fields['direction_weights'].text()=='0.5'
    dialog.fields['difference_weights'].setText('2')
    dialog.accept()
    assert dialog.result_config.difference_weights==(2.,)
    assert dialog.result_config.direction_weights==(.5,)
    window.close()


def test_real_analysis_process_saves_reloads_and_selects_candidate(source,app):
    from brushbot.stroke_classification.analysis_ui import AnalysisPanel
    store,task,model,bundle=source
    widget=AnalysisPanel('C');widget.set_source(store,task,model,bundle)
    widget.cs.setText('0.1, 1')
    widget.center.setValue(.1);widget.generate_nearby()
    assert widget.cs.text()=='0.025, 0.05, 0.1, 0.2, 0.4'
    widget.cs.setText('0.1, 1')
    assert widget.estimate()>0
    received=[];widget.candidateChosen.connect(received.append)
    widget.start()
    for _ in range(1000):
        if not widget.busy:break
        QtTest.QTest.qWait(10)
    assert not widget.busy
    assert widget.result is not None, widget.status.text()
    assert widget.result['status']=='completed'
    assert widget.records.count()==1
    assert widget.rows.rowCount()==2
    widget.rows.selectRow(1);widget.apply_candidate()
    assert received[0]['candidate']['C']==1.
    reopened=AnalysisPanel('C');reopened.set_source(store,task,model,bundle)
    reopened.load_record()
    assert reopened.result['rows']==widget.result['rows']
    assert len(store.list_tasks())==1  # Temporary fits do not create model-history entries.
    widget.close();reopened.close()


def test_cancelled_analysis_does_not_become_success(source,app):
    from brushbot.stroke_classification.analysis_ui import AnalysisPanel
    store,task,model,bundle=source
    widget=AnalysisPanel('C');widget.set_source(store,task,model,bundle)
    widget.start();widget.cancel()
    for _ in range(1000):
        if not widget.busy:break
        QtTest.QTest.qWait(10)
    assert not widget.busy
    assert widget.result is None
    assert '取消' in widget.status.text()
    for path in store.task_path(task['id']).glob('analyses/*/record.json'):
        assert json.loads(path.read_text())['status']!='completed'
    widget.close()


def test_candidate_copy_does_not_train_and_includes_source_settings(source,app):
    from brushbot.stroke_classification.ui import TrainerWindow
    store,task,model,bundle=source
    window=TrainerWindow(store.root)
    window.apply_analysis_candidate(dict(candidate={**model['candidate'],'C':.03,'weight':2.},train_config=task['config'],source_fingerprint=task['source_fingerprint']))
    assert window.config.cs==(.03,)
    assert window.config.difference_weights==(2.,)
    assert [key for key,check in window.family_checks.items() if check.isChecked()]==['F4']
    assert window.training_job.process.state()==QtCore.QProcess.NotRunning
    assert len(store.list_tasks())==1
    window.close()


def test_legacy_results_remain_viewable_without_analysis(tmp_path,app):
    from pathlib import Path
    from brushbot.stroke_classification.legacy import import_historical_baseline
    from brushbot.stroke_classification.store import ModelStore
    from brushbot.stroke_classification.ui import TrainerWindow
    folder=Path(__file__).resolve().parents[1]/'outputs/stroke_model_random10_20261106'
    if not (folder/'model.joblib').exists():pytest.skip('local historical model not present')
    store=ModelStore(tmp_path/'store');task=import_historical_baseline(store,folder)
    window=TrainerWindow(store.root);errors=[];window.error=errors.append
    window.show_task_results(task['id'])
    assert not errors
    assert window.space_explorer.bundle is not None
    assert not window.learning_panel.generate.isEnabled()
    assert not window.parameter_panel.generate.isEnabled()
    window.close()


def test_small_window_scrolls_results_instead_of_clipping_controls(tmp_path,app):
    from brushbot.stroke_classification.ui import TrainerWindow
    window=TrainerWindow(tmp_path/'store');window.resize(1060,710);window.navigation.setCurrentRow(2);window.show()
    app.processEvents()
    page=window.pages.widget(2)
    assert isinstance(page,QtWidgets.QScrollArea)
    assert page.verticalScrollBar().maximum()>0
    window.close()
