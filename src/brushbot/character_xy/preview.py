"""Static XY overview and an offline SVG inspector without third-party assets."""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image


COLORS = ('#2563eb', '#dc2626', '#059669', '#9333ea', '#d97706', '#0891b2',
          '#db2777', '#4f46e5', '#65a30d', '#9a3412')
FLAG_LABELS = {
    'junctions_require_stroke_resolution': '存在分叉区域，需后续确定笔画连接',
    'point_features_require_process_definition': '存在点状部分，需后续定义落笔方式',
    'loop_direction_is_not_inferred': '存在闭环，尚未指定书写方向',
    'small_components_removed': '已按面积阈值删除小分量，请核对是否包含细小点画',
    'thinning_empty_components_retained_as_points': '细化后消失的部件已保留为点',
    'foreground_dominant_check_inversion_or_threshold': '前景占比偏高，请检查反色或阈值',
    'elongated_component_collapsed_check_source': '细长部件被细化为点，请检查原图与分辨率',
}


def _data_url(image):
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii')


def _static(analysis, directory):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    geometry = analysis['geometry']
    figure = Figure(figsize=(15, 5.5), layout='constrained')
    FigureCanvasAgg(figure)
    original, skeleton, xy = figure.subplots(1, 3)
    original.imshow(analysis['image'])
    original.set_title('Processed character image')
    skeleton.imshow(np.where(analysis['mask'], .78, 1), cmap='gray', vmin=0, vmax=1)
    ys, xs = np.nonzero(analysis['skeleton'])
    skeleton.scatter(xs, ys, s=1, color='#dc2626')
    skeleton.set_title('Ink mask + raw skeleton')
    for axis in (original, skeleton):
        axis.set_axis_off()
    for i, path in enumerate(geometry['paths']):
        points = np.asarray(path['xy'])
        color = COLORS[i % len(COLORS)]
        xy.plot(*points.T, color=color, lw=1.5)
        centre = points[len(points)//2]
        xy.annotate(path['id'], centre, color=color, fontsize=6)
    for node in geometry['nodes']:
        color = '#d97706' if node['kind'] == 'junction' else '#334155'
        xy.scatter(*node['xy'], color=color, s=18 if node['kind'] == 'isolated' else 8,
                   marker='D' if node['kind'] == 'isolated' else 'o', zorder=4)
    xy.axhline(0, color='#cbd5e1', lw=.6)
    xy.axvline(0, color='#cbd5e1', lw=.6)
    xy.set_aspect('equal', adjustable='datalim')
    xy.grid(alpha=.2)
    xy.set_xlabel('X ('+geometry['units']+')')
    xy.set_ylabel('Y ('+geometry['units']+')')
    xy.set_title('XY graph segments (no stroke order)')
    stats = geometry['statistics']
    figure.suptitle(f"{stats['path_segment_count']} paths / {stats['junction_region_count']} junction regions / "
                    f"{stats['isolated_point_count']} point features | edge coverage: "
                    f"{geometry['coverage']['traced_edges']} traced + "
                    f"{geometry['coverage']['junction_internal_edges']} inside junctions")
    figure.savefig(directory/'preview.png', dpi=150)
    figure.clear()


def _svg_paths(geometry, *, cartesian=False):
    parts = []
    for i, path in enumerate(geometry['paths']):
        points = np.asarray(path['xy' if cartesian else 'processed_pixel_xy']).copy()
        if cartesian:
            points[:, 1] *= -1
        points_text = ' '.join(f'{x:.8g},{y:.8g}' for x, y in points)
        color = COLORS[i % len(COLORS)]
        parts.append(f'<polyline class="path" data-path-id="{path["id"]}" points="{points_text}" '
                     f'stroke="{color}" fill="none"><title>{path["id"]}: {path["length"]:.4g} '
                     f'{geometry["units"]}</title></polyline>')
    return ''.join(parts)


def _svg_nodes(geometry, radius, *, cartesian=False):
    parts = []
    for node in geometry['nodes']:
        x, y = node['xy' if cartesian else 'processed_pixel']
        if cartesian:
            y = -y
        color = '#d97706' if node['kind'] == 'junction' else '#0f172a'
        r = radius*(1.5 if node['kind'] == 'isolated' else 1)
        parts.append(f'<circle cx="{x:.8g}" cy="{y:.8g}" r="{r:.8g}" fill="{color}">'
                     f'<title>{node["id"]}: {node["kind"]}; XY={node["xy"]}</title></circle>')
    return ''.join(parts)


def _html(analysis, directory):
    geometry = analysis['geometry']
    width, height = analysis['image'].size
    points = np.asarray([n['xy'] for n in geometry['nodes']] +
                        [p for path in geometry['paths'] for p in path['xy']], float)
    low, high = points.min(axis=0), points.max(axis=0)
    span = max(float(np.max(high-low)), 1.)
    pad = .08*span
    view = [low[0]-pad, -high[1]-pad, max(high[0]-low[0], span*.1)+2*pad,
            max(high[1]-low[1], span*.1)+2*pad]
    skeleton_rgba = np.zeros((*analysis['skeleton'].shape, 4), dtype=np.uint8)
    skeleton_rgba[:, :, 0] = 220
    skeleton_rgba[:, :, 3] = analysis['skeleton']*255
    buttons = ''.join(f'<button class="path-choice" data-path-id="{p["id"]}" '
                      f'style="--color:{COLORS[i % len(COLORS)]}">{p["id"]}'
                      f'<span>{p["length"]:.3g} {geometry["units"]}</span></button>'
                      for i, p in enumerate(geometry['paths']))
    stats = geometry['statistics']
    flags = ''.join('<li>'+html.escape(FLAG_LABELS.get(flag, flag))+'</li>' for flag in geometry['review_flags'])
    data = json.dumps(dict(paths=geometry['paths'], units=geometry['units']), ensure_ascii=False,
                      allow_nan=False).replace('<', '\\u003c').replace('&', '\\u0026')
    mapping = {
        '__SOURCE__': html.escape(Path(geometry['source_path']).name),
        '__PROVENANCE__': html.escape(geometry['source_url'] or '未提供来源链接'),
        '__ID__': geometry['geometry_id'],
        '__UNITS__': geometry['units'],
        '__STATS__': f'{stats["path_segment_count"]} 条路径 · {stats["junction_region_count"]} 个分叉区域 · '
                     f'{stats["isolated_point_count"]} 个点状部分 · {stats["ink_component_count"]} 个墨迹分量',
        '__FLAGS__': flags or '<li>没有额外复核标记；仍请对照原图检查。</li>',
        '__COVERAGE__': f'{geometry["coverage"]["traced_edges"]} 条边已追踪，'
                        f'{geometry["coverage"]["junction_internal_edges"]} 条位于分叉区域内，'
                        f'{geometry["coverage"]["untraced_edges"]} 条未覆盖',
        '__WIDTH__': str(width), '__HEIGHT__': str(height),
        '__VIEW__': ' '.join(map(str, view)),
        '__IMAGE__': _data_url(analysis['image']),
        '__SKELETON__': _data_url(Image.fromarray(skeleton_rgba)),
        '__IMAGE_PATHS__': _svg_paths(geometry),
        '__XY_PATHS__': _svg_paths(geometry, cartesian=True),
        '__IMAGE_NODES__': _svg_nodes(geometry, max(width, height)*.003),
        '__XY_NODES__': _svg_nodes(geometry, span*.004, cartesian=True),
        '__BUTTONS__': buttons or '<p>只有点状部分，没有可采样的曲线路径。</p>',
        '__DATA__': data,
    }
    report = _TEMPLATE
    # Single substitution pass: provenance text cannot introduce template tokens.
    import re
    report = re.sub(r'__[A-Z_]+__', lambda match: mapping.get(match[0], match[0]), report)
    (directory/'report.html').write_text(report, encoding='utf-8')


def write_previews(analysis, directory):
    _static(analysis, directory)
    _html(analysis, directory)


_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>整字 XY 路径复核 · __SOURCE__</title>
<style>
:root{font-family:system-ui,"Noto Sans CJK SC",sans-serif;color:#17243b;background:#f4f6fa}
*{box-sizing:border-box}body{margin:0}main{max-width:1500px;margin:auto;padding:30px}
h1{font-size:26px;margin:0 0 10px}h2{font-size:16px;margin:0 0 12px}p{line-height:1.7}
.muted{color:#64748b;font-size:13px}.stats{color:#1d4ed8;font-size:15px}
.controls,.panel,.review{background:white;border:1px solid #dce3ed;border-radius:12px;padding:16px}
.controls{display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin:20px 0}
label{font-size:14px}button{cursor:pointer;border:1px solid #cbd5e1;background:white;border-radius:7px;padding:7px 12px;color:inherit}
button:hover,button.active{background:#eff6ff;border-color:#2563eb}
.workspace{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 220px;gap:16px}
svg{display:block;width:100%;height:470px;background:#fbfdff;touch-action:none;cursor:grab;user-select:none}
.path{stroke-width:2.4;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round;cursor:pointer}
.path.dimmed{opacity:.15}.path.selected{stroke-width:5}
.path-choice{display:flex;justify-content:space-between;width:100%;margin:0 0 6px;border-left:4px solid var(--color);font-size:12px}
.path-choice span{color:#64748b}.paths{max-height:470px;overflow:auto}
.review{margin:16px 0}.review li{margin:7px 0;font-size:14px}.inspector{margin-top:16px}
input[type=range]{width:100%}code{font-size:12px;overflow-wrap:anywhere}
.marker{fill:#facc15;stroke:#17243b;stroke-width:2;vector-effect:non-scaling-stroke;pointer-events:none}
footer{font-size:12px;color:#64748b;line-height:1.8;margin-top:20px;overflow-wrap:anywhere}
@media(max-width:1050px){.workspace{grid-template-columns:1fr 1fr}.sidebar{grid-column:1/-1}.paths{max-height:180px}svg{height:380px}}
@media(max-width:650px){main{padding:16px}.workspace{grid-template-columns:1fr}.sidebar{grid-column:auto}svg{height:360px}}
</style>
<main><h1>整字 XY 路径复核</h1>
<p class="muted">__SOURCE__ · 几何路径段，不代表笔顺或真实运笔方向。橙点为分叉节点，深色点为端点或点状部分。</p>
<p class="stats">__STATS__</p>
<div class="controls">
<label><input id="show-image" type="checkbox" checked> 原图</label>
<label><input id="show-skeleton" type="checkbox"> 原始骨架</label>
<label><input id="show-paths" type="checkbox" checked> 路径</label>
<label><input id="show-nodes" type="checkbox" checked> 节点与点状部分</label>
<button id="reset">复位视图</button><button id="clear">取消选择</button>
<span class="muted">滚轮缩放 · 拖动平移 · 点击路径或编号选择</span></div>
<div class="workspace">
<section class="panel"><h2>原图叠加 · 处理后像素</h2>
<svg id="image-view" viewBox="-.5 -.5 __WIDTH__ __HEIGHT__" aria-label="原图与路径叠加">
<g id="image-layer"><image href="__IMAGE__" x="-.5" y="-.5" width="__WIDTH__" height="__HEIGHT__" opacity=".45"/></g>
<g id="skeleton-layer" style="display:none"><image href="__SKELETON__" x="-.5" y="-.5" width="__WIDTH__" height="__HEIGHT__"/></g>
<g class="path-layer">__IMAGE_PATHS__</g><g class="node-layer">__IMAGE_NODES__</g>
<circle id="image-marker" class="marker" r="3" style="display:none"/>
</svg></section>
<section class="panel"><h2>XY 路径 · __UNITS__ · X 向右 / Y 向上</h2>
<svg id="xy-view" viewBox="__VIEW__" aria-label="笛卡尔 XY 路径">
<g class="path-layer">__XY_PATHS__</g><g class="node-layer">__XY_NODES__</g>
<circle id="xy-marker" class="marker" r="1" style="display:none"/>
</svg><p id="bounds" class="muted"></p></section>
<aside class="panel sidebar"><h2>路径编号</h2><div class="paths">__BUTTONS__</div></aside></div>
<section class="panel inspector"><h2>路径弧长采样</h2>
<p id="selection" class="muted">选择一条路径，沿归一化弧长 s 检查 XY。s 不代表时间。</p>
<input id="sample" aria-label="归一化弧长" type="range" min="0" max="1000" value="0" disabled>
<p id="sample-readout"></p></section>
<section class="review"><h2>复核提示</h2><ul>__FLAGS__</ul><p class="muted">骨架边覆盖：__COVERAGE__。覆盖统计检查追踪是否遗漏，不是字形质量评分。分叉区域内部像素保存在节点中，尚未变成运笔路径。</p></section>
<footer>geometry_id: <code>__ID__</code><br>来源记录：__PROVENANCE__<br>
数据文件：geometry.json / paths.csv / raw_paths.csv / nodes.csv / xy_paths.npz。CSV 的 u_px、v_px 是纠正 EXIF 后的原图坐标。磁响应关联使用 geometry_id + path_id + s，以 geometry.json / paths.csv / xy_paths.npz 的规范路径为准。raw_paths.csv 的 raw_s 仅用于原始骨架诊断，不可作为关联用的 s。</footer>
</main>
<script id="geometry-data" type="application/json">__DATA__</script>
<script>
'use strict';
const data=JSON.parse(document.getElementById('geometry-data').textContent);
const views=Array.from(document.querySelectorAll('svg'));
const initial=new Map(views.map(v=>[v,v.getAttribute('viewBox')]));
const slider=document.getElementById('sample');
let selected=null;
function sample(path, key, s) {
  let i=0; while(i<path.s.length-2 && path.s[i+1]<s) i++;
  const f=(s-path.s[i])/(path.s[i+1]-path.s[i]);
  return path[key][i].map((v,j)=>v+(path[key][i+1][j]-v)*f);
}
function updateSample(){
  if(!selected)return;
  const s=Number(slider.value)/1000, xy=sample(selected,'xy',s), pixel=sample(selected,'processed_pixel_xy',s);
  document.getElementById('sample-readout').textContent='s = '+s.toFixed(3)+' · X = '+xy[0].toFixed(4)+' · Y = '+xy[1].toFixed(4)+' '+data.units;
  for(const [id,point] of [['image-marker',pixel],['xy-marker',[xy[0],-xy[1]]]]){
    const marker=document.getElementById(id), view=marker.ownerSVGElement;
    marker.setAttribute('cx',point[0]);marker.setAttribute('cy',point[1]);
    marker.setAttribute('r',view.viewBox.baseVal.width*.009);marker.style.display='';
  }
}
function choose(id){
  selected=data.paths.find(p=>p.id===id)||null;
  document.querySelectorAll('[data-path-id]').forEach(el=>{
    const match=selected && el.dataset.pathId===selected.id;
    el.classList.toggle('selected',Boolean(match));el.classList.toggle('active',Boolean(match));
    el.classList.toggle('dimmed',Boolean(selected && !match && el.classList.contains('path')));
  });
  slider.disabled=!selected;
  document.getElementById('selection').textContent=selected?
    selected.id+' · '+selected.start_node_id+' → '+selected.end_node_id+' · 长度 '+selected.length.toFixed(4)+' '+data.units+
    (selected.topological_loop?' · 环路，方向待定':' · 方向仅用于数据索引'):'选择一条路径，沿归一化弧长 s 检查 XY。s 不代表时间。';
  document.getElementById('sample-readout').textContent='';
  document.querySelectorAll('.marker').forEach(m=>m.style.display='none');
  updateSample();
}
document.querySelectorAll('[data-path-id]').forEach(el=>el.addEventListener('click',()=>choose(el.dataset.pathId)));
slider.addEventListener('input',updateSample);
document.getElementById('clear').addEventListener('click',()=>choose(null));
function toggle(id,selector){document.getElementById(id).addEventListener('change',e=>document.querySelectorAll(selector).forEach(el=>el.style.display=e.target.checked?'':'none'));}
toggle('show-image','#image-layer');toggle('show-skeleton','#skeleton-layer');
toggle('show-nodes','.node-layer');toggle('show-paths','.path-layer');
function bounds(){const b=document.getElementById('xy-view').viewBox.baseVal;document.getElementById('bounds').textContent='当前视图 X: '+b.x.toFixed(2)+' … '+(b.x+b.width).toFixed(2)+' / Y: '+(-b.y-b.height).toFixed(2)+' … '+(-b.y).toFixed(2)+' '+data.units;}
function cursor(view,event){const p=new DOMPoint(event.clientX,event.clientY);return p.matrixTransform(view.getScreenCTM().inverse());}
for(const view of views){
  let drag=null;
  view.addEventListener('wheel',event=>{
    event.preventDefault();const point=cursor(view,event),b=view.viewBox.baseVal;
    const factor=event.deltaY>0?1.15:1/1.15, base=Number(initial.get(view).split(' ')[2]);
    if(b.width*factor<base*.005 || b.width*factor>base*20)return;
    view.setAttribute('viewBox',[point.x+(b.x-point.x)*factor,point.y+(b.y-point.y)*factor,b.width*factor,b.height*factor].join(' '));
    bounds();updateSample();
  },{passive:false});
  view.addEventListener('pointerdown',event=>{
    if(event.button!==0 || event.target.closest('[data-path-id]'))return;
    drag={x:event.clientX,y:event.clientY,box:Array.from([view.viewBox.baseVal.x,view.viewBox.baseVal.y,view.viewBox.baseVal.width,view.viewBox.baseVal.height]),matrix:view.getScreenCTM().inverse()};
    view.setPointerCapture(event.pointerId);
  });
  view.addEventListener('pointermove',event=>{
    if(!drag)return;
    const start=new DOMPoint(drag.x,drag.y).matrixTransform(drag.matrix),now=new DOMPoint(event.clientX,event.clientY).matrixTransform(drag.matrix);
    view.setAttribute('viewBox',[drag.box[0]+start.x-now.x,drag.box[1]+start.y-now.y,drag.box[2],drag.box[3]].join(' '));bounds();
  });
  view.addEventListener('pointerup',()=>drag=null);view.addEventListener('pointercancel',()=>drag=null);
}
document.getElementById('reset').addEventListener('click',()=>{views.forEach(v=>v.setAttribute('viewBox',initial.get(v)));bounds();updateSample();});
bounds();
</script></html>'''
