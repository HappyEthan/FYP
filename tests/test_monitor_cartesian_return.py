import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from brushbot.monitor.cartesian_return_panel import CartesianReturnPanel


@pytest.fixture
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class CapturingService:
    def __init__(self):
        self.requests = []
        self.experiment_state = "READY"
        self.return_state = "IDLE"

    def submit(self, action, payload):
        self.requests.append((action, payload))
        return "request-1"

    def snapshot(self):
        return {
            "experiment": {"state": self.experiment_state},
            "cartesian_return": {
                "state": self.return_state,
                "last_error": "",
                "target_pose_m_rad": None,
            },
        }


def test_cartesian_panel_edits_do_not_move_and_submit_full_pose(qapp):
    service = CapturingService()
    panel = CartesianReturnPanel(service, [100, 200, 60, 90, 0, -180])
    panel.x.setValue(101)
    panel.x.setValue(100)
    qapp.processEvents()
    assert service.requests == []
    panel.return_button.click()
    action, payload = service.requests[-1]
    assert action == "return_pose"
    assert payload["target_pose_m_rad"] == pytest.approx(
        [0.1, 0.2, 0.06, np.pi / 2, 0, -np.pi])
    panel.close()


def test_cartesian_panel_has_explicit_units_and_interlocks(qapp):
    service = CapturingService()
    panel = CartesianReturnPanel(service)
    assert all(widget.suffix().strip() == "mm" for widget in (panel.x, panel.y, panel.z))
    assert all(widget.suffix().strip() == "°" for widget in (panel.rx, panel.ry, panel.rz))

    service.experiment_state = "RUN"
    panel.refresh()
    assert not panel.return_button.isEnabled()
    service.experiment_state = "END_WAIT"
    service.return_state = "IDLE"
    panel.refresh()
    assert panel.return_button.isEnabled()
    service.return_state = "RETURNING"
    panel.refresh()
    assert not panel.return_button.isEnabled()
    panel.close()
