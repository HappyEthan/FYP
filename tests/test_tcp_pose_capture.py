"""Actual TCP samples use an independent, timestamped stream."""

import csv
import json
import threading
from pathlib import Path

from tests.test_strokeplan_experiment import stack


def test_pose_sampler_writes_si_pose_and_monotonic_timestamps(tmp_path):
    from brushbot.experiments.tcp_pose_capture import TCPPoseSampler

    ticks = iter((100, 130))
    sampler = TCPPoseSampler(
        lambda: (-0.1, 0.5, 0.028, 0.0, 0.26, 0.0),
        clock_ns=lambda: next(ticks), interval_s=1.0)
    sampler.start(tmp_path)
    summary = sampler.stop()

    with (tmp_path / "actual_tcp.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["valid"] == "true"
    assert rows[0]["request_start_ns"] == "100"
    assert rows[0]["request_end_ns"] == "130"
    assert float(rows[0]["z_m"]) == 0.028
    assert rows[0]["x_m"] == "-0.1"
    assert summary["valid_samples"] == 1
    assert json.loads((tmp_path / "actual_tcp_meta.json").read_text()) == summary


def test_pose_sampler_keeps_slow_reads_off_the_calling_thread(tmp_path):
    from brushbot.experiments.tcp_pose_capture import TCPPoseSampler

    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def read_pose():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(1.0)
        return (0.0, 0.0, 0.03, 0.0, 0.0, 0.0)

    sampler = TCPPoseSampler(read_pose, interval_s=0.01)
    sampler.start(tmp_path)
    assert entered.wait(1.0)
    release.set()
    summary = sampler.stop()
    assert summary["valid_samples"] >= 2


def test_recorded_fake_run_keeps_actual_pose_in_separate_stream(tmp_path):
    from brushbot.experiments.tcp_pose_capture import TCPPoseSampler
    from scripts.run_strokeplan_experiment import run_recorded

    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode="p")
    sampler = TCPPoseSampler(
        lambda: arm.read_state()["tcp_pose"],
        clock_ns=clock.now_ns, interval_s=1.0)
    result = run_recorded(
        engine, hub, clock=clock, sleep=lambda _: None, pose_sampler=sampler)

    assert result["state"] == "END_WAIT"
    run_dir = Path(result["run_dir"])
    with (run_dir / "actual_tcp.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and rows[0]["valid"] == "true"
    control = [json.loads(line) for line in (run_dir / "control.jsonl").read_text().splitlines()]
    assert all(not row["actual_pose_available"] for row in control)
    assert result["pose_capture"]["valid_samples"] >= 1


def test_initial_pose_capture_failure_prevents_arm_motion(tmp_path):
    from brushbot.experiments.tcp_pose_capture import TCPPoseSampler
    from scripts.run_strokeplan_experiment import run_recorded

    engine, hub, arm, source, clock, _ = stack(tmp_path, control_mode="p")

    def fail_read():
        raise OSError("second connection unavailable")

    sampler = TCPPoseSampler(fail_read, clock_ns=clock.now_ns)
    result = run_recorded(
        engine, hub, clock=clock, sleep=lambda _: None, pose_sampler=sampler)

    assert result["state"] != "END_WAIT"
    assert not any(call["action"] in {"move_pose", "push_pose", "start_servo"}
                   for call in arm.calls)
    assert result["pose_capture"]["valid_samples"] == 0
    assert result["pose_capture"]["invalid_samples"] == 1


def test_transient_pose_read_error_is_logged_and_sampling_recovers(tmp_path):
    from brushbot.experiments.tcp_pose_capture import TCPPoseSampler

    recovered = threading.Event()
    calls = 0

    def read_pose():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("one timeout")
        if calls == 3:
            recovered.set()
        return (0.0, 0.0, 0.03, 0.0, 0.0, 0.0)

    sampler = TCPPoseSampler(read_pose, interval_s=0.01)
    sampler.start(tmp_path)
    assert recovered.wait(1.0)
    summary = sampler.stop()
    with (tmp_path / "actual_tcp.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["valid"] for row in rows[:3]] == ["true", "false", "true"]
    assert "one timeout" in rows[1]["error"]
    assert summary["invalid_samples"] == 1
