"""GUI interaction regressions; optional monitor dependencies, no hardware."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("pyqtgraph")
pytest.importorskip("PyQt5")
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtTest import QTest

from brushbot.monitor.window import MonitorWindow
from brushbot.monitor.sources import ArraySource


@pytest.fixture
def window(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MonitorWindow(str(tmp_path / "recordings"), str(tmp_path / "configs"))
    w.timer.stop()
    w.show()
    app.processEvents()
    yield w
    if w.src is not None:
        w._disconnect()
    w.close()
    w.deleteLater()
    app.processEvents()


def test_disconnected_actions_explain_and_prevent_invalid_operations(window):
    window.btn_src_serial.click()
    for button in (window.btn_base, window.btn_rec, window.btn_pause):
        assert not button.isEnabled()
        assert button.toolTip()
    QTest.keyClick(window, QtCore.Qt.Key_Space)
    assert not window._paused


def test_monitor_is_minimal_and_defaults_to_raw_400_ut(window):
    for name in (
        "btn_src_synth", "btn_cal", "btn_cal_panel", "cb_preset",
        "btn_save_preset", "btn_load_preset", "sp_x_gain",
        "sp_neg_y_gain", "cb_xy_alpha",
    ):
        assert not hasattr(window, name)
    assert window.sp_radius.value() == 400
    assert window.cb_alpha.currentText() == "原始"


def test_recording_has_no_action_or_marker_controls(window):
    assert not hasattr(window, "ed_action")
    assert not hasattr(window, "btn_mark")
    assert not hasattr(window, "_mark_open")
    assert window.btn_rec.text() == "开始录制"
    window._src_mode = "串口"
    window.src = ArraySource([0.0], [[10.0, 20.0, 30.0]])
    window.src.start()
    window.bl.take(np.array([[10.0, 20.0, 30.0], [10.0, 20.0, 30.0]]))
    window._sync_controls()
    window.btn_rec.click()
    assert window.btn_rec.text() == "停止录制"
    window.rec.add(0.0, [0.0, 0.0, 0.0])
    window.btn_rec.click()
    assert window.btn_rec.text() == "开始录制"


def test_display_controls_preserve_physical_data(window):
    window.chk_z.click()
    window.chk_mag.click()
    assert window.p_z.isVisible() and window.p_mag.isVisible()
    window.rb.append(0, (10, 20, 30))
    window.rb.append(.01, (20, 30, 40))
    window.sp_radius.setValue(500)
    window.cb_alpha.setCurrentText("原始")
    window._redraw()
    np.testing.assert_allclose(window.cur_x.getData()[1], [10, 20])
    np.testing.assert_allclose(window.c_pt.getData(), ([20], [30]))
    np.testing.assert_allclose(window.rb.latest(2)[1], [[10, 20, 30], [20, 30, 40]])


def test_bad_frame_is_gapped_and_does_not_flatten_normal_trace(window):
    window.bl.b0 = np.array([30.0, -1030.0, -4200.0])
    window.bl.sigma = np.array([2.0, 2.0, 3.0])
    window.bl.ready = True
    rows = [window.bl.b0, [76.65, -0.15, -0.242], window.bl.b0 + [10, 20, 30]]
    for i, row in enumerate(rows):
        window.rb.append(i * .003, row)
    window._redraw()
    plotted = window.cur_x.getData()[1]
    assert np.isnan(plotted[1])
    assert window._display_bad_frames == 1
    assert window.p_x.getViewBox().viewRange()[1][1] <= 60.0


def test_serial_controls_fit_laptop_window(window):
    window.btn_src_serial.click()
    window.resize(1100, 760)
    QtWidgets.QApplication.processEvents()
    for button in (window.btn_conn, window.btn_base, window.btn_rec):
        assert button.isVisible()
        rect = QtCore.QRect(button.mapTo(window, QtCore.QPoint()), button.size())
        assert window.rect().contains(rect)
    assert window.width() <= 1100


def test_replay_controls_open_pause_restart_and_disconnect(window, monkeypatch):
    from brushbot.monitor.recorder import Recorder
    rec = Recorder(window.out_dir, [10, 20, 30], {"name": "array"})
    for k in range(100):
        rec.add(k / 100, [k, k*2, k*3])
    csv, _ = rec.finish()
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **kw: (csv, ""))
    window.btn_conn.click()
    assert window.src is not None
    assert not window.btn_rec.isEnabled()
    window.cb_speed.setCurrentText("2x")
    assert window.src.rate == 2
    QTest.keyClick(window, QtCore.Qt.Key_Space)
    assert window._paused
    window.src.seek(.5)
    window.btn_restart.click()
    assert window.src._i == 0
    assert not window._paused
    window.btn_conn.click()
    assert window.src is None
    assert not window.btn_pause.isEnabled()
    assert window.btn_src_serial.isEnabled()
