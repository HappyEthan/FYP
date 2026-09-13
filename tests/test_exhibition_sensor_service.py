import time

import numpy as np
import pytest

from brushbot.exhibition.sensor_service import SensorMonitorService


class FakeSource:
    def __init__(self, frames):
        self.frames = list(frames)
        self.started = False
        self.stopped = False
        self.port = "fake"
        self.baud = 115200
        self.bad_lines = 2

    @property
    def info(self):
        return {"name": "serial", "port": self.port, "baud": self.baud,
                "nominal_rate_hz": 100.0, "units": "uT"}

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def read_frames(self):
        if not self.frames:
            return []
        frame = self.frames.pop(0)
        return [frame]


class PhaseSource(FakeSource):
    def __init__(self, pre_frame, baseline_frame):
        super().__init__([pre_frame])
        self.phase = "pre"
        self.baseline_frame = baseline_frame

    def read_frames(self):
        if self.phase == "pre" and self.frames:
            return super().read_frames()
        if self.phase == "baseline":
            return [self.baseline_frame]
        return []


class BrokenSource(FakeSource):
    def read_frames(self):
        raise OSError("read failed")


def test_sensor_service_connects_and_exposes_xy_and_signal_history():
    frames = [
        {"sensor_t_us": 0, "B_uT": [10.0, 20.0, 30.0], "source_kind": "serial"},
        {"sensor_t_us": 10000, "B_uT": [11.0, 22.0, 30.0], "source_kind": "serial"},
    ]
    source = FakeSource(frames)
    svc = SensorMonitorService(source_factory=lambda p, b: source,
                               poll_interval=0.001)
    try:
        snap = svc.connect("fake", 115200)
        assert snap["connected"] is True
        for _ in range(100):
            if len(svc.snapshot()["series"]["x"]) >= 2:
                break
            time.sleep(0.002)
        snap = svc.snapshot()
        assert snap["port"] == "fake"
        assert snap["bad_lines"] == 2
        assert len(snap["series"]["x"]) == 2
        assert snap["xy"]["x"] == 11.0
        assert snap["xy"]["y"] == 22.0
        assert snap["pressure_bxy_uT"] == np.hypot(11.0, 22.0)
        assert snap["display"]["xy_radius_uT"] == 400
        assert snap["display"]["channels"] == {"x": "ΔBx", "y": "ΔBy"}
    finally:
        svc.close()
    assert source.started and source.stopped


def test_sensor_service_baseline_uses_monitor_baseline_and_contact_gate():
    frames = [
        {"sensor_t_us": i * 10000, "B_uT": [100.0, 200.0, 300.0], "source_kind": "serial"}
        for i in range(20)
    ]
    source = FakeSource(frames)
    svc = SensorMonitorService(source_factory=lambda p, b: source,
                               poll_interval=0.001, baseline_duration_s=0.01)
    try:
        svc.connect("fake", 115200)
        assert svc.start_baseline()["baseline_running"] is True
        for _ in range(100):
            if svc.snapshot()["baseline_ready"]:
                break
            time.sleep(0.002)
        snap = svc.snapshot()
        assert snap["baseline_ready"] is True
        assert np.allclose(snap["baseline"], [100.0, 200.0, 300.0])
        assert snap["pressure_bxy_uT"] == 0.0
        assert snap["contact"] is False
    finally:
        svc.close()


def test_sensor_service_baseline_excludes_samples_before_request():
    pre = {"sensor_t_us": 0, "B_uT": [10.0, 20.0, 30.0], "source_kind": "serial"}
    during = {"sensor_t_us": 10000, "B_uT": [100.0, 200.0, 300.0], "source_kind": "serial"}
    source = PhaseSource(pre, during)
    svc = SensorMonitorService(source_factory=lambda p, b: source,
                               poll_interval=0.001, baseline_duration_s=0.03)
    try:
        svc.connect("fake", 115200)
        for _ in range(100):
            if svc.snapshot()["series"]["x"]:
                break
            time.sleep(0.002)
        source.phase = "baseline"
        assert svc.start_baseline()["baseline_running"] is True
        for _ in range(100):
            if svc.snapshot()["baseline_ready"]:
                break
            time.sleep(0.002)
        assert np.allclose(svc.snapshot()["baseline"], [100.0, 200.0, 300.0])
    finally:
        svc.close()


def test_sensor_service_poll_failure_stops_and_detaches_source():
    source = BrokenSource([])
    svc = SensorMonitorService(source_factory=lambda p, b: source,
                               poll_interval=0.001)
    try:
        svc.connect("fake", 115200)
        for _ in range(100):
            snap = svc.snapshot()
            if not snap["connected"]:
                break
            time.sleep(0.002)
        snap = svc.snapshot()
        assert source.stopped is True
        assert snap["connected"] is False
        assert snap["sample_rate_hz"] == 0.0
        assert snap["bad_lines"] == 0
    finally:
        svc.close()


def test_sensor_snapshot_exposes_bxy_pressure_from_current_xy():
    frames = [{"sensor_t_us": 0, "B_uT": [3.0, 4.0, 9.0], "source_kind": "serial"}]
    source = FakeSource(frames)
    service = SensorMonitorService(source_factory=lambda _p, _b: source,
                                   poll_interval=0.001)
    try:
        service.connect("fake", 115200)
        for _ in range(100):
            if service.snapshot()["series"]["x"]:
                break
            time.sleep(0.002)
        assert service.snapshot()["pressure_bxy_uT"] == pytest.approx(5.0)
    finally:
        service.close()


def test_sensor_service_reports_connection_error_without_raising_to_ui():
    def broken(_port, _baud):
        raise OSError("permission denied")

    svc = SensorMonitorService(source_factory=broken)
    try:
        snap = svc.connect("/dev/ttyUSB0", 115200)
        assert snap["connected"] is False
        assert "permission denied" in snap["error"]
    finally:
        svc.close()


def test_sensor_snapshot_can_limit_history_for_realtime_transport():
    frames = [
        {"sensor_t_us": i * 10000, "B_uT": [float(i), float(i * 2), 0.0], "source_kind": "serial"}
        for i in range(20)
    ]
    source = FakeSource(frames)
    svc = SensorMonitorService(source_factory=lambda p, b: source, poll_interval=0.001)
    try:
        svc.connect("fake", 115200)
        for _ in range(100):
            if len(svc.snapshot()["series"]["x"]) >= 20:
                break
            time.sleep(0.002)
        snap = svc.snapshot(max_points=5)
        assert len(snap["series"]["x"]) == 5
        assert len(snap["series"]["y"]) == 5
    finally:
        svc.close()
