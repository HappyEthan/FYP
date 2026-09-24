"""Recoverable, streaming experiment run recording."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import queue
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


_SENSOR_FIELDS = (
    "seq", "sensor_t_us", "host_rx_ns", "Bx_uT", "By_uT", "Bz_uT",
    "dBx_uT", "dBy_uT", "dBz_uT", "baseline_id", "valid", "invalid_reason",
)
_STREAM_FILES = {
    "sensor": "sensor.csv",
    "control": "control.jsonl",
    "event": "events.jsonl",
}
_TERMINAL = {"completed", "aborted", "fault"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(_json_safe(value), ensure_ascii=False, indent=2,
                       sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_json_bytes(value))
    os.replace(temporary, path)


def _process_exists(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


class RunRecorder:
    """Write three append-only streams and atomically finalize a run manifest."""

    def __init__(self, root: str, snapshots: dict, *, queue_size: int = 4096,
                 started_at: datetime | None = None):
        if isinstance(queue_size, bool) or not isinstance(queue_size, int) or queue_size < 1:
            raise ValueError("queue_size must be a positive integer")
        self._started_at = started_at or datetime.now(timezone.utc)
        if self._started_at.tzinfo is None:
            raise ValueError("started_at must include a timezone")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._recover_interrupted()
        self.run_id, self.run_dir = self._create_run_dir()
        self._finished = False
        self._writer_error = None
        self._queue = queue.Queue(maxsize=int(queue_size))
        self._sentinel = object()
        self._files = {}
        self._sensor_writer = None

        self._manifest = {
            "run_id": self.run_id,
            "status": "running",
            "reason": "",
            "started_at": self._started_at.isoformat(),
            "finished_at": None,
            "writer_pid": os.getpid(),
            "sha256": {},
            "filter": _json_safe(snapshots.get("filter")),
            "adapter": _json_safe(snapshots.get("adapter")),
            "execution_environment": str(
                snapshots.get("execution_environment", "unspecified")),
            "baselines": [],
        }
        if snapshots.get("brush_id") is not None:
            self._manifest["brush_id"] = str(snapshots["brush_id"])
        self._write_snapshots(dict(snapshots))
        _atomic_json(self.run_dir / "manifest.json", self._manifest)

        self._thread = threading.Thread(
            target=self._writer_loop,
            name=f"experiment-recorder-{self.run_id}",
            daemon=True,
        )
        self._thread.start()

    def _recover_interrupted(self) -> None:
        for manifest_path in self.root.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if manifest.get("status") != "running":
                continue
            if _process_exists(manifest.get("writer_pid")):
                continue
            manifest["status"] = "interrupted"
            manifest["reason"] = "recovered_after_unclean_shutdown"
            manifest["finished_at"] = _utc_now()
            _atomic_json(manifest_path, manifest)

    def _create_run_dir(self):
        stamp = self._started_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        for _ in range(100):
            run_id = f"{stamp}-{secrets.token_hex(3)}"
            folder = self.root / run_id
            try:
                folder.mkdir()
            except FileExistsError:
                continue
            return run_id, folder
        raise RuntimeError("could not allocate unique experiment run_id")

    def _save_bytes(self, name: str, payload: bytes) -> None:
        path = self.run_dir / name
        path.write_bytes(payload)
        self._manifest["sha256"][name] = hashlib.sha256(payload).hexdigest()

    def _save_json(self, name: str, value: Any) -> None:
        self._save_bytes(name, _json_bytes(value))

    def _write_snapshots(self, snapshots: dict) -> None:
        raw = snapshots.get("input_bytes")
        if raw is not None:
            if not isinstance(raw, bytes):
                raise ValueError("input_bytes must be bytes")
            self._save_bytes("input.json", raw)
        resolved = snapshots.get("resolved", snapshots.get("experiment"))
        if resolved is not None:
            self._save_json("resolved.json", resolved)
        if snapshots.get("setup") is not None:
            self._save_json("setup.json", snapshots["setup"])
        if snapshots.get("calibration") is not None:
            self._save_json("calibration.json", snapshots["calibration"])

        compiled = snapshots.get("compiled")
        if compiled is not None:
            plan = compiled.get("plan")
            if plan is None or not hasattr(plan, "save"):
                raise ValueError("compiled.plan must support save(path)")
            plan_path = self.run_dir / "compiled_plan.npz"
            plan.save(plan_path)
            self._manifest["sha256"][plan_path.name] = hashlib.sha256(
                plan_path.read_bytes()).hexdigest()
            timeline_keys = (
                "t_s", "s", "phase", "pose_m_rad", "g_ref_uT", "depth_ff_m",
            )
            missing = [key for key in timeline_keys if key not in compiled]
            if missing:
                raise ValueError("compiled timeline missing: " + ", ".join(missing))
            timeline_path = self.run_dir / "timeline.npz"
            np.savez(timeline_path, **{key: np.asarray(compiled[key]) for key in timeline_keys})
            self._manifest["sha256"][timeline_path.name] = hashlib.sha256(
                timeline_path.read_bytes()).hexdigest()

    def _writer_loop(self) -> None:
        try:
            self._files = {
                stream: (self.run_dir / filename).open("w", encoding="utf-8", newline="")
                for stream, filename in _STREAM_FILES.items()
            }
            self._sensor_writer = csv.DictWriter(
                self._files["sensor"], fieldnames=_SENSOR_FIELDS, extrasaction="ignore")
            self._sensor_writer.writeheader()
            for handle in self._files.values():
                handle.flush()
            while True:
                item = self._queue.get()
                try:
                    if item is self._sentinel:
                        break
                    if self._writer_error is None:
                        stream, row = item
                        self._write_item(stream, row)
                except Exception as exc:  # propagated by finish/write health checks
                    self._writer_error = f"{type(exc).__name__}: {exc}"
                finally:
                    self._queue.task_done()
        except Exception as exc:
            self._writer_error = f"{type(exc).__name__}: {exc}"
        finally:
            for handle in self._files.values():
                try:
                    handle.flush()
                    os.fsync(handle.fileno())
                    handle.close()
                except OSError as exc:
                    if self._writer_error is None:
                        self._writer_error = f"{type(exc).__name__}: {exc}"

    def _write_item(self, stream: str, row: dict) -> None:
        if stream == "sensor":
            encoded = {}
            for field in _SENSOR_FIELDS:
                value = _json_safe(row.get(field))
                if isinstance(value, bool):
                    value = "true" if value else "false"
                encoded[field] = value
            self._sensor_writer.writerow(encoded)
            self._files["sensor"].flush()
            return
        payload = json.dumps(_json_safe(row), ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
        self._files[stream].write(payload + "\n")
        self._files[stream].flush()

    def write(self, stream: str, row: dict) -> None:
        if stream not in _STREAM_FILES:
            raise ValueError(f"unknown stream: {stream}")
        if self._finished:
            raise RuntimeError("recorder is already finished")
        if self._writer_error is not None:
            raise RuntimeError("logger_fault: " + self._writer_error)
        try:
            self._queue.put_nowait((stream, dict(row)))
        except queue.Full as exc:
            self._writer_error = "logger queue overflow"
            raise RuntimeError("logger_fault: logger queue overflow") from exc

    def record_baseline(self, metadata: dict) -> None:
        """Persist the frozen B0 and the sequence after which it applies."""
        if self._finished:
            raise RuntimeError("recorder is already finished")
        expected_id = len(self._manifest["baselines"])
        try:
            b0 = np.asarray(metadata["B0_uT"], dtype=float)
            last_seq = int(metadata["last_seq"])
            baseline_id = int(metadata.get("baseline_id", expected_id))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("baseline requires B0_uT and last_seq") from exc
        if (b0.shape != (3,) or not np.isfinite(b0).all()
                or last_seq < 0 or baseline_id < 0):
            raise ValueError("baseline baseline_id/B0_uT/last_seq is invalid")
        if baseline_id != expected_id:
            raise ValueError(f"baseline_id must be {expected_id}")
        baseline = _json_safe(dict(metadata))
        baseline["baseline_id"] = baseline_id
        baseline["applies_after_seq"] = last_seq
        self._manifest["baselines"].append(baseline)
        if "baseline" not in self._manifest:
            self._manifest["baseline"] = baseline
        _atomic_json(self.run_dir / "manifest.json", self._manifest)

    def finish(self, status: str, reason: str = "") -> str:
        if status not in _TERMINAL:
            raise ValueError("status must be completed, aborted, or fault")
        if self._finished:
            return str(self.run_dir)
        self._finished = True
        self._queue.put(self._sentinel)
        self._thread.join()
        writer_error = self._writer_error
        if writer_error is not None:
            status = "fault"
            reason = "logger_fault: " + writer_error
        self._manifest["status"] = status
        self._manifest["reason"] = str(reason)
        self._manifest["finished_at"] = _utc_now()
        _atomic_json(self.run_dir / "manifest.json", self._manifest)
        if writer_error is not None:
            raise RuntimeError(reason)
        return str(self.run_dir)
