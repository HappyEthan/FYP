"""Manual sensor connection controls for the exhibition monitor."""

from __future__ import annotations

from copy import deepcopy

from PyQt5 import QtWidgets

from .state_store import ExhibitionStateStore


class ConnectionPanel(QtWidgets.QGroupBox):
    """Call only the injected network gateway and display sensor state."""

    def __init__(self, store: ExhibitionStateStore, gateway, parent=None):
        super().__init__("串口与基线", parent)
        self.store = store
        self.gateway = gateway
        self.sensor: dict | None = None
        self._build_ui()
        self.store.changed.connect(self._on_store_changed)
        self._on_store_changed()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QtWidgets.QLabel("串口设备"))
        self.port_edit = QtWidgets.QLineEdit("/dev/ttyUSB0", objectName="serial-port")
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
        layout.addStretch()

        # Task 1 exposed this spelling; retain a visible compatibility alias
        # while the canonical Task 3 button is named ``baseline``.
        self.legacy_baseline_button = QtWidgets.QPushButton("获取基线", objectName="capture-baseline")
        self.legacy_baseline_button.clicked.connect(self._take_baseline)
        layout.addWidget(self.legacy_baseline_button)

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
        self.legacy_baseline_button.setEnabled(connected and not running)
        self.baseline_button.setText("取基线中" if running else "获取基线")
        self.legacy_baseline_button.setText(self.baseline_button.text())

    def _publish(self, status: int, payload: dict) -> None:
        if not isinstance(payload, dict):
            payload = {"connected": False, "error": "网关返回了无效状态"}
        sensor = payload.get("sensor") if isinstance(payload.get("sensor"), dict) else payload
        if status >= 400:
            sensor = dict(sensor)
            sensor.setdefault("connected", bool((self.sensor or {}).get("connected")))
            sensor["error"] = sensor.get("error") or payload.get("error") or f"请求失败 ({status})"
        self.store.update_snapshot({"sensor": sensor})

    def _connect_sensor(self):
        try:
            port = self.port_edit.text().strip()
            baud = int(self.baud_combo.currentText())
            status, payload = self.gateway.connect_sensor(port, baud)
            self._publish(status, payload)
        except Exception as exc:
            self.apply_sensor({"connected": False, "error": str(exc)})

    def _disconnect_sensor(self):
        try:
            status, payload = self.gateway.disconnect_sensor()
            self._publish(status, payload)
        except Exception as exc:
            self.apply_sensor({"connected": False, "error": str(exc)})

    def _take_baseline(self):
        try:
            status, payload = self.gateway.take_baseline()
            self._publish(status, payload)
        except Exception as exc:
            current = dict(self.sensor or {})
            current["error"] = str(exc)
            self.apply_sensor(current)
