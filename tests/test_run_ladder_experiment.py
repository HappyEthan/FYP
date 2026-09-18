"""`scripts/run_ladder_experiment.py` 的装配与驱动逻辑。

脚本本身要连真机，但拼装和节拍推进是纯逻辑，这里用合成装置驱动，不碰硬件。
"""

import importlib.util
import json
from pathlib import Path

import pytest

from brushbot.experiments.fake import make_ladder_rig

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
    assert json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["status"] == "aborted"


def test_dry_run_compiles_without_connecting_hardware(tmp_path, capsys):
    script = _load_script()
    installation = tmp_path / "rig-a.json"
    installation.write_text(json.dumps(_installation()), encoding="utf-8")
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
    # 16 趟 × 4 段 = 64 个相位名，首末分别是 approach_00 与 transit_15。
    assert "64 种" in out
    assert "approach_00" in out and "transit_15" in out


def test_max_depth_cap_shrinks_the_ladder(tmp_path, capsys):
    script = _load_script()
    installation = tmp_path / "rig-a.json"
    installation.write_text(json.dumps(_installation()), encoding="utf-8")
    experiment = ROOT / "configs" / "experiments" / "z_ladder_x.json"

    code = script.main([
        "--installation", str(installation),
        "--experiment", str(experiment),
        "--ip", "127.0.0.1",
        "--transport-timeout-s", "0.2",
        "--max-depth-mm", "2",
        "--dry-run",
    ])

    assert code == 0
    assert "本次压深上限: 2 mm" in capsys.readouterr().out
