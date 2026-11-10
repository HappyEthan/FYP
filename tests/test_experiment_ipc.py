import json
import socket

import pytest

from brushbot.experiments.fake import make_rig
from brushbot.experiments.cartesian_return import CartesianReturnController
from brushbot.experiments.ipc import ExperimentIPCServer, send_ipc_request
from brushbot.experiments.service import ExperimentService
from brushbot.local_ipc import connect_local
from brushbot import local_ipc


def test_ipc_exposes_status_but_not_arbitrary_motion(tmp_path):
    rig = make_rig(recorder_root=tmp_path / "runs")
    service = ExperimentService(
        rig.engine, CartesianReturnController(rig.arm, rig.setup))
    path = tmp_path / "experiment.sock"
    server = ExperimentIPCServer(service, path)
    server.start()
    try:
        status = send_ipc_request(path, {"request_id": "1", "action": "status"})
        assert status["experiment"]["state"] == "READY"
        rejected = send_ipc_request(path, {"request_id": "2", "action": "move"})
        assert rejected["status"] == "rejected"
        assert rig.arm.calls == []
        if not local_ipc.IS_WINDOWS:
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        server.close()
        service.close()


def test_ipc_rejects_oversized_message(tmp_path):
    rig = make_rig(recorder_root=tmp_path / "runs")
    service = ExperimentService(
        rig.engine, CartesianReturnController(rig.arm, rig.setup))
    path = tmp_path / "experiment.sock"
    server = ExperimentIPCServer(service, path, max_message_bytes=128)
    server.start()
    try:
        with connect_local(path) as client:
            client.sendall((json.dumps({"action": "status", "padding": "x" * 500}) + "\n").encode())
            response = json.loads(client.makefile("r").readline())
        assert response["status"] == "rejected"
    finally:
        server.close()
        service.close()


class _CapturingService:
    def __init__(self):
        self.requests = []

    def submit(self, action, payload):
        self.requests.append((action, payload))
        return "service-id"

    def snapshot(self):
        return {"experiment": {"state": "READY"},
                "cartesian_return": {"state": "IDLE"}}


@pytest.mark.parametrize("case", [
    {"request_id": "1", "action": "return"},
    {"request_id": "2", "action": "return_pose"},
    {"request_id": "3", "action": "return_pose", "target_pose_m_rad": [0] * 5},
    {"request_id": "4", "action": "return_pose", "target_pose_m_rad": [0] * 7},
    {"request_id": "5", "action": "return_pose",
     "target_pose_m_rad": [0, 0, 0, 0, float("inf"), 0]},
])
def test_ipc_rejects_bare_or_invalid_return_before_service_submission(tmp_path, case):
    service = _CapturingService()
    path = tmp_path / "experiment.sock"
    server = ExperimentIPCServer(service, path)
    server.start()
    try:
        response = send_ipc_request(path, case)
        assert response["status"] == "rejected"
        assert service.requests == []
    finally:
        server.close()
