"""E2E 验收 pytest 属主 (审计 A1): 四问数字从 print 升级为机器断言.

数字漂出判据 → 本测试红, CI 可见; 验收产物 (plan npz + JSON) 可复现落盘.
判据: Q1 ≤3µT / Q2 ≤3.5µT / Q3 闭环<开环 (断言在 run_acceptance 内部);
Q4 链路级 → tests/test_strokeplan.py::test_waypoints_chain_writes_ink.
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from demo_target_pipeline import run_acceptance  # noqa: E402

from brushbot.strokeplan import StrokePlan  # noqa: E402


def test_e2e_acceptance_criteria_and_artifacts(tmp_path):
    numbers = run_acceptance(save_dir=tmp_path, make_plot=False, verbose=False)
    assert numbers["passed"]
    assert all(v <= 3.0 for v in numbers["q1_rms_uT"])
    assert all(v <= 3.5 for v in numbers["q2_rms_uT"])
    assert numbers["q3_rms_pct"]["closed"] < numbers["q3_rms_pct"]["open"]
    # 产物落盘且可回读: StrokePlan npz + 数字 JSON (验收证据不再零留存)
    back = StrokePlan.load(tmp_path / "plan_var.npz")
    assert len(back.strokes) >= 1
    assert back.meta["stroke_durations_s"] == numbers["stroke_durations_s"]
    data = json.loads((tmp_path / "acceptance.json").read_text())
    assert data["q1_rms_uT"] == numbers["q1_rms_uT"]
    assert np.isfinite(np.concatenate(
        [back.strokes[0].g_press, back.strokes[0].z_ff])).all()
