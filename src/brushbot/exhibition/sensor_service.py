"""Backend-owned sensor stream for the exhibition monitor page.

The browser only receives snapshots; serial I/O remains in ``monitor.sources``.
"""

from __future__ import annotations

import copy
import threading
import time
from collections import deque

import numpy as np

from brushbot.monitor.core import Baseline, derive, frame_quality_mask
from brushbot.monitor.sources import SerialSource


class SensorMonitorService:
    """Own a sensor source, poll it in the background and expose UI snapshots."""

    def __init__(self, source_factory=None, *, history_size=800,
                 poll_interval=0.02, baseline_duration_s=1.0):
        self.source_factory = source_factory or (lambda port, baud: SerialSource(port, baud))
        self.history_size = int(history_size)
        self.poll_interval = float(poll_interval)
        self.baseline_duration_s = float(baseline_duration_s)
        self._lock = threading.RLock()
        self._source = None
        self._connected = False
        self._error = None
        self._port = None
        self._baud = None
        self._history = deque(maxlen=self.history_size)
        self._baseline = Baseline()
        self._baseline_running = False
        self._baseline_started = 0.0
        self._baseline_samples = []
        self._stop = threading.Event()
        self._thread = None

    def connect(self, port, baud=115200):
        port = str(port or "").strip()
        if not port:
            raise ValueError("port is required")
        self.disconnect()
        try:
            source = self.source_factory(port, int(baud))
            source.start()
        except Exception as exc:
            with self._lock:
                self._connected = False
                self._port, self._baud = port, int(baud)
                self._error = str(exc)
            return self.snapshot()
        with self._lock:
            self._source = source
            self._connected = True
            self._port, self._baud = port, int(baud)
            self._error = None
            self._history.clear()
            self._baseline = Baseline()
            self._stop.clear()
            self._thread = threading.Thread(target=self._poll_loop,
                                             name="exhibition-sensor", daemon=True)
            self._thread.start()
        return self.snapshot()

    def disconnect(self):
        with self._lock:
            source, thread = self._source, self._thread
            self._source = None
            self._connected = False
            self._baseline_running = False
            self._stop.set()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        if source is not None:
            try:
                source.stop()
            except Exception as exc:
                with self._lock:
                    self._error = str(exc)
        return self.snapshot()

    def close(self):
        self.disconnect()

    def start_baseline(self):
        with self._lock:
            if not self._connected:
                raise RuntimeError("sensor is not connected")
            if self._baseline_running:
                return self.snapshot()
            self._baseline_running = True
            self._baseline_started = time.monotonic()
            self._baseline_samples = []
            thread = threading.Thread(target=self._baseline_worker,
                                       name="exhibition-baseline", daemon=True)
            thread.start()
            return self.snapshot()

    def _baseline_worker(self):
        time.sleep(max(self.baseline_duration_s, 0.0))
        with self._lock:
            rows = list(self._baseline_samples)
            self._baseline_samples = []
            self._baseline_running = False
            if not rows:
                self._error = "baseline requires sensor samples"
                return
            values = np.asarray([row[1] for row in rows], dtype=float)
            try:
                mask = frame_quality_mask(values)
                valid = values[mask]
                if len(valid) == 0:
                    raise ValueError("baseline has no valid samples")
                self._baseline.take(valid)
                self._error = None
            except ValueError as exc:
                self._error = str(exc)

    def _poll_loop(self):
        while not self._stop.wait(self.poll_interval):
            with self._lock:
                source = self._source
            if source is None:
                return
            try:
                frames = source.read_frames()
                with self._lock:
                    for frame in frames or []:
                        b = tuple(float(v) for v in frame["B_uT"])
                        t = float(frame.get("sensor_t_us", 0)) / 1e6
                        row = (t, b)
                        self._history.append(row)
                        if self._baseline_running:
                            self._baseline_samples.append(row)
            except Exception as exc:
                failed_source = None
                with self._lock:
                    if self._source is source:
                        failed_source = self._source
                        self._source = None
                        self._error = str(exc)
                        self._connected = False
                        self._baseline_running = False
                        self._stop.set()
                if failed_source is not None:
                    try:
                        failed_source.stop()
                    except Exception as stop_exc:
                        with self._lock:
                            self._error = str(stop_exc)
                return

    def snapshot(self, max_points=None):
        with self._lock:
            rows = list(self._history)
            if max_points is not None:
                limit = max(1, int(max_points))
                rows = rows[-limit:]
            source = self._source
            baseline = self._baseline
            if rows:
                t = np.asarray([r[0] for r in rows], dtype=float)
                values = np.asarray([r[1] for r in rows], dtype=float)
                current = values[-1] - baseline.b0 if baseline.ready else values[-1]
                times = (t - t[-1]).tolist()
                xs = (values[:, 0] - baseline.b0[0]).tolist() if baseline.ready else values[:, 0].tolist()
                ys = (values[:, 1] - baseline.b0[1]).tolist() if baseline.ready else values[:, 1].tolist()
            else:
                current = np.zeros(3)
                times, xs, ys = [], [], []
            pressure_bxy = float(np.hypot(current[0], current[1]))
            gate = 3.0 * baseline.sigma_norm if baseline.ready else float("inf")
            contact = bool(gate > 0 and derive(current, gate)["mag_xy"] >= gate) if np.isfinite(gate) else False
            nominal = 0.0
            if source is not None:
                nominal = float(getattr(source, "info", {}).get("nominal_rate_hz", 0.0))
            return {
                "connected": bool(self._connected),
                "port": self._port,
                "baud": self._baud,
                "error": self._error,
                "bad_lines": int(getattr(source, "bad_lines", 0)) if source else 0,
                "sample_rate_hz": nominal,
                "baseline_ready": bool(baseline.ready),
                "baseline_running": bool(self._baseline_running),
                "baseline": baseline.b0.tolist(),
                "contact": contact,
                "xy": {"x": float(current[0]), "y": float(current[1])},
                "pressure_bxy_uT": pressure_bxy,
                "series": {"t": times, "x": xs, "y": ys},
                "display": {"xy_radius_uT": 400,
                            "channels": {"x": "ΔBx", "y": "ΔBy"},
                            "series_units": "µT", "time_units": "s"},
            }
