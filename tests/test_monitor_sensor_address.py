"""Address selection must never mix sensors or duplicate primary samples."""
import json
import os

import numpy as np
import pytest

from brushbot.monitor.recorder import Recorder
from brushbot.monitor.sources import SerialSource


PAYLOAD = (
    b"1000000,400,-3700,5700\n"
    b"# sensor,0x0C,1000000,400,-3700,5700\n"
    b"# sensor,0x0D,1001000,250,-20,60\n"
    b"# sensor,0x2A,1002000,10,20,30\n"
)


class Port:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False
        self.writes = []

    def read(self, _size):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        pass

    def write(self, payload):
        self.writes.append(payload)
        return len(payload)

    def flush(self):
        pass


@pytest.mark.parametrize("address, expected, timestamp", [
    ("0x0D", [250., -20., 60.], 1001000),
    (13, [250., -20., 60.], 1001000),
    ("0x0C", [400., -3700., 5700.], 1000000),
    ("0x2A", [10., 20., 30.], 1002000),
])
def test_explicit_address_filters_primary_duplicate_and_other_sensors(address, expected, timestamp):
    src = SerialSource(address=address)
    src._ser = Port([PAYLOAD])
    frames = src.read_frames()
    assert [(f["sensor_t_us"], f["B_uT"]) for f in frames] == [(timestamp, expected)]
    assert src.bad_lines == 0
    assert src.info["sensor_address"] == f"0x{src.address:02X}"


def test_default_primary_keeps_legacy_stream_without_duplicate_addressed_frames():
    src = SerialSource()
    src._ser = Port([PAYLOAD])
    assert src.read() == [(0., 400., -3700., 5700.)]


def test_missing_selected_address_never_falls_back_to_another_sensor():
    src = SerialSource(address="0x0E")
    src._ser = Port([PAYLOAD])
    assert src.read_frames() == []
    assert src.bad_lines == 0


def test_addressed_frame_can_be_split_between_serial_reads():
    src = SerialSource(address="0x0d")
    src._ser = Port([b"1000000,400,-3700,5700\n# sensor,0x0D,1001000,25", b"0,-20,60\n"])
    assert src.read() == []
    assert src.read() == [(0., 250., -20., 60.)]


@pytest.mark.parametrize("address", ["garbage", "0x00", "0x78", True, 1.5])
def test_invalid_address_is_rejected_before_opening_port(address):
    with pytest.raises(ValueError, match="地址"):
        SerialSource(address=address)


def test_reboot_waits_for_selected_sensor_and_preserves_its_first_frame():
    src = SerialSource(address="0x0D")
    port = Port([
        b"# fw=fixed90 reboot requested\nREADY\n100000,1,2,3\n"
        b"# sensor,0x0C,100000,1,2,3\n# sensor,0x0D,200000,7,8,9\n"
    ])
    src._ser = port
    result = src.reboot(timeout_s=.5)
    assert result["first_frame_sensor_t_us"] == 200000
    assert port.writes == [b"REBOOT\n"]
    assert src.read_frames()[0]["B_uT"] == [7., 8., 9.]


def test_recording_keeps_the_selected_sensor_address(tmp_path):
    source = SerialSource(address="0x0D")
    recorder = Recorder(str(tmp_path), [250, -20, 60], source.info)
    recorder.add(0, [1, 2, 3])
    _, path = recorder.finish()
    assert json.loads(path.read_text())["sensor_address"] == "0x0D"


@pytest.fixture
def window(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("pyqtgraph")
    from PyQt5 import QtWidgets
    from brushbot.monitor.window import MonitorWindow

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MonitorWindow(str(tmp_path / "recordings"), control_socket=str(tmp_path / "monitor.sock"))
    w.timer.stop()
    w.show()
    app.processEvents()
    yield w
    if w.src is not None:
        w._disconnect()
    w.close()
    w.deleteLater()
    app.processEvents()


def test_monitor_selects_address_and_clears_previous_capture_on_reconnect(window, monkeypatch):
    import serial

    ports = [Port([PAYLOAD]), Port([PAYLOAD])]
    opened = []

    def open_port(*_args, **_kwargs):
        port = ports[len(opened)]
        opened.append(port)
        return port

    monkeypatch.setattr(serial, "Serial", open_port)
    window.btn_src_serial.click()
    window.cb_address.setCurrentText("0x0D")
    window.btn_conn.click()
    assert window.src.address == 0x0D
    assert not window.cb_address.isEnabled()
    window._tick()
    np.testing.assert_allclose(window.rb.latest(1)[1], [[250, -20, 60]])
    assert "0x0D" in window.lbl_source.text()
    window.bl.take(np.array([[250, -20, 60], [251, -21, 61]]))
    window._redraw()
    window.btn_conn.click()
    assert opened[0].closed and window.cb_address.isEnabled()
    window.cb_address.setCurrentText("0x0C")
    window.btn_conn.click()
    assert window.src.address == 0x0C
    assert window.rb.n_total == 0 and not window.bl.ready
    assert window.cur_x.getData()[0] is None or len(window.cur_x.getData()[0]) == 0
    window._tick()
    np.testing.assert_allclose(window.rb.latest(1)[1], [[400, -3700, 5700]])


def test_address_control_accepts_custom_hex_and_fits_laptop_width(window):
    from PyQt5 import QtCore, QtWidgets

    assert not window.cb_address.isVisible()
    window.btn_src_serial.click()
    window.cb_address.setCurrentText("0x2A")
    assert window.cb_address.currentText() == "0x2A"
    window.resize(1100, 760)
    QtWidgets.QApplication.processEvents()
    for widget in (window.cb_address, window.btn_conn):
        assert widget.isVisible()
        rect = QtCore.QRect(widget.mapTo(window, QtCore.QPoint()), widget.size())
        assert window.rect().contains(rect)
    assert window.width() <= 1100
