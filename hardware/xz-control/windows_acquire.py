#!/usr/bin/env python3
"""Windows command-line X/Z motion and magnetic acquisition.

This is the non-GUI replacement for the peer acquisition flow.  It uses the
XZ1 serial protocol already implemented by ``firmware/XZ_Controller`` and the
FYP monitor's raw-B semantics:

    t_us,Bx_uT,By_uT,Bz_uT

The run sequence is:

    ZERO ALL (software zero, no physical movement)
    baseline at rest
    X forward
    Z upward
    X back
    Z back down to the starting zero (unless --leave-z-up is supplied)

Sensor data are collected during every motion stage and saved as CSV together
with raw B, dB, device time, controller position, and sample_valid.  The
script intentionally has no PySide6 dependency and is suitable for Windows
PowerShell or cmd.exe.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

try:
    import serial
    from serial import SerialException
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - gives a useful CLI error on Windows.
    serial = None
    list_ports = None

    class SerialException(Exception):
        pass


PROTOCOL = "XZ1"
DEFAULT_MOTOR_BAUD = 115200
DEFAULT_SENSOR_BAUD = 115200
DEFAULT_PULSES_PER_REV = 1000
DEFAULT_MM_PER_REV = 4.0
DEFAULT_X_MM = 125.0
DEFAULT_Z_MM = 20.0
DEFAULT_SPEED_PPS = 1000
DEFAULT_ACCEL_PPS2 = 1000
DEFAULT_BASELINE_SECONDS = 2.0
DEFAULT_SENSOR_TIMEOUT = 2.0
DEFAULT_MOTION_TIMEOUT = 180.0
SPIKE_UT = 1000.0
RETURN_UT = 250.0


def available_ports() -> list:
    """Return currently enumerated Windows serial ports, sorted by device."""
    if list_ports is None:
        raise RuntimeError("未安装 pyserial，请先运行: python -m pip install pyserial")
    return sorted(list(list_ports.comports()), key=lambda item: item.device.lower())


def port_label(info) -> str:
    """Build a useful Windows device label without assuming a USB chipset."""
    parts = [info.device, info.description or "未知设备"]
    if getattr(info, "manufacturer", None):
        parts.append(str(info.manufacturer))
    vid, pid = getattr(info, "vid", None), getattr(info, "pid", None)
    if vid is not None and pid is not None:
        parts.append(f"VID:PID={vid:04X}:{pid:04X}")
    if getattr(info, "serial_number", None):
        parts.append(f"SN={info.serial_number}")
    return " | ".join(parts)


def choose_port(role: str, excluded: set[str] | None = None) -> str:
    """Interactively select one port, allowing refresh and literal COM names."""
    excluded = {value.upper() for value in (excluded or set())}
    while True:
        ports = [info for info in available_ports()
                 if info.device.upper() not in excluded]
        print(f"\n可用的 {role} 串口：")
        if not ports:
            print("  （没有可用串口；请插入设备后按 R 刷新，或按 Q 退出）")
        else:
            for index, info in enumerate(ports, start=1):
                print(f"  [{index}] {port_label(info)}")
        answer = input(f"请选择{role}串口编号/COM 名称（R=刷新，Q=退出）：").strip()
        if answer.lower() in {"q", "quit", "exit"}:
            raise RuntimeError("用户取消了串口选择")
        if answer.lower() in {"r", "refresh", "刷新", ""}:
            continue
        if answer.isdigit():
            index = int(answer) - 1
            if 0 <= index < len(ports):
                return ports[index].device
        literal = answer.upper()
        for info in ports:
            if info.device.upper() == literal:
                return info.device
        print("输入无效，请重新选择。")


def resolve_ports(args: argparse.Namespace) -> tuple[str, str]:
    """Use explicit ports when supplied; otherwise enter the COM chooser."""
    if args.motor_port and args.sensor_port:
        if args.motor_port.upper() == args.sensor_port.upper():
            raise ValueError("电机串口和传感器串口不能是同一个 COM 口")
        return args.motor_port, args.sensor_port
    print("正在搜索 Windows 串口。请根据设备描述选择对应端口。")
    motor_port = args.motor_port or choose_port("电机控制器")
    sensor_port = args.sensor_port or choose_port("磁传感器", {motor_port})
    if motor_port.upper() == sensor_port.upper():
        raise ValueError("电机串口和传感器串口不能是同一个 COM 口")
    return motor_port, sensor_port


def ask_distance(label: str, default: float) -> float:
    """Ask for a non-negative distance in millimetres, keeping a default."""
    while True:
        answer = input(f"{label}（mm，直接回车使用 {default:g}）：").strip()
        if not answer:
            return float(default)
        try:
            value = float(answer)
        except ValueError:
            print("请输入数字，例如 125 或 20。")
            continue
        if math.isfinite(value) and value >= 0:
            return value
        print("距离必须是非负有限数。")


def ask_positive_int(label: str, default: int) -> int:
    """Ask for a positive integer such as pulses/s, keeping a default."""
    while True:
        answer = input(f"{label}（脉冲/秒，直接回车使用 {default}）：").strip()
        if not answer:
            return int(default)
        try:
            value = int(answer)
        except ValueError:
            print("请输入正整数，例如 1000。")
            continue
        if value > 0:
            return value
        print("速度必须是正整数。")


def prepare_interactive(args: argparse.Namespace) -> None:
    """Let a double-clicked run set distances and explicitly confirm start."""
    print(f"\n已选择电机串口: {args.motor_port}")
    print(f"已选择磁传感器串口: {args.sensor_port}")
    if args.no_confirm:
        return
    while True:
        args.x_mm = ask_distance("X 轴移动距离", args.x_mm)
        args.z_mm = ask_distance("Z 轴上升距离", args.z_mm)
        try:
            x_pulses = pulses_for_distance(args.x_mm, args.pulses_per_rev,
                                           args.mm_per_rev)
            z_pulses = pulses_for_distance(args.z_mm, args.pulses_per_rev,
                                           args.mm_per_rev)
        except ValueError as exc:
            print(f"距离不能换算为整数脉冲：{exc}")
            continue
        break
    args.x_speed_pps = ask_positive_int("X 轴速度", args.x_speed_pps)
    args.z_speed_pps = ask_positive_int("Z 轴速度", args.z_speed_pps)
    print("\n本次运动参数：")
    print(f"  X: {args.x_mm:g} mm -> {x_pulses} pulses")
    print(f"  Z: {args.z_mm:g} mm -> {z_pulses} pulses")
    print(f"  速度: X={args.x_speed_pps} pulses/s, Z={args.z_speed_pps} pulses/s")
    print("  顺序: ZERO ALL -> 基线 -> X前进 -> Z上升 -> X返回 -> Z回零")
    print("  运动过程中会实时显示 X/Z 位置和 Bx/By/Bz。")
    answer = input("确认设备已准备好后按 Enter 开始（Q=取消）：").strip()
    if answer.lower() in {"q", "quit", "exit"}:
        raise RuntimeError("用户取消了采集")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def open_serial(port: str, baudrate: int, timeout: float):
    if serial is None:
        raise RuntimeError("未安装 pyserial，请先运行: python -m pip install pyserial")
    kwargs = dict(port=port, baudrate=baudrate, timeout=timeout,
                  write_timeout=1.0)
    try:
        return serial.Serial(exclusive=True, **kwargs)
    except TypeError:
        # ``exclusive`` is not available in some older pyserial builds.
        return serial.Serial(**kwargs)


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def population_std(values: Iterable[float]) -> float:
    values = list(values)
    if not values:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def vec_norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def quality_mask(values: list[tuple[float, float, float]],
                 spike_uT: float = SPIKE_UT,
                 return_uT: float = RETURN_UT) -> tuple[list[bool], list[str]]:
    """Match the FYP isolated-spike rule without requiring NumPy."""
    valid = [all(math.isfinite(v) for v in row) for row in values]
    reason = ["" if ok else "nonfinite" for ok in valid]
    for i in range(1, len(values) - 1):
        prev, cur, nxt = values[i - 1], values[i], values[i + 1]
        isolated = (
            vec_norm(tuple(cur[j] - prev[j] for j in range(3))) >= spike_uT
            and vec_norm(tuple(cur[j] - nxt[j] for j in range(3))) >= spike_uT
            and vec_norm(tuple(nxt[j] - prev[j] for j in range(3))) <= return_uT
        )
        if isolated:
            valid[i] = False
            reason[i] = "isolated_spike"
    return valid, reason


@dataclass(frozen=True)
class SensorFrame:
    sensor_t_us: int
    device_time_unwrapped_us: int
    device_clock_segment: int
    host_rx_ns: int
    bx: float
    by: float
    bz: float


@dataclass
class RecordedFrame:
    frame: SensorFrame
    stage: str
    host_elapsed_s: float
    motor_status: dict


class LiveDisplay:
    """Small console status line; no GUI or terminal-specific dependency."""

    def __init__(self, pulses_per_mm: float, interval_s: float = 0.2):
        self.pulses_per_mm = pulses_per_mm
        self.interval_s = interval_s
        self.last_print = 0.0
        self.last_width = 0
        self.stage = "idle"
        self.closed = False

    def set_stage(self, stage: str) -> None:
        if self.closed:
            return
        if self.stage != stage:
            if self.last_width:
                print()
            self.stage = stage
            self.last_print = 0.0

    @staticmethod
    def _position(status: dict, key: str, pulses_per_mm: float) -> str:
        value = status.get(key)
        if value is None:
            return "------"
        try:
            pulses = int(value)
        except (TypeError, ValueError):
            return "------"
        return f"{pulses:>7d}p/{pulses / pulses_per_mm:>7.2f}mm"

    @staticmethod
    def _field(value: Optional[float]) -> str:
        return "------" if value is None else f"{value:>9.2f}"

    def update(self, stage: str, status: Optional[dict],
               frame: Optional[SensorFrame],
               baseline: Optional[tuple[float, float, float]] = None,
               force: bool = False) -> None:
        if self.closed:
            return
        self.set_stage(stage)
        now = time.monotonic()
        if not force and now - self.last_print < self.interval_s:
            return
        status = status or {}
        if frame is None:
            bx = by = bz = None
            dbx = dby = dbz = None
        else:
            bx, by, bz = frame.bx, frame.by, frame.bz
            if baseline is None:
                dbx = dby = dbz = None
            else:
                dbx = bx - baseline[0]
                dby = by - baseline[1]
                dbz = bz - baseline[2]
        busy = status.get("busy", "-")
        line = (
            f"阶段={stage:<12} "
            f"X={self._position(status, 'x', self.pulses_per_mm)} "
            f"Z={self._position(status, 'z', self.pulses_per_mm)} "
            f"Bx={self._field(bx)} dBx={self._field(dbx)} uT "
            f"By={self._field(by)} dBy={self._field(dby)} uT "
            f"Bz={self._field(bz)} dBz={self._field(dbz)} uT busy={busy}"
        )
        padding = max(0, self.last_width - len(line))
        print("\r" + line + (" " * padding), end="", flush=True)
        self.last_width = len(line)
        self.last_print = now

    def close(self) -> None:
        if not self.closed:
            if self.last_width:
                print()
            self.closed = True


class SensorReader:
    """Read only the FYP raw four-column sensor protocol."""

    def __init__(self, port: str, baudrate: int):
        self.port = port
        self.baudrate = baudrate
        self.ser = open_serial(port, baudrate, timeout=0.0)
        self._buffer = bytearray()
        self.bytes_received = 0
        self.lines_seen = 0
        self.bad_lines = 0
        self._last_raw_t: Optional[int] = None
        self._device_offset = 0
        self._device_segment = 0

    def discard_pending(self) -> None:
        """Drop bytes already waiting before baseline or recording starts."""
        self._buffer.clear()
        try:
            self.ser.reset_input_buffer()
        except (OSError, SerialException):
            pass

    def _parse_line(self, raw: bytes, host_rx_ns: int) -> Optional[SensorFrame]:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line or line.startswith("#") or line.upper() == "READY":
            return None
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4 or parts[0].lower() == "t_us":
            self.bad_lines += 1
            return None
        try:
            sensor_t_us = int(float(parts[0]))
            bx, by, bz = (float(parts[1]), float(parts[2]), float(parts[3]))
        except (TypeError, ValueError, OverflowError):
            self.bad_lines += 1
            return None
        if sensor_t_us < 0 or not all(math.isfinite(v) for v in (bx, by, bz)):
            self.bad_lines += 1
            return None

        if self._last_raw_t is not None and sensor_t_us < self._last_raw_t:
            # micros() is uint32 on the ESP32.  A small backwards jump is a
            # reset; a large one is treated as a normal uint32 wrap.
            if self._last_raw_t - sensor_t_us > 2 ** 31:
                self._device_offset += 2 ** 32
            else:
                self._device_segment += 1
                self._device_offset = 0
        self._last_raw_t = sensor_t_us
        return SensorFrame(
            sensor_t_us=sensor_t_us,
            device_time_unwrapped_us=sensor_t_us + self._device_offset,
            device_clock_segment=self._device_segment,
            host_rx_ns=host_rx_ns,
            bx=bx,
            by=by,
            bz=bz,
        )

    def read_available(self) -> list[SensorFrame]:
        waiting = int(self.ser.in_waiting)
        if waiting <= 0:
            return []
        data = self.ser.read(min(waiting, 65536))
        self.bytes_received += len(data)
        self._buffer.extend(data)
        frames: list[SensorFrame] = []
        host_rx_ns = time.monotonic_ns()
        while b"\n" in self._buffer:
            raw, rest = self._buffer.split(b"\n", 1)
            self._buffer = bytearray(rest)
            self.lines_seen += 1
            frame = self._parse_line(raw.rstrip(b"\r"), host_rx_ns)
            if frame is not None:
                frames.append(frame)
        return frames

    def close(self) -> None:
        try:
            self.ser.close()
        except (OSError, SerialException):
            pass


class MotorProtocolError(RuntimeError):
    pass


class MotorController:
    """Small synchronous XZ1 client with the required heartbeat."""

    def __init__(self, port: str, baudrate: int):
        self.port = port
        self.baudrate = baudrate
        self.ser = open_serial(port, baudrate, timeout=0.0)
        self._buffer = bytearray()
        self.last_status: Optional[dict] = None
        self.hello_info: Optional[dict] = None
        self.last_ping = 0.0
        self.bad_lines = 0

    def _write(self, line: str) -> None:
        self.ser.write((line + "\n").encode("ascii"))

    def heartbeat(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last_ping >= 0.25:
            self._write("PING")
            self.last_ping = now

    def poll(self) -> list[dict]:
        waiting = int(self.ser.in_waiting)
        if waiting <= 0:
            return []
        self._buffer.extend(self.ser.read(min(waiting, 65536)))
        events: list[dict] = []
        while b"\n" in self._buffer:
            raw, rest = self._buffer.split(b"\n", 1)
            self._buffer = bytearray(rest)
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                self.bad_lines += 1
                continue
            if not isinstance(item, dict):
                self.bad_lines += 1
                continue
            if item.get("type") == "status":
                self.last_status = item
            events.append(item)
        return events

    @staticmethod
    def _first_command(command: str) -> str:
        return command.split()[0]

    def hello(self, timeout: float = 3.0) -> dict:
        self.poll()
        self._write("HELLO")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.heartbeat()
            for event in self.poll():
                if event.get("type") == "error":
                    raise MotorProtocolError(
                        f"电机 HELLO 失败: {event.get('code', event)}")
                if event.get("type") == "hello":
                    if event.get("protocol") != PROTOCOL:
                        raise MotorProtocolError("电机协议不是 XZ1")
                    self.hello_info = event
                    return event
            time.sleep(0.005)
        raise MotorProtocolError("等待电机 HELLO 超时；请确认固件和串口")

    def command(self, command: str, timeout: float = 5.0) -> dict:
        expected = self._first_command(command)
        self.heartbeat(force=True)
        self._write(command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.heartbeat()
            for event in self.poll():
                if event.get("type") == "error":
                    raise MotorProtocolError(
                        f"电机命令 {command!r} 被拒绝: {event.get('code', event)}")
                if event.get("type") == "ack" and event.get("cmd") == expected:
                    return self.last_status or {}
            time.sleep(0.005)
        raise MotorProtocolError(f"等待电机命令确认超时: {command}")

    def request_status(self, timeout: float = 2.0) -> dict:
        self._write("STATUS")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.heartbeat()
            events = self.poll()
            for event in events:
                if event.get("type") == "error":
                    raise MotorProtocolError(
                        f"STATUS 失败: {event.get('code', event)}")
                if event.get("type") == "status":
                    return event
            time.sleep(0.005)
        if self.last_status is not None:
            return self.last_status
        raise MotorProtocolError("等待电机 STATUS 超时")

    def move_relative(self, dx: int, dz: int, order: str,
                      speed_x: int, speed_z: int, accel_x: int,
                      accel_z: int,
                      service: Callable[[], None],
                      timeout: float) -> dict:
        status = self.last_status or self.request_status()
        try:
            start_x, start_z = int(status["x"]), int(status["z"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MotorProtocolError("电机 STATUS 缺少当前位置") from exc
        expected_x, expected_z = start_x + dx, start_z + dz
        command = (f"MOVE REL {order} {dx} {dz} {speed_x} {speed_z} "
                   f"{accel_x} {accel_z}")
        self.command(command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.heartbeat()
            events = self.poll()
            for event in events:
                if event.get("type") == "error":
                    raise MotorProtocolError(
                        f"运动命令被拒绝: {event.get('code', event)}")
                if event.get("type") == "status" and event.get("fault") != "NONE":
                    raise MotorProtocolError(
                        f"运动中电机故障: {event.get('fault')}")
            service()
            status = self.last_status
            if status:
                if status.get("fault") != "NONE":
                    raise MotorProtocolError(
                        f"运动中电机故障: {status.get('fault')}")
                if (int(status.get("busy", 1)) == 0
                        and int(status.get("x")) == expected_x
                        and int(status.get("z")) == expected_z):
                    return status
            time.sleep(0.003)
        raise MotorProtocolError(
            f"运动超时: 目标位置 ({expected_x}, {expected_z})")

    def stop(self) -> None:
        try:
            self._write("STOP")
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if any(e.get("type") == "ack" and e.get("cmd") == "STOP"
                       for e in self.poll()):
                    break
                time.sleep(0.005)
        except (OSError, SerialException):
            pass

    def disarm(self) -> None:
        try:
            self._write("DISARM")
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                if any(e.get("type") == "ack" and e.get("cmd") == "DISARM"
                       for e in self.poll()):
                    break
                time.sleep(0.005)
        except (OSError, SerialException):
            pass

    def close(self) -> None:
        try:
            self.ser.close()
        except (OSError, SerialException):
            pass


class AcquisitionSession:
    def __init__(self, motor: MotorController, sensor: SensorReader,
                 run_dir: Path, sensor_timeout: float,
                 display: Optional[LiveDisplay] = None):
        self.motor = motor
        self.sensor = sensor
        self.run_dir = run_dir
        self.sensor_timeout = sensor_timeout
        self.display = display
        self.stage = "idle"
        self.recording = False
        self.record_start_ns: Optional[int] = None
        self.last_record_sample_monotonic: Optional[float] = None
        self.latest_frame: Optional[SensorFrame] = None
        self.records: list[RecordedFrame] = []
        self.baseline_frames: list[SensorFrame] = []
        self.baseline: Optional[tuple[float, float, float]] = None
        self.baseline_sigma: Optional[tuple[float, float, float]] = None
        self.baseline_invalid_count = 0
        self.events_path = run_dir / "events.jsonl"
        self.events = self.events_path.open("w", encoding="utf-8")

    def event(self, name: str, **payload) -> None:
        row = dict(event=name, utc=utc_now(), stage=self.stage, **payload)
        self.events.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.events.flush()

    def handle_motor_events(self, events: list[dict]) -> None:
        for event in events:
            if event.get("type") == "error":
                raise MotorProtocolError(
                    f"电机返回错误: {event.get('code', event)}")
            if event.get("type") == "status" and event.get("fault") != "NONE":
                raise MotorProtocolError(
                    f"电机故障: {event.get('fault')}")

    def pump_sensor(self, record: bool) -> int:
        frames = self.sensor.read_available()
        if not frames:
            if self.display:
                self.display.update(self.stage, self.motor.last_status,
                                    self.latest_frame, self.baseline)
            return 0
        now = time.monotonic()
        self.latest_frame = frames[-1]
        if record and self.recording and self.record_start_ns is not None:
            status = dict(self.motor.last_status or {})
            for frame in frames:
                self.records.append(RecordedFrame(
                    frame=frame,
                    stage=self.stage,
                    host_elapsed_s=(frame.host_rx_ns - self.record_start_ns) / 1e9,
                    motor_status=status,
                ))
            self.last_record_sample_monotonic = now
        if self.display:
            self.display.update(self.stage, self.motor.last_status,
                                self.latest_frame, self.baseline)
        return len(frames)

    def require_sensor_alive(self) -> None:
        if not self.recording:
            return
        if (self.last_record_sample_monotonic is None
                or time.monotonic() - self.last_record_sample_monotonic > self.sensor_timeout):
            raise RuntimeError(
                f"磁传感器超过 {self.sensor_timeout:g} 秒没有有效样本")

    def collect_baseline(self, seconds: float, min_samples: int = 20) -> None:
        self.stage = "baseline"
        self.event("baseline_start", duration_s=seconds)
        start = time.monotonic()
        last_frame = start
        self.baseline_frames.clear()
        while time.monotonic() - start < seconds:
            self.motor.heartbeat()
            self.handle_motor_events(self.motor.poll())
            frames = self.sensor.read_available()
            if frames:
                self.baseline_frames.extend(frames)
                self.latest_frame = frames[-1]
                last_frame = time.monotonic()
            elif time.monotonic() - last_frame > self.sensor_timeout:
                raise RuntimeError("基线阶段没有收到有效磁场数据")
            if self.display:
                self.display.update(self.stage, self.motor.last_status,
                                    self.latest_frame, self.baseline)
            time.sleep(0.002)

        if len(self.baseline_frames) < min_samples:
            raise RuntimeError(
                f"基线有效样本不足: {len(self.baseline_frames)} < {min_samples}")
        values = [(f.bx, f.by, f.bz) for f in self.baseline_frames]
        valid, _ = quality_mask(values)
        good = [row for row, ok in zip(values, valid) if ok]
        self.baseline_invalid_count = len(values) - len(good)
        if len(good) < min_samples:
            raise RuntimeError(
                f"剔除基线异常帧后样本不足: {len(good)} < {min_samples}")
        self.baseline = tuple(mean(row[i] for row in good) for i in range(3))
        self.baseline_sigma = tuple(
            population_std(row[i] for row in good) for i in range(3))
        self.event("baseline_complete", samples=len(values),
                   valid_samples=len(good), baseline_uT=self.baseline,
                   sigma_uT=self.baseline_sigma,
                   invalid_samples=self.baseline_invalid_count)
        print(
            "\n基线完成："
            f" Bx0={self.baseline[0]:.3f} uT"
            f" By0={self.baseline[1]:.3f} uT"
            f" Bz0={self.baseline[2]:.3f} uT"
        )

    def start_recording(self) -> None:
        if self.baseline is None:
            raise RuntimeError("没有有效基线，不能开始实验")
        self.sensor.discard_pending()
        self.records.clear()
        self.record_start_ns = time.monotonic_ns()
        self.last_record_sample_monotonic = None
        self.recording = True
        self.stage = "ready"
        if self.display:
            self.display.update(self.stage, self.motor.last_status,
                                self.latest_frame, self.baseline, force=True)
        self.event("recording_start")

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        if self.display:
            self.display.update(self.stage, self.motor.last_status,
                                self.latest_frame, self.baseline, force=True)
        self.event("stage_start", stage_name=stage)

    def service_motion(self) -> None:
        self.handle_motor_events(self.motor.poll())
        self.pump_sensor(record=True)
        self.require_sensor_alive()

    def stop_recording(self) -> None:
        self.pump_sensor(record=True)
        self.recording = False
        if self.display:
            self.display.update(self.stage, self.motor.last_status,
                                self.latest_frame, self.baseline, force=True)
        self.event("recording_stop", samples=len(self.records))

    def _status_value(self, status: dict, key: str):
        value = status.get(key)
        return "" if value is None else value

    def write_outputs(self, outcome: str, error: Optional[str], metadata: dict) -> None:
        values = [(r.frame.bx, r.frame.by, r.frame.bz) for r in self.records]
        valid, reasons = quality_mask(values)
        baseline = self.baseline or (0.0, 0.0, 0.0)
        first_device_us = (self.records[0].frame.device_time_unwrapped_us
                           if self.records else None)
        csv_path = self.run_dir / "sensor.csv"
        header = [
            "seq", "sensor_t_us", "device_time_unwrapped_us",
            "device_clock_segment", "sensor_t_s", "host_rx_ns", "host_elapsed_s",
            "stage", "motor_x_pulses", "motor_z_pulses",
            "motor_target_x_pulses", "motor_target_z_pulses", "motor_busy",
            "motor_phase", "motor_fault", "Bx_uT", "By_uT", "Bz_uT",
            "dBx_uT", "dBy_uT", "dBz_uT", "sample_valid", "invalid_reason",
        ]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for index, record in enumerate(self.records):
                frame = record.frame
                status = record.motor_status
                sensor_t_s = ("" if first_device_us is None else
                              f"{(frame.device_time_unwrapped_us - first_device_us) / 1e6:.6f}")
                d = (frame.bx - baseline[0], frame.by - baseline[1],
                     frame.bz - baseline[2])
                writer.writerow([
                    index + 1,
                    frame.sensor_t_us,
                    frame.device_time_unwrapped_us,
                    frame.device_clock_segment,
                    sensor_t_s,
                    frame.host_rx_ns,
                    f"{record.host_elapsed_s:.6f}",
                    record.stage,
                    self._status_value(status, "x"),
                    self._status_value(status, "z"),
                    self._status_value(status, "tx"),
                    self._status_value(status, "tz"),
                    self._status_value(status, "busy"),
                    self._status_value(status, "phase"),
                    self._status_value(status, "fault"),
                    f"{frame.bx:.6f}", f"{frame.by:.6f}", f"{frame.bz:.6f}",
                    f"{d[0]:.6f}", f"{d[1]:.6f}", f"{d[2]:.6f}",
                    int(valid[index]), reasons[index],
                ])

        metadata.update({
            "outcome": outcome,
            "error": error,
            "sample_count": len(self.records),
            "invalid_sample_count": sum(not value for value in valid),
            "sensor_bad_lines": self.sensor.bad_lines,
            "sensor_lines_seen": self.sensor.lines_seen,
            "sensor_bytes_received": self.sensor.bytes_received,
            "baseline_B0_uT": dict(zip(("Bx_uT", "By_uT", "Bz_uT"), baseline)),
            "delta_definition": {
                "dBx_uT": "Bx_uT - baseline_B0_uT.Bx_uT",
                "dBy_uT": "By_uT - baseline_B0_uT.By_uT",
                "dBz_uT": "Bz_uT - baseline_B0_uT.Bz_uT",
            },
            "baseline_sigma_uT": (None if self.baseline_sigma is None else
                                   dict(zip(("Bx_uT", "By_uT", "Bz_uT"),
                                            self.baseline_sigma))),
            "baseline_sample_count": len(self.baseline_frames),
            "baseline_invalid_sample_count": self.baseline_invalid_count,
            "sample_quality": {
                "column": "sample_valid",
                "rule": "finite and not isolated >1000uT spike returning within 250uT",
                "raw_values_preserved": True,
            },
            "files": {"sensor": csv_path.name, "events": self.events_path.name},
        })
        (self.run_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self) -> None:
        if self.display:
            self.display.close()
        try:
            self.events.close()
        except OSError:
            pass


def pulses_for_distance(distance_mm: float, pulses_per_rev: int,
                        mm_per_rev: float) -> int:
    if not math.isfinite(distance_mm) or distance_mm < 0:
        raise ValueError("距离必须是非负有限数")
    if pulses_per_rev <= 0 or not math.isfinite(mm_per_rev) or mm_per_rev <= 0:
        raise ValueError("脉冲/转和毫米/转必须为正数")
    pulses = distance_mm * pulses_per_rev / mm_per_rev
    rounded = int(round(pulses))
    if not math.isclose(pulses, rounded, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"距离换算后不是整数脉冲: {pulses}")
    return rounded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Windows X/Z 脉冲运动 + FYP 风格 Bx/By/Bz 采集（无 GUI）")
    parser.add_argument("--motor-port", default=None,
                        help="电机控制器串口，例如 COM5；省略时启动交互式选择")
    parser.add_argument("--sensor-port", default=None,
                        help="磁传感器串口，例如 COM6；省略时启动交互式选择")
    parser.add_argument("--output", default=None,
                        help="输出目录；默认 data/experiments_windows/<时间戳>")
    parser.add_argument("--motor-baud", type=int, default=DEFAULT_MOTOR_BAUD)
    parser.add_argument("--sensor-baud", type=int, default=DEFAULT_SENSOR_BAUD)
    parser.add_argument("--pulses-per-rev", type=int, default=DEFAULT_PULSES_PER_REV)
    parser.add_argument("--mm-per-rev", type=float, default=DEFAULT_MM_PER_REV)
    parser.add_argument("--x-mm", type=float, default=DEFAULT_X_MM)
    parser.add_argument("--z-mm", type=float, default=DEFAULT_Z_MM,
                        help="Z 上升距离，默认 20 mm")
    parser.add_argument("--x-sign", type=int, choices=(-1, 1), default=1,
                        help="X 方向符号，默认 +1")
    parser.add_argument("--z-up-sign", type=int, choices=(-1, 1), default=-1,
                        help="Z 上升方向符号；当前固件默认 -1")
    parser.add_argument("--x-speed-pps", type=int, default=DEFAULT_SPEED_PPS)
    parser.add_argument("--z-speed-pps", type=int, default=DEFAULT_SPEED_PPS)
    parser.add_argument("--x-accel-pps2", type=int, default=DEFAULT_ACCEL_PPS2)
    parser.add_argument("--z-accel-pps2", type=int, default=DEFAULT_ACCEL_PPS2)
    parser.add_argument("--baseline-seconds", type=float,
                        default=DEFAULT_BASELINE_SECONDS)
    parser.add_argument("--sensor-timeout", type=float,
                        default=DEFAULT_SENSOR_TIMEOUT)
    parser.add_argument("--motion-timeout", type=float,
                        default=DEFAULT_MOTION_TIMEOUT)
    parser.add_argument("--leave-z-up", action="store_true",
                        help="X 返回后不执行最后的 Z 回零；默认回到初始 (0,0)")
    parser.add_argument("--no-confirm", action="store_true",
                        help="跳过距离输入和 Enter 确认，适合批处理")
    return parser


def run(args: argparse.Namespace) -> Path:
    if args.baseline_seconds <= 0 or args.sensor_timeout <= 0 or args.motion_timeout <= 0:
        raise ValueError("时间参数必须为正数")
    for value, name in ((args.x_speed_pps, "X速度"), (args.z_speed_pps, "Z速度"),
                        (args.x_accel_pps2, "X加速度"), (args.z_accel_pps2, "Z加速度")):
        if value <= 0:
            raise ValueError(f"{name}必须为正整数")
    x_pulses = pulses_for_distance(args.x_mm, args.pulses_per_rev, args.mm_per_rev)
    z_pulses = pulses_for_distance(args.z_mm, args.pulses_per_rev, args.mm_per_rev)
    dx = args.x_sign * x_pulses
    dz_up = args.z_up_sign * z_pulses

    if args.output:
        run_dir = Path(args.output).expanduser().resolve()
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_dir = Path(__file__).resolve().parent / "data" / "experiments_windows" / stamp
    run_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "schema_version": 1,
        "created_at": utc_now(),
        "ports": {"motor": args.motor_port, "sensor": args.sensor_port},
        "units": {"distance": "mm", "motion": "pulses", "magnetic": "uT"},
        "conversion": {
            "pulses_per_revolution": args.pulses_per_rev,
            "millimeters_per_revolution": args.mm_per_rev,
            "pulses_per_mm": args.pulses_per_rev / args.mm_per_rev,
        },
        "motion": {
            "x_distance_mm": args.x_mm,
            "z_rise_mm": args.z_mm,
            "x_pulses": x_pulses,
            "z_pulses": z_pulses,
            "x_sign": args.x_sign,
            "z_up_sign": args.z_up_sign,
            "speed_pps": {"x": args.x_speed_pps, "z": args.z_speed_pps},
            "acceleration_pps2": {"x": args.x_accel_pps2, "z": args.z_accel_pps2},
            "sequence": [
                "ZERO ALL",
                "baseline",
                "X forward",
                "Z upward",
                "X return",
                "Z return to zero" if not args.leave_z_up else "leave Z upward",
            ],
            "zero_is_software_position": True,
        },
        "sensor_protocol": "t_us,Bx_uT,By_uT,Bz_uT; raw B, dB=B-B0",
        "notes": [
            "电机位置是固件发脉冲的软件计数，不是编码器读数。",
            "脚本不提供硬件急停、限位或自动 HOME；正式运行前必须确认机械安全。",
        ],
    }

    motor: Optional[MotorController] = None
    sensor: Optional[SensorReader] = None
    session: Optional[AcquisitionSession] = None
    outcome = "aborted"
    failure: Optional[str] = None
    final_status: Optional[dict] = None
    try:
        motor = MotorController(args.motor_port, args.motor_baud)
        sensor = SensorReader(args.sensor_port, args.sensor_baud)
        display = LiveDisplay(args.pulses_per_rev / args.mm_per_rev)
        session = AcquisitionSession(motor, sensor, run_dir, args.sensor_timeout,
                                     display=display)
        session.event("run_start", x_pulses=dx, z_up_pulses=dz_up)

        hello = motor.hello()
        metadata["motor_hello"] = hello
        status = motor.last_status or motor.request_status()
        if status.get("fault") != "NONE":
            session.event("clear_fault", previous_fault=status.get("fault"))
            motor.command("CLEAR")

        # ZERO ALL only changes the controller's software coordinates; it does
        # not move either axis.  This is the requested starting zero.
        motor.command("ZERO ALL")
        status = motor.request_status()
        if int(status.get("x", 999)) != 0 or int(status.get("z", 999)) != 0:
            raise MotorProtocolError("ZERO ALL 后控制器位置不是 (0,0)")
        metadata["zero_status"] = status
        session.event("zero_set", x=0, z=0)

        # Match the FYP monitor boundary: discard bytes accumulated before the
        # baseline window so an old serial backlog cannot seed B0.
        sensor.discard_pending()
        session.collect_baseline(args.baseline_seconds)
        sensor.discard_pending()
        motor.heartbeat(force=True)
        motor.command("ARM")
        session.start_recording()

        stages = [
            ("x_forward", dx, 0, "XZ"),
            ("z_up", 0, dz_up, "ZX"),
            ("x_return", -dx, 0, "XZ"),
        ]
        if not args.leave_z_up:
            stages.append(("z_return", 0, -dz_up, "ZX"))

        for stage, move_x, move_z, order in stages:
            session.set_stage(stage)
            session.event("move_request", dx=move_x, dz=move_z, order=order)
            result = motor.move_relative(
                move_x, move_z, order,
                args.x_speed_pps, args.z_speed_pps,
                args.x_accel_pps2, args.z_accel_pps2,
                service=session.service_motion,
                timeout=args.motion_timeout,
            )
            session.event("move_complete", status=result)

        session.stop_recording()
        final_status = motor.request_status()
        if not args.leave_z_up and (int(final_status.get("x", 999)) != 0
                                    or int(final_status.get("z", 999)) != 0):
            raise MotorProtocolError(
                f"回零后位置不正确: x={final_status.get('x')} z={final_status.get('z')}")
        outcome = "completed"
        session.event("run_complete", status=final_status)
    except KeyboardInterrupt:
        failure = "用户中断"
        if session:
            session.event("user_interrupt")
    except Exception as exc:  # report the error in metadata, then shut down safely.
        failure = str(exc)
        if session:
            session.event("run_error", error=failure)
    finally:
        if motor is not None:
            if outcome != "completed":
                motor.stop()
            motor.disarm()
            if final_status is None:
                final_status = motor.last_status
        try:
            if session is not None:
                metadata["final_motor_status"] = final_status
                session.write_outputs(outcome, failure, metadata)
        finally:
            if session is not None:
                session.close()
            if sensor is not None:
                sensor.close()
            if motor is not None:
                motor.close()

    if outcome != "completed":
        raise RuntimeError(f"采集未完成，结果已保存到 {run_dir}: {failure}")
    return run_dir


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.motor_port, args.sensor_port = resolve_ports(args)
        prepare_interactive(args)
        run_dir = run(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"完成，数据已保存到: {run_dir}")
    print(f"  sensor.csv: {run_dir / 'sensor.csv'}")
    print(f"  metadata.json: {run_dir / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
