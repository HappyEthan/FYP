import numpy as np
import pytest

from scripts.record_hanzi_openloop import (
    WORK_Z_MM,
    SAFE_X_MM,
    SAFE_Y_MM,
    build_hanzi_waypoints,
    densify_waypoints,
    build_servo_waypoints,
    validate_initial_pose,
    stream_poses,
    signal_monitor,
)


def test_yong_waypoints_are_multi_stroke_and_safe():
    waypoints = build_hanzi_waypoints("永")
    assert len(waypoints) > 20
    xyz = np.asarray([p[:3] for p in waypoints], dtype=float)
    assert np.all((xyz[:, 0] >= SAFE_X_MM[0]) & (xyz[:, 0] <= SAFE_X_MM[1]))
    assert np.all((xyz[:, 1] >= SAFE_Y_MM[0]) & (xyz[:, 1] <= SAFE_Y_MM[1]))
    assert WORK_Z_MM in xyz[:, 2]
    assert xyz[:, 2].min() < WORK_Z_MM
    assert (xyz[:, 0].max() - xyz[:, 0].min() >= 130.0
            or xyz[:, 1].max() - xyz[:, 1].min() >= 130.0)
    angles = np.asarray([p[3:5] for p in waypoints], dtype=float)
    lean = np.linalg.norm(angles, axis=1)
    assert lean.max() == pytest.approx(0.0)


def test_densify_limits_cartesian_step():
    points = [(0.0, 0.0, 35.0, 180.0, 0.0, 90.0),
              (10.0, 0.0, 35.0, 180.0, 0.0, 90.0)]
    dense = densify_waypoints(points, max_step_mm=0.5)
    assert len(dense) > 2
    steps = [np.linalg.norm(np.asarray(dense[i + 1][:3]) - dense[i][:3])
             for i in range(len(dense) - 1)]
    assert max(steps) <= 0.5 + 1e-9


def test_densify_halves_vertical_step():
    points = [(0, 0, 50, 0, 0, 0), (0, 0, 35, 0, 0, 0)]
    dense = densify_waypoints(points, max_step_mm=0.5, max_z_step_mm=0.25)
    assert max(abs(dense[i + 1][2] - dense[i][2])
               for i in range(len(dense) - 1)) <= 0.25 + 1e-9


def test_densify_limits_orientation_step():
    points = [(0, 0, 50, 0, 0, 0), (0, 0, 50, 0, 10, 0)]
    dense = densify_waypoints(points, max_angle_step_deg=0.1)
    assert max(abs(dense[i + 1][4] - dense[i][4])
               for i in range(len(dense) - 1)) <= 0.1 + 1e-9


def test_actual_tcp_is_first_pose_for_continuous_entry():
    planned = build_servo_waypoints()
    current = (-148.5, 499.0, 129.0, 1.0, 0.0, -1.0)
    dense = densify_waypoints([current, *planned], max_z_step_mm=0.25)
    assert dense[0] == current
    assert np.linalg.norm(np.asarray(dense[1][:3]) - np.asarray(dense[0][:3])) <= 0.5 + 1e-9


def test_stream_poses_ticks_before_every_push():
    class Fake:
        def __init__(self): self.pushed = []
        def HRIF_PushServoP(self, pose, ucs, tcp):
            self.pushed.append(pose); return ["0"]
    calls = []
    fake = Fake()
    stream_poses(fake, [(1,2,3,0,0,0), (2,3,4,0,0,0)], (0,)*6, (0,)*6,
                 tick=lambda: calls.append(True))
    assert len(calls) == len(fake.pushed) == 2


def test_missing_monitor_socket_has_actionable_error():
    try:
        signal_monitor("/tmp/definitely-missing-brushbot.sock", "start_record")
    except RuntimeError as exc:
        assert "Monitor" in str(exc)
        assert "socket" in str(exc)
    else:
        raise AssertionError("missing Monitor socket must be reported")


def test_initial_xy_move_stays_at_wait_height():
    poses = build_servo_waypoints()
    assert poses[0][2] == 130.0
    assert poses[1][2] == 130.0


def test_initial_pose_requires_matching_orientation():
    try:
        validate_initial_pose((-150, 500, 130, 10, 0, 0))
    except RuntimeError:
        return
    raise AssertionError("orientation mismatch must be rejected")


def test_initial_pose_ignores_two_degree_orientation_error_and_wraps_angles():
    assert validate_initial_pose((-150, 500, 130, 1.5, -1.5, 358.5))
