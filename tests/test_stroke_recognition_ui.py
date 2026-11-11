import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time

import pytest
from PyQt5 import QtCore, QtTest, QtWidgets

from brushbot.stroke_recognition.ui import RecognizerWindow
from brushbot.stroke_recognition.controller import LiveController
from tests.test_stroke_recognition_inference import model_store


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_for(predicate, timeout=5000):
    until=time.monotonic()+timeout/1000
    while time.monotonic()<until:
        if predicate():return
        QtTest.QTest.qWait(10)
    assert predicate()


def make_window(tmp_path,store,app):
    settings=QtCore.QSettings(str(tmp_path/'settings.ini'),QtCore.QSettings.IniFormat)
    ctrl=LiveController(tmp_path/'sessions')
    return RecognizerWindow(store,tmp_path/'sessions',controller=ctrl,settings=settings)


def close_window(window):
    window.close()
    wait_for(lambda:window.controller.closed and not window.isVisible())


def test_dark_window_shared_history_and_loading_without_hardware(tmp_path,model_store,app):
    store,task=model_store
    w=make_window(tmp_path,store.root,app)
    try:
        w.show();app.processEvents()
        assert '#0d121c' in w.styleSheet()
        assert w.history.topLevelItemCount()==1
        parent=w.history.topLevelItem(0)
        assert parent.childCount()==5
        assert not w.controller.snapshot()['connected']
        assert not w.start_button.isEnabled()
        w.history.setCurrentItem(parent.child(0))
        w.load_selected_model()
        wait_for(lambda:w.controller.snapshot()['model'] is not None)
        w.poll()
        assert task['name'] in w.model_label.text()
        assert w.score_table.rowCount()==7
        assert not w.start_button.isEnabled()
        selected=w.history.currentItem().data(0,QtCore.Qt.UserRole)
        w.refresh_history()
        assert w.history.currentItem().data(0,QtCore.Qt.UserRole)==selected
    finally:close_window(w)


def test_imported_zip_appears_in_same_history(tmp_path,model_store,app):
    store,task=model_store
    package=store.export(task['id'],tmp_path/'model.zip')
    w=make_window(tmp_path,tmp_path/'destination',app)
    try:
        assert w.history.topLevelItemCount()==0
        w.import_package(package)
        wait_for(lambda:w.history.topLevelItemCount()==1)
        assert (tmp_path/'destination'/'tasks'/task['id']/'task.json').is_file()
    finally:close_window(w)


def test_current_and_locked_result_remain_separate(tmp_path,model_store,app):
    store,task=model_store
    w=make_window(tmp_path,store.root,app)
    try:
        snap=w.controller.snapshot()
        snap.update(running=True, current=dict(stroke_id=2,label='横',duration=.4,
                    scores=list(range(7)),model_name='model'),
                    latest_final=dict(stroke_id=1,label='撇',duration=.8,model_name='model'),
                    history=[dict(stroke_id=1,label='撇',duration=.8,status='locked',model_name='model')])
        w.render_snapshot(snap)
        assert w.current_label.text()=='横'
        assert w.final_label.text()=='撇'
        assert w.history_table.rowCount()==1
        snap['current']=None
        w.render_snapshot(snap)
        assert w.final_label.text()=='撇'
    finally:close_window(w)


def test_threshold_confirmation_and_interval_are_sent_and_persisted(tmp_path,model_store,app):
    store,task=model_store
    w=make_window(tmp_path,store.root,app)
    try:
        w.down_threshold.setValue(90)
        w.up_threshold.setValue(30)
        w.threshold_confirm.setChecked(True)
        w.apply_configuration()
        wait_for(lambda:w.controller.snapshot()['thresholds_confirmed'])
        assert w.controller.snapshot()['config']['down_threshold']==90
    finally:close_window(w)
    settings=QtCore.QSettings(str(tmp_path/'settings.ini'),QtCore.QSettings.IniFormat)
    assert float(settings.value('down_threshold'))==90
    assert settings.value('threshold_confirmed',False,type=bool)
