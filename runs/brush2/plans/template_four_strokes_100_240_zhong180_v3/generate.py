#!/usr/bin/env python3
"""Generate four brush2 targets with a hard 20-second writing limit, offline."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from brushbot.target_strokeplan import StrokePlan
from brushbot.experiments.strokeplan_execution import compile_recorded_plan
from brushbot.experiments.z_identification import _check_trajectory
from scripts.generate_calligraphy_trial import contact_profile
from scripts.generate_strokeplan_from_json import build_plan

SOURCE = ROOT / 'runs/brush2/plans/template_four_strokes_100_240_zhong180_v1'
CONTEXT = ROOT / 'runs/brush2/plans/11_中字底横延长30mm_实测第9次'
PREVIEW = Path('/home/ethan/.codex/skills/brushbot-strokeplan/scripts/preview_target.py')
SPECS = [
    dict(id='heng', name='长横', label='Heng / long horizontal', axis=0,
         original_span_mm=120., span_mm=110., smoothing_mm=5., angular_accel=40.),
    dict(id='shu', name='悬针竖', label='Shu / pointed vertical', axis=1,
         original_span_mm=180., span_mm=170., smoothing_mm=5., angular_accel=40.),
    dict(id='pie', name='斜撇', label='Pie / left falling', axis=0,
         original_span_mm=140., span_mm=100., smoothing_mm=6., angular_accel=30.),
    dict(id='na', name='斜捺', label='Na / right falling', axis=0,
         original_span_mm=140., span_mm=140., smoothing_mm=6., angular_accel=30.),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    output = Path(__file__).resolve().parent
    if any(p.name != 'generate.py' for p in output.iterdir()):
        raise FileExistsError('refusing to replace an existing output bundle')
    table, setup, entry = [json.loads((CONTEXT / name).read_text()) for name in
                           ['feedforward.json', 'settings.json', 'entry_profile.json']]
    context_hashes = {name: digest(CONTEXT / name) for name in
                     ['feedforward.json', 'settings.json', 'entry_profile.json']}
    reference = StrokePlan.load(CONTEXT / 'character.npz')
    plotting_spec = importlib.util.spec_from_file_location('original_target_panels', SOURCE / 'generate.py')
    plotting = importlib.util.module_from_spec(plotting_spec)
    plotting_spec.loader.exec_module(plotting)
    report = dict(
        validation='V3 reload, hard writing-duration assertion, full directional-executor preflight; no hardware',
        max_writing_duration_s=20., dt_s=.02,
        duration_definition='XY writing phase; entry, loading, lift, return and baseline are additional',
        execution_context=str(CONTEXT.relative_to(ROOT)),
        execution_context_sha256=context_hashes,
        reference_character=str((CONTEXT / 'character.npz').relative_to(ROOT)),
        reference_sha256=digest(CONTEXT / 'character.npz'),
        reference_writing_durations_s=[float(st.t[-1]) for st in reference.strokes],
        table_assumption='Historical +X, 10 mm/s, fixed Ry15 table reused for other directions, slower local motion and tilt azimuths; unvalidated experimentally.',
        coordinate_frame='paper; drawing right +X, drawing up +Y',
        magnetic_intent='Same 100..240 uT geometric levels and normalized-arclength knots as v1; no physical width calibration',
        executor_limits_changed=False, strokes=[])
    prepared = []
    for spec in SPECS:
        name = spec['id']
        original = StrokePlan.load(SOURCE / name / 'strokeplan.npz')
        recipe = json.loads((SOURCE / name / 'recipe.json').read_text())
        scale = spec['span_mm'] / spec['original_span_mm']
        recipe['placement']['scale'] = scale
        recipe['orientation']['smoothing_mm'] = spec['smoothing_mm']
        recipe['timing']['angular_accel_deg_s2'] = spec['angular_accel']
        recipe['timing']['speed_knots_s_mm_s'] = [[0, 5], [.03, 10], [.97, 10], [1, 5]]
        recipe['description'] = '教学笔画形状与五档磁目标；主体速度上限10 mm/s；书写段不超过20秒。'
        recipe['notes'] += [
            '20秒硬约束适用于沿XY书写段，进出笔、加载、抬笔返回和基线另计。',
            '保留形状比例与五档磁目标；适当缩放，起收采用短局部减速，姿态按更平滑的切线转向。',
            '平滑参数作用于姿态方向；XY路径仍使用原图引导线，未改为直线或删去起收段。']
        plan = build_plan(recipe)
        for field in ['template_id', 'source_template_sha256', 'magnetic_reference_id',
                      'magnetic_scale', 'magnetic_reference_sha256', 'magnetic_levels_uT',
                      'phase_control_points', 'writing_hint', 'geometry_review_status']:
            plan.meta[field] = copy.deepcopy(original.meta[field])
        sizing = copy.deepcopy(original.meta['sizing'])
        sizing.update(target_span_mm=spec['span_mm'],
                      mm_per_source_px=sizing['mm_per_source_px'] * scale,
                      scale_relative_to_v1=scale)
        plan.meta.update(
            sizing=sizing, source_target=str((SOURCE / name / 'strokeplan.npz').relative_to(ROOT)),
            source_target_sha256=digest(SOURCE / name / 'strokeplan.npz'),
            max_writing_duration_s=20.,
            duration_definition=report['duration_definition'],
            pause_interpretation='short local slowdown only; no inserted dwell',
            orientation_smoothing_mm=spec['smoothing_mm'],
            validation=report['validation'])
        st = plan.strokes[0]
        assert st.t[-1] <= 20., (name, st.t[-1])
        knots = recipe['magnetic_target']['knots_s_uT']
        assert knots == original.meta['recipe']['magnetic_target']['knots_s_uT']
        assert np.allclose(st.g_target, contact_profile(st.s, knots), atol=1e-10, rtol=0)
        assert st.g_target.min() >= 100 - 1e-8 and st.g_target.max() <= 240 + 1e-8
        speeds = np.linalg.norm(np.diff(st.xy, axis=0), axis=1) / np.diff(st.t) * 1000
        assert speeds.max() <= 10.000001
        span = np.ptp(st.xy * 1000, axis=0)
        assert abs(span[spec['axis']] - spec['span_mm']) < .12
        compiled = compile_recorded_plan(plan, table, setup,
            label=f'template_{name}_100_240_v3', entry_profile=entry, control_mode='feedforward')
        limits = _check_trajectory(compiled['pose_m_rad'], setup, entry)
        measurement_s = float(np.count_nonzero(compiled['phase'] == 'measure_00') * .02)
        assert measurement_s <= 20., (name, measurement_s)
        summary = dict(id=name, name=spec['name'], plan=f'{name}/strokeplan.npz',
            writing_duration_s=float(st.t[-1]), measurement_phase_duration_s=measurement_s,
            full_motion_duration_s=float(compiled['t_s'][-1]),
            bbox_mm=span.tolist(), scale_relative_to_v1=scale,
            length_mm=float(np.linalg.norm(np.diff(st.xy, axis=0), axis=1).sum() * 1000),
            max_writing_xy_speed_mm_s=float(speeds.max()),
            target_range_uT=[float(st.g_target.min()), float(st.g_target.max())],
            orientation_smoothing_mm=spec['smoothing_mm'], compiled_limits=limits,
            source_target_sha256=plan.meta['source_target_sha256'])
        prepared.append((spec, recipe, plan, compiled, summary))
        report['strokes'].append(summary)

    preflight = output / 'preflight'
    preflight.mkdir()
    fig, grid = plt.subplots(4, 3, figsize=(15, 15), squeeze=False)
    for axes, (spec, recipe, plan, compiled, summary) in zip(grid, prepared):
        folder = output / spec['id']
        folder.mkdir()
        write_json(folder / 'recipe.json', recipe)
        write_json(folder / 'summary.json', summary)
        plan.save(folder / 'strokeplan.npz')
        reloaded = StrokePlan.load(folder / 'strokeplan.npz')
        assert reloaded.strokes[0].t[-1] <= 20.
        np.savez_compressed(preflight / f"compiled_{spec['id']}.npz",
            **{key: compiled[key] for key in
               ['t_s', 's', 'phase', 'pose_m_rad', 'g_ref_uT', 'depth_ff_m']},
            artifact_role='derived_nominal_trajectory_not_robot_commands')
        plotting.panels(axes, reloaded.strokes[0], spec,
                        plan.meta['phase_control_points'], reference)
        subprocess.run([sys.executable, str(PREVIEW), str(folder / 'strokeplan.npz'),
                        '--repo', str(ROOT), '--output-dir', str(folder / 'preview')],
                       check=True, capture_output=True, text=True)
    fig.suptitle('Four synthetic targets | writing <= 20 s | gray: Zhong size reference')
    fig.tight_layout(rect=(0, 0, 1, .975))
    fig.savefig(output / 'overview.png', dpi=150)
    plt.close(fig)
    assert context_hashes == {name: digest(CONTEXT / name) for name in context_hashes}
    write_json(output / 'preflight.json', report)
    rows = '\n'.join(
        f"| `{r['id']}` | {r['name']} | {r['bbox_mm'][0]:.1f} × {r['bbox_mm'][1]:.1f} | "
        f"{r['writing_duration_s']:.2f} | {r['full_motion_duration_s']:.2f} |"
        for r in report['strokes'])
    readme = f'''# brush2 四笔画：书写段不超过20秒

四笔均通过 V3 重新加载、书写段时长检查及现有方向姿态执行器的离线预检。未连接硬件，未提高执行器限值。

| STROKE | 笔画 | 尺寸：宽 × 高 / mm | 书写段 / s | 含进出笔、转场的运动 / s |
| --- | --- | --- | --- | --- |
{rows}

20秒约束指沿XY书写段；进笔、接触旋转、加载、抬笔、返回和基线另计。表中的计划运动时长也不包含从当前位姿启动自动定位的时间。作为参照，“中”的原四笔书写时间为8.02、20.32、11.42、18.94秒；本组执行严格的20秒上限。

保留教学图的笔画形状和100–240 µT等比五档磁目标。横缩至110 mm宽，竖缩至170 mm高，撇缩至100 mm宽，捺保留140 mm宽。原撇路径约217 mm，在10 mm/s上限下必须缩放才能满足20秒。

取消原来长距离低速和整笔2–3倍放慢；主体期望速度10 mm/s，起收采用短局部减速，转弯继续受现有运动约束限制。姿态切线平滑参数从1 mm调整为横/竖5 mm、撇/捺6 mm；XY仍来自原图引导线。未插入额外原地停驻。磁档位仍是合成宽度意图，未标定实际宽度。

![四笔画预览](overview.png)

## 运行

在已有Brushbot Python环境、项目根目录中先做单笔预检：

```bash
cd /home/ethan/FYP
PLAN_DIR=runs/brush2/plans/{output.name}
SETUP_DIR=runs/brush2/plans/11_中字底横延长30mm_实测第9次
STROKE=heng

PYTHONPATH=src:. python scripts/run_strokeplan_experiment.py \\
  "$PLAN_DIR/$STROKE/strokeplan.npz" \\
  --feedforward "$SETUP_DIR/feedforward.json" \\
  --settings "$SETUP_DIR/settings.json" \\
  --entry-profile "$SETUP_DIR/entry_profile.json" \\
  --control-mode feedforward \\
  --record-actual-tcp \\
  --run-label "template_${{STROKE}}_100_240_v3" \\
  --dry-run
```

确认当前brush2仍匹配这套现场配置，手动沾水并确认自动回位与书写路径净空后，把末尾`--dry-run`改为`--execute`，按终端提示输入`RUN`。脚本先自动抬笔、高位移动并对齐到下述等待位，到位检查通过后清空旧磁数据，再重新采集基线并开始书写。其余笔画将`STROKE`改为`shu`、`pie`、`na`，逐笔预检、执行并更换纸张。

现场配置沿用先前“中”字：TCP_brush / Base，接触参考Z40 mm；等待XYZ = [-370, 500, 130] mm，RPY = [0, 15, 0]°。进笔倾角30°、书写倾角15°，接触旋转时反向移动5 mm。绘图右方为机器人+X、上方为+Y。默认IP192.168.0.10，串口/dev/ttyACM0，波特率115200；连接参数可通过`--ip`、`--serial-port`、`--baud`指定。

本组仍假设其他方向、局部低速和动态姿态可沿用brush2旧+X、10 mm/s、固定Ry15°前馈表，需通过试写验证。运行数据保存在`runs/brush2/`。

[预检报告](preflight.json)包含时长、配置哈希和限值实测差分。`preflight/compiled_*.npz`为独立派生的名义轨迹，包含前馈Z；不回填到目标StrokePlan。各笔`preview/`含独立预览、CSV及目标哈希。v1、v2和历史配置均保留原值。
'''
    with (output / 'README.md').open('x', encoding='utf-8') as stream:
        stream.write(readme)
    write_json(output / 'manifest.json', {str(path.relative_to(output)): digest(path)
               for path in sorted(output.rglob('*')) if path.is_file()})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
