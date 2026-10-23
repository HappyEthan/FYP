#!/usr/bin/env python3
"""Offline short-Heng candidate: gradual expansion and a compact finish."""
from __future__ import annotations

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

TEMPLATE = ROOT/"outputs/stroke_templates/strokes/sohu_heng_20261017_final/templates/heng_short"
LONG = ROOT/"runs/brush2/plans/heng_80mm_hidden_tail_v5/heng/strokeplan.npz"
CONTEXT = ROOT/"runs/brush2/plans/11_中字底横延长30mm_实测第9次"
PREVIEW = ROOT / "scripts/preview_strokeplan.py"
LEVELS = [100., 124.46659545769568, 154.91933384829667, 192.8228205467164, 240.]


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
    template = json.loads((TEMPLATE/"template.json").read_text())
    source = np.asarray(template["references"][0]["xy_px"], float)
    assert template["variant"] == "short"
    assert template["references"][0]["anchors"] == [0, 3, 18, 24]
    # Use the source Cartesian guide, not its body-normalized prototype.
    # Scale the entry independently, retaining the short-Heng body's rise.
    entry_scale = 1.8/arc(source[:4])[-1]
    entry_rel = (source[:4]-source[3])*entry_scale
    body_anchor_x = -20.-entry_rel[0, 0]
    body_scale = (16.5-body_anchor_x)/(source[18, 0]-source[3, 0])
    body = (source[3:19]-source[3])*body_scale+[body_anchor_x, 0.]
    entry = entry_rel+body[0]
    retained = np.vstack([entry[:-1], body])

    direction = body[-1]-body[0]
    direction /= np.linalg.norm(direction)
    normal = np.array([-direction[1], direction[0]])
    basis = np.column_stack([direction, normal])
    first_local = np.array([[0., 0.], [.7, 0.], [1.5, .3], [1.5, -.2]])
    second_local = np.array([[1.5, -.2], [1.5, -.7], [.6, -.65], [.5, -.5]])
    first, second = bezier(first_local), bezier(second_local)
    micro_rel = np.vstack([first, second[1:]])@basis.T
    cap_x = 20.-micro_rel[:, 0].max()
    cap = body[-1]+(cap_x-body[-1, 0])/direction[0]*direction
    incoming = body[-1]-body[-2]
    incoming /= np.linalg.norm(incoming)
    controls = np.array([body[-1], body[-1]+.8*incoming, cap-.8*direction, cap])
    continuation = bezier(controls)
    micro = micro_rel+cap
    prefix = np.vstack([retained, continuation[1:]])
    points = np.vstack([prefix, micro[1:]])
    shift_y = -.5*(points[:, 1].min()+points[:, 1].max())
    points[:, 1] += shift_y
    micro[:, 1] += shift_y
    controls[:, 1] += shift_y
    cap[1] += shift_y
    d = arc(points)
    micro_index = len(prefix)-1
    raw_micro_start = float(d[micro_index])
    assert abs(np.ptp(points[:, 0])-40.) < 1e-10
    assert abs(arc(points[:4])[-1]-1.8) < 1e-10
    assert arc(micro)[-1] < 5.

    # The single growing body target comes from the short-Heng rule. These
    # are authored ordinal levels, not inferred force/contact-width values.
    specifications = [
        (0, "尖起", LEVELS[0], "L1"),
        (1, "斜切轻按", LEVELS[1], "L2"),
        (3, "转入右上行笔", LEVELS[1], "L2"),
        (10, "主体逐渐展开", LEVELS[2], "L3"),
        (18, "右端展开至较粗处", LEVELS[3], "L4"),
        (micro_index, "提锋后进入微小收笔区", LEVELS[1], "L2"),
        (len(points)-1, "回收结束，随后抬笔", LEVELS[0], "L1"),
    ]
    rows = [dict(source_point_index=(index if index<=18 else None), action=action,
                 distance_mm=float(d[index]), s=float(d[index]/d[-1]),
                 level=level, g_target_uT=target)
            for index, action, target, level in specifications]
    knots = [[r["s"], r["g_target_uT"]] for r in rows]

    # Reuse the existing direction/time planner, with a straight virtual
    # continuation for the end gesture's tilt. Save actual curved XY below.
    proxy = points.copy()
    proxy[micro_index:] = cap+(d[micro_index:]-raw_micro_start)[:, None]*direction
    assert np.allclose(arc(proxy), d, atol=1e-10, rtol=0)
    pre_peak = (d[18]-4.)/d[-1]
    speed_knots = [[0., 1.5], [rows[1]["s"], 2.], [rows[2]["s"], 2.],
        [(d[3]+2.)/d[-1], 8.], [pre_peak, 8.], [rows[4]["s"], 2.],
        [rows[5]["s"], 1.5], [1., .8]]
    reference_recipe = dict(schema_version=1, id="heng_short", name="短横40mm",
        description="右上行笔、渐行渐粗、局部提锋收束。",
        reference=str((TEMPLATE/"template.json").relative_to(ROOT)),
        placement=dict(origin_mm=[140., 0.], rotation_deg=0., scale=1.),
        path=dict(kind="rounded_polyline", points_mm=proxy.tolist(), corner_radius_mm=0.),
        magnetic_target=dict(interpolation="quintic", knots_s_uT=knots),
        timing=dict(speed_mm_s=8., accel_mm_s2=30., angular_speed_deg_s=20.,
                    angular_accel_deg_s2=35., speed_knots_s_mm_s=speed_knots),
        orientation=dict(kind="tangent_tilt", tilt_deg=15., smoothing_mm=5.),
        filter_definition=dict(kind="ema", alpha=.3))
    reference = build_plan(reference_recipe).strokes[0]
    origin = np.array([140., 0.])
    xy = reference.xy*1000.-origin
    along = (xy-cap)@direction
    local = along >= 0.
    distance = raw_micro_start+along[local]
    xy[local] = np.column_stack([np.interp(distance, d, points[:, i]) for i in range(2)])
    final_arc = arc(xy)
    k = int(np.flatnonzero(local)[0])
    micro_start = float(np.interp(0., along[k-1:k+1], final_arc[k-1:k+1]))
    rows[-2]["distance_mm"] = micro_start
    rows[-1]["distance_mm"] = float(final_arc[-1])
    for row in rows:
        row["s"] = row["distance_mm"]/final_arc[-1]
    knots = [[r["s"], r["g_target_uT"]] for r in rows]
    s = final_arc/final_arc[-1]
    st = Stroke(s, (xy+origin)/1000., reference.t.copy(), contact_profile(s, knots),
                reference.orientation.copy())
    recipe = dict(schema="short-heng-candidate-v1", generator="generate.py:build_candidate",
        width_mm=40., width_basis="authored default: half of the current 80mm long-Heng",
        source_template_id=template["template_id"],
        source_template=str((TEMPLATE/"template.json").relative_to(ROOT)),
        source_review_status=template["guide_trace"]["review_status"],
        rule="向右上行笔，宽度逐渐展开；末端提锋描边收笔。",
        entry_length_mm=1.8, entry_mm_per_source_px=float(entry_scale),
        body_mm_per_source_px=float(body_scale), retained_source_points=[0, 18],
        continuation_controls_local_mm=controls.tolist(),
        finishing_controls_body_frame_mm=[first_local.tolist(), second_local.tolist()],
        finishing_body_heading_deg=float(np.rad2deg(np.arctan2(direction[1], direction[0]))),
        bezier_samples_per_piece=181, origin_mm=origin.tolist(),
        magnetic_target=dict(interpolation="quintic", knots_s_uT=knots,
                             available_levels_uT=LEVELS, status="authored width intention; no physical width calibration"),
        timing=reference_recipe["timing"],
        orientation=dict(tilt_deg=15., smoothing_mm=5.,
                         policy="follow body and its straight continuation; do not chase the small finishing return"),
        notes=["起笔动作与主体分别缩放，末端小动作总路程小于5mm。",
               "短横主体单调增至L4；收笔降至L2和L1，无行笔中段的减小再增大。",
               "本地recipe由generate.py重建；不直接兼容通用JSON生成CLI。"])
    plan = StrokePlan([st], dict(source="synthetic", coordinate_frame="paper", feature=FEATURE,
        filter_definition=dict(kind="ema", alpha=.3), orientation_convention="base_rpy_rad",
        name="短横40mm：渐行渐粗与微小收笔", template_id=template["template_id"],
        source_template_sha256=digest(TEMPLATE/"template.json"),
        xy_source="Cartesian source guide; independently scaled entry/body; authored compact finishing gesture",
        g_target_source="authored five-level intention from short-Heng caption; not measured magnetic field, force or width",
        orientation_source=recipe["orientation"]["policy"],
        time_source="existing directional_stroke retimer on equal-distance body reference; actual XY independently preflighted",
        phase_control_points=rows, generation_recipe=recipe,
        max_writing_duration_s=20., validation="synthetic target candidate; paper-ink appearance untested"))
    plan.validate()
    return plan, recipe, points, micro, micro_start, rows


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(__file__).resolve().parent
    if any(p.name not in {"generate.py", "__pycache__"} for p in out.iterdir()):
        raise FileExistsError("refusing to replace an output bundle")
    sources = [TEMPLATE/"template.json", TEMPLATE/"source.jpg", TEMPLATE/"raw_trace.json", LONG] + [
        CONTEXT/n for n in ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    plan, recipe, points, micro, micro_start, rows = build_candidate()
    st = plan.strokes[0]
    distance = arc(st.xy*1000.)
    speed = np.linalg.norm(np.diff(st.xy, axis=0), axis=1)/np.diff(st.t)*1000.
    assert st.t[-1] <= 20.
    assert abs(np.ptp(st.xy[:, 0])*1000.-40.) < .02
    assert speed.max() <= 10.0001
    peak_s = rows[4]["s"]
    assert np.all(np.diff(st.g_target[st.s<=peak_s]) >= -1e-8)
    assert np.all(np.diff(st.g_target[st.s>=peak_s]) <= 1e-8)
    assert st.g_target.min() >= 100.-1e-8 and st.g_target.max() <= LEVELS[3]+1e-8
    table, setup, entry, pi = [json.loads((CONTEXT/n).read_text()) for n in
                              ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    compiled = compile_recorded_plan(plan, table, setup, label="heng_short_40mm_gradual_v1_pi",
                                    control_mode="pi", feedback_profile=pi, entry_profile=entry)
    limits = _check_trajectory(compiled["pose_m_rad"], setup, entry)
    assert np.count_nonzero(compiled["phase"]=="measure_00")*.02 <= 20.
    tail_mask = distance>=micro_start
    heading = np.unwrap([orientation_heading(r) for r in st.orientation])
    summary = dict(writing_duration_s=float(st.t[-1]),
        full_nominal_motion_duration_s=float(compiled["t_s"][-1]),
        bbox_mm=np.ptp(st.xy*1000., axis=0).tolist(), path_length_mm=float(distance[-1]),
        max_xy_speed_mm_s=float(speed.max()), g_target_range_uT=[float(st.g_target.min()), float(st.g_target.max())],
        magnetic_rule="single monotonic expansion to L4, then unloading through L2 to L1",
        in_plan_entry_length_mm=1.8,
        finishing=dict(authored_length_mm=float(arc(micro)[-1]), authored_bbox_mm=np.ptp(micro, axis=0).tolist(),
                       start_distance_mm=micro_start, start_s=float(micro_start/distance[-1]),
                       tilt_azimuth_span_deg=float(np.rad2deg(np.ptp(heading[tail_mask])))),
        control=compiled["spec_snapshot"]["control"], compiled_limits=limits,
        source_sha256=hashes, execution_context=str(CONTEXT.relative_to(ROOT)),
        validation="V3 reload, monotonic short-Heng phase assertions, <=20s, actual-XY full nominal preflight with Zhong PI; no hardware",
        limitations=["Synthetic target levels are not calibrated physical widths or forces.",
            "Small finishing geometry does not guarantee the bend is invisible in ink.",
            "Independent old entry_profile still adds 5mm reverse before the target and uses the original load/lift sequence.",
            "Historical +X fixed-Ry15 table reused at varying azimuths/local speeds under the existing trial assumption."])
    (out/"heng_short").mkdir()
    plan.save(out/"heng_short/strokeplan.npz")
    StrokePlan.load(out/"heng_short/strokeplan.npz")
    write_json(out/"heng_short/recipe.json", recipe)
    write_json(out/"heng_short/geometry.json", dict(points_local_mm=points.tolist(), micro_points_local_mm=micro.tolist()))
    with (out/"heng_short/phase_table.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out/"preflight").mkdir()
    np.savez_compressed(out/"preflight/compiled_heng_short_pi.npz", **{k: compiled[k] for k in
        ("t_s", "s", "phase", "pose_m_rad", "g_ref_uT", "depth_ff_m")},
        artifact_role="derived_nominal_trajectory_not_actual_feedback_commands")
    write_json(out/"preflight/resolved_control.json", compiled["spec_snapshot"]["control"])
    subprocess.run([sys.executable, str(PREVIEW), str(out/"heng_short/strokeplan.npz"), "--repo", str(ROOT),
                    "--output-dir", str(out/"heng_short/preview")], check=True, capture_output=True, text=True)

    long = StrokePlan.load(LONG).strokes[0]
    xy = st.xy*1000.-np.array([140., 0.])
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    axes[0].plot(long.xy[:, 0]*1000.-140., long.xy[:, 1]*1000., color="0.78", lw=2, label="Long-Heng / 80 mm")
    axes[0].plot(xy[:, 0], xy[:, 1], color="#197e9b", lw=2, label="Short-Heng / 40 mm")
    axes[0].plot(xy[tail_mask, 0], xy[tail_mask, 1], color="#d87525", lw=2, label="Local finish")
    axes[0].set_aspect("equal", adjustable="datalim")
    axes[0].set(xlabel="Drawing right (mm)", ylabel="Drawing up (mm)", title="Right-upward body; compact entry/finish")
    axes[0].legend(fontsize=8)
    axes[1].plot(distance, st.g_target, color="#197e9b")
    axes[1].scatter([r["distance_mm"] for r in rows], [r["g_target_uT"] for r in rows], s=16, color="#d87525")
    axes[1].set(xlabel="Arclength (mm)", ylabel="Magnetic target (uT)", title="Short-Heng: progressive expansion, then unload")
    axes[2].plot(st.t, st.g_target, color="#197e9b")
    axes[2].set(xlabel="Writing time (s)", ylabel="Magnetic target (uT)", title=f"Writing {st.t[-1]:.2f} s / no added dwell")
    for ax in axes:
        ax.grid(alpha=.25)
    fig.suptitle("Synthetic short-Heng candidate | manually authored magnetic targets; no physical-width or ink validation")
    fig.tight_layout()
    fig.savefig(out/"overview.png", dpi=170)
    plt.close(fig)
    assert hashes == {str(p.relative_to(ROOT)): digest(p) for p in sources}
    write_json(out/"summary.json", summary)
    readme = f"""# brush2 短横40mm：渐行渐粗候选

参考短横原图及描述“向右上行笔，宽度逐渐展开；末端转向收笔”。默认宽40mm，为当前长横80mm的一半；采用原图笛卡尔引导线的主体，起笔动作另缩为1.8mm路程，收笔另设为{arc(micro)[-1]:.2f}mm路程的小区域动作。该40mm尺寸和数值均是本轮工程初值。

磁目标按短横规则单次渐增：100→124.47→154.92→192.82→124.47→100uT。L2在进入主体处短暂保持，此后主体逐渐升至L4，右端提锋后回落。可用五档仍是100..240uT，本笔未使用L5。磁目标是人工合成宽度意图，未标定真实笔宽或起收笔接触状态。

书写{st.t[-1]:.2f}秒，名义完整运动{compiled['t_s'][-1]:.2f}秒，基线与启动定位另计。主体速度上限8mm/s，起笔1.5..2mm/s，末端局部动作1.5渐降至0.8mm/s；未加原地停驻。

沿用15度书写倾角，倾斜方位参考主体与其直线延长，不追随局部回收。小收笔范围约{np.ptp(micro,axis=0)[0]:.2f}×{np.ptp(micro,axis=0)[1]:.2f}mm，总路程小于5mm；是否能藏在墨迹内仍需试写。

已通过V3重载、短横磁目标单调阶段检查、20秒上限和独立方向执行器的名义预检。离线编译显式加载“中”实验PI配置；反馈仅在书写阶段启用。未连接机器人，未提高限值。

本包仅生成书写目标。独立旧entry_profile仍有额外5mm反向进笔，加载与抬笔流程也未修改，不能把计划内1.8mm起笔理解成整个落笔流程都已缩短。旧+X固定Ry15前馈表在不同方位和低速下的适用性仍属实验假设。

![短横候选](overview.png)

目标：[heng_short/strokeplan.npz](heng_short/strokeplan.npz)；配方：[heng_short/recipe.json](heng_short/recipe.json)；阶段：[heng_short/phase_table.csv](heng_short/phase_table.csv)；报告：[summary.json](summary.json)。本地配方由generate.py:build_candidate重建，不直接兼容通用JSON生成CLI。preflight内为独立派生名义轨迹，不是原始目标或真实反馈记录。原模板、长横与现场配置哈希均保持不变。
"""
    with (out/"README.md").open("x", encoding="utf-8") as stream:
        stream.write(readme)
    write_json(out/"manifest.json", {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*"))
                                     if p.is_file() and "__pycache__" not in p.parts})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
