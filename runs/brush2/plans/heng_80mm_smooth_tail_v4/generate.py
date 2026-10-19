#!/usr/bin/env python3
"""Offline brush2 80 mm Heng: replace the terminal return with a small arc."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from brushbot.experiments.strokeplan_character import orientation_heading
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from brushbot.target_strokeplan import StrokePlan
from scripts.generate_strokeplan_from_json import build_plan

SOURCE = ROOT / "runs/brush2/plans/template_four_strokes_100_240_zhong180_v3/heng"
CONTEXT = ROOT / "runs/brush2/plans/11_中字底横延长30mm_实测第9次"
PREVIEW = Path("/home/ethan/.codex/skills/brushbot-strokeplan/scripts/preview_target.py")
JOIN_INDEX = 34


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def arc_mm(points):
    return np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]


def matrices(rpy):
    """Base RPY convention: Rz(yaw) Ry(pitch) Rx(roll)."""
    r, p, y = np.asarray(rpy, float).T
    cr, sr, cp, sp, cy, sy = np.cos(r), np.sin(r), np.cos(p), np.sin(p), np.cos(y), np.sin(y)
    return np.stack([
        cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr,
        sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr,
        -sp, cp*sr, cp*cr,
    ], axis=-1).reshape((-1, 3, 3))


def kinematics(stroke, setup, tail_start_mm):
    """Geometric flange origin from commanded TCP + saved rigid tool transform.

    This is not joint IK, an actual flange recording or a brush contact model.
    """
    rotation = matrices(stroke.orientation)
    tool = np.asarray(setup["tool_coord_si"], float)
    tool_rotation = matrices(tool[None, 3:])[0]
    tcp_to_flange = -tool_rotation.T @ tool[:3]
    offset_mm = np.einsum("nij,j->ni", rotation, tcp_to_flange) * 1000.
    heading = np.unwrap([orientation_heading(r) for r in stroke.orientation])
    tail = stroke.s * arc_mm(stroke.xy * 1000.)[-1] >= tail_start_mm - 1e-6
    return dict(
        heading_deg=np.rad2deg(heading),
        offset_mm=offset_mm,
        flange_xy_mm=stroke.xy*1000. + offset_mm[:, :2],
        tail=tail,
        summary=dict(
            writing_tilt_deg_range=np.rad2deg(np.arccos(np.clip(rotation[:, 2, 2], -1., 1.)))[[0, -1]].tolist(),
            heading_span_deg=float(np.ptp(np.rad2deg(heading))),
            tail_heading_span_deg=float(np.ptp(np.rad2deg(heading[tail]))),
            tail_orientation_induced_flange_travel_mm=float(arc_mm(offset_mm[tail, :2])[-1]),
            horizontal_flange_offset_radius_mm=float(np.linalg.norm(offset_mm[:, :2], axis=1).mean()),
            yaw_deg_range=np.rad2deg(stroke.orientation[:, 2])[[np.argmin(stroke.orientation[:, 2]), np.argmax(stroke.orientation[:, 2])]].tolist(),
        ),
    )


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(__file__).resolve().parent
    if any(p.name not in {"generate.py", "__pycache__"} for p in output.iterdir()):
        raise FileExistsError("refusing to replace an existing output bundle")
    source_files = [SOURCE/"recipe.json", SOURCE/"strokeplan.npz"] + [
        CONTEXT/name for name in ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    initial_hashes = {str(p.relative_to(ROOT)): digest(p) for p in source_files}
    original = StrokePlan.load(SOURCE/"strokeplan.npz")
    recipe = json.loads((SOURCE/"recipe.json").read_text())
    old_points = np.asarray(recipe["path"]["points_mm"], float) * (80./120.)
    old_arc = arc_mm(old_points)
    body = old_points[:JOIN_INDEX+1]
    incoming = body[-1] - body[-2]
    p0 = body[-1]
    # The 80 mm path spans local x=-40..40. Preserve the body, blend
    # tangentially into a forward-only finishing arc, rising only 0.8 mm.
    p1 = p0 + np.array([3., 3.*incoming[1]/incoming[0]])
    p3 = np.array([40., p0[1]+.8])
    p2 = p3 - np.array([2., 0.])
    controls = np.array([p0, p1, p2, p3])
    u = np.linspace(0., 1., 181)[:, None]
    tail = (1-u)**3*p0 + 3*(1-u)**2*u*p1 + 3*(1-u)*u**2*p2 + u**3*p3
    points = np.vstack([body, tail[1:]])
    arc = arc_mm(points)
    join_distance = float(arc[JOIN_INDEX])
    tail_length = float(arc[-1] - join_distance)
    assert np.all(np.diff(tail[:, 0]) > 0.)
    assert np.ptp(tail[:, 1]) <= 1. + 1e-12
    outgoing = p1-p0
    assert abs(incoming[0]*outgoing[1] - incoming[1]*outgoing[0]) < 1e-9

    rows = []
    for index, action, level in [(0, "尖起", 100.), (1, "斜切轻按", 192.8228205467164),
                                (3, "转入行笔", 192.8228205467164),
                                (18, "前半段渐提", 124.46659545769568),
                                (23, "中段较细", 124.46659545769568),
                                (34, "后半段渐按／开始小弧收笔", 192.8228205467164)]:
        rows.append(dict(source_point_index=index, action=action, distance_mm=float(arc[index]),
                         s=float(arc[index]/arc[-1]), g_target_uT=level))
    for fraction, action, level in [(.6, "小弧提笔，取消尾部再加载", 124.46659545769568),
                                    (1., "结束接触目标，随后由执行器抬笔", 100.)]:
        distance = join_distance + fraction*tail_length
        rows.append(dict(source_point_index=None, action=action, distance_mm=float(distance),
                         s=float(distance/arc[-1]), g_target_uT=level))
    recipe.update(name="长横80mm：局部小弧收笔", description="保留主体、80mm宽；以切线连续的小弧替换尾端大回折，逐步降低收笔磁目标。")
    recipe["placement"]["scale"] = 1.
    recipe["path"] = dict(kind="rounded_polyline", points_mm=points.tolist(), corner_radius_mm=0.)
    recipe["magnetic_target"]["knots_s_uT"] = [[r["s"], r["g_target_uT"]] for r in rows]
    recipe["timing"]["speed_knots_s_mm_s"] = [
        [0., 3.], [rows[1]["s"], 3.], [rows[2]["s"], 3.],
        [rows[2]["s"]+.05, 10.], [rows[5]["s"]-.02, 10.],
        [rows[5]["s"], 7.], [1., 3.],
    ]
    recipe["notes"] = [
        "主体与起笔形状沿用v3，以原始120mm几何统一缩放至80mm。",
        "尾端从源点34开始，由密集采样的三次Bezier替换；接点与主体切线一致、末端切线沿+X。",
        "尾部不向-X回折，纵向总变化0.8mm；这些是待试写的工程初值，不是墨迹预测。",
        "磁阶段按新几何弧长重算；尾部L4→L2→L1，取消L2→L3再加载。",
        "100..240uT为五档合成宽度意图；本横实际使用100..192.8228uT，未标定真实宽度。",
        "15度沿平滑切线倾斜、5mm姿态平滑和既有运动限值沿用v3。",
        "缩小后起笔3mm/s，转入主体后升至10mm/s；收笔由7渐降至3mm/s，控制名义加速度。",
        "仅沿XY书写段受20秒上限约束；进笔、加载、抬笔、返回和基线另计。",
        "起笔、进入接触和抬笔流程仍由独立的既有entry_profile定义。",
    ]
    plan = build_plan(recipe)
    plan.meta.update(
        source_target=str((SOURCE/"strokeplan.npz").relative_to(ROOT)),
        source_target_sha256=digest(SOURCE/"strokeplan.npz"),
        template_id=original.meta["template_id"],
        phase_control_points=rows,
        geometry_review_status="authored tail revision; offline only, ink quality untested",
        geometry_revision=dict(method="sampled cubic Bezier after retained source point 34",
                               control_points_local_mm=controls.tolist(), width_mm=80.,
                               endpoint_return_mm=0., tail_rise_mm=.8),
        max_writing_duration_s=20.,
    )
    st = plan.strokes[0]
    assert st.t[-1] <= 20.
    assert abs(np.ptp(st.xy[:, 0])*1000.-80.) < .05
    tail_samples = st.s >= join_distance/arc[-1]
    assert np.min(np.diff(st.xy[tail_samples, 0])) >= -1e-12
    assert np.max(np.diff(st.g_target[tail_samples])) <= 1e-8
    assert st.g_target.min() >= 100.-1e-9 and st.g_target.max() <= 240.+1e-9

    table, setup, entry, pi = [json.loads((CONTEXT/name).read_text()) for name in
                              ("feedforward.json", "settings.json", "entry_profile.json", "pi_profile.json")]
    compiled = compile_recorded_plan(plan, table, setup, label="heng_80mm_smooth_tail_v4_pi",
                                    control_mode="pi", feedback_profile=pi, entry_profile=entry)
    limits = _check_trajectory(compiled["pose_m_rad"], setup, entry)
    assert compiled["spec_snapshot"]["control"]["enabled"] is True
    assert compiled["spec_snapshot"]["control"]["mode"] == "pi"
    assert np.count_nonzero(compiled["phase"] == "measure_00")*.02 <= 20.

    # A size-only 80 mm control isolates the tail edit in the comparison plot.
    size_only_recipe = json.loads((SOURCE/"recipe.json").read_text())
    size_only_recipe["placement"]["scale"] = 80./120.
    size_only = build_plan(size_only_recipe).strokes[0]
    old_kin = kinematics(size_only, setup, float(old_arc[JOIN_INDEX]))
    new_kin = kinematics(st, setup, join_distance)
    original_kin = kinematics(original.strokes[0], setup, float(old_arc[JOIN_INDEX]*110./80.))
    speeds = np.linalg.norm(np.diff(st.xy, axis=0), axis=1)/np.diff(st.t)*1000.
    summary = dict(
        artifact_role="offline target candidate and independent nominal preflight",
        writing_duration_s=float(st.t[-1]),
        measurement_phase_duration_s=float(np.count_nonzero(compiled["phase"] == "measure_00")*.02),
        full_nominal_motion_duration_s=float(compiled["t_s"][-1]),
        bbox_mm=np.ptp(st.xy*1000., axis=0).tolist(), length_mm=float(arc_mm(st.xy*1000.)[-1]),
        max_xy_speed_mm_s=float(speeds.max()),
        g_target_range_uT=[float(st.g_target.min()), float(st.g_target.max())],
        tail=dict(start_s=float(join_distance/arc[-1]), length_mm=tail_length,
                  forward_span_mm=float(tail[-1, 0]-tail[0, 0]), rise_mm=.8, return_mm=0.,
                  control_points_local_mm=controls.tolist()),
        old_v3=dict(width_mm=110., duration_s=float(original.strokes[0].t[-1]),
                    kinematics=original_kin["summary"]),
        size_only_80mm=dict(duration_s=float(size_only.t[-1]),
                            tail_return_mm=float(np.max(old_points[JOIN_INDEX:, 0])-old_points[-1, 0]),
                            kinematics=old_kin["summary"]),
        revised_80mm=dict(kinematics=new_kin["summary"]),
        kinematics_scope="Rigid tool geometry from planned TCP; no joint IK, joint limits, collision verification, contact-tip or actual flange measurement.",
        compiled_limits=limits, control=compiled["spec_snapshot"]["control"],
        execution_context=str(CONTEXT.relative_to(ROOT)), source_sha256=initial_hashes,
        calibration_assumption="Historical +X fixed-Ry15 table reused at varying azimuths and local speeds; no new calibration claimed.",
        validation="V3 reload, geometry/stage assertions, existing directional compilation with Zhong PI profile and separate nominal trajectory limits; no hardware",
    )

    folder = output/"heng"
    folder.mkdir()
    write_json(folder/"recipe.json", recipe)
    plan.save(folder/"strokeplan.npz")
    loaded = StrokePlan.load(folder/"strokeplan.npz")
    assert np.array_equal(loaded.strokes[0].xy, st.xy)
    with (folder/"phase_table.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output/"preflight").mkdir()
    np.savez_compressed(output/"preflight/compiled_heng_pi.npz", **{k: compiled[k] for k in
                       ("t_s", "s", "phase", "pose_m_rad", "g_ref_uT", "depth_ff_m")},
                       artifact_role="derived_nominal_trajectory_not_feedback_commands")
    write_json(output/"preflight/resolved_control.json", compiled["spec_snapshot"]["control"])
    subprocess.run([sys.executable, str(PREVIEW), str(folder/"strokeplan.npz"), "--repo", str(ROOT),
                    "--output-dir", str(folder/"preview")], check=True, capture_output=True, text=True)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.7))
    origin = np.asarray(recipe["placement"]["origin_mm"])
    a, b = size_only.xy*1000.-origin, st.xy*1000.-origin
    for ax in axes[:2]:
        ax.plot(a[:, 0], a[:, 1], color="0.6", lw=2., label="Original shape scaled to 80 mm")
        ax.plot(b[:, 0], b[:, 1], color="#167eaa", lw=2., label="Revised 80 mm: small finishing arc")
        ax.scatter(*b[-1], color="#167eaa", marker="x", s=45, zorder=5)
        ax.set_aspect("equal", adjustable="box")
        ax.set(xlabel="Drawing right (mm)", ylabel="Drawing up (mm)")
        ax.grid(alpha=.25)
    axes[0].set_title("Body retained; only the ending is redrawn")
    axes[0].legend(fontsize=8, loc="lower right")
    axes[1].set(xlim=(29., 41.), ylim=(.5, 7.7), title="Tail detail: no leftward return")
    axes[2].plot(size_only.s, size_only.g_target, color="0.6", label="Size-only control")
    axes[2].plot(st.s, st.g_target, color="#167eaa", label="Revised / remapped stages")
    axes[2].axvline(join_distance/arc[-1], color="#167eaa", ls=":", lw=1.)
    axes[2].set(xlabel="Normalized path arclength", ylabel="Magnetic target (uT)",
                title="Tail target falls without a second loading")
    axes[2].grid(alpha=.25)
    axes[2].legend(fontsize=8)
    fig.suptitle(f"Heng candidate | width 80 mm | writing {st.t[-1]:.2f} s | geometry targets, not predicted ink")
    fig.tight_layout()
    fig.savefig(output/"comparison.png", dpi=170)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.7))
    for kin, label, color in [(old_kin, "Original shape / 80 mm", "0.6"),
                               (new_kin, "Revised / 80 mm", "#167eaa")]:
        axes[0].plot(kin["offset_mm"][:, 0], kin["offset_mm"][:, 1], color=color, label=label)
        axes[0].plot(kin["offset_mm"][kin["tail"], 0], kin["offset_mm"][kin["tail"], 1], color=color, lw=3)
        axes[1].plot(kin["flange_xy_mm"][:, 0]-origin[0], kin["flange_xy_mm"][:, 1]-origin[1], color=color, label=label)
    angle = np.linspace(0., 2*np.pi, 361)
    radius = new_kin["summary"]["horizontal_flange_offset_radius_mm"]
    axes[0].plot(radius*np.cos(angle), radius*np.sin(angle), ls=":", lw=1., color="0.75", label="Possible offsets at 15 deg (not a commanded circle)")
    axes[0].scatter(0., 0., color="black", marker="+", label="TCP reference")
    axes[0].set(title=f"Flange offset from TCP: radius {radius:.1f} mm", xlabel="Relative X (mm)", ylabel="Relative Y (mm)")
    axes[1].plot(b[:, 0], b[:, 1], color="#e88919", ls="--", label="Revised TCP path")
    axes[1].set(title="Geometrically inferred flange XY", xlabel="Drawing right (mm)", ylabel="Drawing up (mm)")
    axes[2].plot(size_only.s, old_kin["heading_deg"], color="0.6", label="Original shape / 80 mm")
    axes[2].plot(st.s, new_kin["heading_deg"], color="#167eaa", label="Revised / 80 mm")
    axes[2].set(title="Tilt azimuth follows the smoothed tangent", xlabel="Normalized path arclength", ylabel="Tilt azimuth (deg)")
    for ax in axes:
        ax.grid(alpha=.25)
        ax.legend(fontsize=7, loc="best")
    for ax in axes[:2]:
        ax.set_aspect("equal", adjustable="box")
    fig.suptitle("15 deg tilt + saved 262 mm tool | rigid geometry only; no joint IK or measured flange trajectory")
    fig.tight_layout()
    fig.savefig(output/"tilt_geometry.png", dpi=170)
    plt.close(fig)

    assert initial_hashes == {str(p.relative_to(ROOT)): digest(p) for p in source_files}
    write_json(output/"summary.json", summary)
    readme = f"""# brush2 长横80mm：小弧收笔候选

