"""Manual sensor connection controls for the exhibition monitor."""

from __future__ import annotations

from copy import deepcopy

from PyQt5 import QtCore, QtWidgets

from .state_store import ExhibitionStateStore


class _CallSignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(object, int, object)
    failed = QtCore.pyqtSignal(object, object)


class _CallRunnable(QtCore.QRunnable):
    def __init__(self, token, operation, signals):
        super().__init__()
        self.token = token
        self.operation = operation
        self.signals = signals

    def run(self):  # noqa: D401 - QRunnable callback
        try:
            status, payload = self.operation()
            self.signals.finished.emit(self.token, int(status), payload)
        except Exception as exc:  # pragma: no cover - exercised by gateway failures
            self.signals.failed.emit(self.token, exc)


class ConnectionPanel(QtWidgets.QGroupBox):
    """Call only the injected network gateway and display sensor state."""

    def __init__(self, store: ExhibitionStateStore, gateway, parent=None):
        super().__init__("串口与基线", parent)
        self.store = store
        self.gateway = gateway
        self.sensor: dict | None = None
        self._pending_calls = {}
        self._pool = QtCore.QThreadPool(self)
        self._build_ui()
        self.store.changed.connect(self._on_store_changed)
        self._on_store_changed()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QtWidgets.QLabel("串口设备"))
        self.port_edit = QtWidgets.QLineEdit("/dev/ttyACM0", objectName="serial-port")
        self.port_edit.setPlaceholderText("串口设备")
        layout.addWidget(self.port_edit)

        layout.addWidget(QtWidgets.QLabel("波特率"))
        self.baud_combo = QtWidgets.QComboBox(objectName="serial-baud")
        self.baud_combo.addItems(["115200", "57600", "38400", "19200", "9600"])
        layout.addWidget(self.baud_combo)

        self.connect_button = QtWidgets.QPushButton("连接传感器", objectName="connect-sensor")
        self.connect_button.clicked.connect(self._connect_sensor)
        layout.addWidget(self.connect_button)
        self.disconnect_button = QtWidgets.QPushButton("断开传感器", objectName="disconnect-sensor")
        self.disconnect_button.clicked.connect(self._disconnect_sensor)
        layout.addWidget(self.disconnect_button)
        self.baseline_button = QtWidgets.QPushButton("获取基线", objectName="baseline")
        self.baseline_button.clicked.connect(self._take_baseline)
        layout.addWidget(self.baseline_button)

        self.status_label = QtWidgets.QLabel("未连接", objectName="sensor-status")
        self.status_label.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.status_label)
        self.detail_label = QtWidgets.QLabel("请输入串口并连接板卡", objectName="sensor-detail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)
        self.error_label = QtWidgets.QLabel("", objectName="sensor-error")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b56b2f;")
        layout.addWidget(self.error_label)
        self.contact_label = QtWidgets.QLabel("离开", objectName="contact-status")
        layout.addWidget(self.contact_label)
        self.pressure_label = QtWidgets.QLabel("压力：— µT", objectName="pressure")
        layout.addWidget(self.pressure_label)
        layout.addStretch()

    def _on_store_changed(self):
        snapshot = self.store.snapshot()
        if isinstance(snapshot, dict) and isinstance(snapshot.get("sensor"), dict):
            self.apply_sensor(snapshot["sensor"])
        elif isinstance(snapshot, dict) and "connected" in snapshot:
            self.apply_sensor(snapshot)

    def apply_sensor(self, sensor: dict | None) -> None:
        self.sensor = deepcopy(sensor) if isinstance(sensor, dict) else None
        current = self.sensor or {}
        connected = bool(current.get("connected"))
        running = bool(current.get("baseline_running"))
        error = str(current.get("error") or "")
        self.contact_label.setText("接触" if current.get("contact") else "离开")
        pressure = current.get("pressure_bxy_uT")
        try:
            pressure = float(pressure)
        except (TypeError, ValueError):
            pressure = None
        self.pressure_label.setText(
            f"压力：{pressure:.1f} µT" if pressure is not None else "压力：— µT"
        )
        self.status_label.setText("已连接" if connected else ("连接失败" if error else "未连接"))
        if connected:
            port = current.get("port") or ""
            rate = float(current.get("sample_rate_hz") or 0.0)
            bad_lines = int(current.get("bad_lines") or 0)
            self.detail_label.setText(f"{port} · {rate:.1f} Hz · 坏帧 {bad_lines}")
        else:
            self.detail_label.setText("请输入串口并连接板卡")
        self.error_label.setText(error)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.port_edit.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.baseline_button.setEnabled(connected and not running)
        self.baseline_button.setText("取基线中" if running else "获取基线")

    def _publish(self, status: int, payload: dict) -> None:
        if not isinstance(payload, dict):
            payload = {"connected": False, "error": "网关返回了无效状态"}
        incoming = payload.get("sensor") if isinstance(payload.get("sensor"), dict) else payload
        latest = self.store.snapshot() or {}
        existing = latest.get("sensor") if isinstance(latest, dict) else None
        sensor = deepcopy(existing) if isinstance(existing, dict) else {}
        sensor.update(deepcopy(incoming))
        # Command responses may be compact or stale.  Never replace a live
        # stream's history with a response that omits (or resets) its series.
        if isinstance(existing, dict) and "series" in existing:
            sensor["series"] = deepcopy(existing["series"])
        if status >= 400:
            sensor = dict(sensor)
            sensor.setdefault("connected", bool((self.sensor or {}).get("connected")))
            sensor["error"] = sensor.get("error") or payload.get("error") or f"请求失败 ({status})"
        self.store.update_snapshot({"sensor": sensor})

    def _start_call(self, action, operation):
        token = object()
        signals = _CallSignals()
        signals.finished.connect(self._on_call_finished)
        signals.failed.connect(self._on_call_failed)
        worker = _CallRunnable(token, operation, signals)
        worker.setAutoDelete(False)
        self._pending_calls[token] = (action, signals, worker)
        self._pool.start(worker)

    def close(self):
        """Stop accepting UI updates and wait briefly for command workers."""
        self._pending_calls.clear()
        self._pool.clear()
        self._pool.waitForDone(1000)
        super().close()

    @QtCore.pyqtSlot(object, int, object)
    def _on_call_finished(self, token, status, payload):
        pending = self._pending_calls.pop(token, None)
        if pending is None:
            return
        self._publish(status, payload)

    @QtCore.pyqtSlot(object, object)
    def _on_call_failed(self, token, exc):
        pending = self._pending_calls.pop(token, None)
        if pending is None:
            return
        action = pending[0]
        current = dict(self.sensor or {})
        current["error"] = str(exc)
        if action == "baseline":
            current["baseline_running"] = False
        self.apply_sensor(current)

    def _connect_sensor(self):
        port = self.port_edit.text().strip()
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            self.apply_sensor({"connected": False, "error": "波特率无效"})
            return
        self._start_call("connect", lambda: self.gateway.connect_sensor(port, baud))

    def _disconnect_sensor(self):
        self._start_call("disconnect", self.gateway.disconnect_sensor)

    def _take_baseline(self):
        current = dict(self.sensor or {})
        current["baseline_running"] = True
        self.apply_sensor(current)
        self._start_call("baseline", self.gateway.take_baseline)
