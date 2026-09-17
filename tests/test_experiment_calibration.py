import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from brushbot.experiments.calibration import summarize_ladder, summarize_scan, validate_calibration


def _table():
    return {
        "version": 1,
        "feature": "dBxy_norm_uT",
        "source": "measured",
        "installation_id": "fixture-a",
        "sensor_mount_id": "mount-a",
        "filter": {"kind": "ema", "alpha": 0.3},
        "speed_range_mm_s": [4.0, 6.0],
        "directions": ["x_positive"],
        "depth_mm": [0.0, 1.0, 2.0],
        "amplitude_uT": [0.0, 50.0, 110.0],
        "approved": True,
    }


def _context():
    return {
        "installation_id": "fixture-a",
        "sensor_mount_id": "mount-a",
        "filter": {"kind": "ema", "alpha": 0.3},
        "speed_mm_s": 5.0,
        "direction": "x_positive",
        "target_uT": 80.0,
    }


def test_measured_monotonic_approved_table_is_accepted():
    assert validate_calibration(_table(), _context())["amplitude_uT"][-1] == 110


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", "simulation", "source"),
        ("approved", False, "approved"),
        ("feature", "dB_norm_uT", "feature"),
        ("depth_mm", [0, 2, 1], "depth_mm"),
        ("amplitude_uT", [0, 50, 40], "amplitude_uT"),
    ],
)
def test_unusable_calibration_is_rejected_without_sorting(field, value, message):
    table = _table()
    table[field] = value
    with pytest.raises(ValueError, match=message):
        validate_calibration(table, _context())


def test_context_mismatch_and_extrapolation_are_rejected():
    with pytest.raises(ValueError, match="installation_id"):
        validate_calibration(_table(), {**_context(), "installation_id": "other"})
    with pytest.raises(ValueError, match="direction"):
        validate_calibration(_table(), {**_context(), "direction": "y_positive"})
    with pytest.raises(ValueError, match="speed"):
        validate_calibration(_table(), {**_context(), "speed_mm_s": 10})
    with pytest.raises(ValueError, match="target_uT"):
        validate_calibration(_table(), {**_context(), "target_uT": 120})


def test_scan_summary_is_explicitly_command_based_without_actual_pose(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"run_id": "r1"}))
    with (tmp_path / "sensor.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "seq", "dBx_uT", "dBy_uT", "valid",
        ])
        writer.writeheader()
        writer.writerow({"seq": 1, "dBx_uT": 3, "dBy_uT": 4, "valid": "true"})
    (tmp_path / "control.jsonl").write_text(json.dumps({
        "sample_seq": 1,
        "phase": "cruise",
        "depth_ff_m": 0.001,
        "depth_fb_m": 0.001,
        "actual_pose_available": False,
        "actual_pose_m_rad": None,
    }) + "\n")
    summary = summarize_scan(str(tmp_path))
    assert summary["position_basis"] == "command_based"
    assert summary["approved"] is False
    assert summary["pairs"] == [{
        "sample_seq": 1,
        "depth_mm": 2.0,
        "amplitude_uT": 5.0,
        "phase": "cruise",
    }]


