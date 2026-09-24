"""Standalone safe-return script behavior, exercised without robot hardware."""

import importlib.util
import math
from pathlib import Path

import pytest

from brushbot.experiments.fake import FakeArm


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "return_to_origin.py"
    spec = importlib.util.spec_from_file_location("return_to_origin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup():
    return {
        # Deliberately different: the standalone script target is code-defined.
        "origin_x_mm": 100.0,
        "origin_y_mm": 200.0,
        "wait_z_mm": 60.0,
        "vertical_rpy_rad": [0.0, 0.0, 0.0],
        "workspace_min_mm": [-400.0, 400.0, 0.0],
        "workspace_max_mm": [100.0, 600.0, 200.0],
        "return_speed_mm_s": 10.0,
        "max_xy_speed_mm_s": 20.0,
        "max_z_speed_mm_s": 20.0,
        "pose_tolerance_mm": 0.1,
        "orientation_tolerance_rad": 0.01,
    }


def test_confirmed_return_sends_one_direct_move_to_code_defined_origin():
    script = _load_script()
    arm = FakeArm((-0.15, 0.45, 0.02, 1.0, 2.0, 3.0))
    output = []

    code = script.execute_return(
        arm, _setup(), input_fn=lambda _prompt: "",
        output_fn=output.append, sleep=lambda _seconds: None)

    assert code == 0
    assert arm.pose == pytest.approx(
        (-0.2, 0.5, 0.13, 0.0, math.radians(15.0), 0.0))
    move_poses = [call["pose"] for call in arm.calls if call["action"] == "move_pose"]
    assert move_poses == pytest.approx([
        (-0.2, 0.5, 0.13, 0.0, math.radians(15.0), 0.0),
    ])
    assert not any("安全路线" in line for line in output)
    assert any("COMPLETED" in line for line in output)


def test_unconfirmed_return_sends_no_motion_command():
    script = _load_script()
    arm = FakeArm((-0.15, 0.45, 0.02, 1.0, 2.0, 3.0))

    code = script.execute_return(
        arm, _setup(), input_fn=lambda _prompt: "no",
        output_fn=lambda _line: None, sleep=lambda _seconds: None)

    assert code == 1
    assert arm.calls == []


def test_keyboard_interrupt_stops_an_active_return():
    script = _load_script()
    class InterruptingArm(FakeArm):
        def move_pose(self, pose, speed_mm_s):
            super().move_pose(pose, speed_mm_s)
            raise KeyboardInterrupt

    arm = InterruptingArm((-0.15, 0.45, 0.02, 1.0, 2.0, 3.0))

    code = script.execute_return(
        arm, _setup(), input_fn=lambda _prompt: "",
        output_fn=lambda _line: None, sleep=lambda _seconds: None)

    assert code == 130
    assert arm.calls[-1]["action"] == "stop"


def test_move_failure_reports_the_original_error_and_stops():
    script = _load_script()
    output = []

    class FailingArm(FakeArm):
        def move_pose(self, pose, speed_mm_s):
            raise RuntimeError("HRIF_MoveL failed: 42")

    arm = FailingArm((-0.15, 0.45, 0.02, 1.0, 2.0, 3.0))
    code = script.execute_return(
        arm, _setup(), input_fn=lambda _prompt: "",
        output_fn=output.append, sleep=lambda _seconds: None)

    assert code == 2
    assert arm.calls[-1]["action"] == "stop"
    assert any("HRIF_MoveL failed: 42" in line for line in output)


def test_main_uses_hardcoded_connection_defaults_without_cli_arguments():
    script = _load_script()
    arm = FakeArm((-0.15, 0.45, 0.02, 1.0, 2.0, 3.0))
    connections = []

    def connect(ip, gid, tcp_name):
        connections.append((ip, gid, tcp_name))
        return arm

    code = script.main(
        input_fn=lambda _prompt: "", output_fn=lambda _line: None,
        sleep=lambda _seconds: None, connect_arm=connect)

    assert code == 0
    assert connections == [("192.168.0.10", 1, "TCP_brush")]
    assert arm.pose == pytest.approx(
        (-0.2, 0.5, 0.13, 0.0, math.radians(15.0), 0.0))
    move_calls = [call for call in arm.calls if call["action"] == "move_pose"]
    assert move_calls
    assert all(call["speed_mm_s"] == pytest.approx(30.0) for call in move_calls)


def test_main_allows_return_from_140_mm_high_position():
    """Catch a return envelope whose Z ceiling regresses below 140 mm."""
    script = _load_script()
    arm = FakeArm((-0.299991, 0.5, 0.139902, 0.0, 0.0, 0.0))

    code = script.main(
        input_fn=lambda _prompt: "", output_fn=lambda _line: None,
        sleep=lambda _seconds: None, connect_arm=lambda _ip, _gid, _tcp: arm)

    assert code == 0
    assert arm.pose == pytest.approx(
        (-0.2, 0.5, 0.13, 0.0, math.radians(15.0), 0.0))
    assert [call["action"] for call in arm.calls] == ["move_pose"]
