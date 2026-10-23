#!/usr/bin/env python3
"""Offline 80 mm Heng with a sub-5 mm local finishing gesture."""
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

from brushbot.experiments.strokeplan_character import orientation_heading
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from brushbot.target_strokeplan import FEATURE, Stroke, StrokePlan
from scripts.generate_calligraphy_trial import contact_profile
from scripts.generate_strokeplan_from_json import build_plan

SOURCE = ROOT/"runs/brush2/plans/template_four_strokes_100_240_zhong180_v3/heng"
PREVIOUS = ROOT/"runs/brush2/plans/heng_80mm_smooth_tail_v4"
CONTEXT = ROOT/"runs/brush2/plans/11_中字底横延长30mm_实测第9次"
PREVIEW = ROOT / "scripts/preview_strokeplan.py"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def arc(points):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]


def bezier(controls):
    p = np.asarray(controls, float)
    u = np.linspace(0., 1., 181)[:, None]
    return (1-u)**3*p[0] + 3*(1-u)**2*u*p[1] + 3*(1-u)*u**2*p[2] + u**3*p[3]


def build_candidate():
    source = json.loads((SOURCE/"recipe.json").read_text())
    body = np.asarray(source["path"]["points_mm"], float)[:35]*(80./120.)
    incoming = body[-1]-body[-2]
    # Continue the main stroke to the local terminal region. This section
    # is ordinary forward writing, not an expanded finishing gesture.
    continuation_controls = [body[-1].tolist(),
        (body[-1]+[2., 2.*incoming[1]/incoming[0]]).tolist(), [36.5, 5.], [38.5, 5.]]
    continuation = bezier(continuation_controls)
    first_controls = [[38.5, 5.], [39.2, 5.], [40., 5.3], [40., 4.8]]
    second_controls = [[40., 4.8], [40., 4.3], [39.1, 4.35], [39., 4.5]]
    first, second = bezier(first_controls), bezier(second_controls)
    micro = np.vstack([first, second[1:]])
    prefix = np.vstack([body, continuation[1:]])
    points = np.vstack([prefix, micro[1:]])
    d = arc(points)
    micro_index = len(prefix)-1
    micro_start = float(d[micro_index])
    micro_length = float(d[-1]-micro_start)
    assert micro_length < 5.
    assert np.all(np.ptp(micro, axis=0) < 5.)

    rows = []
    for index, action, target in [(0, "尖起", 100.), (1, "斜切轻按", 192.8228205467164),
                                 (3, "转入行笔", 192.8228205467164),
                                 (18, "前半段渐提", 124.46659545769568),
                                 (23, "中段较细", 124.46659545769568),
                                 (34, "主体后段渐按，随后沿主体卸载", 192.8228205467164),
                                 (micro_index, "进入微小收笔区", 124.46659545769568),
                                 (len(points)-1, "微小回收结束，随后抬笔", 100.)]:
        rows.append(dict(action=action, distance_mm=float(d[index]), s=float(d[index]/d[-1]),
                         g_target_uT=target))
    knots = [[r["s"], r["g_target_uT"]] for r in rows]

    # Use the existing body-direction planner on a surrogate continuation.
    # Every surrogate segment has the SAME length as its real XY counterpart;
    # after micro_start only its direction is changed to the main-body tangent.
    # Thus this is a time/pose reference, never the saved execution geometry.
    proxy = points.copy()
    proxy[micro_index:, 0] = points[micro_index, 0] + d[micro_index:]-micro_start
    proxy[micro_index:, 1] = points[micro_index, 1]
    assert np.allclose(arc(proxy), d, atol=1e-10, rtol=0)
    reference_recipe = copy.deepcopy(source)
    reference_recipe["placement"]["scale"] = 1.
    reference_recipe["path"] = dict(kind="rounded_polyline", points_mm=proxy.tolist(), corner_radius_mm=0.)
    reference_recipe["magnetic_target"]["knots_s_uT"] = knots
    # Leave a small speed margin for the final equal-arclength resampling.
    reference_recipe["timing"]["speed_mm_s"] = 9.9
    reference_recipe["timing"]["speed_knots_s_mm_s"] = [
        [0., 3.], [rows[1]["s"], 3.], [rows[2]["s"], 3.],
        [rows[2]["s"]+.05, 10.], [rows[5]["s"]-.02, 10.],
        [rows[5]["s"], 6.], [rows[6]["s"], 1.5], [1., .8],
    ]
    reference = build_plan(reference_recipe).strokes[0]
    origin = np.asarray(source["placement"]["origin_mm"], float)
    xy = reference.xy*1000.-origin
    # Keep the planner's sampled body exactly. Replace only the virtual
    # straight continuation with its equal-distance micro-gesture samples.
    local = xy[:, 0] >= points[micro_index, 0]
    proxy_x = xy[:, 0].copy()
    local_distance = micro_start + xy[local, 0]-points[micro_index, 0]
    xy[local] = np.column_stack([np.interp(local_distance, d, points[:, i]) for i in range(2)])
    final_arc = arc(xy)
    s = final_arc/final_arc[-1]
    k = int(np.flatnonzero(local)[0])
    micro_start = float(np.interp(points[micro_index, 0], proxy_x[k-1:k+1], final_arc[k-1:k+1]))
    rows[-2]["distance_mm"] = micro_start
    rows[-1]["distance_mm"] = float(final_arc[-1])
    for row in rows:
        row["s"] = row["distance_mm"]/final_arc[-1]
    knots = [[r["s"], r["g_target_uT"]] for r in rows]
    st = Stroke(s, (xy+origin)/1000., reference.t.copy(), contact_profile(s, knots),
                reference.orientation.copy())
    recipe = dict(
        schema="local-hidden-tail-candidate-v1", generator="generate.py:build_candidate",
        description="80mm长横；末端保留微小回收，总路程和范围均小于5mm。",
        source_recipe=str((SOURCE/"recipe.json").relative_to(ROOT)),
        width_mm=80., retained_source_points=[0, 34], origin_mm=origin.tolist(),
        continuation_bezier_controls_mm=continuation_controls,
        finishing_bezier_controls_mm=[first_controls, second_controls],
        bezier_samples_per_piece=181,
        magnetic_target=dict(interpolation="quintic", knots_s_uT=knots,
            status="unchanged candidate levels; stages remapped, not entry/exit calibration"),
        timing=reference_recipe["timing"],
        orientation=dict(tilt_deg=15., smoothing_mm=5.,
            policy="follow body and straight tangent continuation; do not follow the micro-return direction"),
        note="This local recipe uses generate.py, not the generic JSON CLI. The time/pose surrogate is not the saved XY target.",
    )
    plan = StrokePlan([st], dict(
        source="synthetic", coordinate_frame="paper", feature=FEATURE,
        filter_definition=source["filter_definition"], orientation_convention="base_rpy_rad",
        name="长横80mm：微小收笔候选", description=recipe["description"],
        source_target=str((SOURCE/"strokeplan.npz").relative_to(ROOT)),
        source_target_sha256=digest(SOURCE/"strokeplan.npz"),
        previous_target_sha256=digest(PREVIOUS/"heng/strokeplan.npz"),
        template_id=StrokePlan.load(SOURCE/"strokeplan.npz").meta["template_id"],
        xy_source="retained scaled template body, cubic continuation and two micro finishing Beziers",
        orientation_source=recipe["orientation"]["policy"],
        time_source="existing directional_stroke retimer on equal-arclength body-tangent reference; real XY independently preflighted",
        g_target_source="same candidate level amplitudes; remapped actual-arclength phases, not measured force or width",
        phase_control_points=rows, generation_recipe=recipe,
        validation="offline candidate; hiding the bend in real ink remains unverified"))
    plan.validate()
    return plan, recipe, points, micro_start, micro, rows


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    out = Path(__file__).resolve().parent
    if any(p.name not in {"generate.py", "__pycache__"} for p in out.iterdir()):
        raise FileExistsError("refusing to overwrite an output bundle")
    sources = [SOURCE/"recipe.json", SOURCE/"strokeplan.npz", PREVIOUS/"heng/strokeplan.npz"] + [
        CONTEXT/n for n in ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    plan, recipe, points, micro_start, micro, rows = build_candidate()
    st = plan.strokes[0]
    actual_arc = arc(st.xy*1000.)
    mask = actual_arc >= micro_start-1e-6
    assert st.t[-1] <= 20.
    assert np.linalg.norm(np.diff(st.xy[mask], axis=0), axis=1).sum()*1000. < 5.
    assert abs(np.ptp(st.xy[:, 0])*1000.-80.) < .02
    assert np.max(np.diff(st.g_target[st.s>=rows[5]["s"]])) <= 1e-8
    speed = np.linalg.norm(np.diff(st.xy, axis=0), axis=1)/np.diff(st.t)*1000.
    assert speed.max() <= 10.0001
    table, setup, entry, pi = [json.loads((CONTEXT/n).read_text()) for n in
                              ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    compiled = compile_recorded_plan(plan, table, setup, label="heng_80mm_hidden_tail_v5_pi",
                                    control_mode="pi", feedback_profile=pi, entry_profile=entry)
    limits = _check_trajectory(compiled["pose_m_rad"], setup, entry)
    headings = np.unwrap([orientation_heading(r) for r in st.orientation])
    summary = dict(
        writing_duration_s=float(st.t[-1]), full_nominal_motion_duration_s=float(compiled["t_s"][-1]),
        bbox_mm=np.ptp(st.xy*1000., axis=0).tolist(), length_mm=float(actual_arc[-1]),
        max_xy_speed_mm_s=float(speed.max()), g_target_range_uT=[float(st.g_target.min()), float(st.g_target.max())],
        finishing=dict(start_distance_mm=micro_start, start_s=float(micro_start/actual_arc[-1]),
            authored_length_mm=float(arc(micro)[-1]),
            sampled_length_mm=float(arc(st.xy[mask]*1000.)[-1]),
            authored_bbox_mm=np.ptp(micro, axis=0).tolist(), sampled_bbox_mm=np.ptp(st.xy[mask]*1000., axis=0).tolist(),
            x_return_from_rightmost_mm=float(np.max(micro[:, 0])-micro[-1, 0]),
            writing_duration_s=float(st.t[-1]-np.interp(micro_start, actual_arc, st.t)),
            tilt_azimuth_span_deg=float(np.rad2deg(np.ptp(headings[mask])))),
        control=compiled["spec_snapshot"]["control"], compiled_limits=limits,
        source_sha256=hashes, execution_context=str(CONTEXT.relative_to(ROOT)),
        validation="V3 reload, explicit <5mm checks, hard <=20s writing limit, real-XY directional compilation using Zhong PI profile; no hardware",
        limitations=["No ink image or width calibration; small XY region does not prove an invisible bend.",
            "Entry/exit candidate target amplitudes are not newly calibrated; L1 remains a contact tier.",
            "Independent entry_profile still includes the old 5mm reverse and original loading/lift sequence.",
            "Historical fixed-Ry15 table applied to dynamic pose and local speeds under the existing assumption."],
    )
    (out/"heng").mkdir()
    write_json(out/"heng/recipe.json", recipe)
    write_json(out/"heng/geometry.json", dict(points_local_mm=points.tolist(), micro_start_distance_mm=micro_start))
    plan.save(out/"heng/strokeplan.npz")
    StrokePlan.load(out/"heng/strokeplan.npz")
    with (out/"heng/phase_table.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out/"preflight").mkdir()
    np.savez_compressed(out/"preflight/compiled_heng_pi.npz", **{k: compiled[k] for k in
        ("t_s", "s", "phase", "pose_m_rad", "g_ref_uT", "depth_ff_m")},
        artifact_role="derived_nominal_trajectory_not_actual_feedback_commands")
    write_json(out/"preflight/resolved_control.json", compiled["spec_snapshot"]["control"])
    subprocess.run([sys.executable, str(PREVIEW), str(out/"heng/strokeplan.npz"), "--repo", str(ROOT),
                    "--output-dir", str(out/"heng/preview")], check=True, capture_output=True, text=True)

    previous = StrokePlan.load(PREVIOUS/"heng/strokeplan.npz").strokes[0]
    origin = np.asarray(recipe["origin_mm"])
    xy, old = st.xy*1000.-origin, previous.xy*1000.-origin
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for ax in axes[0]:
        ax.plot(old[:, 0], old[:, 1], color="0.65", lw=2, label="Previous: 8.7 mm finishing arc")
        ax.plot(xy[:, 0], xy[:, 1], color="#197e9b", lw=2, label="New: main body + local finish")
        ax.plot(xy[mask, 0], xy[mask, 1], color="#db7525", lw=2.5, label="Local finishing gesture")
        ax.set_aspect("equal", adjustable="box")
        ax.set(xlabel="Drawing right (mm)", ylabel="Drawing up (mm)")
        ax.grid(alpha=.25)
    axes[0, 0].set_title("Whole stroke stays 80 mm wide")
    axes[0, 0].legend(fontsize=8, loc="lower right")
    axes[0, 1].set(xlim=(30.5, 40.6), ylim=(3.7, 5.8), title="Main writing reaches the terminal region first")
    axes[1, 0].plot(xy[:, 0], xy[:, 1], color="#197e9b", lw=2)
    axes[1, 0].plot(xy[mask, 0], xy[mask, 1], color="#db7525", lw=2.5)
    axes[1, 0].scatter(*micro[0], color="green", s=20, label="Local gesture starts")
    axes[1, 0].scatter(*micro[-1], color="#db7525", marker="x", s=35, label="Ends after 1 mm return")
    low, span = micro.min(axis=0), np.ptp(micro, axis=0)
    axes[1, 0].add_patch(Rectangle(low, *span, fill=False, ls=":", color="0.4"))
    axes[1, 0].set(xlim=(38., 40.4), ylim=(4.05, 5.5), xlabel="Drawing right (mm)", ylabel="Drawing up (mm)",
                   title=f"Gesture: {span[0]:.1f} x {span[1]:.2f} mm; travel {arc(micro)[-1]:.2f} mm")
    axes[1, 0].set_aspect("equal", adjustable="box")
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].grid(alpha=.25)
    axes[1, 1].plot(actual_arc, st.g_target, color="#197e9b")
    axes[1, 1].axvline(micro_start, ls=":", color="#db7525", label="Local finish starts")
    axes[1, 1].set(xlim=(68., actual_arc[-1]+.2), xlabel="Actual path arclength (mm)", ylabel="Target (uT)",
                   title="Existing candidate levels; unload before micro return")
    axes[1, 1].legend(fontsize=8)
    axes[1, 1].grid(alpha=.25)
    fig.suptitle(f"80 mm Heng | writing {st.t[-1]:.2f} s | small geometry candidate, not predicted ink coverage")
    fig.tight_layout()
    fig.savefig(out/"comparison.png", dpi=170)
    plt.close(fig)
    assert hashes == {str(p.relative_to(ROOT)): digest(p) for p in sources}
    write_json(out/"summary.json", summary)
    readme = f"""# brush2 长横80mm：局部收笔小于5mm

主体先到末端区域，再作微小回收。局部收笔总路程{arc(micro)[-1]:.2f}mm，范围{span[0]:.1f}×{span[1]:.2f}mm，向左回收1mm；总路程和范围均小于5mm。几何目标是把弯折限制在末端小区域内，尚未证明真实墨迹能覆盖它。

书写{st.t[-1]:.2f}秒，名义完整运动{compiled['t_s'][-1]:.2f}秒，基线与启动定位另计。主体参考速度上限9.9mm/s，为最终重采样留出余量，实际目标速度不超过10mm/s；局部收笔由1.5渐降至0.8mm/s。

15度倾角的方位仅跟随主体和主体末端的直线延长参考，不追随微小回折；本次局部收笔方位变化{summary['finishing']['tilt_azimuth_span_deg']:.2f}度。时间／姿态参考与真实XY按等弧长对应，复用现有方向规划器，之后单独检查真实XY与名义Z的完整轨迹。无需修改生产生成器或执行器。

磁目标档位仍是候选值100..192.8228uT：在进入微小收笔区前由L4降至L2，在小区域内再降至L1。阶段按新弧长重算。这不是起收笔磁目标或笔宽标定完成；L1仍表示接触。独立entry_profile中的5mm反向进笔、加载和抬笔流程仍沿用旧配置，需继续讨论。

离线编译显式使用“中”实验的PI配置，反馈只在书写阶段启用。未连接硬件；通过预检不代表墨迹效果已验证。

![局部收笔对比](comparison.png)

目标：[heng/strokeplan.npz](heng/strokeplan.npz)；几何：[heng/geometry.json](heng/geometry.json)；报告：[summary.json](summary.json)。本包recipe.json是局部配方，由generate.py:build_candidate重建，不能直接传给通用JSON生成CLI。preflight/内为独立派生名义轨迹，包含查表Z，不是实际反馈或原始目标。
"""
    with (out/"README.md").open("x", encoding="utf-8") as stream:
        stream.write(readme)
    write_json(out/"manifest.json", {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*"))
                                     if p.is_file() and "__pycache__" not in p.parts})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
