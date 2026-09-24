"""`scripts/run_ladder_experiment.py` 的装配与驱动逻辑。

脚本本身要连真机，但拼装和节拍推进是纯逻辑，这里用合成装置驱动，不碰硬件。
"""

import csv
import copy
import io
import importlib.util
import json
import math
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from brushbot.experiments.config import load_experiment
from brushbot.experiments.fake import make_ladder_rig
from brushbot.experiments.trajectory import compile_experiment

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "run_ladder_experiment.py"
    spec = importlib.util.spec_from_file_location("run_ladder_experiment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _installation(**overrides):
    setup = {
        "installation_id": "fixture-a", "verified": True,
        "tcp_name": "tcp0", "ucs_name": "ucs0",
        "tool_coord_si": [0.0] * 6, "user_coord_si": [0.0] * 6,
        "vertical_rpy_rad": [0.0, 0.0, 0.0], "sensor_mount_id": "mount-a",
        "origin_x_mm": 100.0, "origin_y_mm": 200.0,
        "wait_z_mm": 60.0, "contact_z_mm": 40.0,
        "workspace_min_mm": [0.0, 0.0, 0.0],
        "workspace_max_mm": [400.0, 400.0, 100.0],
        "max_depth_mm": 30.0, "max_xy_speed_mm_s": 50.0,
        "max_z_speed_mm_s": 20.0, "max_accel_mm_s2": 200.0,
        "max_step_mm": 2.0, "approach_speed_mm_s": 10.0,
        "return_speed_mm_s": 50.0, "pose_tolerance_mm": 0.5,
        "orientation_tolerance_rad": 0.01,
        "baseline_window_s": 0.04, "baseline_timeout_s": 1.0,
        "baseline_min_samples": 3, "baseline_max_std_uT": [0.1, 0.1, 0.1],
        "baseline_max_drift_uT_s": 0.1, "sensor_max_age_s": 0.05,
        "max_tick_lateness_s": 0.05, "stop_timeout_s": 1.0,
        "gripper_width_mm": 14.0, "gripper_speed": 30, "gripper_force": 30,
        "filter": {"kind": "ema", "alpha": 0.3},
    }
    setup.update(overrides)
    return setup


def _automatic_wetting_installation():
    return _installation(
        origin_x_mm=-200.0,
        origin_y_mm=500.0,
        wait_z_mm=130.0,
        contact_z_mm=40.0,
        workspace_min_mm=[-400.0, 400.0, 0.0],
        workspace_max_mm=[100.0, 600.0, 150.0],
    )


class InterruptingClock:
    """第 N 次 `advance` 时抛 KeyboardInterrupt，模拟操作者中断。

    合成时钟没有挂钟可对齐，`_pace` 走的是 `advance` 分支，所以中断注入点在这里。
    """

    def __init__(self, inner, after):
        self._inner = inner
        self._after = after
        self._calls = 0

    def now_ns(self):
        return self._inner.now_ns()

    def advance(self, dt):
        self._calls += 1
        if self._calls == self._after:
            raise KeyboardInterrupt
        self._inner.advance(dt)


def test_stack_runs_a_ladder_to_end_wait(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    engine, hub = script.build_experiment_stack(
        spec=rig.spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)

    snapshot = script.run_experiment(engine, hub, clock=rig.clock)

    assert snapshot["state"] == "END_WAIT"
    run_dir = Path(snapshot["run_dir"])
    assert (run_dir / "control.jsonl").exists()
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["status"] == "completed"


def test_ladder_run_completes_after_sensor_history_wraps(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    engine, hub = script.build_experiment_stack(
        spec=rig.spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)
    hub._rows = deque(maxlen=3)

    snapshot = script.run_experiment(engine, hub, clock=rig.clock)

    assert snapshot["state"] == "END_WAIT"
    with (Path(snapshot["run_dir"]) / "sensor.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) > 3
    assert int(rows[-1]["seq"]) == len(rows)


def test_ladder_run_uses_local_date_and_readable_name_during_recording(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    spec = copy.deepcopy(rig.spec)
    spec["run_label"] = "full_ry15"
    engine, hub = script.build_experiment_stack(
        spec=spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)

    snapshot = script.run_experiment(engine, hub, clock=rig.clock)

    run_dir = Path(snapshot["run_dir"])
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    local_start = datetime.fromisoformat(manifest["started_at"]).astimezone(
        ZoneInfo("Asia/Shanghai"))
    assert run_dir.parent == tmp_path / f"{local_start:%Y-%m-%d}"
    assert run_dir.name == (
        f"{local_start:%H-%M-%S}__full_ry15__{manifest['run_id'][-6:]}")
    assert manifest["status"] == "completed"
    assert manifest["brush_id"] == "brush2"


def test_brush2_runner_allows_other_start_xyz_without_changing_approach(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    pose = rig.arm.pose
    rig.arm.pose = (pose[0] + 0.01, pose[1], pose[2], *pose[3:])
    engine, hub = script.build_experiment_stack(
        spec=rig.spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)

    snapshot = script.run_experiment(
        engine, hub, clock=rig.clock, require_wait_position=False)

    assert snapshot["state"] == "END_WAIT"
    first_move = next(call for call in rig.arm.calls if call["action"] == "move_pose")
    assert first_move["pose"] == pytest.approx(tuple(engine._compiled["pose_m_rad"][0]))


def test_zero_argument_defaults_compile_the_hardcoded_real_ladder():
    script = _load_script()
    args = script._parse([])

    assert args.installation is None
    assert args.ip == "192.168.0.10"
    assert args.serial_port == "/dev/ttyACM0"
    assert Path(args.run_root) == ROOT / "runs" / "brush2"
    setup = script._hardcoded_setup()
    assert setup["origin_x_mm"] == pytest.approx(-200.0)
    assert setup["origin_y_mm"] == pytest.approx(500.0)
    assert setup["wait_z_mm"] == pytest.approx(130.0)
    assert setup["contact_z_mm"] == pytest.approx(40.0)
    assert setup["max_depth_mm"] == pytest.approx(20.0)
    assert setup["approach_speed_mm_s"] == pytest.approx(13.0)
    assert setup["return_speed_mm_s"] == pytest.approx(20.0)
    assert setup["max_z_speed_mm_s"] == pytest.approx(13.0)
    assert setup["vertical_rpy_rad"] == pytest.approx(
        [0.0, math.radians(15.0), 0.0])

    spec = script._configure_batch_spec(load_experiment(args.experiment), setup)
    assert spec["run_label"] == script.RUN_LABEL
    assert spec["path"]["order"] == "one_way"
    assert spec["path"]["steps"] == 8
    compiled = compile_experiment(spec, setup)
    assert compiled["pose_m_rad"][0].tolist() == pytest.approx(
        [-0.2, 0.5, 0.12, 0.0, math.radians(15.0), 0.0])
    assert compiled["pose_m_rad"][:, 0].max() == pytest.approx(0.0)
    measure_z_mm = [
        compiled["pose_m_rad"][compiled["phase"] == f"measure_{visit:02d}", 2][0]
        * 1000.0
        for visit in range(8)
    ]
    assert measure_z_mm == pytest.approx(
        [36.0, 34.285714, 32.571429, 30.857143,
         29.142857, 27.428571, 25.714286, 24.0])
    assert compiled["automatic_rebaseline_next_visits"] == list(range(8))


def test_runtime_orientation_is_captured_without_replacing_fixed_wait_xyz():
    script = _load_script()
    setup = script._hardcoded_setup()
    arm = make_ladder_rig().arm
    arm.pose = (-0.2, 0.5, 0.13, 0.001, math.radians(15.001), 0.0)

    captured = script._capture_runtime_orientation(setup, arm)

    assert captured == pytest.approx((0.001, math.radians(15.001), 0.0))
    assert setup["vertical_rpy_rad"] == pytest.approx(captured)
    assert setup["origin_x_mm"] == pytest.approx(-200.0)
    assert setup["origin_y_mm"] == pytest.approx(500.0)
    assert setup["wait_z_mm"] == pytest.approx(130.0)
    spec = script._configure_batch_spec(
        load_experiment(script.DEFAULT_EXPERIMENT), setup)
    compiled = compile_experiment(spec, setup)
    for axis, value in enumerate(captured):
        assert compiled["pose_m_rad"][:, 3 + axis].tolist() == pytest.approx(
            [value] * len(compiled["pose_m_rad"]))


def test_runtime_orientation_accepts_current_posture_before_run():
    script = _load_script()
    setup = script._hardcoded_setup()
    arm = make_ladder_rig().arm
    arm.pose = (-0.2, 0.5, 0.13, math.radians(15), 0.0, math.radians(90))

    captured = script._capture_runtime_orientation(setup, arm)

    assert captured == pytest.approx(arm.pose[3:])
    assert setup["vertical_rpy_rad"] == pytest.approx(captured)


def test_runtime_orientation_still_rejects_nonfinite_pose():
    script = _load_script()
    setup = script._hardcoded_setup()
    arm = make_ladder_rig().arm
    arm.pose = (-0.2, 0.5, 0.13, 0.0, float("nan"), 0.0)

    with pytest.raises(RuntimeError, match="有限数值"):
        script._capture_runtime_orientation(setup, arm)


def test_batch_parameters_are_general_and_validate_workspace():
    script = _load_script()
    setup = script._hardcoded_setup()
    template = load_experiment(script.DEFAULT_EXPERIMENT)

    configured = script._configure_batch_spec(
        template, setup, z_start_mm=30.0, z_end_mm=24.0,
        z_level_count=4, run_label="trial_b")

    assert configured["run_label"] == "trial_b"
    assert configured["path"]["depth_from_mm"] == pytest.approx(10.0)
    assert configured["path"]["depth_to_mm"] == pytest.approx(16.0)
    assert configured["path"]["steps"] == 4
    assert configured["path"]["order"] == "one_way"
    assert "pause_every_passes" not in configured["path"]
    assert "pause_z_mm" not in configured["path"]
    assert configured["path"]["wetting"] == {
        "every_paths": 1,
        "x_mm": -300.0,
        "y_mm": 500.0,
        "cup_rim_z_mm": 100.0,
        "safe_z_mm": 120.0,
        "dip_z_mm": 50.0,
        "dwell_s": 1.0,
        "settle_s": 0.5,
    }
    compiled = compile_experiment(configured, setup)
    phases = compiled["phase"]
    poses_mm = compiled["pose_m_rad"][:, :3] * 1000.0
    assert compiled["automatic_rebaseline_next_visits"] == [0, 1, 2, 3]
    for visit in range(4):
        measure = poses_mm[phases == f"measure_{visit:02d}"]
        assert measure[0, 0] == pytest.approx(-200.0, abs=0.05)
        assert measure[-1, 0] == pytest.approx(0.0)
    with pytest.raises(ValueError, match="Z_END_MM"):
        script._configure_batch_spec(
            template, setup, z_start_mm=27.0, z_end_mm=16.0,
            z_level_count=5, run_label="unsafe")


def test_named_tcp_coordinates_are_read_without_switching_tcp():
    script = _load_script()

    class Client:
        def __init__(self):
            self.calls = []

        def HRIF_ReadTCPByName(self, name):
            self.calls.append(("read_tcp", name))
            return ["0", "1", "2", "3", "4", "5", "6"]

    client = Client()
    values = script._read_named_coordinate(
        client, "HRIF_ReadTCPByName", "TCP_brush")

    assert values == pytest.approx((1, 2, 3, 4, 5, 6))
    assert client.calls == [("read_tcp", "TCP_brush")]


def test_runner_prompts_after_passes_four_eight_and_twelve(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(
        recorder_root=str(tmp_path), steps=8, pause_every_passes=4)
    spec = copy.deepcopy(rig.spec)
    spec["path"]["pause_z_mm"] = 100.0
    engine, hub = script.build_experiment_stack(
        spec=spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)
    prompts = []
    pause_z_m = []

    snapshot = script.run_experiment(
        engine, hub, clock=rig.clock,
        input_fn=lambda prompt: (
            prompts.append(prompt), pause_z_m.append(rig.arm.pose[2]), "")[-1])

    assert snapshot["state"] == "END_WAIT"
    assert len(prompts) == 3
    assert pause_z_m == pytest.approx([0.1, 0.1, 0.1])
    manifest = json.loads(
        (Path(snapshot["run_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert [item["effective_visit"] for item in manifest["baselines"]] == [
        0, 4, 8, 12,
    ]
    with (Path(snapshot["run_dir"]) / "sensor.csv").open(
            newline="", encoding="utf-8") as handle:
        sensor_rows = list(csv.DictReader(handle))
    baseline_sequences = {
        seq
        for item in manifest["baselines"]
        for seq in range(item["first_seq"], item["last_seq"] + 1)
    }
    acquisition_rows = [
        row for row in sensor_rows if int(row["seq"]) in baseline_sequences]
    assert acquisition_rows
    assert all(row["dBx_uT"] == "" and row["baseline_id"] == ""
               for row in acquisition_rows)
    assert {row["baseline_id"] for row in sensor_rows if row["baseline_id"]} == {
        "0", "1", "2", "3",
    }


def test_one_way_batch_runs_only_configured_paths_and_records_label(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(
        recorder_root=str(tmp_path), steps=5, pause_every_passes=4)
    spec = copy.deepcopy(rig.spec)
    spec["run_label"] = "repeat_02"
    spec["path"]["order"] = "one_way"
    spec["path"]["pause_z_mm"] = 100.0
    engine, hub = script.build_experiment_stack(
        spec=spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)
    prompts = []

    snapshot = script.run_experiment(
        engine, hub, clock=rig.clock,
        input_fn=lambda prompt: prompts.append(prompt) or "")

    assert snapshot["state"] == "END_WAIT"
    assert len(prompts) == 1
    run_dir = Path(snapshot["run_dir"])
    resolved = json.loads((run_dir / "resolved.json").read_text(encoding="utf-8"))
    assert resolved["run_label"] == "repeat_02"
    phases = {
        json.loads(line)["phase"]
        for line in (run_dir / "control.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert {phase for phase in phases if phase.startswith("measure_")} == {
        f"measure_{visit:02d}" for visit in range(5)
    }


def test_runner_prompts_to_wet_and_rebaselines_between_every_path(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(
        recorder_root=str(tmp_path), steps=5, pause_every_passes=1)
    spec = copy.deepcopy(rig.spec)
    spec["path"]["order"] = "one_way"
    spec["path"]["pause_z_mm"] = 100.0
    engine, hub = script.build_experiment_stack(
        spec=spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)
    prompts = []
    pause_z_m = []

    snapshot = script.run_experiment(
        engine, hub, clock=rig.clock,
        input_fn=lambda prompt: (
            prompts.append(prompt), pause_z_m.append(rig.arm.pose[2]), "")[-1])

    assert snapshot["state"] == "END_WAIT"
    assert len(prompts) == 4
    assert all("沾水" in prompt and "4 个行程" not in prompt for prompt in prompts)
    assert pause_z_m == pytest.approx([0.1, 0.1, 0.1, 0.1])
    manifest = json.loads(
        (Path(snapshot["run_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert [item["effective_visit"] for item in manifest["baselines"]] == [
        0, 1, 2, 3, 4,
    ]


def test_runner_automatically_rebaselines_after_each_wetting_cycle(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path), steps=5)
    spec = copy.deepcopy(rig.spec)
    spec["path"]["order"] = "one_way"
    spec["path"]["wetting"] = {
        "every_paths": 1,
        "x_mm": 0.0,
        "y_mm": 200.0,
        "cup_rim_z_mm": 80.0,
        "safe_z_mm": 100.0,
        "dip_z_mm": 50.0,
        "dwell_s": 0.04,
        "settle_s": 0.04,
    }
    engine, hub = script.build_experiment_stack(
        spec=spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)
    prompts = []

    snapshot = script.run_experiment(
        engine, hub, clock=rig.clock,
        input_fn=lambda prompt: prompts.append(prompt) or "")

    assert snapshot["state"] == "END_WAIT"
    assert prompts == []
    manifest = json.loads(
        (Path(snapshot["run_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert [item["effective_visit"] for item in manifest["baselines"]] == [
        0, 0, 1, 2, 3, 4,
    ]
    events = [
        json.loads(line)
        for line in (Path(snapshot["run_dir"]) / "events.jsonl").read_text(
            encoding="utf-8").splitlines()
    ]
    assert [item["effective_visit"] for item in events
            if item["event"] == "automatic_rebaseline_started"] == [0, 1, 2, 3, 4]


def test_runner_reports_live_magnetic_values_at_a_bounded_rate(tmp_path):
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    engine, hub = script.build_experiment_stack(
        spec=rig.spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=rig.clock)
    lines = []

    snapshot = script.run_experiment(
        engine, hub, clock=rig.clock,
        live_output_fn=lines.append, live_interval_s=0.2)

    assert snapshot["state"] == "END_WAIT"
    assert lines
    assert all("phase=" in "\n".join(line) and "Zcmd=" in "\n".join(line)
               and "depth=" in "\n".join(line) and "Bx=" in "\n".join(line)
               and "|ΔBxy|=" in "\n".join(line)
               and "baseline=" in "\n".join(line) for line in lines)
    control_count = len((Path(snapshot["run_dir"]) / "control.jsonl").read_text(
        encoding="utf-8").splitlines())
    assert len(lines) < control_count / 5


class _TTYBuffer(io.StringIO):
    def isatty(self):
        return True


def test_live_panel_redraws_in_place_and_restores_cursor():
    script = _load_script()
    stream = _TTYBuffer()
    panel = script.LiveStatusPanel(stream)
    first = ("Z Ladder  10.0%", "phase=measure_00", "Zcmd=36.00mm depth=0.00mm",
             "Bx=1.00 By=2.00 Bz=3.00 uT", "|ΔBxy|=0.50uT baseline=0")
    second = ("Z Ladder  11.0%", "phase=measure_00", "Zcmd=36.00mm depth=0.00mm",
              "Bx=1.10 By=2.10 Bz=3.10 uT", "|ΔBxy|=0.60uT baseline=0")

    panel.update(first)
    panel.update(second)
    panel.pause()

    output = stream.getvalue()
    assert output.count("\x1b[?25l") == 1
    assert "\x1b[5A" in output
    assert output.count("\x1b[2K") >= 5
    assert output.endswith("\x1b[?25h\n")


def test_live_panel_plain_stream_uses_one_compact_log_line():
    script = _load_script()
    stream = io.StringIO()
    panel = script.LiveStatusPanel(stream)

    panel.update(("Z Ladder  10.0%", "phase=measure_00", "Zcmd=36.00mm",
                  "Bx=1.00 By=2.00 Bz=3.00 uT", "|ΔBxy|=0.50uT"))

    assert stream.getvalue() == (
        "Z Ladder  10.0% | phase=measure_00 | Zcmd=36.00mm | "
        "Bx=1.00 By=2.00 Bz=3.00 uT | |ΔBxy|=0.50uT\n")


def test_interrupt_lifts_and_ends_aborted_not_hung(tmp_path):
    # Ctrl+C 不能直接退出：压深扫描途中刷子可能正压在纸面下。这条测试钉住
    # "中断 -> request_stop -> ABORT_LIFT 抬笔 -> 走到终态" 而不是卡死或抛在循环里。
    script = _load_script()
    rig = make_ladder_rig(recorder_root=str(tmp_path))
    clock = InterruptingClock(rig.clock, after=200)
    engine, hub = script.build_experiment_stack(
        spec=rig.spec, setup=rig.setup, arm=rig.arm, source=rig.source,
        root=tmp_path, clock=clock)

    with pytest.raises(KeyboardInterrupt):
        script.run_experiment(engine, hub, clock=clock)

    assert engine.state == "ABORTED"
    run_dir = Path(engine.run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted"
    local_start = datetime.fromisoformat(manifest["started_at"]).astimezone(
        ZoneInfo("Asia/Shanghai"))
    assert run_dir.parent == tmp_path / f"{local_start:%Y-%m-%d}"
    assert run_dir.name.startswith(f"{local_start:%H-%M-%S}__")


def test_dry_run_compiles_without_connecting_hardware(tmp_path, capsys):
    script = _load_script()
    installation = tmp_path / "rig-a.json"
    installation.write_text(
        json.dumps(_automatic_wetting_installation()), encoding="utf-8")
    experiment = ROOT / "configs" / "experiments" / "z_ladder_x.json"

    code = script.main([
        "--installation", str(installation),
        "--experiment", str(experiment),
        "--ip", "127.0.0.1",
        "--transport-timeout-s", "0.2",
        "--dry-run",
    ])

    assert code == 0
    out = capsys.readouterr().out
    assert "预检通过" in out
    # 8 条单向路径，每条 8 个沾水 phase + 4 个测量/回程 phase。
    assert "96 种" in out
    assert "approach_00" in out and "wet_transfer_out_07" in out


def test_max_depth_cap_does_not_expand_the_configured_ladder(tmp_path, capsys):
    script = _load_script()
    installation = tmp_path / "rig-a.json"
    installation.write_text(
        json.dumps(_automatic_wetting_installation()), encoding="utf-8")
    experiment = ROOT / "configs" / "experiments" / "z_ladder_x.json"

    code = script.main([
        "--installation", str(installation),
        "--experiment", str(experiment),
        "--ip", "127.0.0.1",
        "--transport-timeout-s", "0.2",
        "--max-depth-mm", "15",
        "--dry-run",
    ])

    assert code == 0
    assert "本次压深上限: 15 mm（批次定义为 16 mm）" in capsys.readouterr().out
