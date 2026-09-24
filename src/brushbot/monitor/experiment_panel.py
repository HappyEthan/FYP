"""Qt experiment controls; device work is delegated to the service."""

from __future__ import annotations

import copy
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from brushbot.experiments.config import load_experiment


class ExperimentPanel(QtWidgets.QGroupBox):
    activeChanged = QtCore.pyqtSignal(bool)

    def __init__(self, service=None, setup=None, parent=None):
        super().__init__("03  StrokePlan experiment", parent)
        self.service = service
        self.setup = copy.deepcopy(setup or {})
        self._path = None
        self._spec = None
        self._build_ui()
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(100)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.file_label = QtWidgets.QLabel("No experiment JSON selected")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)
        self.choose_button = QtWidgets.QPushButton("Choose JSON")
        self.choose_button.clicked.connect(self.choose_file)
        layout.addWidget(self.choose_button)
        form = QtWidgets.QFormLayout()
        self.origin_x = QtWidgets.QDoubleSpinBox()
        self.origin_y = QtWidgets.QDoubleSpinBox()
        self.wait_z = QtWidgets.QDoubleSpinBox()
        for widget in (self.origin_x, self.origin_y, self.wait_z):
            widget.setRange(-2000, 2000)
            widget.setDecimals(3)
            widget.setSuffix(" mm")
        self.origin_x.setValue(float(self.setup.get("origin_x_mm", 0)))
        self.origin_y.setValue(float(self.setup.get("origin_y_mm", 0)))
        self.wait_z.setValue(float(self.setup.get("wait_z_mm", 0)))
        form.addRow("Start X", self.origin_x)
        form.addRow("Start Y", self.origin_y)
        form.addRow("Wait Z", self.wait_z)
        layout.addLayout(form)
        self.target_label = QtWidgets.QLabel("Magnetic target: not loaded")
        layout.addWidget(self.target_label)
        row = QtWidgets.QHBoxLayout()
        self.execute_button = QtWidgets.QPushButton("Execute")
        self.stop_button = QtWidgets.QPushButton("Stop")
        row.addWidget(self.execute_button)
        row.addWidget(self.stop_button)
        layout.addLayout(row)
        self.status_label = QtWidgets.QLabel("Offline")
        layout.addWidget(self.status_label)
        self.execute_button.clicked.connect(self.submit_start)
        self.stop_button.clicked.connect(self.submit_stop)
        self.execute_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    def choose_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose experiment", "", "JSON (*.json)")
        if path:
            self.load_path(path)

    def load_path(self, path):
        spec = load_experiment(path)
        self._path = Path(path)
        self._spec = spec
        self.file_label.setText(str(self._path))
        control = spec["control"]
        if not control["enabled"]:
            self.target_label.setText("Magnetic target: 不适用 (open loop)")
        else:
            target = control.get("target_uT")
            self.target_label.setText(
                "Magnetic target: not configured" if target is None
                else f"Magnetic target: {target:g} uT")
        self.execute_button.setEnabled(self.service is not None)

    def _resolved_setup(self):
        setup = copy.deepcopy(self.setup)
        setup["origin_x_mm"] = self.origin_x.value()
        setup["origin_y_mm"] = self.origin_y.value()
        setup["wait_z_mm"] = self.wait_z.value()
        return setup

    def submit_start(self):
        if self.service is None or self._path is None:
            return
        spec = load_experiment(self._path)
        self._spec = spec
        self.service.submit("load", {"spec": spec, "setup": self._resolved_setup()})
        self.service.submit("start", {})

    def submit_stop(self):
        if self.service is not None:
            self.service.submit("stop", {"reason": "operator_stop"})

    def refresh(self):
        if self.service is None:
            return
        snapshot = self.service.snapshot()
        experiment = snapshot["experiment"]
        cartesian_return = snapshot["cartesian_return"]
        state = experiment["state"]
        active = state not in {"UNPREPARED", "READY", "END_WAIT", "ABORTED", "FAULT"}
        return_active = cartesian_return["state"] in {"READY", "RETURNING"}
        self.status_label.setText(
            f"{state} | {experiment.get('phase', '')} | {experiment.get('run_dir') or '-'}")
        self.choose_button.setEnabled(not active)
        self.origin_x.setEnabled(not active)
        self.origin_y.setEnabled(not active)
        self.wait_z.setEnabled(not active)
        self.execute_button.setEnabled(
            not active and not return_active and self._spec is not None)
        self.stop_button.setEnabled(active)
        self.activeChanged.emit(active or return_active)

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
