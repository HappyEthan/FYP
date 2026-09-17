"""Independent Cartesian return geometry and controller; no StrokePlan dependency."""

from __future__ import annotations

import copy
import math
import secrets

import numpy as np


_ACTIVE_STATES = {"READY", "RETURNING"}
_TERMINAL_STATES = {"IDLE", "COMPLETED", "ABORTED", "FAULT"}


def _pose6(values, field: str) -> tuple[float, float, float, float, float, float]:
    try:
        pose = tuple(float(value) for value in values)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain six finite numbers") from exc
    if len(pose) != 6 or not np.isfinite(pose).all():
        raise ValueError(f"{field} must contain six finite numbers")
    return pose


def target_pose_si(x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg) -> tuple:
    """Freeze a monitor target expressed in millimetres/degrees as metres/radians."""
    values = _pose6((x_mm, y_mm, z_mm, rx_deg, ry_deg, rz_deg), "target pose")
    return (
        values[0] / 1000.0,
        values[1] / 1000.0,
        values[2] / 1000.0,
        math.radians(values[3]),
        math.radians(values[4]),
        math.radians(values[5]),
    )


def _workspace_bounds(setup: dict) -> tuple[np.ndarray, np.ndarray]:
    try:
        lower = np.asarray(setup["workspace_min_mm"], dtype=float)
        upper = np.asarray(setup["workspace_max_mm"], dtype=float)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("workspace bounds must be finite three-vectors") from exc
    if (lower.shape != (3,) or upper.shape != (3,)
            or not np.isfinite(np.vstack([lower, upper])).all()
            or np.any(lower >= upper)):
        raise ValueError("workspace bounds must be finite increasing three-vectors")
    return lower, upper


def _validate_workspace(poses: list[tuple] | tuple, setup: dict) -> None:
    lower, upper = _workspace_bounds(setup)
    rows = np.atleast_2d(np.asarray(poses, dtype=float))
    xyz_mm = rows[:, :3] * 1000.0
    if np.any(xyz_mm < lower):
        raise ValueError("Cartesian return pose is outside workspace")
    if np.any(xyz_mm > upper):
        raise ValueError("Cartesian return pose is outside workspace")

def _append_distinct(route: list[tuple], pose: tuple, previous: tuple) -> tuple:
    if not np.allclose(pose, previous, rtol=0.0, atol=1e-12):
        route.append(pose)
        return pose
    return previous


def build_return_route(current_pose, target_pose, setup: dict) -> list[tuple]:
    """Build lift, XY translation, orientation, then optional descent waypoints."""
    current = _pose6(current_pose, "current pose")
    target = _pose6(target_pose, "target pose")
    travel_z = max(current[2], target[2])
    route: list[tuple] = []
    previous = current
    candidates = (
        (current[0], current[1], travel_z, *current[3:]),
        (target[0], target[1], travel_z, *current[3:]),
        (target[0], target[1], travel_z, *target[3:]),
        target,
    )
    for candidate in candidates:
        previous = _append_distinct(route, candidate, previous)
    _validate_workspace([current, *route], setup)
    return route


class CartesianReturnController:
    """Run one validated return route without owning experiment state."""

    def __init__(self, arm, setup: dict):
        self.arm = arm
        self.setup = copy.deepcopy(setup)
        self.state = "IDLE"
        self.operation_id = None
        self.target_pose = None
        self.last_error = ""
        self._route: list[tuple] = []
        self._index = 0
        self._pending = None
        self._validate_speed()

    def _validate_speed(self) -> float:
        try:
            speed = float(self.setup["return_speed_mm_s"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("return_speed_mm_s must be positive and finite") from exc
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("return_speed_mm_s must be positive and finite")
        limits = [self.setup.get("max_xy_speed_mm_s"), self.setup.get("max_z_speed_mm_s")]
        finite_limits = [float(value) for value in limits if value is not None]
        if finite_limits and speed > min(finite_limits):
            raise ValueError("return_speed_mm_s exceeds configured speed limit")
        return speed

    def prepare(self, target_pose) -> dict:
        target = _pose6(target_pose, "target pose")
        _validate_workspace([target], self.setup)
        if self.state in _ACTIVE_STATES:
            if target == self.target_pose:
                return self.snapshot()
            raise RuntimeError("a Cartesian return operation is already active")
        self.target_pose = target
        self.operation_id = secrets.token_hex(8)
        self.last_error = ""
        self._route = []
        self._index = 0
        self._pending = None
        self.state = "READY"
        return self.snapshot()

    def _pose_matches(self, actual, expected) -> bool:
        actual_pose = np.asarray(_pose6(actual, "actual pose"))
        expected_pose = np.asarray(expected, dtype=float)
        position_tolerance = float(self.setup.get("pose_tolerance_mm", 0.1)) / 1000.0
        orientation_tolerance = float(self.setup.get("orientation_tolerance_rad", 0.01))
        angle = np.abs(
            (actual_pose[3:] - expected_pose[3:] + np.pi) % (2 * np.pi) - np.pi)
        return (np.linalg.norm(actual_pose[:3] - expected_pose[:3]) <= position_tolerance
                and np.all(angle <= orientation_tolerance))

    def _read_pose(self) -> tuple:
        state = self.arm.read_state()
        if not state.get("available") or state.get("tcp_pose") is None:
            raise RuntimeError("current pose is unavailable")
        return _pose6(state["tcp_pose"], "current pose")

    def _fault(self, reason: str) -> None:
        self.last_error = str(reason)
        try:
            self.arm.stop()
        except Exception:
            pass
        self.state = "FAULT"

    def step(self) -> dict:
        if self.state in _TERMINAL_STATES:
            return self.snapshot()
        try:
            if self.state == "READY":
                current = self._read_pose()
                self._route = build_return_route(current, self.target_pose, self.setup)
                self.state = "RETURNING"
                if not self._route:
                    self.state = "COMPLETED"
                    return self.snapshot()
            if self._pending is not None:
                if not self._pose_matches(self._read_pose(), self._pending):
                    return self.snapshot()
                self._pending = None
                self._index += 1
            if self._index >= len(self._route):
                self.state = "COMPLETED"
                return self.snapshot()
            pose = self._route[self._index]
            self.arm.move_pose(pose, self._validate_speed())
            self._pending = pose
        except Exception as exc:
            self._fault("communication_fault" if not isinstance(exc, ValueError) else str(exc))
        return self.snapshot()

    def request_stop(self, reason: str) -> dict:
        if self.state not in _ACTIVE_STATES:
            return self.snapshot()
        try:
            self.arm.stop()
        except Exception:
            self.last_error = "communication_fault"
            self.state = "FAULT"
            return self.snapshot()
        self.last_error = str(reason)
        self.state = "ABORTED"
        return self.snapshot()

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "operation_id": self.operation_id,
            "target_pose_m_rad": copy.deepcopy(self.target_pose),
            "last_error": self.last_error,
            "route_index": self._index,
            "route_length": len(self._route),
        }
