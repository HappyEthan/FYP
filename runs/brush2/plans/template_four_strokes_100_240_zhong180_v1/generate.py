#!/usr/bin/env python3
"""Reproduce four offline target plans from pinned teaching-guide geometry."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from brushbot.stroke_templates.schema import validate_template
from brushbot.target_strokeplan import StrokePlan
from scripts.generate_calligraphy_trial import contact_profile
from scripts.generate_strokeplan_from_json import build_plan


REFERENCE = 'runs/brush2/plans/11_中字底横延长30mm_实测第9次/character.npz'
LEVELS = 'runs/brush2/plans/width_level_reference_v1/width_levels.csv'
CENTER = np.array([140., 0.])
SPECS = [
    dict(id='heng', name='长横', label='Heng / long horizontal', axis=0, span_mm=120.,
         template='outputs/stroke_templates/strokes/sohu_heng_20261017_final/templates/heng_long/template.json',
         template_id='a15ac6cf8b548ebbff250b5a9eedabb509cdb451c943c867b48b74321c3b5cec',
         controls=[(0,1,'尖起'),(1,4,'斜切轻按'),(3,4,'转入行笔'),(18,2,'前半段渐提'),
                   (23,2,'中段较细'),(34,4,'后半段渐按'),(38,2,'提锋至右上角'),
                   (41,3,'斜向收束'),(45,1,'结束接触目标')],
         speeds=[(0,3),(1,3),(3,7),(4,10),(32,10),(34,5),(38,3),(41,3),(45,3)]),
    dict(id='shu', name='悬针竖', label='Shu / pointed vertical', axis=1, span_mm=180.,
         template='outputs/stroke_templates/strokes/sohu_basics_20261017_v1/templates/shu_xuanzhen/template.json',
         template_id='c73eea3a3083436cd582a11b7ca56827b9291bd6d826ba6f17b85e1bec81d8c2',
         controls=[(0,1,'尖起'),(4,4,'右下轻按'),(6,4,'驻笔与移正'),(9,2,'较细处转入直下'),
                   (10,4,'下段行至较粗处'),(11,1,'渐提收尖')],
         speeds=[(0,3),(4,2),(6,2),(9,8),(10,5),(11,3)]),
    dict(id='pie', name='斜撇', label='Pie / left falling', axis=0, span_mm=140.,
         template='outputs/stroke_templates/strokes/sohu_basics_20261017_v1/templates/pie_slant/template.json',
         template_id='2835b97b6b7766e0fb236ba98a2ecd11f7c8b363782bf74d285916cdc3730ad3',
         controls=[(0,1,'尖起'),(4,3,'右下轻按'),(6,4,'驻笔与调锋'),(10,4,'转入左下行笔'),
                   (15,3,'弧形撇身'),(19,2,'末段渐提'),(28,1,'向左收尖')],
         speeds=[(0,3),(4,2),(6,2),(10,5),(12,10),(19,10),(25,5),(28,3)]),
    dict(id='na', name='斜捺', label='Na / right falling', axis=0, span_mm=140.,
         template='outputs/stroke_templates/strokes/sohu_basics_20261017_v1/templates/na_slant/template.json',
         template_id='0c5cda3ff065c92f7a3b02a35fd08797f5fd928168ac6df1f9d941c06a2bd252',
         controls=[(0,1,'尖锋斜切'),(1,2,'短横接触'),(2,2,'短横行笔'),(4,1,'较细处折向右下'),
                   (12,2,'捺身渐按'),(16,3,'捺身展开'),(19,4,'接近捺脚'),
                   (22,5,'较粗处转向'),(25,5,'稍驻低速段'),(28,3,'向右渐提'),(31,1,'平出收尖')],
         speeds=[(0,3),(1,3),(4,4),(6,8),(12,10),(19,6),(22,4),(25,4),(28,5),(31,5)]),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def make_recipe(spec, model, levels):
    source_xy = np.asarray(model['references'][0]['xy_px'], float)
    factor = spec['span_mm'] / np.ptp(source_xy[:, spec['axis']])
    centered = source_xy - (source_xy.min(axis=0) + source_xy.max(axis=0))/2
    points_mm = centered * factor
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points_mm, axis=0), axis=1))]
    source_s = arc / arc[-1]
    controls = [dict(source_point_index=index, s=float(source_s[index]), action=action,
                     level_id=f'L{level}', g_target_uT=levels[f'L{level}'],
                     basis='authored candidate from writing hint and visual source-diagram review')
                for index, level, action in spec['controls']]
    recipe = dict(schema_version=1, id=spec['id'], name=spec['name'],
        description='教学引导线几何与经验五档磁目标；初次离线试生成。',
        reference=spec['template'],
        placement=dict(origin_mm=CENTER.tolist(), rotation_deg=0, scale=1),
        path=dict(kind='rounded_polyline', points_mm=points_mm.tolist(), corner_radius_mm=0),
        magnetic_target=dict(interpolation='quintic',
            knots_s_uT=[[c['s'], c['g_target_uT']] for c in controls]),
        timing=dict(speed_mm_s=10, accel_mm_s2=30, angular_speed_deg_s=20,
                    angular_accel_deg_s2=40,
                    speed_knots_s_mm_s=[[float(source_s[i]), speed] for i,speed in spec['speeds']]),
        orientation=dict(kind='tangent_tilt', tilt_deg=15, smoothing_mm=1),
        filter_definition=dict(kind='ema', alpha=.3),
        notes=[model['guide_trace']['writing_hint'],
               'XY 取原图笛卡尔坐标 references[0].xy_px，保留原走向、起收和可见端点。',
               '等比缩放；未将原型的主体归一化坐标误作原图朝向。',
               '100–240 µT 五档为用户正相关假设下的合成宽度意图，未测得真实宽度。',
               '稍驻采用局部减速的首版解释；未插入额外原地停顿段。',
               '多方向曲线与动态姿态仅为离线目标，需匹配执行接口和校准条件。'])
    return recipe, controls, factor, source_s


def panels(axes, stroke, spec, controls, reference):
    from matplotlib.collections import LineCollection
    from matplotlib.colors import Normalize
    points = stroke.xy*1000-CENTER
    for ref in reference.strokes:
        old = ref.xy*1000-CENTER
        axes[0].plot(old[:,0], old[:,1], color='.7', alpha=.35, lw=.8)
    segments = np.stack((points[:-1], points[1:]), axis=1)
    color = LineCollection(segments, cmap='viridis', norm=Normalize(100,240), linewidth=2.4)
    color.set_array((stroke.g_target[:-1]+stroke.g_target[1:])/2)
    axes[0].add_collection(color)
    axes[0].scatter(*points[0], c='green', s=26, marker='o', label='start', zorder=5)
    axes[0].scatter(*points[-1], c='red', s=35, marker='x', label='end', zorder=5)
    axes[0].set(xlim=(-100,100), ylim=(-100,100), aspect='equal',
                xlabel='Drawing X relative to center (mm)', ylabel='Drawing Y (mm)',
                title=f"{spec['label']} | gray: Zhong reference")
    axes[0].legend(fontsize=7)
    axes[1].plot(stroke.s, stroke.g_target, lw=1.8)
    axes[1].scatter([c['s'] for c in controls], [c['g_target_uT'] for c in controls], s=18)
    axes[1].set(xlabel='Normalized XY arclength s', ylabel='Target (uT)',
                title='Authored phase / magnetic knots', xlim=(0,1), ylim=(90,250))
    axes[2].plot(stroke.t, stroke.g_target, lw=1.8)
    axes[2].set(xlabel='Time (s)', ylabel='Target (uT)',
                title=f'Target in time | {stroke.t[-1]:.2f} s', ylim=(90,250))
    for ax in axes:
        ax.grid(alpha=.2)


def main(output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output = Path(output).resolve()
    if output.exists() and any(p.name != 'generate.py' for p in output.iterdir()):
        raise FileExistsError(f'refusing to replace existing bundle: {output}')
    reference = StrokePlan.load(ROOT/REFERENCE)
    reference_xy = np.concatenate([s.xy for s in reference.strokes])*1000
    with (ROOT/LEVELS).open(encoding='utf-8', newline='') as stream:
        level_rows = list(csv.DictReader(stream))
    levels = {row['level_id']:float(row['g_target_uT']) for row in level_rows}
    expected = 100*2.4**np.linspace(0,1,5)
    if not np.allclose(list(levels.values()), expected, atol=1e-10, rtol=0):
        raise ValueError('magnetic reference differs from selected 100..240 geometric levels')
    prepared = []
    for spec in SPECS:
        model = validate_template(json.loads((ROOT/spec['template']).read_text()))
        if model['template_id'] != spec['template_id']:
            raise ValueError('pinned template version differs')
        recipe, controls, factor, source_s = make_recipe(spec, model, levels)
        plan = build_plan(recipe)
        plan.meta.update(source='synthetic', template_id=model['template_id'],
            source_template_sha256=digest(ROOT/spec['template']),
            xy_source='source-oriented teaching guide references[0].xy_px, uniformly scaled and centered',
            g_target_source='synthetic user-assumed monotone width intent; 100..240 uT geometric levels',
            magnetic_reference_id='brush2_20260925_raw_xy_width_levels_v1',
            magnetic_scale='baseline-subtracted EMA XY norm; historical brush2 raw response scale',
            magnetic_reference_sha256=digest(ROOT/LEVELS), magnetic_levels_uT=levels,
            phase_control_points=controls, writing_hint=model['guide_trace']['writing_hint'],
            sizing=dict(reference_plan=REFERENCE, reference_sha256=digest(ROOT/REFERENCE),
                        reference_bbox_mm=np.ptp(reference_xy,axis=0).tolist(),
                        source_axis='x' if spec['axis']==0 else 'y', target_span_mm=spec['span_mm'],
                        mm_per_source_px=factor, center_paper_mm=CENTER.tolist()),
            pose_note='15-degree smoothed tangent tilt, same target construction as Zhong',
            pause_interpretation='local slowdown only; no inserted dwell',
            geometry_review_status='teaching candidate; not measured physical pen-tip motion',
            validation='target-only V3 and offline sampling checks; no physical or execution validation')
        plan.validate()
        prepared.append((spec, model, recipe, controls, factor, source_s, plan))
    output.mkdir(parents=True, exist_ok=True)
    if Path(__file__).resolve().parent != output:
        shutil.copyfile(__file__, output/'generate.py')
    write_json(output/'magnetic_levels.json', dict(levels=levels,
        reference_id='brush2_20260925_raw_xy_width_levels_v1', source_csv=LEVELS,
        source_sha256=digest(ROOT/LEVELS), width_basis='user assumed monotone ordinal levels'))
    write_json(output/'reference_zhong_xy.json', dict(source=REFERENCE,
        source_sha256=digest(ROOT/REFERENCE), bbox_mm=np.ptp(reference_xy,axis=0).tolist(),
        center_paper_mm=CENTER.tolist(), xy_mm=[(s.xy*1000).tolist() for s in reference.strokes]))
    entries = []
    fig, grid = plt.subplots(4,3,figsize=(15,15),squeeze=False)
    for row_axes, (spec,model,recipe,controls,factor,source_s,plan) in zip(grid,prepared):
        folder = output/spec['id']; folder.mkdir()
        write_json(folder/'recipe.json', recipe)
        write_json(folder/'source_template.json', model)
        shutil.copyfile(ROOT/Path(spec['template']).parent/'source.jpg', folder/'source.jpg')
        plan.save(folder/'strokeplan.npz')
        loaded = StrokePlan.load(folder/'strokeplan.npz'); st = loaded.strokes[0]
        assert np.allclose(st.g_target, contact_profile(st.s,recipe['magnetic_target']['knots_s_uT']),atol=1e-10)
        speed = np.linalg.norm(np.diff(st.xy,axis=0),axis=1)/np.diff(st.t)*1000
        assert float(speed.max()) <= 10.000001
        assert st.g_target.min() >= 100-1e-8 and st.g_target.max() <= 240+1e-8
        with (folder/'target.csv').open('x',encoding='utf-8',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(['t_s','s','x_mm','y_mm','g_target_uT','roll_rad','pitch_rad','yaw_rad'])
            writer.writerows([t,s,*xy,g,*rpy] for t,s,xy,g,rpy in zip(st.t,st.s,st.xy*1000,st.g_target,st.orientation))
        with (folder/'phase_table.csv').open('x',encoding='utf-8',newline='') as stream:
            writer=csv.writer(stream)
            writer.writerow(['source_point_index','s','action','level_id','g_target_uT','basis','timing_note'])
            writer.writerows([c['source_point_index'],c['s'],c['action'],c['level_id'],c['g_target_uT'],
                              c['basis'],'local speed cap and angular retiming; no added dwell'] for c in controls)
        measured_span=np.ptp(st.xy*1000,axis=0)
        assert abs(measured_span[spec['axis']]-spec['span_mm']) < .12
        entry=dict(id=spec['id'],name=spec['name'],template=spec['template'],template_id=model['template_id'],
                   bbox_mm=measured_span.tolist(),uniform_mm_per_source_px=factor,
                   length_mm=float(np.linalg.norm(np.diff(st.xy,axis=0),axis=1).sum()*1000),
                   duration_s=float(st.t[-1]),samples=len(st.s),max_xy_speed_mm_s=float(speed.max()),
                   target_range_uT=[float(st.g_target.min()),float(st.g_target.max())],
                   start_end_paper_mm=(st.xy[[0,-1]]*1000).tolist(),
                   plan=f"{spec['id']}/strokeplan.npz",preview=f"{spec['id']}/preview.png",
                   writing_hint=model['guide_trace']['writing_hint'],
                   validation='V3 reload, magnetic-knot evaluation, target range, size and speed checks')
        write_json(folder/'summary.json',entry)
        panels(row_axes,st,spec,controls,reference)
        fig_one,axes=plt.subplots(1,3,figsize=(15,4.7))
        panels(axes,st,spec,controls,reference)
        fig_one.suptitle('Teaching XY + synthetic magnetic target | not predicted ink')
        fig_one.tight_layout(); fig_one.savefig(folder/'preview.png',dpi=150); plt.close(fig_one)
        entries.append(entry)
    fig.suptitle('Four template targets | shared Zhong scale | geometric magnetic levels 100-240 uT',fontsize=14)
    fig.tight_layout(rect=(0,0,1,.975)); fig.savefig(output/'overview.png',dpi=150); plt.close(fig)
    report=dict(reference=REFERENCE,reference_sha256=digest(ROOT/REFERENCE),
                reference_bbox_mm=np.ptp(reference_xy,axis=0).tolist(),source='synthetic',
                coordinate_frame='paper; drawing right +X, drawing up +Y',
                magnetic_levels_uT=levels,cruise_speed_mm_s=10,tilt_deg=15,
                generator_sha256=digest(__file__),
                source_api_sha256={str(p):digest(ROOT/p) for p in [
                    'src/brushbot/target_strokeplan.py','scripts/generate_strokeplan_from_json.py',
                    'scripts/generate_directional_character_trial.py','scripts/generate_calligraphy_trial.py']},
                validation='offline target plans only; no compilation or robot execution',strokes=entries)
    write_json(output/'summary.json',report)
    cards=[]
    for e in entries:
        key=e['id']; size=' × '.join(f'{v:.1f}' for v in e['bbox_mm'])
        cards.append(f'<section><h2>{html.escape(e["name"])}</h2><p>XY 包围盒 {size} mm；'
                     f'时长 {e["duration_s"]:.2f} s；最大 XY 速度 {e["max_xy_speed_mm_s"]:.2f} mm/s。</p>'
                     f'<p>{html.escape(e["writing_hint"])}</p><p><a href="{key}/strokeplan.npz">StrokePlan NPZ</a> · '
                     f'<a href="{key}/target.csv">目标 CSV</a> · <a href="{key}/phase_table.csv">阶段控制点表</a> · '
                     f'<a href="{key}/recipe.json">可复现配方</a> · '
                     f'<a href="{key}/validation_preview/stroke_00.png">独立读回预览</a></p>'
                     f'<img src="{key}/preview.png" alt="{key} target preview">'
                     f'<details><summary>原始教学图</summary><img class="source" src="{key}/source.jpg"></details></section>')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    page+='<title>四种笔画 StrokePlan 初次生成</title><style>body{font:16px/1.65 sans-serif;max-width:1450px;margin:30px auto;padding:0 18px;background:#f7f8fa;color:#182333}section{background:white;padding:20px;margin:20px 0;border-radius:12px}img{max-width:100%;height:auto}.source{max-height:700px}a{color:#245a9b}</style>'
    page+='<h1>横、竖、撇、捺：StrokePlan 初次生成</h1><p>参考现有中字符号约 138.9 × 180 mm；分别使用长横、悬针竖、斜撇、斜捺的教学引导线，保留原图方向并等比缩放。四笔独立，不组成一个字。</p>'
    page+='<p>五档磁目标为 100、124.47、154.92、192.82、240 µT。磁曲线为图像与描述指导的人工初值；颜色表示目标磁幅值，未预测真实墨迹宽度。灰线仅显示中字的尺寸参考。</p>'
    page+='<p>默认巡航上限 10 mm/s，起收与局部动作减速，姿态沿平滑切线倾斜 15°。“稍驻”先解释为局部低速，未增加原地停顿。当前为无 Z 的离线 V3 目标；多方向与动态姿态执行、前馈适用性及笔迹效果另行验证。</p>'
    page+='<p><a href="overview.png">打开四笔总览图</a> · <a href="summary.json">生成摘要</a> · <a href="generate.py">复现脚本</a></p><img src="overview.png" alt="four stroke overview">'
    page+=''.join(cards)+'</html>'
    (output/'report.html').write_text(page,encoding='utf-8')
    for e in entries:
        print(f"{e['name']}: {e['bbox_mm'][0]:.2f} x {e['bbox_mm'][1]:.2f} mm, "
              f"{e['duration_s']:.2f} s, {e['target_range_uT'][0]:.2f}..{e['target_range_uT'][1]:.2f} uT")
    print(output/'report.html')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parent)
    main(parser.parse_args().output_dir)
