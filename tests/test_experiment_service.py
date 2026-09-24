import time

from brushbot.experiments.fake import make_rig
from brushbot.experiments.cartesian_return import CartesianReturnController
from brushbot.experiments.service import ExperimentService


def _service(rig):
    returns = CartesianReturnController(rig.arm, rig.setup)
    return ExperimentService(rig.engine, returns), returns


def test_loading_does_not_move(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    service, _ = _service(rig)
    before = list(rig.arm.calls)
    request = service.submit("load", {"spec": rig.spec, "setup": rig.setup})
    assert service.wait_request(request, 1)["status"] == "completed"
    assert rig.arm.calls == before
    service.close()


def test_unknown_action_is_rejected_without_side_effects(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    service, _ = _service(rig)
    before = list(rig.arm.calls)
    request = service.submit("enable", {})
    result = service.wait_request(request, 1)
    assert result["status"] == "rejected"
    assert rig.arm.calls == before
    service.close()


def test_service_can_run_fake_rig_to_end_wait(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    service, _ = _service(rig)
    request = service.submit("start", {})
    assert service.wait_request(request, 1)["status"] == "completed"
    deadline = time.monotonic() + 3
    while service.snapshot()["experiment"]["state"] != "END_WAIT" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.snapshot()["experiment"]["state"] == "END_WAIT"
    service.close()


def test_return_pose_does_not_require_loaded_experiment(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.engine.state = "UNPREPARED"
    rig.engine._compiled = None
    service, returns = _service(rig)
    try:
        request = service.submit(
            "return_pose", {"target_pose_m_rad": rig.start_pose})
        assert service.wait_request(request, 1)["status"] == "completed"
        deadline = time.monotonic() + 1
        while returns.state not in {"COMPLETED", "FAULT"} and time.monotonic() < deadline:
            time.sleep(0.005)
        assert returns.state == "COMPLETED"
    finally:
        service.close()


def test_service_rejects_return_while_experiment_is_active(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    service, returns = _service(rig)
    try:
        started = service.submit("start", {})
        assert service.wait_request(started, 1)["status"] == "completed"
        before = list(rig.arm.calls)
        rejected = service.submit(
            "return_pose", {"target_pose_m_rad": rig.start_pose})
        assert service.wait_request(rejected, 1)["status"] == "rejected"
        assert returns.state == "IDLE"
        assert rig.arm.calls == before
    finally:
        service.close()


def test_service_rejects_experiment_start_while_return_is_active(tmp_path):
    rig = make_rig(recorder_root=tmp_path)
    rig.arm.pose = (0.2, 0.2, 0.04, 1.0, 2.0, 3.0)
    service, returns = _service(rig)
    try:
        returning = service.submit(
            "return_pose", {"target_pose_m_rad": rig.start_pose})
        assert service.wait_request(returning, 1)["status"] == "completed"
        before = list(rig.arm.calls)
        rejected = service.submit("start", {})
        assert service.wait_request(rejected, 1)["status"] == "rejected"
        assert returns.state in {"READY", "RETURNING"}
        assert len(rig.arm.calls) <= len(before) + 1
    finally:
        service.close()
