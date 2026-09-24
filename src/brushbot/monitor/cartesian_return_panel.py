"""Independent six-dimensional Cartesian return controls."""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from brushbot.experiments.cartesian_return import target_pose_si


class CartesianReturnPanel(QtWidgets.QGroupBox):
    """Edit a full target locally and submit it through the shared service."""

    EXPERIMENT_ACTIVE = {"BASELINE", "APPROACH", "RUN", "LIFT", "ABORT_LIFT"}
    RETURN_ACTIVE = {"READY", "RETURNING"}

    def __init__(self, service=None, initial_pose=None, parent=None):
        super().__init__("04  笛卡尔回到开始位置", parent)
        self.service = service
        self._build_ui(initial_pose or [0.0] * 6)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(100)
        self.refresh()

    def _build_ui(self, initial_pose):
        if len(initial_pose) != 6:
            raise ValueError("initial_pose must contain XYZ mm and RPY degrees")
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.x = self._spin_box(" mm", -2000.0, 2000.0, initial_pose[0])
        self.y = self._spin_box(" mm", -2000.0, 2000.0, initial_pose[1])
        self.z = self._spin_box(" mm", -2000.0, 2000.0, initial_pose[2])
        self.rx = self._spin_box(" °", -360.0, 360.0, initial_pose[3])
        self.ry = self._spin_box(" °", -360.0, 360.0, initial_pose[4])
        self.rz = self._spin_box(" °", -360.0, 360.0, initial_pose[5])
        for label, widget in (
            ("X", self.x), ("Y", self.y), ("Z", self.z),
            ("Rx", self.rx), ("Ry", self.ry), ("Rz", self.rz),
        ):
            form.addRow(label, widget)
            widget.valueChanged.connect(self._update_target_summary)
        layout.addLayout(form)
        self.target_label = QtWidgets.QLabel()
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        self.return_button = QtWidgets.QPushButton("回到开始位置")
        self.return_button.clicked.connect(self.submit_return)
        layout.addWidget(self.return_button)
        self.status_label = QtWidgets.QLabel("返回状态：离线")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self._update_target_summary()

    @staticmethod
    def _spin_box(suffix, lower, upper, value):
        widget = QtWidgets.QDoubleSpinBox()
        widget.setRange(lower, upper)
        widget.setDecimals(3)
        widget.setSuffix(suffix)
        widget.setValue(float(value))
        return widget

    def _values(self):
        return (
            self.x.value(), self.y.value(), self.z.value(),
            self.rx.value(), self.ry.value(), self.rz.value(),
        )

    def _update_target_summary(self):
        x, y, z, rx, ry, rz = self._values()
        self.target_label.setText(
            f"目标：XYZ=({x:.3f}, {y:.3f}, {z:.3f}) mm；"
            f"RPY=({rx:.3f}, {ry:.3f}, {rz:.3f}) °")

    def submit_return(self):
        if self.service is None:
            return
        target = target_pose_si(*self._values())
        self.service.submit("return_pose", {"target_pose_m_rad": list(target)})

    def refresh(self):
        if self.service is None:
            self.return_button.setEnabled(False)
            self.status_label.setText("返回状态：离线")
            return
        snapshot = self.service.snapshot()
        experiment = snapshot.get("experiment", {})
        returning = snapshot.get("cartesian_return", {})
        experiment_active = experiment.get("state") in self.EXPERIMENT_ACTIVE
        return_active = returning.get("state") in self.RETURN_ACTIVE
        self.return_button.setEnabled(not experiment_active and not return_active)
        state = returning.get("state", "IDLE")
        error = returning.get("last_error") or ""
        self.status_label.setText(
            f"返回状态：{state}" + (f"；错误：{error}" if error else ""))

    def closeEvent(self, event):
        self._timer.stop()
        super().closeEvent(event)
