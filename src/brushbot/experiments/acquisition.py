"""Single-owner magnetic sampling, baseline gating and control consumption."""

from __future__ import annotations

import copy
import math
from collections import deque
from typing import Callable

import numpy as np

from brushbot.filter import ButterworthFilter, EMA, OneEuroFilter


def _make_filter(config: dict):
    kind = config.get("kind")
    if kind == "ema":
        return EMA(float(config["alpha"]))
    if kind == "butterworth":
        return ButterworthFilter(float(config["fc"]), float(config.get("fs", 100.0)))
    if kind == "one_euro":
        return OneEuroFilter(
            min_cutoff=float(config.get("min_cutoff", 1.0)),
            beta=float(config.get("beta", 0.0)),
            d_cutoff=float(config.get("d_cutoff", 1.0)),
            fs=float(config.get("fs", 100.0)),
        )
    raise ValueError(f"unsupported control filter kind: {kind}")


class SampleHub:
    """The sole consumer of a source, with non-destructive subscriber cursors."""

    def __init__(self, source, clock_ns: Callable[[], int], *, control_filter=None,
                 max_samples: int = 100_000,
                 abort_on_invalid_running_sample: bool = False,
                 baseline_quality_axes=(0, 1, 2)):
        if max_samples < 1:
            raise ValueError("max_samples must be positive")
        self.source = source
        self.clock_ns = clock_ns
        self._rows = deque(maxlen=int(max_samples))
        self._seq = 0
        self._last_sensor_t_us = None
        self._baseline = None
        self._baseline_id = -1
        self._baseline_start_seq = None
        self._policy = {}
        self._control_filter = control_filter
        self._latest_filtered = None
        self._latest_control_row = None
        self._running = False
        self.fault = None
        self.abort_on_invalid_running_sample = bool(abort_on_invalid_running_sample)
        axes = tuple(baseline_quality_axes)
        if not axes or len(set(axes)) != len(axes) or any(
                isinstance(axis, bool) or not isinstance(axis, (int, np.integer))
                or axis not in (0, 1, 2) for axis in axes):
            raise ValueError('baseline_quality_axes must be distinct axes from 0, 1, 2')
        self._baseline_quality_axes = list(axes)

    @property
    def baseline_ready(self) -> bool:
        return self._baseline is not None

    @property
    def baseline_B0_uT(self):
        return None if self._baseline is None else self._baseline.copy()

    def set_running(self, running: bool) -> None:
        self._running = bool(running)

    def _append(self, row: dict) -> None:
        self._rows.append(row)

    def poll_once(self) -> list:
        """Read the source once. Only the acquisition thread may call this."""
        if self.fault is not None:
            return []
        try:
            frames = self.source.read_frames()
        except Exception as exc:
            self.fault = "source_disconnected"
            raise RuntimeError("source_disconnected") from exc
        if frames is None:
            self.fault = "source_disconnected"
            raise RuntimeError("source_disconnected")

        added = []
        for frame in frames:
            self._seq += 1
            host_rx_ns = int(
                frame["host_rx_ns"] if "host_rx_ns" in frame else self.clock_ns())
            sensor_t_us = frame.get("sensor_t_us")
            values = np.asarray(frame.get("B_uT"), dtype=float)
            valid = values.shape == (3,) and bool(np.isfinite(values).all())
            reason = "" if valid else "non_finite_or_malformed"
            if self.fault is not None:
                valid = False
                reason = "sensor_time_faulted"
            elif not isinstance(sensor_t_us, (int, np.integer)):
                valid = False
                reason = "invalid_sensor_time"
                self.fault = reason
            elif (self._last_sensor_t_us is not None
                  and int(sensor_t_us) <= self._last_sensor_t_us):
                # Accept only a declared uint32 clock crossing its boundary
                # with a short forward interval. Preserve raw time in the log;
                # freshness and baseline timing still use host monotonic time.
                modulus = getattr(self.source, 'sensor_time_modulus_us', None)
                wrapped = (modulus == 2**32
                           and 0 <= int(sensor_t_us) < self._last_sensor_t_us < modulus
                           and 0 < int(sensor_t_us)+modulus-self._last_sensor_t_us <= 1_000_000)
                if wrapped:
                    self._last_sensor_t_us = int(sensor_t_us)
                else:
                    valid = False
                    reason = "sensor_time_rollback"
                    self.fault = reason
            elif isinstance(sensor_t_us, (int, np.integer)):
                self._last_sensor_t_us = int(sensor_t_us)
            if not valid and self._running and self.abort_on_invalid_running_sample:
                self.fault = "sensor_invalid"

            b_list = values.tolist() if values.shape == (3,) else [None, None, None]
            row = {
                "seq": self._seq,
                "sensor_t_us": int(sensor_t_us) if isinstance(sensor_t_us, (int, np.integer)) else None,
                "host_rx_ns": host_rx_ns,
                "Bx_uT": b_list[0],
                "By_uT": b_list[1],
                "Bz_uT": b_list[2],
                "B_uT": b_list,
                "dBx_uT": None,
                "dBy_uT": None,
                "dBz_uT": None,
                "baseline_id": None,
                "valid": bool(valid),
                "invalid_reason": reason,
                "source_kind": frame.get("source_kind", "unknown"),
            }
            if valid and self._baseline is not None:
                delta = values - self._baseline
                row["baseline_id"] = self._baseline_id
                row["dBx_uT"], row["dBy_uT"], row["dBz_uT"] = (
                    float(delta[0]), float(delta[1]), float(delta[2]))
                filtered = np.asarray(self._control_filter.update(delta), dtype=float)
                self._latest_filtered = filtered
                self._latest_control_row = row
            self._append(row)
            added.append(copy.deepcopy(row))
        return added

    def take_since(self, seq: int) -> list:
        """Return retained samples after a cursor; fail if required rows were overwritten."""
        cursor = int(seq)
        if self._rows and cursor < self._rows[0]["seq"] - 1:
            raise RuntimeError("sample_buffer_overflow")
        # 订阅者通常只取上一拍之后的新尾部。反向遍历会在遇到 cursor 时立即停止，
        # 因此每拍成本与新增样本数相关，而不是与整场实验累计的历史长度相关。
        rows = []
        for row in reversed(self._rows):
            if row["seq"] <= cursor:
                break
            rows.append(copy.deepcopy(row))
        rows.reverse()
        return rows

    def begin_baseline(self) -> None:
        """Clear the active offset so baseline-acquisition rows have no delta."""
        if self._running:
            raise RuntimeError("cannot take baseline while running")
        self._baseline = None
        self._baseline_start_seq = None
        self._latest_filtered = None
        self._latest_control_row = None

    def set_baseline(self, samples: list, policy: dict, *, enforce_quality: bool = True) -> dict:
        """Validate and freeze B0; baseline rows themselves keep empty deltas."""
        if self._running:
            raise RuntimeError("cannot take baseline while running")
        if not policy.get("airborne_confirmed"):
            raise ValueError("airborne confirmation is required")
        if not policy.get("pose_static"):
            raise ValueError("pose_static confirmation is required")
        valid = [row for row in samples if row.get("valid")]
        minimum = int(policy.get("baseline_min_samples", 0))
        if len(valid) < minimum:
            raise ValueError("insufficient baseline samples")
        if not valid:
            raise ValueError("insufficient baseline samples")
        start_ns = int(valid[0]["host_rx_ns"])
        end_ns = int(valid[-1]["host_rx_ns"])
        duration_s = (end_ns - start_ns) / 1e9
        window_s = float(policy.get("baseline_window_s", 0.0))
        if duration_s + 1e-12 < window_s:
            raise ValueError("baseline samples do not span baseline_window_s")

        values = np.asarray([row["B_uT"] for row in valid], dtype=float)
        if values.ndim != 2 or values.shape[1] != 3 or not np.isfinite(values).all():
            raise ValueError("baseline contains invalid samples")
        std = values.std(axis=0)
        limits = np.asarray(policy["baseline_max_std_uT"], dtype=float)
        if enforce_quality:
            if (limits.shape != (3,) or not np.isfinite(limits).all()
                    or np.any(std[self._baseline_quality_axes] > limits[self._baseline_quality_axes])):
                raise ValueError("baseline standard deviation exceeds limit")
        times = (np.asarray([row["host_rx_ns"] for row in valid], dtype=float) - start_ns) / 1e9
        if duration_s > 0:
            slopes = np.array([np.polyfit(times, values[:, axis], 1)[0] for axis in range(3)])
        else:
            slopes = np.full(3, np.inf)
        drift_limit = float(policy["baseline_max_drift_uT_s"])
        if enforce_quality:
            if (not math.isfinite(drift_limit) or drift_limit < 0
                    or np.any(np.abs(slopes[self._baseline_quality_axes]) > drift_limit + 1e-9)):
                raise ValueError("baseline drift exceeds limit")

        baseline = values.mean(axis=0)
        filt = self._control_filter or _make_filter(policy["filter"])
        filt.reset()
        for value in values:
            filt.update(value - baseline)
        self._control_filter = filt
        self._baseline = baseline
        self._baseline_id += 1
        self._baseline_start_seq = max(int(row["seq"]) for row in valid)
        self._policy = copy.deepcopy(policy)
        self._latest_filtered = None
        self._latest_control_row = None
        return {
            "baseline_id": self._baseline_id,
            "B0_uT": baseline.tolist(),
            "std_uT": std.tolist(),
            "drift_uT_s": slopes.tolist(),
            "quality_axes": self._baseline_quality_axes.copy(),
            "first_seq": min(int(row["seq"]) for row in valid),
            "last_seq": self._baseline_start_seq,
        }

    def latest_control(self, now_ns: int) -> dict:
        if self.fault is not None:
            raise RuntimeError(self.fault)
        if self._baseline is None or self._latest_control_row is None:
            raise RuntimeError("no valid post-baseline control sample")
        age_s = (int(now_ns) - int(self._latest_control_row["host_rx_ns"])) / 1e9
        max_age = float(self._policy.get("sensor_max_age_s", math.inf))
        if age_s < 0 or age_s > max_age:
            raise RuntimeError("stale control sample")
        filtered = np.asarray(self._latest_filtered, dtype=float)
        return {
            "sample_seq": int(self._latest_control_row["seq"]),
            "sample_age_s": float(age_s),
            "dB_control_uT": filtered.tolist(),
            "a_control_uT": float(np.hypot(filtered[0], filtered[1])),
        }
