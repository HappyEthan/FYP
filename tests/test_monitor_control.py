import threading
import time

import pytest

from brushbot.monitor.control import MonitorControlServer, send_command


def test_control_socket_round_trip_and_gui_thread_drain(tmp_path):
    socket_path = str(tmp_path / "monitor.sock")
    server = MonitorControlServer(socket_path)
    try:
        server.start()
    except PermissionError:
        pytest.skip("sandbox disallows local Unix socket binding")
    try:
        result = []
        worker = threading.Thread(
            target=lambda: result.append(send_command(socket_path, "start_record")))
        worker.start()
        deadline = time.monotonic() + 1.0
        while worker.is_alive() and time.monotonic() < deadline:
            server.drain(lambda request: {
                "status": "recording" if request["action"] == "start_record"
                else "rejected"})
            time.sleep(0.005)
        worker.join(timeout=1.0)
        assert result == [{"status": "recording"}]
    finally:
        server.close()
