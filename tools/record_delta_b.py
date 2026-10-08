#!/usr/bin/env python3
"""Record unsmoothed MLX90393 Delta B CSV output from the XIAO ESP32-C3."""

from __future__ import annotations

import argparse
import csv
import json
import re
import select
import sys
import time
from datetime import datetime
from pathlib import Path

import serial


HEADER = "t_us,dBx,dBy,dBz"
DATA_RE = re.compile(
    r"^(?P<t_us>\d+),"
    r"(?P<dx>[+-]?(?:\d+(?:\.\d*)?|\.\d+)),"
    r"(?P<dy>[+-]?(?:\d+(?:\.\d*)?|\.\d+)),"
    r"(?P<dz>[+-]?(?:\d+(?:\.\d*)?|\.\d+))$"
)
B0_RE = re.compile(
    r"^# B0 "
    r"(?P<bx>[+-]?(?:\d+(?:\.\d*)?|\.\d+)),"
    r"(?P<by>[+-]?(?:\d+(?:\.\d*)?|\.\d+)),"
    r"(?P<bz>[+-]?(?:\d+(?:\.\d*)?|\.\d+))$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record real, unsmoothed t_us,dBx,dBy,dBz samples."
    )
    parser.add_argument("--port", required=True, help="例如 /dev/cu.usbmodem101")
    parser.add_argument("--action", required=True, help="例如 circle_cw 或 line_lr")
    parser.add_argument("--rep", type=int, required=True, help="重复编号，从 1 开始")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--lead-in", type=float, default=3.0)
    parser.add_argument("--tail", type=float, default=3.0)
    parser.add_argument(
        "--manual-markers",
        action="store_true",
        help="从标准输入接收 s/e，手动标记动作开始和结束",
    )
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--note", default="")
    parser.add_argument("--header-timeout", type=float, default=20.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/sensor/delta_b"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.rep < 1:
        raise SystemExit("--rep 必须从 1 开始")
    if args.seconds <= 0:
        raise SystemExit("--seconds 必须大于 0")
    if args.lead_in < 0 or args.tail < 0:
        raise SystemExit("--lead-in 和 --tail 不能小于 0")
    if not args.manual_markers and args.lead_in + args.tail >= args.seconds:
        raise SystemExit("--lead-in 与 --tail 之和必须小于 --seconds")
    if args.header_timeout <= 0:
        raise SystemExit("--header-timeout 必须大于 0")
    if re.fullmatch(r"[A-Za-z0-9_-]+", args.action) is None:
        raise SystemExit("--action 只能包含英文字母、数字、下划线和连字符")

    created_at = datetime.now().astimezone()
    stamp = created_at.strftime("%Y%m%d_%H%M%S")
    stem = f"{stamp}_{args.action}_r{args.rep:02d}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / f"{stem}.csv"
    json_path = args.output_dir / f"{stem}.json"

    print(
        "正在打开串口。打开后请按一下板子的 Reset，"
        "再保持传感器未按压、静止约 2.5 秒。"
    )
    baseline = None
    rows = []
    first_t_us = None
    header_seen = False
    action_started = False
    action_ended = False
    action_start_t_us = None
    action_end_t_us = None

    port = serial.Serial(args.port, args.baud, timeout=1.0)
    try:
        port.reset_input_buffer()
        opened_wall = time.monotonic()
        while True:
            if args.manual_markers and header_seen:
                readable, _, _ = select.select([sys.stdin], [], [], 0)
                if readable:
                    command = sys.stdin.readline().strip().lower()
                    if command == "s" and not action_started:
                        if not rows:
                            print("尚未收到数据，请稍后再发送 s。", flush=True)
                        else:
                            action_started = True
                            action_start_t_us = rows[-1][0]
                            print(f">>> START {args.action}", flush=True)
                    elif (
                        command == "e"
                        and action_started
                        and not action_ended
                    ):
                        action_ended = True
                        action_end_t_us = rows[-1][0]
                        print(
                            f">>> STOP {args.action}; "
                            f"继续静止记录 {args.tail:g} 秒",
                            flush=True,
                        )

            try:
                raw_line = port.readline()
            except serial.SerialException as exc:
                if header_seen:
                    raise SystemExit(
                        f"录制中串口断开，已放弃本次不完整记录：{exc}"
                    ) from exc

                print("检测到开发板复位，正在等待 USB 串口重新连接……")
                try:
                    port.close()
                except serial.SerialException:
                    pass

                while True:
                    if time.monotonic() - opened_wall >= args.header_timeout:
                        raise SystemExit(
                            "Reset 后串口重连超时；请重新插拔 USB 后再试。"
                        )
                    try:
                        port = serial.Serial(args.port, args.baud, timeout=1.0)
                        print("串口已重新连接，继续等待 B0 和 Delta B 表头。")
                        break
                    except serial.SerialException:
                        time.sleep(0.2)
                continue

            text = raw_line.decode("ascii", errors="replace").strip()
            if (
                not header_seen
                and time.monotonic() - opened_wall >= args.header_timeout
            ):
                raise SystemExit(
                    "等待 Delta B 表头超时。确认 SENSOR_OUTPUT_MODE=2，"
                    "并在运行命令后按一下板子的 Reset。"
                )
            if not text:
                continue

            b0_match = B0_RE.fullmatch(text)
            if b0_match:
                baseline = {
                    "Bx_uT": float(b0_match["bx"]),
                    "By_uT": float(b0_match["by"]),
                    "Bz_uT": float(b0_match["bz"]),
                }
                continue

            if text == HEADER:
                if args.manual_markers:
                    print(
                        "基线完成，手动标记模式已就绪。"
                        "输入 s 标记动作开始，输入 e 标记动作结束。",
                        flush=True,
                    )
                else:
                    print(
                        f"基线完成，开始录制 {args.seconds:g} 秒。"
                        f"前 {args.lead_in:g} 秒保持静止，看到 START 后执行"
                        f"动作 {args.action!r}，看到 STOP 后松开并保持静止。",
                        flush=True,
                    )
                header_seen = True
                continue

            match = DATA_RE.fullmatch(text)
            if not match or not header_seen:
                continue

            t_us = int(match["t_us"])
            if first_t_us is None:
                first_t_us = t_us

            rows.append(
                (
                    t_us,
                    (t_us - first_t_us) / 1_000_000.0,
                    float(match["dx"]),
                    float(match["dy"]),
                    float(match["dz"]),
                )
            )
            elapsed_s = (t_us - first_t_us) / 1_000_000.0
            if args.manual_markers:
                if (
                    action_ended
                    and t_us - action_end_t_us >= args.tail * 1_000_000
                ):
                    break
            else:
                if not action_started and elapsed_s >= args.lead_in:
                    action_started = True
                    action_start_t_us = t_us
                    print(f">>> START {args.action}", flush=True)
                if (
                    not action_ended
                    and elapsed_s >= args.seconds - args.tail
                ):
                    action_ended = True
                    action_end_t_us = t_us
                    print(
                        f">>> STOP {args.action}; 保持静止",
                        flush=True,
                    )
                if elapsed_s >= args.seconds:
                    break
    finally:
        if port.is_open:
            port.close()

    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(("t_us", "t_s", "dBx_uT", "dBy_uT", "dBz_uT"))
        writer.writerows(rows)

    intervals_us = [
        rows[index][0] - rows[index - 1][0] for index in range(1, len(rows))
    ]
    if args.manual_markers:
        action_window = {
            "start": (action_start_t_us - rows[0][0]) / 1_000_000.0,
            "end": (action_end_t_us - rows[0][0]) / 1_000_000.0,
        }
    else:
        action_window = {
            "start": args.lead_in,
            "end": args.seconds - args.tail,
        }

    metadata = {
        "created_at": created_at.isoformat(),
        "action": args.action,
        "repetition": args.rep,
        "valid": True,
        "note": args.note,
        "sensor": "MLX90393",
        "board": "Seeed Studio XIAO ESP32-C3",
        "port": args.port,
        "baud": args.baud,
        "units": {"t_us": "us", "t_s": "s", "dBx_uT": "uT", "dBy_uT": "uT", "dBz_uT": "uT"},
        "delta_definition": "dB = B - B0",
        "baseline_B0_uT": baseline,
        "display_smoothing_applied": False,
        "recording_mode": (
            "manual_markers" if args.manual_markers else "timed_window"
        ),
        "requested_duration_s": (
            None if args.manual_markers else args.seconds
        ),
        "action_window_s": action_window,
        "action_start_t_us": action_start_t_us,
        "action_end_t_us": action_end_t_us,
        "sample_count": len(rows),
        "measured_duration_s": rows[-1][1] if rows else 0.0,
        "mean_sample_rate_hz": (
            1_000_000.0 / (sum(intervals_us) / len(intervals_us))
            if intervals_us
            else None
        ),
        "max_interval_us": max(intervals_us) if intervals_us else None,
        "csv_file": csv_path.name,
    }
    with json_path.open("w", encoding="utf-8") as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2)
        output.write("\n")

    print(f"已保存 {len(rows)} 个样本：{csv_path}")
    print(f"元数据：{json_path}")
    if baseline is None:
        print("警告：未捕获到 B0 行；请检查固件是否为 SENSOR_OUTPUT_MODE=2。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
