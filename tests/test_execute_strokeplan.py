import math

import numpy as np

from brushbot.strokeplan import Stroke, StrokePlan
from scripts.execute_strokeplan import build_servo_poses, execute_plan


class FakeCPS:
    def __init__(self):
        self.pose = [-0.299025, 0.500067, 0.130, 0.0, math.radians(5), 0.0]
        self.pushes = []
        self.starts = []
        self.stops = 0

    def HRIF_ReadCurFSM(self): return ["0", "33"]
    def HRIF_ReadActTcpPos(self): return ["0", *map(str, self.pose)]
    def HRIF_ReadCurTCP(self): return ["0", "0", "0", "40", "0", "0", "0"]
    def HRIF_ReadCurUCS(self): return ["0", "0", "0", "0", "0", "0", "0"]
    def HRIF_StartServo(self, dt, lookahead): self.starts.append((dt, lookahead)); return ["0"]
    def HRIF_PushServoP(self, pose, ucs, tcp): self.pushes.append(tuple(pose)); self.pose = list(pose); return ["0"]
    def HRIF_GrpStop(self): self.stops += 1; return ["0"]


def make_plan():
    s = np.linspace(0, 1, 3)
    return StrokePlan([Stroke(s, np.array([[-.299025, .500067], [-.149025, .500067], [.000975, .500067]]),
                             np.array([0., 50., 90.]), np.array([0., .001, .003]))],
                      {"stroke_durations_s": [1.0], "orientation_rpy_rad": [0., math.radians(5), 0.]})


def test_build_servo_poses_keeps_surface_frame_and_lifts():
    poses = build_servo_poses(make_plan(), z_surface_mm=40.0, wait_z_mm=130.0,
                              lift_mm=10.0)
    assert poses[0][2] == 0.040
    assert poses[1][2] == 0.039
    assert poses[-1][2] == 0.130
    assert poses[0][3:] == (0.0, math.radians(5), 0.0)


def test_execute_plan_starts_only_after_confirmation_and_stops():
    cps = FakeCPS()
    result = execute_plan(cps, make_plan(), confirm=lambda: True, tick=lambda: None,
                          z_surface_mm=40.0, wait_z_mm=130.0, lift_mm=10.0)
    assert result["status"] == "completed"
    assert cps.starts == [(0.02, 0.1)]
    assert cps.stops == 1
    assert len(cps.pushes) == len(build_servo_poses(make_plan(), 40.0, 130.0, 10.0))


def test_execute_plan_cancel_sends_no_motion():
    cps = FakeCPS()
    result = execute_plan(cps, make_plan(), confirm=lambda: False, tick=lambda: None,
                          z_surface_mm=40.0, wait_z_mm=130.0, lift_mm=10.0)
    assert result["status"] == "cancelled"
    assert cps.starts == [] and cps.pushes == [] and cps.stops == 0
