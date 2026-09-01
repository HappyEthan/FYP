#!/usr/bin/env python3
"""MLX90393 XY 轴向增益标定。

保持触角弯曲幅度近似不变并转一整圈，估计原始椭圆的 X/Y 半径，计算
只修正 X 轴所需的系数 kx = Ry / Rx。脚本只读取串口，不向板子写命令。

固件串口格式：t_us,Bx,By,Bz（默认 115200 baud）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np


def available_ports() -> list[str]:
    """返回当前系统枚举到的串口设备。"""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [p.device for p in list_ports.comports()]


def parse_line(raw: bytes):
    """解析固件的一行；表头、空行和坏行返回 None。"""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split(",")
    if len(parts) != 4:
        return None
    try:
        return tuple(float(x) for x in parts)
    except ValueError:
        return None


def collect(ser, seconds: float, label: str) -> tuple[np.ndarray, int]:
    """在指定时间内采集 (t_us, Bx, By, Bz)。"""
    rows = []
    bad = 0
    deadline = time.monotonic() + seconds
    last_report = -1
    while time.monotonic() < deadline:
        raw = ser.readline()
        if raw:
            row = parse_line(raw)
            if row is None:
                if raw.strip() and not raw.lstrip().startswith(b"#"):
                    bad += 1
            else:
                rows.append(row)
        remain = max(0, int(np.ceil(deadline - time.monotonic())))
        if remain != last_report:
            print(f"\r{label}: 剩余 {remain:2d} s，已收 {len(rows):5d} 点", end="", flush=True)
            last_report = remain
    print()
    return np.asarray(rows, dtype=float).reshape(-1, 4), bad


def estimate_x_gain(dxy: np.ndarray, percentile: float = 99.0) -> dict:
    """由已去基线的圆周样本估计轴向半径与 X 增益。

    使用绝对值分位数而非单个最大值，避免一个串口毛刺决定标定结果。
    起止时靠近圆心的少量过渡样本不会影响高分位数；不能按原始半径过滤，
    否则会偏向椭圆长轴并系统性低估短轴。
    """
    xy = np.asarray(dxy, dtype=float).reshape(-1, 2)
    xy = xy[np.all(np.isfinite(xy), axis=1)]
    if len(xy) < 50:
        raise ValueError("有效圆周样本不足 50 点")

    rx = float(np.percentile(np.abs(xy[:, 0]), percentile))
    ry = float(np.percentile(np.abs(xy[:, 1]), percentile))
    if rx <= 1e-9 or ry <= 1e-9:
        raise ValueError("X 或 Y 方向变化太小；请确保完整转过一圈")

    kx = ry / rx
    before_ratio = max(rx, ry) / min(rx, ry)
    rx_after = kx * rx
    after_ratio = max(rx_after, ry) / min(rx_after, ry)
    return {
        "method": "axis_aligned_percentile",
        "percentile": percentile,
        "samples_used": int(len(xy)),
        "Rx_uT": rx,
        "Ry_uT": ry,
        "x_gain": kx,
        "y_gain": 1.0,
        "axis_ratio_before": before_ratio,
        "axis_ratio_after": after_ratio,
    }


def save_results(out_dir: Path, baseline: np.ndarray, circle: np.ndarray,
                 result: dict, port: str, baud: int, bad_lines: int) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = out_dir / f"xy_circle_{stamp}"
    csv_path = stem.with_suffix(".csv")
    json_path = stem.with_suffix(".json")

    b0 = baseline[:, 1:4].mean(axis=0)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t_us", "Bx_uT", "By_uT", "Bz_uT",
                         "dBx_uT", "dBy_uT", "dBz_uT"])
        for row in circle:
            d = row[1:4] - b0
            writer.writerow([*row, *d])

    payload = {
        "format_version": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "port": port,
        "baud": baud,
        "baseline_samples": int(len(baseline)),
        "circle_samples": int(len(circle)),
        "bad_lines": int(bad_lines),
        "baseline_B0_uT": {"Bx": float(b0[0]), "By": float(b0[1]), "Bz": float(b0[2])},
        "calibration": result,
        "application": {
            "formula": "dBx_corrected = x_gain * (Bx - B0x)",
            "dBy_formula": "dBy_corrected = By - B0y",
        },
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return csv_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="MLX90393 XY 圆周标定：估计 X 轴增益")
    parser.add_argument("--port", help="串口，例如 /dev/ttyACM0；不填时自动检测唯一串口")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--baseline-seconds", type=float, default=3.0)
    parser.add_argument("--circle-seconds", type=float, default=12.0)
    parser.add_argument("--percentile", type=float, default=99.0)
    parser.add_argument("--out-dir", type=Path, default=Path("calibration/xy"))
    args = parser.parse_args()

    try:
        import serial
    except ImportError:
        print('缺少 pyserial，请先运行: pip install -e ".[monitor]"', file=sys.stderr)
        return 2

    ports = available_ports()
    port = args.port
    if port is None:
        if len(ports) == 1:
            port = ports[0]
        elif not ports:
            print("未检测到串口。请检查 USB 数据线和板子，然后运行：", file=sys.stderr)
            print("  python -m serial.tools.list_ports -v", file=sys.stderr)
            print("检测到设备后用 --port /dev/ttyACM0（或实际路径）重试。", file=sys.stderr)
            return 2
        else:
            print("检测到多个串口，请用 --port 指定：", *ports, sep="\n  ", file=sys.stderr)
            return 2

    print(f"打开 {port} @ {args.baud}（脚本只读，不向板子发送数据）")
    try:
        ser = serial.Serial(port, args.baud, timeout=0.1)
    except (OSError, serial.SerialException) as exc:
        print(f"无法打开串口: {exc}", file=sys.stderr)
        print("若提示 Permission denied，请把当前用户加入 dialout 组并重新登录。", file=sys.stderr)
        return 2

    try:
        time.sleep(1.5)  # 部分开发板开串口后会复位
        ser.reset_input_buffer()
        input("\n让触角完全松开并保持静止，然后按 Enter 开始取基线……")
        baseline, bad0 = collect(ser, args.baseline_seconds, "基线采集")
        if len(baseline) < 30:
            raise RuntimeError(f"基线只收到 {len(baseline)} 点，请检查固件输出格式和波特率")
        b0 = baseline[:, 1:4].mean(axis=0)
        sigma = baseline[:, 1:4].std(axis=0)
        print("B0 = (%.2f, %.2f, %.2f) µT；噪声 σ = (%.2f, %.2f, %.2f) µT" % (*b0, *sigma))

        input("\n按 Enter 后开始转圈：保持弯曲幅度不变，缓慢、完整地转至少 2 圈……")
        print("现在开始转圈。")
        circle, bad1 = collect(ser, args.circle_seconds, "圆周采集")
        if len(circle) < 50:
            raise RuntimeError(f"圆周只收到 {len(circle)} 点")

        dxy = circle[:, 1:3] - b0[:2]
        result = estimate_x_gain(dxy, args.percentile)
        csv_path, json_path = save_results(
            args.out_dir, baseline, circle, result, port, args.baud, bad0 + bad1)
    except (EOFError, KeyboardInterrupt):
        print("\n标定已取消。")
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"标定失败: {exc}", file=sys.stderr)
        return 1
    finally:
        ser.close()

    print("\n标定完成")
    print("  Rx = %.2f µT" % result["Rx_uT"])
    print("  Ry = %.2f µT" % result["Ry_uT"])
    print("  X 轴系数 kx = Ry/Rx = %.6f" % result["x_gain"])
    print("  应用公式: dBx_corrected = %.6f * (Bx - B0x)" % result["x_gain"])
    print("  原始长短轴比: %.3f；轴向修正后: %.3f" %
          (result["axis_ratio_before"], result["axis_ratio_after"]))
    print(f"  原始记录: {csv_path}")
    print(f"  标定结果: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