def _write_run(folder, *, contact_z_mm=40.0, steps=3, amplitude_per_mm=50.0,
               drift_per_s=0.0, use_actual=True, skip_visit=None,
               amp_per_visit=None, timeline_steps=None, stop_after_visit=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(
        json.dumps({"run_id": "r1", "status": "completed"}), encoding="utf-8")
    (folder / "setup.json").write_text(
        json.dumps({"contact_z_mm": contact_z_mm}), encoding="utf-8")

    depths = list(np.linspace(0.0, 20.0, steps))
    visits = depths + list(reversed(depths))
    rows = []
    sensors = []
    seq = 0
    t_s = 0.0
    for visit, depth in enumerate(visits):
        if stop_after_visit is not None and visit > stop_after_visit:
            break
        if visit == skip_visit:
            continue
        for _ in range(4):
            seq += 1
            t_s += 0.02
            z_m = (contact_z_mm - depth) / 1000.0
            amplitude = (amp_per_visit[visit] if amp_per_visit is not None
                         else depth * amplitude_per_mm) + drift_per_s * t_s
            sensors.append({
                "seq": seq, "sensor_t_us": seq * 20000,
                "host_rx_ns": int(t_s * 1e9),
                "dBx_uT": amplitude, "dBy_uT": 0.0, "dBz_uT": 0.0, "valid": "1",
            })
            rows.append({
                "host_ns": int(t_s * 1e9), "t_s": t_s,
                "phase": f"measure_{visit:02d}",
                "sample_seq": seq,
                "actual_pose_available": use_actual,
                "actual_pose_m_rad": [0.0, 0.0, z_m, 0.0, 0.0, 0.0] if use_actual else None,
                "depth_ff_m": depth / 1000.0,
            })
    with (folder / "sensor.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(sensors[0]))
        writer.writeheader()
        writer.writerows(sensors)
    with (folder / "control.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    if timeline_steps is not None:
        # 模仿 recorder 写入 key 全集，phase 展开为每趟的 approach/measure/lift/transit。
        legs = []
        for v in range(2 * timeline_steps):
            legs.append(f"approach_{v:02d}")
            legs.append(f"measure_{v:02d}")
            legs.append(f"lift_{v:02d}")
            legs.append(f"transit_{v:02d}")
        n_tl = len(legs)
        np.savez(folder / "timeline.npz",
                 t_s=np.linspace(0.0, 10.0, n_tl),
                 s=np.linspace(0.0, 10.0, n_tl),
                 phase=np.asarray(legs, dtype="U12"),
                 pose_m_rad=np.zeros((n_tl, 6)),
                 g_ref_uT=np.zeros((n_tl, 3)),
                 depth_ff_m=np.linspace(0.0, 0.02, n_tl))
    return folder


def test_summarize_ladder_reports_each_rung(tmp_path):
    folder = _write_run(tmp_path / "run")
    summary = summarize_ladder(str(folder))
    assert summary["feature"] == "dBxy_norm_uT"
    assert summary["source"] == "measured"
    assert summary["position_basis"] == "actual_pose"
    assert summary["approved"] is False
    assert summary["steps"] == 3
    assert [rung["depth_cmd_mm"] for rung in summary["rungs"]] == pytest.approx(
        [0.0, 10.0, 20.0])
    assert summary["rungs"][0]["amplitude_uT"] == pytest.approx(0.0, abs=1e-6)
    assert summary["rungs"][2]["amplitude_uT"] == pytest.approx(1000.0, rel=1e-6)


def test_summarize_ladder_pairs_down_with_up_at_the_same_depth(tmp_path):
    # 升程档序与降程相反。若配对写错，第 0 档会混进 20 mm 的样本，
    # depth_cmd_mm 变成 10、hysteresis 变成 1000。这条测试专门盯这个 bug。
    folder = _write_run(tmp_path / "run")
    summary = summarize_ladder(str(folder))
    for rung in summary["rungs"]:
        assert rung["n"] == 8
        assert rung["hysteresis_uT"] == pytest.approx(0.0, abs=1e-6)


def test_summarize_ladder_detects_drift(tmp_path):
    # 夹具首尾两个样本都在 depth 0，深度贡献完全抵消；端点间漂移增量应正好是
    # drift_per_s * span_s。只断言 > 0 太弱（换了错误的漂移定义也能过），这里钉死
    # 端点定义：per_minute_uT 必须精确等于 drift_per_s * 60。
    folder = _write_run(tmp_path / "run", drift_per_s=1.0)
    summary = summarize_ladder(str(folder))
    assert summary["drift"]["total_uT"] == pytest.approx(0.46, rel=1e-9)
    assert summary["drift"]["per_minute_uT"] == pytest.approx(1.0 * 60.0, rel=1e-9)


def test_summarize_ladder_marks_a_truncated_run_bad(tmp_path):
    # 8 档（16 趟）梯子在升程开始前被截断，只录到 visit 5（control.jsonl 停在第 6 趟）。
    # 修复前从"实际出现的最大趟号"推档数会得到 half=3，把 visit 0（0 mm）配 visit 5
    # （14.3 mm），每档中位深度都 7.14 mm、steps 报 3、monotonic 可能仍为 True——
    # 静默产生错误的标定曲线。修复后应从编译期 timeline.npz 取档数：steps 报 8，
    # 缺了升程的档幅值全为 NaN、monotonic 判 False，坏数据自己暴露。
    folder = _write_run(tmp_path / "run", steps=8, timeline_steps=8,
                        stop_after_visit=5)
    summary = summarize_ladder(str(folder))
    assert summary["steps"] == 8
    assert summary["rungs"][0]["depth_cmd_mm"] == pytest.approx(0.0)
    assert all(math.isnan(rung["amplitude_uT"]) for rung in summary["rungs"])
    assert summary["quality"]["monotonic"] is False
    assert any("monotonic" in note for note in summary["quality"]["notes"])


def test_summarize_ladder_notes_inferred_rung_count_without_timeline(tmp_path):
    # 没有 timeline.npz（旧 run 或测试夹具）时，档数只能从实测趟号推导；若 run 实际被截断，
    # 推得的档数会低估且无从辨认。摘要必须如实注明档数来源，而不是让它看起来像可信的编译期档数。
    folder = _write_run(tmp_path / "run")
    summary = summarize_ladder(str(folder))
    assert summary["steps"] == 3
    assert any("inferred from recorded visits" in note
               and "truncated" in note
               for note in summary["quality"]["notes"])


def test_summarize_ladder_flags_non_monotonic(tmp_path):
    # dBxy 幅值是模长（hypot），恒非负，用负 per_mm 会得到单调递增的模长 [0,500,1000]。
    # 要构造非单调必须让中档幅值整体更高：档幅值 [0,800,500]，中档比最深档还高。
    # 按趟展开为 [0,800,500,500,800,0]（降程后原路升回）。
    folder = _write_run(tmp_path / "run",
                        amp_per_visit=[0.0, 800.0, 500.0, 500.0, 800.0, 0.0])
    summary = summarize_ladder(str(folder))
    assert summary["quality"]["monotonic"] is False
    assert any("monotonic" in note for note in summary["quality"]["notes"])


def test_summarize_ladder_falls_back_to_command_depth(tmp_path):
    folder = _write_run(tmp_path / "run", use_actual=False)
    summary = summarize_ladder(str(folder))
    assert summary["position_basis"] == "command_based"
    assert summary["rungs"][0]["depth_actual_median_mm"] is None
    assert summary["rungs"][0]["depth_cmd_mm"] == pytest.approx(0.0)


def test_summarize_ladder_keeps_rung_count_when_a_leg_has_no_samples(tmp_path):
    # 某一趟一个有效样本都没有时，不能把降程/升程的分界左移去凑配对——那会把不同深度的档
    # 配到一起、并静默少报档数。该档应得到 NaN 幅值，并让 monotonic 判 False。
    folder = _write_run(tmp_path / "run", steps=3, skip_visit=1)
    summary = summarize_ladder(str(folder))
    assert summary["steps"] == 3
    assert math.isnan(summary["rungs"][1]["amplitude_uT"])
    assert summary["quality"]["monotonic"] is False
