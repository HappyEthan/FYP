import threading
import time
from pathlib import Path

from brushbot import local_ipc
from brushbot.monitor.control import MonitorControlServer, send_command


def test_tcp_loopback_endpoint_works_when_windows_backend_is_selected(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(local_ipc, "IS_WINDOWS", True)
    path = tmp_path / "monitor.endpoint"
    server = MonitorControlServer(path)
    server.start()
    result = []
    worker = threading.Thread(
        target=lambda: result.append(send_command(path, "start_record"))
    )
    worker.start()
    deadline = time.monotonic() + 1.0
    while worker.is_alive() and time.monotonic() < deadline:
        server.drain(lambda request: {
            "status": "recording" if request["action"] == "start_record" else "rejected"
        })
        time.sleep(0.005)
    worker.join(timeout=1.0)
    try:
        assert result == [{"status": "recording"}]
        endpoint = Path(server.path)
        assert endpoint.exists()
    finally:
        server.close()
    assert not endpoint.exists()
