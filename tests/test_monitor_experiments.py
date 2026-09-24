import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PyQt5")
from PyQt5 import QtWidgets

from brushbot.experiments.fake import make_rig
from brushbot.experiments.cartesian_return import CartesianReturnController
from brushbot.experiments.service import ExperimentService
from brushbot.monitor.experiment_panel import ExperimentPanel
from brushbot.monitor.window import MonitorWindow


def test_panel_loading_and_coordinate_edits_do_not_move(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    rig = make_rig(recorder_root=tmp_path / "runs")
    service = ExperimentService(
        rig.engine, CartesianReturnController(rig.arm, rig.setup))
    panel = ExperimentPanel(service, rig.setup)
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(rig.spec))
    before = list(rig.arm.calls)
    panel.load_path(path)
    panel.origin_x.setValue(123)
    panel.origin_y.setValue(234)
    panel.wait_z.setValue(65)
    app.processEvents()
    assert rig.arm.calls == before
    assert panel.execute_button.isEnabled()
    assert not hasattr(panel, "return_button")
    panel.close()
    service.close()


def test_open_loop_preview_shows_magnetic_target_not_applicable(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    rig = make_rig(recorder_root=tmp_path / "runs")
    service = ExperimentService(
        rig.engine, CartesianReturnController(rig.arm, rig.setup))
    panel = ExperimentPanel(service, rig.setup)
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(rig.spec))
    panel.load_path(path)
    assert "不适用" in panel.target_label.text()
    panel.close()
    service.close()


def test_monitor_embeds_panel_and_experiment_service_owns_sampling_source(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    rig = make_rig(recorder_root=tmp_path / "runs")
    service = ExperimentService(
        rig.engine, CartesianReturnController(rig.arm, rig.setup))
    window = MonitorWindow(
        str(tmp_path / "legacy"), str(tmp_path / "configs"),
        experiment_service=service, experiment_setup=rig.setup,
    )
    window.timer.stop()
    window.show()
    app.processEvents()
    assert window.experiment_panel.service is service
    assert window.cartesian_return_panel.service is service
    assert not window.btn_conn.isEnabled()
    window.close()
