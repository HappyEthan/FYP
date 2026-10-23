#!/usr/bin/env python3
"""采集原始串口与磁数据，检查基线条件；不导入机器人执行入口。"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/"src"))
from brushbot.experiments.acquisition import SampleHub
from brushbot.monitor.sources import SerialSource

DEFAULT_SETTINGS = ROOT/"runs/brush2/plans/11_中字底横延长30mm_实测第9次/settings.json"
POLICY_KEYS = ("baseline_min_samples", "baseline_window_s", "baseline_max_std_uT",
               "baseline_max_drift_uT_s", "sensor_max_age_s", "filter")


def summarize_stream(rows, *, started_ns, now_ns, policy):
    valid = [r for r in rows if r.get("valid")]
    times = [int(r["host_rx_ns"]) for r in valid]
    duration = (int(now_ns)-int(started_ns))/1e9
    span = (times[-1]-times[0])/1e9 if len(times)>1 else 0.
    age = (int(now_ns)-times[-1])/1e9 if times else None
    gaps = np.diff([int(started_ns), *times, int(now_ns)])/1e9
    first = max(0, bisect_right(times, times[-1]-round(policy["baseline_window_s"]*1e9))-1) if times else 0
    candidate = valid[first:]
    candidate_span = (times[-1]-times[first])/1e9 if candidate else 0.
    internal_gap = float(np.max(np.diff(times[first:]))/1e9) if len(candidate)>1 else 0.
    error, baseline = "", None
    # This is a diagnostic candidate only. The robot runner still verifies its
    # actual wait pose and takes an independent baseline before any writing.
    probe = SampleHub(None, clock_ns=lambda: int(now_ns))
    try:
        baseline = probe.set_baseline(candidate, dict(policy, airborne_confirmed=True, pose_static=True))
        if age is None or age < 0 or age > policy["sensor_max_age_s"]:
            raise ValueError("stale final sensor sample")
        if internal_gap > policy["sensor_max_age_s"]:
            raise ValueError("sensor stream gap exceeds freshness limit")
    except ValueError as exc:
        error = str(exc)
    return dict(total_samples=len(rows), valid_samples=len(valid), invalid_samples=len(rows)-len(valid),
        observation_duration_s=duration, valid_span_s=span,
        first_valid_delay_s=(times[0]-int(started_ns))/1e9 if times else None,
        last_valid_age_s=age, longest_gap_s=float(gaps.max()) if len(gaps) else duration,
        effective_rate_over_valid_span_hz=(len(valid)-1)/span if span>0 else None,
        candidate_samples=len(candidate), candidate_span_s=candidate_span,
        candidate_max_internal_gap_s=internal_gap, baseline_candidate_ready=not error,
        baseline_error=error, candidate_statistics=baseline,
        required=dict(policy), pose_confirmation="user must keep brush airborne and stationary; no robot pose was measured",
        robot_connected=False)


class RawTap:
    def __init__(self, serial, stream):
        self.serial, self.stream = serial, stream

    def read(self, count):
        chunk = self.serial.read(count)
        if chunk:
            self.stream.write(chunk)
            self.stream.flush()
        return chunk

    def __getattr__(self, name):
        return getattr(self.serial, name)


def current_openers(port):
    matches = []
    proc_root = Path("/proc")
    if not proc_root.exists():
        return matches
    for process in proc_root.iterdir():
        if not process.name.isdecimal() or int(process.name)==os.getpid():
            continue
        try:
            for fd in (process/"fd").iterdir():
                if str(fd.readlink()) == str(port):
                    matches.append(dict(pid=int(process.name), process=(process/"comm").read_text().strip()))
                    break
        except (OSError, PermissionError):
            continue
    return matches


def read_run(path):
    settings = json.loads((path/"settings.json").read_text())
    events = [json.loads(line) for line in (path/"events.jsonl").read_text().splitlines() if line.strip()]
    start = next(e["host_ns"] for e in events if e["event"]=="baseline_started")
    end = next(e["host_ns"] for e in reversed(events) if e["event"] in {"baseline_failed", "baseline_fixed"})
    rows = []
    with (path/"sensor.csv").open() as stream:
        for row in csv.DictReader(stream):
            rows.append(dict(seq=int(row["seq"]), sensor_t_us=int(row["sensor_t_us"]),
                host_rx_ns=int(row["host_rx_ns"]), valid=row["valid"].lower()=="true",
                B_uT=[float(row[k]) for k in ("Bx_uT", "By_uT", "Bz_uT")]))
    return rows, start, end, settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration-s", type=float, default=12.)
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--replay-run", type=Path, help="只分析已有run，不打开串口")
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration_s) or args.duration_s<=0:
        parser.error("duration must be finite and positive")
    if args.replay_run is None:
        opened = current_openers(args.port)
        if opened:
            parser.error("串口已有占用，请关闭对应Monitor/实验后再检查："+json.dumps(opened, ensure_ascii=False))
    stamp = datetime.now(ZoneInfo("Asia/Shanghai"))
    out = args.output_dir or ROOT/"runs/brush2"/stamp.strftime("%Y-%m-%d")/"sensor_checks"/(stamp.strftime("%H-%M-%S")+"_"+uuid.uuid4().hex[:6])
    out.mkdir(parents=True, exist_ok=False)
    print("串口诊断目录:", out)
    failure, rows, source_stats = "", [], {}
    if args.replay_run is not None:
        rows, started, now, settings = read_run(args.replay_run)
    else:
        print("请保持笔离纸、静止。采集原始串口；本入口不控制机械臂。")
        settings = json.loads(args.settings.read_text())
        source = SerialSource(args.port, args.baud)
        started = time.monotonic_ns()
        try:
            with (out/"raw_serial.log").open("xb") as raw:
                source.start()
                source._ser = RawTap(source._ser, raw)
                hub = SampleHub(source, clock_ns=time.monotonic_ns)
                deadline = time.monotonic()+args.duration_s
                while time.monotonic()<deadline:
                    rows.extend(hub.poll_once())
                    time.sleep(.02)
                source_stats = source.diagnostics
        except (Exception, KeyboardInterrupt) as exc:
            failure = f"{type(exc).__name__}: {exc}"
            source_stats = source.diagnostics
        finally:
            now = time.monotonic_ns()
            source.stop()
    policy = {key: settings[key] for key in POLICY_KEYS}
    report = summarize_stream(rows, started_ns=started, now_ns=now, policy=policy)
    report.update(mode="replay" if args.replay_run else "serial_read_only", source_diagnostics=source_stats,
                  source_run=str(args.replay_run) if args.replay_run else None, acquisition_error=failure)
    if failure:
        report["baseline_candidate_ready"] = False
    with (out/"sensor.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["seq", "sensor_t_us", "host_rx_ns", "Bx_uT", "By_uT", "Bz_uT", "valid"])
        writer.writerows([r["seq"], r.get("sensor_t_us"), r["host_rx_ns"], *r["B_uT"], r["valid"]] for r in rows)
    (out/"summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["baseline_candidate_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
