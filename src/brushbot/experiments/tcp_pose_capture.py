"""Record actual TCP poses on a separate, low-rate reader connection.

The command loop never waits for a pose request.  Timestamps share its
monotonic clock, so downstream analysis can align samples without pretending
that one asynchronous pose belongs to a particular 20 ms command tick.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import threading
import time


FIELDS = (
    "sample_index", "request_start_ns", "request_end_ns",
    "x_m", "y_m", "z_m", "rx_rad", "ry_rad", "rz_rad", "valid", "error",
)


class TCPPoseSampler:
    def __init__(self, read_pose, *, clock_ns=time.monotonic_ns,
                 interval_s=0.1, source="HRIF_ReadActTcpPos (independent connection)"):
        if not callable(read_pose) or not callable(clock_ns):
            raise ValueError("pose reader and clock must be callable")
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("pose sampling interval must be finite and positive")
        self.read_pose = read_pose
        self.clock_ns = clock_ns
        self.interval_s = float(interval_s)
        self.source = str(source)
        self._stop = threading.Event()
        self._thread = None
        self._stream = None
        self._writer = None
        self._run_dir = None
        self._rows = 0
        self._valid = 0
        self._max_duration_ns = 0
        self._worker_error = None
        self._summary = None

    def start(self, run_dir):
        if self._stream is not None:
            raise RuntimeError("actual TCP sampler already started")
        self._run_dir = Path(run_dir)
        self._stream = (self._run_dir / "actual_tcp.csv").open(
            "x", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._stream, fieldnames=FIELDS)
        self._writer.writeheader()
        self._stream.flush()
        # Probe before the background loop starts. A missing second connection
        # must fail before the experiment can move the arm.
        self._sample_once(fail_initial=True)
        self._thread = threading.Thread(
            target=self._run, name="actual-tcp-sampler", daemon=True)
        self._thread.start()

    def _sample_once(self, *, fail_initial=False):
        started = int(self.clock_ns())
        pose = None
        error = ""
        try:
            pose = tuple(float(value) for value in self.read_pose())
            if (len(pose) != 6 or not all(map(math.isfinite, pose))
                    or any(abs(value) > 10 for value in pose[:3])):
                raise ValueError("actual TCP pose is not six finite SI values")
        except Exception as exc:
            pose = None
            error = f"{type(exc).__name__}: {exc}"
        finished = int(self.clock_ns())
        row = {
            "sample_index": self._rows,
            "request_start_ns": started,
            "request_end_ns": finished,
            "valid": "true" if pose is not None else "false",
            "error": error,
        }
        if pose is not None:
            row.update(zip(FIELDS[3:9], pose))
            self._valid += 1
        self._writer.writerow(row)
        self._stream.flush()
        self._rows += 1
        self._max_duration_ns = max(self._max_duration_ns, finished - started)
        if fail_initial and pose is None:
            raise RuntimeError("initial actual TCP read failed: " + error)

    def _run(self):
        try:
            while not self._stop.wait(self.interval_s):
                self._sample_once()
        except Exception as exc:
            self._worker_error = f"{type(exc).__name__}: {exc}"

    def stop(self):
        if self._summary is not None:
            return self._summary
        if self._stream is None:
            return None
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        stopped = self._thread is None or not self._thread.is_alive()
        if stopped:
            self._stream.close()
        self._summary = {
            "source": self.source,
            "clock": "host_monotonic_ns",
            "units": "metres_and_radians",
            "requested_interval_s": self.interval_s,
            "samples": self._rows,
            "valid_samples": self._valid,
            "invalid_samples": self._rows - self._valid,
            "max_read_duration_ms": self._max_duration_ns / 1e6,
            "worker_stopped": stopped,
            "worker_error": self._worker_error,
        }
        (self._run_dir / "actual_tcp_meta.json").write_text(
            json.dumps(self._summary, indent=2) + "\n", encoding="utf-8")
        return self._summary
