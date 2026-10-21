"""Source-aligned inspection of the exact guide path published as a template."""
from __future__ import annotations

import base64
import html
import json


def write_guide_report(destination, model, source, trace):
    payload = dict(model=model, trace=trace, image='data:image/jpeg;base64,'+base64.b64encode(source).decode())
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    name = html.escape(model['guide_trace']['name'])
    stroke_id = model['type']+'_'+model['variant']
    destination.write_text(PAGE.replace('__NAME__', name).replace('__ID__', stroke_id).replace('__DATA__', serialized), encoding='utf-8')


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__NAME__ · 原图引导线模板</title><style>
:root{font-family:system-ui,'Noto Sans CJK SC',sans-serif;color:#25364a;background:#f4f6f9}*{box-sizing:border-box}body{max-width:1120px;margin:auto;padding:24px}h1{margin:10px 0}p{line-height:1.7}a{color:#245db9}button,input{font:inherit}section{background:white;border:1px solid #dce3ec;border-radius:12px;padding:18px;margin:16px 0}.controls{display:flex;gap:16px;flex-wrap:wrap;align-items:center}#progress{width:240px;max-width:100%}svg{display:block;width:100%;height:280px;background:#f9fafb;border-radius:8px;margin:12px 0}.zooms{display:grid;grid-template-columns:1fr 1fr;gap:18px}.zooms section{min-width:0;margin-top:0}.zooms svg{height:200px}.muted{color:#66758b;font-size:14px}#readout,#facts{overflow-wrap:anywhere;font-variant-numeric:tabular-nums}.downloads{display:flex;gap:18px;flex-wrap:wrap}@media(max-width:600px){body{padding:14px}.zooms{grid-template-columns:1fr}svg{height:230px}}
</style><p class="muted">BRUSHBOT · 笔画库 / 原图追踪</p><h1>__NAME__</h1>
<p>这条模板来自教学图中的白色运笔引导线。橙色为起笔，蓝色为行笔，绿色为收笔。当前保存的路径与下图一致，可叠加原始追踪线检查简化前后的差别。</p>
<section><div class="controls"><label><input id="showSource" type="checkbox" checked>原图</label><label><input id="showRaw" type="checkbox">原始追踪线</label><label><input id="fullImage" type="checkbox">完整教学图</label><label>沿路径 <input id="progress" type="range" min="0" max="1" step=".001" value="0"></label></div>
<svg id="canvas" role="img" aria-label="模板与来源原图叠加"></svg><div id="readout"></div></section>
<div class="zooms"><section><h2>起笔局部</h2><svg id="head" role="img" aria-label="起笔局部放大"></svg></section><section><h2>收笔局部</h2><svg id="tail" role="img" aria-label="收笔局部放大"></svg></section></div>
<section><h2>来源与保存信息</h2><p id="facts"></p><p id="hint"></p><p><a id="article" target="_blank" rel="noopener">阅读来源文章</a> · <a href="source.jpg" target="_blank">打开原图</a></p><div class="downloads"><a id="downloadCsv" href="__ID___xy.csv" download="__ID___xy.csv">下载模板 XY（CSV）</a><a href="template.json" download>下载模板 JSON</a><a href="raw_trace.json" download>下载原始追踪 JSON</a></div>
<p class="muted">待人工检查。阶段边界由教学说明和引导线转折解释。<span id="widthDetail"></span>教学引导线包含示意成分，尚未对应实测笔尖运动、时间、压力或磁响应。</p></section>
<script id="guide-data" type="application/json">__DATA__</script><script>
'use strict';const data=JSON.parse(document.getElementById('guide-data').textContent),m=data.model,g=m.guide_trace,r=m.references[0],$=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg',H=g.image_size_px[1],path=r.xy_px.map(p=>[p[0],H-1-p[1]]),raw=data.trace.source_points_image_px,a=r.anchors;
const arc=[0];for(let i=1;i<path.length;i++)arc.push(arc.at(-1)+Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]));
function add(svg,tag,attrs){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);svg.appendChild(n);return n;}
function box(points,pad=14){const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),x=Math.min(...xs),y=Math.min(...ys);return [x-pad,y-pad,Math.max(...xs)-x+2*pad,Math.max(...ys)-y+2*pad];}
function draw(){for(const id of ['canvas','head','tail']){const svg=$(id);svg.replaceChildren();const crop=data.trace.box;let bounds=[crop[0],crop[1],crop[2]-crop[0],crop[3]-crop[1]];if(id==='canvas'&&$('fullImage').checked)bounds=[0,0,...g.image_size_px];else if(id==='head')bounds=box(path.slice(0,a[1]+1),Math.max(14,r.width_px*.7));else if(id==='tail')bounds=box(path.slice(a[2]),Math.max(14,r.width_px*.7));svg.setAttribute('viewBox',bounds.join(' '));
add(svg,'image',{href:data.image,x:0,y:0,width:g.image_size_px[0],height:H,visibility:$('showSource').checked?'visible':'hidden'});
add(svg,'polyline',{class:'raw',points:raw.map(p=>p.join(',')).join(' '),fill:'none',stroke:'#e54ba5','stroke-width':1.2,'stroke-dasharray':'3 2',visibility:$('showRaw').checked?'visible':'hidden'});
for(let i=0;i<3;i++)add(svg,'polyline',{class:'phase',points:path.slice(a[i],a[i+1]+1).map(p=>p.join(',')).join(' '),fill:'none',stroke:['#df8b22','#2670d0','#0b9b72'][i],'stroke-width':2,'stroke-linecap':'round','stroke-linejoin':'round'});
add(svg,'circle',{class:'marker',r:3.2,fill:'#ed3e36',stroke:'white','stroke-width':1});}progress();}
function progress(){const s=+$('progress').value,d=s*arc.at(-1);let i=1;while(i<arc.length-1&&arc[i]<d)i++;const u=(d-arc[i-1])/(arc[i]-arc[i-1]),p=path[i].map((v,k)=>path[i-1][k]+u*(v-path[i-1][k]));document.querySelectorAll('.marker').forEach(n=>{n.setAttribute('cx',p[0]);n.setAttribute('cy',p[1]);});$('readout').textContent=`s=${s.toFixed(3)} · X=${p[0].toFixed(2)} px · Y=${(H-1-p[1]).toFixed(2)} px（左下原点，Y 向上）`;}
$('facts').textContent=`原始 ${g.raw_point_count} 点 → 模板 ${path.length} 点；分阶段简化容差 ${g.simplify_tolerance_px} px，原始点到对应阶段折线的最大距离 ${g.max_raw_point_deviation_px.toFixed(3)} px。归一化参考宽度 ${r.width_px.toFixed(2)} px。`;
$('widthDetail').textContent=r.width_source==='manual_diagram_width_hint'?'轮廓图使用人工参考宽度，仅用于几何归一化：'+g.width_normalization.basis+'。':'宽度为填补白线空隙后的图像轮廓估计，仅用于几何归一化。';
$('hint').textContent=g.writing_hint;$('article').href=g.article_url;for(const id of ['showSource','showRaw','fullImage'])$(id).onchange=draw;$('progress').oninput=progress;draw();
</script></html>'''
