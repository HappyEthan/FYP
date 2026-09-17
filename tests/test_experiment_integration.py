import csv
import json
import time
from pathlib import Path

import numpy as np
import pytest

from brushbot.experiments.cli import main as return_cli
from brushbot.experiments.cartesian_return import CartesianReturnController
from brushbot.experiments.fake import make_rig
from brushbot.experiments.ipc import ExperimentIPCServer
from brushbot.experiments.service import ExperimentService


def _read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_open_loop_records_synthetic_run_then_waits_without_returning(tmp_path):
    rig = make_rig(recorder_root=tmp_path / "runs", closed_loop=False)
    rig.engine.start()
    rig.advance_until("END_WAIT")

    run_dir = Path(rig.engine.snapshot()["run_dir"])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sensor_rows = list(csv.DictReader((run_dir / "sensor.csv").open(encoding="utf-8")))
    control_rows = _read_jsonl(run_dir / "control.jsonl")
    events = _read_jsonl(run_dir / "events.jsonl")

    assert rig.feedback_calls == 0
    assert manifest["status"] == "completed"
    assert manifest["execution_environment"] == "synthetic"
    assert sensor_rows and {"Bx_uT", "By_uT", "Bz_uT"} <= sensor_rows[0].keys()
    assert control_rows and all(row["a_ref_uT"] is None for row in control_rows)
    assert {row["event"] for row in events} >= {
        "baseline_started", "baseline_fixed", "run_started", "lift_completed"
    }

    endpoint_xy = rig.arm.pose[:2]
    assert endpoint_xy != rig.start_pose[:2]
    for _ in range(5):
        rig.advance()
    assert rig.engine.state == "END_WAIT"
    assert rig.arm.pose[:2] == endpoint_xy


def test_closed_loop_deadband_comparison_keeps_same_feedforward_plan(tmp_path):
    zero = make_rig(
        recorder_root=tmp_path / "zero", closed_loop=True, deadband_uT=0.0)
    five = make_rig(
        recorder_root=tmp_path / "five", closed_loop=True, deadband_uT=5.0)

    np.testing.assert_allclose(
        zero.engine._compiled["depth_ff_m"], five.engine._compiled["depth_ff_m"])
    for rig in (zero, five):
        rig.engine.start()
        rig.advance_until("END_WAIT")
        assert rig.feedback_calls > 0
        assert rig.saved_status == "completed"


def test_ipc_cli_returns_only_after_end_wait(tmp_path):
    rig = make_rig(recorder_root=tmp_path / "runs")
    returns = CartesianReturnController(rig.arm, rig.setup)
    service = ExperimentService(rig.engine, returns)
    socket_path = tmp_path / "experiment.sock"
    server = ExperimentIPCServer(service, socket_path)
    server.start()
    try:
        request_id = service.submit("start", {})
        assert service.wait_request(request_id, 1)["status"] == "completed"
        deadline = time.monotonic() + 3
        while service.snapshot()["experiment"]["state"] != "END_WAIT" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.snapshot()["experiment"]["state"] == "END_WAIT"

        output = []
        assert return_cli(
            ["--socket", str(socket_path),
             "--x-mm", "100", "--y-mm", "200", "--z-mm", "60",
             "--rx-deg", str(np.degrees(1.0)),
             "--ry-deg", str(np.degrees(2.0)),
             "--rz-deg", str(np.degrees(3.0))],
            input_fn=lambda _prompt: "return",
            output_fn=output.append,
        ) == 0
        deadline = time.monotonic() + 1
        while service.snapshot()["cartesian_return"]["state"] != "COMPLETED" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert service.snapshot()["cartesian_return"]["state"] == "COMPLETED"
        assert rig.arm.pose == pytest.approx(rig.start_pose)
    finally:
        server.close()
        service.close()
