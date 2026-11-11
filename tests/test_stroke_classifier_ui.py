"""Real offscreen desktop flows, not a browser imitation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PyQt5 import QtWidgets,QtCore
from tests.test_stroke_classifier_data import archive_fixture


@pytest.fixture(scope='module')
def app(): return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_dark_window_import_selection_navigation(tmp_path,app):
    from brushbot.stroke_classification.ui import TrainerWindow
    from brushbot.stroke_classification.data import load_experiment
    w=TrainerWindow(tmp_path/'store')
    assert w.pages.count()==5
    w.add_experiments([load_experiment(archive_fixture(tmp_path/'a.brushrun'))])
    assert w.data_table.rowCount()==1
    assert len(w.selected_experiments())==1
    w.data_table.item(0,0).setCheckState(QtCore.Qt.Unchecked)
    assert not w.selected_experiments()
    w.navigation.setCurrentRow(3);app.processEvents()
    assert w.pages.currentIndex()==3
    assert not w.start_button.isEnabled()
    w.close()


def test_failed_import_remains_visible_and_cannot_train(tmp_path,app):
    from PyQt5 import QtTest
    from brushbot.stroke_classification.ui import TrainerWindow
    w=TrainerWindow(tmp_path/'store')
    w.import_paths([archive_fixture(tmp_path/'five.brushrun',count=5)])
    while w.import_jobs:QtTest.QTest.qWait(10)
    assert w.data_table.rowCount()==1
    assert w.data_table.item(0,3).text()=='有问题'
    assert not w.selected_experiments()
    assert not w.start_button.isEnabled()
    w.close()


def test_training_process_accepts_qt_events(app):
    from brushbot.stroke_classification.jobs import TrainingProcess
    job=TrainingProcess()
    assert QtCore.QCoreApplication.sendEvent(job,QtCore.QEvent(QtCore.QEvent.User)) is True


def test_cancel_timer_does_not_kill_restarted_process(app,tmp_path):
    import sys
    from PyQt5 import QtTest
    from brushbot.stroke_classification.jobs import TrainingProcess
    # Exercise actual QProcess reuse with a harmless sleeping child, no model fitting.
    class SleepProcess(TrainingProcess):
        def command(self,request): return sys.executable,['-c','import time; time.sleep(10)']
    job=SleepProcess();job.start(tmp_path/'unused.json')
    assert job.process.waitForStarted(5000)
    job.cancel();assert job.process.waitForFinished(5000)
    job.start(tmp_path/'unused.json');assert job.process.waitForStarted(5000)
    QtTest.QTest.qWait(1500)
    assert job.process.state()==QtCore.QProcess.Running
    job.process.kill();job.process.waitForFinished(5000)


def test_project_roundtrip_preserves_unchecked_data_and_model_choices(tmp_path,app,monkeypatch):
    from brushbot.stroke_classification.ui import TrainerWindow
    from tests.test_stroke_classifier_training import experiments
    from PyQt5 import QtTest
    w=TrainerWindow(tmp_path/'store');w.add_experiments(experiments(tmp_path,3))
    w.data_table.item(1,0).setCheckState(QtCore.Qt.Unchecked)
    w.family_checks['F1'].setChecked(False)
    path=str(tmp_path/'project.json')
    monkeypatch.setattr(QtWidgets.QFileDialog,'getSaveFileName',lambda *a:(path,''))
    monkeypatch.setattr(QtWidgets.QFileDialog,'getOpenFileName',lambda *a:(path,''))
    w.save_project();w.open_project()
    while w.import_jobs:QtTest.QTest.qWait(10)
    assert len(w.selected_experiments())==2
    assert not w.family_checks['F1'].isChecked()
    w.close()


def test_saved_history_groups_models_and_prediction(tmp_path,app):
    from brushbot.stroke_classification.ui import TrainerWindow
    from brushbot.stroke_classification.training import TrainConfig,train
    from tests.test_stroke_classifier_training import experiments
    ex=experiments(tmp_path)
    task=train(ex,TrainConfig(families=('F0','F4'),cs=(1.,),kernels=('linear',),
               amplitudes=('A1',),weights=(1.,)),tmp_path/'store')
    w=TrainerWindow(tmp_path/'store');w.refresh_history()
    assert w.history.topLevelItemCount()==1
    assert w.history.topLevelItem(0).childCount()==2
    w.load_model(task['id'],task['models'][0]['id'])
    w.recognition_experiments=ex[:1]
    w.run_prediction()
    assert w.prediction_table.rowCount()==7
    assert w.predictions[0]['training_overlap']
    assert len(w.predictions[0]['scores'])==7
    w.close()


def test_real_background_training_process_and_cancellation(tmp_path,app):
    from dataclasses import replace
    from PyQt5 import QtTest
    from brushbot.stroke_classification.ui import TrainerWindow
    from brushbot.stroke_classification.training import TrainConfig
    from tests.test_stroke_classifier_training import experiments
    w=TrainerWindow(tmp_path/'store')
    ex=experiments(tmp_path,4);w.add_experiments(ex)
    w.config=TrainConfig(cs=(1.,),kernels=('linear',),amplitudes=('A1',),directions=('D3',),weights=(1.,),late_weights=(.5,))
    w.start_training()
    assert w.training_job.process.waitForStarted(10000)
    spy=QtTest.QSignalSpy(w.training_job.finished)
    if not spy:assert spy.wait(30000)
    app.processEvents()
    assert spy[0][0] is True,spy[0][1]
    assert w.history.topLevelItemCount()==1
    assert w.history.topLevelItem(0).childCount()==5
    w.config=replace(w.config,cs=(.1,1.,10.,100.),kernels=('linear','rbf'))
    w.start_training();assert w.training_job.process.waitForStarted(10000)
    spy=QtTest.QSignalSpy(w.training_job.finished)
    w.cancel_training()
    if not spy:assert spy.wait(10000)
    app.processEvents()
    assert spy[0][0] is False
    assert w.history.topLevelItemCount()==1
    w.close()


def test_directory_dialog_accepts_multiple_folders(tmp_path,app):
    from PyQt5 import QtTest
    from brushbot.stroke_classification.ui import ExperimentDirectoryDialog
    paths=[tmp_path/'experiment-a',tmp_path/'experiment-b']
    for path in paths:path.mkdir()
    dialog=ExperimentDirectoryDialog(None,str(tmp_path))
    dialog.show()
    view=dialog.findChild(QtWidgets.QTreeView,'treeView')
    model=view.model()
    for _ in range(100):
        if all(model.index(str(path)).isValid() for path in paths):break
        QtTest.QTest.qWait(10)
    selection=view.selectionModel()
    selection.clearSelection()
    for path in paths:
        selection.select(model.index(str(path)),QtCore.QItemSelectionModel.Select|QtCore.QItemSelectionModel.Rows)
    assert view.selectionMode()==QtWidgets.QAbstractItemView.ExtendedSelection
    dialog.accept()
    assert dialog.result()==QtWidgets.QDialog.Accepted
    assert set(dialog.selectedFiles())=={str(path) for path in paths}
    dialog.close()


def test_directory_import_forwards_all_selected_folders(tmp_path,app,monkeypatch):
    from PyQt5 import QtTest
    from brushbot.stroke_classification import ui
    from zipfile import ZipFile
    paths=[]
    for i in range(2):
        archive=archive_fixture(tmp_path/f'run{i}.brushrun',run=f'run-{i}',seed=i+1)
        directory=tmp_path/f'run{i}'
        with ZipFile(archive) as bundle:bundle.extractall(directory)
        paths.append(str(directory))
    def select_directories(dialog):
        dialog.selectFile(paths[0])
        # Simulate the modal file-picker result; real multi-selection is tested above.
        monkeypatch.setattr(dialog,'selectedFiles',lambda:paths)
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(ui.ExperimentDirectoryDialog,'exec_',select_directories)
    window=ui.TrainerWindow(tmp_path/'store')
    window.choose_directory()
    while window.import_jobs:QtTest.QTest.qWait(10)
    assert len(window.selected_experiments())==2
    window.close()
