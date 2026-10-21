"""Portable visual reports for fixed-frame V3 target geometry comparisons."""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
from pathlib import Path

import numpy as np

from brushbot.target_strokeplan import StrokePlan
from .geometry import compare_paths, resample_path
from .image_reference import load_reference, pixels_to_mm, write_json


LIMITATIONS = [
    'Image skeleton is a geometric reference, not a measured brush-tip or TCP trajectory.',
    'XY geometry only: no ink-width prediction, magnetic/timing validation or robot execution.',
    'No fitted alignment, automatic reversal or automatic pass/fail grade.',
    'Nearest-distance metrics ignore order; read ordered, endpoint and length metrics together.',
    'Ordered distance pairs normalized travelled arclength, not elapsed time.',
]


def _draw_overview(reference, entries, results, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.transforms import Affine2D

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    original, extracted, overlay, error = axes.ravel()
    image, transform = reference['image'], reference['metadata']['transform']
    original.imshow(image)
    original.set(title='1  Target image', xlabel='Image x (px)', ylabel='Image y (px)')
    extracted.imshow(image)
    xy = reference['xy_mm']
    angle = np.deg2rad(transform['rotation_deg'])
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    pixel_xy = ((xy-transform['origin_mm']) @ rotation / transform['mm_per_pixel'])*[1, -1]+transform['origin_px']
    extracted.plot(*pixel_xy.T, color='#d97706', linewidth=1.5)
    extracted.scatter(*pixel_xy[0], color='#059669', s=40, label='start', zorder=4)
    extracted.scatter(*pixel_xy[-1], color='#dc2626', marker='x', s=40, label='end', zorder=4)
    extracted.set(title='2  Image reference (inspect selection)', xlabel='Image x (px)', ylabel='Image y (px)')
    extracted.legend(fontsize=8)

    affine = (Affine2D().translate(*(-np.asarray(transform['origin_px'])))
              .scale(transform['mm_per_pixel'], -transform['mm_per_pixel'])
              .rotate_deg(transform['rotation_deg']).translate(*transform['origin_mm']))
    overlay.imshow(image, transform=affine+overlay.transData, alpha=.35)
    overlay.plot(*xy.T, color='black', linewidth=2, label='image reference', zorder=3)
    height, width = image.shape[:2]
    corners = pixels_to_mm([[-.5, -.5], [width-.5, -.5], [width-.5, height-.5], [-.5, height-.5]], transform)
    bounds = [corners, xy]
    for index, (entry, result) in enumerate(zip(entries, results)):
        color = plt.get_cmap('tab10')(index % 10)
        plan = result['candidate_vertices_mm']
        bounds.append(plan)
        overlay.plot(*plan.T, color=color, linewidth=1.4, label=entry['label'], zorder=4)
        overlay.scatter(*plan[0], color=color, marker='^', s=28, zorder=5)
        overlay.scatter(*plan[-1], color=color, marker='x', s=28, zorder=5)
        arrow_path = resample_path(plan, 101)
        for k in (33, 66):
            overlay.annotate('', xy=arrow_path[k+3], xytext=arrow_path[k],
                             arrowprops=dict(arrowstyle='->', color=color, lw=1))
        error.plot(result['progress'], result['ordered_error_mm'], color=color,
                   label=entry['label']+' | ordered')
        error.plot(result['progress'], result['plan_to_reference_mm'], color=color,
                   linestyle='--', alpha=.7, label=entry['label']+' | nearest')
    all_xy = np.vstack(bounds)
    lo, hi = all_xy.min(axis=0), all_xy.max(axis=0)
    padding = max(float(np.max(hi-lo))*.04, .5)
    overlay.set(xlim=(lo[0]-padding, hi[0]+padding), ylim=(lo[1]-padding, hi[1]+padding),
                xlabel='Paper x (mm)', ylabel='Paper y (mm)', title='3  Fixed-frame XY comparison')
    overlay.set_aspect('equal', adjustable='box')
    overlay.legend(fontsize=8)
    overlay.grid(alpha=.2)
    error.set(xlabel='Normalized travelled distance', ylabel='Distance (mm)',
              title='4  Along-path error (solid: ordered; dashed: nearest)')
    error.legend(fontsize=8)
    error.grid(alpha=.2)
    fig.suptitle('StrokePlan XY comparison | geometry only | no automatic alignment', fontsize=14)
    fig.tight_layout(rect=(0, .015, 1, .97))
    fig.savefig(output, dpi=150)
    plt.close(fig)


def _write_html(report, picture, destination):
    esc = html.escape
    columns = [('bidirectional_mean_distance_mm', '平均双向距离 / mm'),
               ('bidirectional_p95_distance_mm', '双向距离 P95 / mm'),
               ('vertex_max_distance_mm', '原始顶点最大距离 / mm'),
               ('ordered_mean_distance_mm', '有序平均距离 / mm'),
               ('start_error_mm', '起点误差 / mm'), ('end_error_mm', '终点误差 / mm'),
               ('length_ratio', '路径长度比')]
    head = ''.join(f'<th>{title}</th>' for _, title in columns)
    rows = []
    for item in report['candidates']:
        values = ''.join(f'<td>{item["metrics"][key]:.4f}</td>' for key, _ in columns)
        rows.append(f'<tr><th>{esc(item["label"])}</th>{values}</tr>')
    state = '已由调用者确认复核' if report['reference_reviewed'] else '尚未确认复核：请先检查参考路径和行笔方向'
    limits = ''.join(f'<li>{esc(text)}</li>' for text in [
        '图片骨架表示墨迹几何，不能作为真实笔尖或 TCP 运动真值。',
        '本报告只评价 XY，不预测墨迹宽度，也不验证磁目标、节拍或真机书写效果。',
        '所有计划共用固定图片坐标变换；不自动缩放、配准、反向或给出达标结论。',
        '最近距离不区分走笔顺序，请结合有序距离、端点误差和长度比阅读。',
        '有序距离按归一化累计行程配对；停顿时间不进入几何评分。',
    ])
    entries = ''.join(f'<li><b>{esc(item["label"])}</b>：第 {item["stroke_index"]} 笔（索引从 0 开始），'
                      f'<code>{esc(item["sha256"])}</code></li>' for item in report['candidates'])
    image_data = base64.b64encode(Path(picture).read_bytes()).decode('ascii')
    metadata = report['reference']
    text = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>StrokePlan XY 离线比较</title><style>
body{{max-width:1200px;margin:36px auto;padding:0 24px;font:16px/1.65 system-ui,sans-serif;color:#172033;background:#fafbfc}}
h1{{font-size:28px}}.notice{{padding:14px 18px;background:#fff3d6;border-left:4px solid #c48510}}
img{{width:100%;height:auto;background:white}}table{{border-collapse:collapse;width:100%;background:white}}
td,th{{padding:10px;border:1px solid #d8dee8;text-align:right}}th:first-child{{text-align:left}}
code{{font-size:12px;overflow-wrap:anywhere}}.scroll{{overflow-x:auto}}a{{color:#1d4ed8}}
</style><h1>StrokePlan XY 离线比较</h1>
<p class="notice">参考状态：{state}。本报告评价几何一致性，不给出自动通过／失败结论。</p>
<img alt="目标图片、参考路径、计划叠加与沿程误差四联图" src="data:image/png;base64,{image_data}">
<div class="scroll"><table><tr><th>计划</th>{head}</tr>{''.join(rows)}</table></div>
<p>参考方向来源：<code>{esc(str(metadata['direction_source']))}</code>；明确选择路径后省略的骨架像素：
{metadata['omitted_skeleton_pixels']}。请检查原始图像与提取预览，确认这条参照适合本次评价。</p>
<p>参考曲线简化容差：{metadata['simplify_tolerance_px']} px；原始有序骨架保存在参照快照的 skeleton_path.csv。</p>
<p><a href="reference_snapshot/reference_preview.png">参考提取预览</a> · <a href="metrics.csv">完整指标 CSV</a> ·
<a href="report.json">参数与来源 JSON</a></p>
<h2>解释范围</h2><ul>{limits}</ul><h2>计划来源</h2><ul>{entries}</ul>
<p>参考文件 SHA256：<code>{esc(metadata['manifest_sha256'])}</code></p></html>'''
    Path(destination).write_text(text, encoding='utf-8')


def compare_plans(reference_dir, candidates, output_dir, *, stroke_index=0,
                  samples=501, reference_reviewed=False):
    """Validate every input, then write a new, portable comparison bundle."""
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f'refusing to replace output: {output}')
    if type(stroke_index) is not int or stroke_index < 0:
        raise ValueError('stroke_index must be a nonnegative integer')
    if type(reference_reviewed) is not bool:
        raise ValueError('reference_reviewed must be boolean')
    if not 1 <= len(candidates) <= 8:
        raise ValueError('compare between one and eight labelled candidates')
    labels = [label for label, _ in candidates]
    if (any(not isinstance(label, str) or not label.strip() or len(label) > 80
            or not label.isprintable() for label in labels) or len(set(labels)) != len(labels)):
        raise ValueError('candidate labels must be unique, nonempty printable text (at most 80 characters)')
    reference = load_reference(reference_dir)
    entries, results, snapshots = [], [], []
    for index, (label, file) in enumerate(candidates):
        payload = Path(file).read_bytes()
        plan = StrokePlan.load(io.BytesIO(payload))
        if plan.meta['coordinate_frame'] != 'paper':
            raise ValueError('candidate coordinate_frame must be paper; transform base coordinates explicitly first')
        if stroke_index >= len(plan.strokes):
            raise ValueError(f'stroke_index {stroke_index} outside candidate {label}')
        result = compare_paths(reference['xy_mm'], np.asarray(plan.strokes[stroke_index].xy)*1000, samples)
        entries.append(dict(label=label, source_path=str(Path(file).resolve()),
                            sha256=hashlib.sha256(payload).hexdigest(), stroke_index=stroke_index,
                            plan_stroke_count=len(plan.strokes), snapshot=f'candidate_{index:02}.npz',
                            samples_csv=f'candidate_{index:02}.csv', metrics=result['metrics']))
        results.append(result)
        snapshots.append(payload)
    ref_meta = reference['metadata']
    report = dict(schema_version=1, role='offline_xy_geometry_comparison',
                  coordinate_frame='paper', alignment='fixed_image_transform_no_candidate_fit',
                  reference_reviewed=reference_reviewed, sample_count=samples,
                  reference=dict(source_directory=str(Path(reference_dir).resolve()),
                                 manifest_sha256=reference['manifest_sha256'],
                                 source_file_sha256=ref_meta['source_file_sha256'],
                                 source_url=ref_meta['source_url'], transform=ref_meta['transform'],
                                 direction_source=ref_meta['direction_source'],
                                 simplify_tolerance_px=ref_meta['simplify_tolerance_px'],
                                 omitted_skeleton_pixels=ref_meta['omitted_skeleton_pixels']),
                  metric_definition=dict(nearest='uniform-arclength samples to original opposite polyline segments',
                                         bidirectional='equal-weight concatenation of both directional distances',
                                         ordered='Euclidean error at matching normalized total travelled arclength',
                                         vertex_max='maximum original-vertex distance to the opposite polyline, both directions',
                                         p95='95th percentile of sampled distances, not exact Hausdorff distance'),
                  limitations=LIMITATIONS, candidates=entries)
    output.mkdir(parents=True, exist_ok=False)
    frozen = output/'reference_snapshot'
    frozen.mkdir()
    for name, payload in reference['snapshots'].items():
        (frozen/name).write_bytes(payload)
    for entry, result, payload in zip(entries, results, snapshots):
        (output/entry['snapshot']).write_bytes(payload)
        with (output/entry['samples_csv']).open('x', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['progress', 'reference_x_mm', 'reference_y_mm', 'plan_x_mm', 'plan_y_mm',
                             'reference_to_plan_mm', 'plan_to_reference_mm', 'ordered_error_mm'])
            writer.writerows(np.column_stack([result['progress'], result['reference_xy_mm'],
                result['candidate_xy_mm'], result['reference_to_plan_mm'],
                result['plan_to_reference_mm'], result['ordered_error_mm']]))
    with (output/'metrics.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['label', *entries[0]['metrics']])
        writer.writeheader()
        writer.writerows(dict(label=entry['label'], **entry['metrics']) for entry in entries)
    write_json(output/'report.json', report)
    _draw_overview(reference, entries, results, output/'overview.png')
    _write_html(report, output/'overview.png', output/'report.html')
    return report
