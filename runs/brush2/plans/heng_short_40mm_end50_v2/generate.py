#!/usr/bin/env python3
"""Change only the short-Heng terminal magnetic target to 50 uT, offline."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]

from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.target_strokeplan import Stroke, StrokePlan
from scripts.generate_calligraphy_trial import contact_profile

SOURCE = ROOT/"runs/brush2/plans/heng_short_40mm_100_193_v1"
CONTEXT = ROOT/"runs/brush2/plans/11_中字底横延长30mm_实测第9次"
PREVIEW = ROOT / "scripts/preview_strokeplan.py"
POLICY = dict(terminal_target_uT=50., initial_target_uT=100.,
    body_levels_uT=[100., 124.46659545769568, 154.91933384829667, 192.8228205467164, 240.],
    scope="subsequent generated candidates: use 50uT at the end of contraction; preserve explicitly specified starting/body levels",
    status="user-requested synthetic terminal target; physical contact and calibration applicability unverified")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def build_candidate():
    original = StrokePlan.load(SOURCE/"heng_short/strokeplan.npz")
    old = original.strokes[0]
    meta = copy.deepcopy(original.meta)
    rows = copy.deepcopy(meta["phase_control_points"])
    rows[-1].update(g_target_uT=50., level="terminal_50", action="回收至50uT目标，随后抬笔")
    knots = [[row["s"], row["g_target_uT"]] for row in rows]
    st = Stroke(old.s.copy(), old.xy.copy(), old.t.copy(), contact_profile(old.s, knots), old.orientation.copy())
    recipe = json.loads((SOURCE/"heng_short/recipe.json").read_text())
    recipe.update(schema="short-heng-end50-candidate-v2", generator="generate.py:build_candidate",
                  source_target=str((SOURCE/"heng_short/strokeplan.npz").relative_to(ROOT)),
                  terminal_policy=POLICY)
    recipe["magnetic_target"].update(knots_s_uT=knots, terminal_target_uT=50.)
    recipe["notes"] = ["沿用v1的XY、时间、姿态和主体磁目标；仅末端收缩目标由100降至50uT。",
        "50uT为独立收笔目标，不重定义原100..240uT五档，也不更改起笔值。",
        "当前历史前馈表下限约72.5uT，末段低于标定范围，目标文件暂不能沿用该表执行。",
        "本地配方由generate.py读取保留的v1目标后重建；未外推或修改标定表。"]
    meta.update(name="短横40mm：收笔末端50uT", phase_control_points=rows,
        generation_recipe=recipe, terminal_policy=POLICY,
        source_target=str((SOURCE/"heng_short/strokeplan.npz").relative_to(ROOT)),
        source_target_sha256=digest(SOURCE/"heng_short/strokeplan.npz"),
        validation="target-only candidate; 50uT terminal value requires measured low-response support before execution")
    plan = StrokePlan([st], meta)
    plan.validate()
    assert st.g_target[0] == 100. and st.g_target[-1] == 50.
    assert all(np.array_equal(getattr(st, key), getattr(old, key)) for key in ("s", "xy", "t", "orientation"))
    unchanged = old.s <= rows[-2]["s"]
    assert np.array_equal(st.g_target[unchanged], old.g_target[unchanged])
    assert np.all(np.diff(st.g_target[~unchanged]) <= 1e-8)
    return plan, recipe, rows


def main():
    out = Path(__file__).resolve().parent
    if any(p.name not in {"generate.py", "__pycache__"} for p in out.iterdir()):
        raise FileExistsError("refusing to replace an output bundle")
    files = [SOURCE/"heng_short/strokeplan.npz", SOURCE/"heng_short/recipe.json"] + [
        CONTEXT/n for n in ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in files}
    plan, recipe, rows = build_candidate()
    st = plan.strokes[0]
    table, setup, entry, pi = [json.loads((CONTEXT/n).read_text()) for n in
                              ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    lower, upper = float(table["amplitude_uT"][0]), float(table["amplitude_uT"][-1])
    outside = (st.g_target<lower) | (st.g_target>upper)
    assert outside.any() and st.g_target[-1] < lower
    try:
        compile_recorded_plan(plan, table, setup, label="heng_short_40mm_end50_v2_pi",
                              control_mode="pi", feedback_profile=pi, entry_profile=entry)
    except ValueError as exc:
        if str(exc) != "target outside measured range; extrapolation disabled":
            raise
        rejection = str(exc)
    else:
        raise AssertionError("an out-of-range 50uT target unexpectedly compiled")
    first = int(np.flatnonzero(outside)[0])
    preflight = dict(status="blocked_by_calibration_range", executable_with_current_table=False,
        table=str((CONTEXT/"feedforward.json").relative_to(ROOT)), measured_range_uT=[lower, upper],
        requested_terminal_uT=50., first_unsupported_time_s=float(st.t[first]),
        unsupported_sample_count=int(outside.sum()), error=rejection,
        method="existing directional compiler with the explicit Zhong PI profile rejected unsupported values",
        extrapolation_used=False, hardware_connected=False)
    summary = dict(writing_duration_s=float(st.t[-1]), bbox_mm=np.ptp(st.xy*1000., axis=0).tolist(),
        g_target_range_uT=[float(st.g_target.min()), float(st.g_target.max())],
        start_target_uT=float(st.g_target[0]), terminal_target_uT=float(st.g_target[-1]),
        changed="only the final L2-to-terminal magnetic transition; geometry, time, orientation and earlier targets are identical to v1",
        terminal_policy=POLICY, validation="V3 reload, exact invariance assertions and independent preview; execution preflight rejected unsupported low-response targets",
        source_sha256=hashes, execution_preflight=preflight)
    (out/"heng_short").mkdir()
    plan.save(out/"heng_short/strokeplan.npz")
    StrokePlan.load(out/"heng_short/strokeplan.npz")
    write_json(out/"heng_short/recipe.json", recipe)
    write_json(out/"terminal_policy.json", POLICY)
    with (out/"heng_short/phase_table.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_json(out/"preflight.json", preflight)
    subprocess.run([sys.executable, str(PREVIEW), str(out/"heng_short/strokeplan.npz"), "--repo", str(ROOT),
                    "--output-dir", str(out/"heng_short/preview")], check=True, capture_output=True, text=True)
    assert hashes == {str(p.relative_to(ROOT)): digest(p) for p in files}
    write_json(out/"summary.json", summary)
    readme = f"""# 短横40mm：收笔末端50uT

