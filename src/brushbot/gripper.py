"""High-level driver for a DH AG-160-95 gripper through HYGripper.

The supplied ``client`` must provide ``HRApp(name, param)``.  In production this
is :class:`brushbot.backends.vendor.CPS.CPSClient`; tests may use a small fake.
All public positions are jaw opening widths in millimetres (0=closed, 95=open).
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Callable, Optional, Sequence


PLUGIN_NAME = "hr_gri_plugins"

ERROR_MESSAGES = {
    60000: "invalid parameter (check that GID starts at 1)",
    60002: "connection failed (check power, RS485 wiring and plugin settings)",
    60004: "clear-fault failed (check communication and wiring)",
    60005: "activation failed",
    60006: "initialization failed",
    60007: "position is out of range",
    60008: "speed is out of range",
    60009: "force is out of range",
    60010: "motion failed",
    60011: "failed to read gripper state",
    60015: "gripper is not registered",
    60017: "gripper is connecting; operation is unavailable",
    60018: "configured gripper type does not match",
    60021: "invalid plugin command",
    60025: "GID is out of range",
    60027: "stop command failed",
    60028: "gripper safety switch is active",
    60030: "gripper is already moving",
    60031: "function is not supported by this gripper",
    60041: "gripper reset failed",
    60043: "gripper is faulted; power-cycle it",
    60498: "unknown gripper error",
}


class GripperError(RuntimeError):
    """Base class for gripper failures."""


class GripperCommandError(GripperError):
    """The controller/plugin rejected a command."""

    def __init__(self, code: int, command: str, reply: Sequence[str]):
        self.code = code
        self.command = command
        self.reply = tuple(reply)
        detail = ERROR_MESSAGES.get(code, "unknown controller error")
        super().__init__(f"{command} failed with {code}: {detail}; reply={list(reply)!r}")


class GripperProtocolError(GripperError):
    """The controller returned a malformed or unexpected reply."""


class GripperTimeoutError(GripperError, TimeoutError):
    """Motion did not finish before the requested timeout."""


@dataclass(frozen=True)
class GripperState:
    """One state snapshot. Motion fields are unavailable while disconnected."""

    connected: bool
    moving: Optional[bool]
    caught: Optional[bool]
    catch_state: Optional[int]
    width_mm: Optional[float]
    raw_position: Optional[int]
    error_code: Optional[int]


class Gripper:
    """DH AG-160-95 command layer for the HYGripper controller plugin."""

    RAW_MIN = 0
    RAW_MAX = 1000
    WIDTH_MIN_MM = 0.0
    WIDTH_MAX_MM = 95.0
    MM_PER_COUNT = 0.095
    SPEED_MIN = 1
    SPEED_MAX = 100
    FORCE_MIN = 20
    FORCE_MAX = 100

    def __init__(self, client, gid: int = 1, model: str = "DHAG",
                 *, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if not isinstance(gid, int) or isinstance(gid, bool) or gid < 1:
            raise ValueError("gid must be an integer >= 1")
        if model.upper() != "DHAG":
            raise ValueError("only model='DHAG' is currently supported")
        self.client = client
        self.gid = gid
        self.model = model.upper()
        self._clock = clock
        self._sleep = sleep

    @classmethod
    def width_to_raw(cls, width_mm: float) -> int:
        width = cls._number("width_mm", width_mm)
        if not cls.WIDTH_MIN_MM <= width <= cls.WIDTH_MAX_MM:
            raise ValueError("width_mm must be in [0, 95]")
        return min(cls.RAW_MAX, max(cls.RAW_MIN, round(width / cls.MM_PER_COUNT)))

    @classmethod
    def raw_to_width(cls, raw: int) -> float:
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise TypeError("raw position must be an integer")
        if not cls.RAW_MIN <= raw <= cls.RAW_MAX:
            raise ValueError("raw position must be in [0, 1000]")
        return raw * cls.MM_PER_COUNT

    def open(self, *, speed: int = 30, force: int = 30) -> None:
        self._move_raw(self.RAW_MAX, speed, force)

    def close(self, *, speed: int = 30, force: int = 30) -> None:
        self._move_raw(self.RAW_MIN, speed, force)

    def move_to_width(self, width_mm: float, *, speed: int = 30,
                      force: int = 30) -> None:
        self._move_raw(self.width_to_raw(width_mm), speed, force)

    def move_rel(self, delta_mm: float, *, speed: int = 30,
                 force: int = 30) -> None:
        delta = self._number("delta_mm", delta_mm)
        if not -self.WIDTH_MAX_MM <= delta <= self.WIDTH_MAX_MM:
            raise ValueError("delta_mm must be in [-95, 95]")
        speed, force = self._motion_params(speed, force)
        raw = round(delta / self.MM_PER_COUNT)
        self._command(f"GripperRelCatchMove,{self.gid},{raw},{speed},{force}")

    def stop(self) -> None:
        self._command(f"GripperStop,{self.gid}")

    def clear_fault(self) -> None:
        self._command(f"GripperClearFault,{self.gid}")

    def is_connected(self) -> bool:
        reply = self._command(f"GetConnectState,{self.gid}")
        # Observed failure replies put GRIPPERFAIL in the status field.  Accept
        # either status or value placement so this also works across plugin builds.
        fields = {str(v).upper() for v in reply[1:]}
        if "GRIPPERFAIL" in fields:
            return False
        if "GRIPPEROK" in fields:
            return True
        raise GripperProtocolError(f"unexpected GetConnectState reply: {reply!r}")

    def is_moving(self) -> bool:
        return bool(self._query_int("IsMoving"))

    def read(self) -> GripperState:
        connect_reply = self._command(f"GetConnectState,{self.gid}")
        fields = {str(v).upper() for v in connect_reply[1:]}
        if "GRIPPERFAIL" in fields:
            code = self._last_int(connect_reply[2:])
            return GripperState(False, None, None, None, None, None, code)
        if "GRIPPEROK" not in fields:
            raise GripperProtocolError(
                f"unexpected GetConnectState reply: {connect_reply!r}")
        moving = self._query_int("IsMoving")
        catch = self._query_int("GetCatchState")
        raw = self._query_int("GetCatchPosition")
        error = self._query_int("GetGripperErrorCode")
        if raw < self.RAW_MIN or raw > self.RAW_MAX:
            raise GripperProtocolError(f"position outside [0, 1000]: {raw}")
        return GripperState(True, bool(moving), catch == 1, catch,
                            self.raw_to_width(raw), raw, error)

    def wait_done(self, timeout: float = 5.0, poll_interval: float = 0.05,
                  *, stop_on_timeout: bool = True) -> GripperState:
        timeout = self._positive("timeout", timeout)
        poll_interval = self._positive("poll_interval", poll_interval)
        deadline = self._clock() + timeout
        while True:
            if not self.is_moving():
                return self.read()
            if self._clock() >= deadline:
                stop_error = None
                if stop_on_timeout:
                    try:
                        self.stop()
                    except GripperError as exc:
                        stop_error = exc
                suffix = f"; stop also failed: {stop_error}" if stop_error else ""
                raise GripperTimeoutError(
                    f"gripper motion timed out after {timeout:g}s{suffix}")
            self._sleep(min(poll_interval, max(0.0, deadline - self._clock())))

    def _move_raw(self, raw: int, speed: int, force: int) -> None:
        speed, force = self._motion_params(speed, force)
        self._command(f"GripperAbsCatchMove,{self.gid},{raw},{speed},{force}")

    def _motion_params(self, speed: int, force: int) -> tuple[int, int]:
        for name, value, low, high in (
            ("speed", speed, self.SPEED_MIN, self.SPEED_MAX),
            ("force", force, self.FORCE_MIN, self.FORCE_MAX),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{name} must be an integer")
            if not low <= value <= high:
                raise ValueError(f"{name} must be in [{low}, {high}]")
        return speed, force

    def _command(self, command: str) -> list[str]:
        reply = self.client.HRApp(PLUGIN_NAME, command)
        if not isinstance(reply, (list, tuple)) or not reply:
            raise GripperProtocolError(f"malformed reply to {command}: {reply!r}")
        values = [str(v) for v in reply]
        try:
            code = int(values[0])
        except (TypeError, ValueError) as exc:
            raise GripperProtocolError(
                f"non-numeric status in reply to {command}: {reply!r}") from exc
        if code != 0:
            raise GripperCommandError(code, command, values)
        return values

    def _query_int(self, name: str) -> int:
        command = f"{name},{self.gid}"
        reply = self._command(command)
        if len(reply) < 3 or reply[1].upper() != "GRIPPEROK":
            raise GripperProtocolError(f"unexpected reply to {command}: {reply!r}")
        try:
            return int(reply[2])
        except ValueError as exc:
            raise GripperProtocolError(
                f"non-integer value in reply to {command}: {reply!r}") from exc

    @staticmethod
    def _last_int(values: Sequence[str]) -> Optional[int]:
        for value in reversed(values):
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _number(name: str, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{name} must be a real number")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        return value

    @classmethod
    def _positive(cls, name: str, value: float) -> float:
        value = cls._number(name, value)
        if value <= 0:
            raise ValueError(f"{name} must be > 0")
        return value