保留v3主体，统一缩为80mm宽；从源点34开始，用切线连续的三次Bezier小弧替换原来的尾部大回折。新尾部向前约{summary['tail']['forward_span_mm']:.2f}mm、上升0.8mm，不向左回移。起笔形状与进出笔配置未修改。

书写段{st.t[-1]:.2f}秒，名义完整运动{compiled['t_s'][-1]:.2f}秒，基线和启动定位另计。主体速度上限10mm/s；起笔3mm/s，收笔7渐降至3mm/s，以约束缩小后的名义加速度。沿用15度切线倾斜、5mm姿态平滑和原执行器限值。目标使用100..192.8228uT，仍为合成宽度意图。

磁阶段按新几何重新映射；收笔L4→L2→L1，不再中途加回L3。L1仍是接触档位，之后执行器按原流程抬笔。

离线编译显式采用“中”实验目录的PI配置（kp=1、ki=0.1、修正限幅±0.8mm），反馈仅在书写阶段启用。该配置记录在preflight/resolved_control.json；目标文件本身不包含控制器配置。现有低层CLI仅改--control-mode pi不能传入这份PI配置，本包未附带会回落到纯前馈的执行指令。

已通过V3重载、几何／阶段断言和现有方向执行器的名义轨迹检查。compiled_heng_pi.npz是独立的派生名义轨迹，不包含真实反馈修正。未连接机器人，未验证墨迹质量或新的标定适用性。

![新旧轨迹对比](comparison.png)

![倾角与法兰运动示意](tilt_geometry.png)

15度是笔杆倾角，倾斜方位仍随平滑切线变化。姿态构造Rz(h)Ry(15)Rz(-h)避免把行笔方向直接变成绕笔轴整圈旋转，但长工具的法兰仍需绕TCP发生位置变化。按保存的刚性TCP变换推算，262mm工具在15度时水平偏置半径约{radius:.1f}mm。图中的虚线圆只是可能偏置的集合，不是机器人要执行一整圈；图中法兰来自刚性几何推算，未做关节逆解、碰撞检查或真实法兰测量，笔毛接触形态也不包含在这个模型中。

目标：[heng/strokeplan.npz](heng/strokeplan.npz)；配方：[heng/recipe.json](heng/recipe.json)；阶段：[heng/phase_table.csv](heng/phase_table.csv)；报告：[summary.json](summary.json)。源计划和现场配置的哈希已核对不变。
"""
    with (output/"README.md").open("x", encoding="utf-8") as stream:
        stream.write(readme)
    write_json(output/"manifest.json", {str(p.relative_to(output)): digest(p)
                                      for p in sorted(output.rglob("*"))
                                      if p.is_file() and "__pycache__" not in p.parts})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
