"""Regression coverage for slow variation planning without freezing Qt."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import threading
import time
import pytest
from PyQt5 import QtCore, QtTest, QtWidgets
from scripts.brush_path_editor_model import PathModel
from tests.test_brush_variation_model import model


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_until(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QtTest.QTest.qWait(5)
    assert predicate(), 'variation preview did not finish'


def test_generate_keeps_event_loop_responsive_during_slow_compile(model, app, monkeypatch):
    from scripts.brush_variation_dialog import VariationDialog
    original = PathModel.compile_workspace
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    heartbeats = []

    def slow_compile(self):
        started.set()
        release.wait(.3)
        try:
            return original(self)
        finally:
            finished.set()

    monkeypatch.setattr(PathModel, 'compile_workspace', slow_compile)
    dialog = VariationDialog(model)
    dialog.enabled.setChecked(True)
    timer = QtCore.QTimer()
    def heartbeat():
        if started.is_set() and not finished.is_set():
            heartbeats.append(True)
            release.set()
    timer.timeout.connect(heartbeat)
    timer.start(5)
    try:
        dialog.generate()
        wait_until(lambda: dialog.last_result is not None)
        assert heartbeats, 'planning blocked the GUI event loop'
        assert dialog.path_after.xData is not None
        assert getattr(model, 'random_variation', None) is None
    finally:
        release.set()
        timer.stop()
        dialog.reject()


def test_apply_reuses_completed_preview_without_another_compile(model, app, monkeypatch):
    from scripts.brush_variation_dialog import VariationDialog
    original = PathModel.compile_workspace
    calls = []
    def compile_workspace(self):
        calls.append(True)
        return original(self)
    monkeypatch.setattr(PathModel, 'compile_workspace', compile_workspace)
    dialog = VariationDialog(model)
    dialog.enabled.setChecked(True)
    dialog.generate()
    wait_until(lambda: dialog.last_result is not None)
    assert len(calls) == 1
    dialog.accept()
    wait_until(lambda: dialog.result() == QtWidgets.QDialog.Accepted)
    assert len(calls) == 1


def test_cancel_closes_window_and_interrupts_detached_planning(model, app, monkeypatch):
    from scripts.brush_variation_dialog import VariationDialog
    original = PathModel.compile_workspace
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow_compile(self):
        started.set()
        release.wait(2)
        try:
            return original(self)
        finally:
            finished.set()
    monkeypatch.setattr(PathModel, 'compile_workspace', slow_compile)
    dialog = VariationDialog(model)
    dialog.enabled.setChecked(True)
    dialog.generate()
    try:
        wait_until(started.is_set)
        assert not dialog.generate_button.isEnabled()
        assert not dialog.apply_button.isEnabled()
        dialog.reject()
        assert dialog.result() == QtWidgets.QDialog.Rejected
        assert not finished.is_set()
    finally:
        release.set()
        wait_until(finished.is_set)
        wait_until(lambda: dialog._worker is None)
    assert dialog.last_result is None
    assert getattr(model, 'random_variation', None) is None


def test_preview_error_is_reported_and_generation_can_retry(model, app, monkeypatch):
    from scripts.brush_variation_dialog import VariationDialog
    original = PathModel.compile_workspace
    def failed_compile(self):
        raise ValueError('controlled preflight failure')
    monkeypatch.setattr(PathModel, 'compile_workspace', failed_compile)
    dialog = VariationDialog(model)
    dialog.enabled.setChecked(True)
    dialog.generate()
    wait_until(lambda: dialog._worker is None)
    assert dialog.last_result is None
    assert 'controlled preflight failure' in dialog.status.text()
    assert dialog.generate_button.isEnabled()
    assert dialog.apply_button.isEnabled()
    monkeypatch.setattr(PathModel, 'compile_workspace', original)
    dialog.generate()
    wait_until(lambda: dialog.last_result is not None)
    dialog.reject()