按用户最新要求，后续候选的末端收缩目标取50uT；起笔仍100uT，原100..240uT五档继续用于主体。当前短横序列为100→124.47→154.92→192.82→124.47→50uT。50不等于离纸或已标定的笔宽。

本版严格保留v1的XY、s、时间和姿态，主体与收笔前的磁目标也保持相同。仅最后一段由124.47平滑降至50，原终点是100。宽40mm，书写{st.t[-1]:.2f}秒，局部收笔几何仍沿用v1。

当前前馈表实测范围{lower:.2f}..{upper:.2f}uT，不覆盖50。现有方向执行器的离线预检按预期拒绝该目标：`{rejection}`。新文件可用于目标讨论与预览，补齐低响应段标定后再检查执行；未外推、裁剪目标或修改原表，未生成名义Z轨迹，未连接硬件。

![末端50目标预览](heng_short/preview/stroke_00.png)

目标：[heng_short/strokeplan.npz](heng_short/strokeplan.npz)；阶段：[heng_short/phase_table.csv](heng_short/phase_table.csv)；[收笔规则](terminal_policy.json)；[预检报告](preflight.json)。v1和历史现场配置均保留原值。
"""
    with (out/"README.md").open("x", encoding="utf-8") as stream:
        stream.write(readme)
    write_json(out/"manifest.json", {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*"))
                                     if p.is_file() and "__pycache__" not in p.parts})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
