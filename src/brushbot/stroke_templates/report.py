"""Portable SVG review/editor. Downloaded edits must be fitted again."""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path

import numpy as np


CSS = """
:root{color-scheme:light;font-family:system-ui,-apple-system,'Noto Sans CJK SC',sans-serif;color:#203047;background:#f3f5f8}
*{box-sizing:border-box}body{margin:0;padding:26px;max-width:1500px;margin:auto}h1{font-size:26px;margin:5px 0 10px}h2{font-size:18px}p{line-height:1.65}
.muted{color:#62728a}.card{background:#fff;border:1px solid #dbe2eb;border-radius:14px;padding:20px;margin:16px 0}.grid{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:18px}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}button,select,input{font:inherit;border:1px solid #becbdc;border-radius:7px;padding:7px 10px;background:#fff;color:#203047}button{cursor:pointer}button:hover{background:#eef4ff}button.primary{background:#235ec5;color:white;border-color:#235ec5}label{font-size:14px}label.field{display:block;margin:12px 0}label.field input{width:100%;margin-top:5px}input[type=checkbox]{accent-color:#235ec5}input[type=range]{width:100%;padding:0}
svg{display:block;background:#fafbfd;width:100%;height:auto;max-height:72vh;border:1px solid #e1e6ee;touch-action:none;user-select:none}.badge{display:inline-block;background:#e9eff9;color:#214c8f;padding:4px 9px;border-radius:20px;font-size:13px;margin-right:6px}.warn{background:#fff3d9;color:#805715}.error{color:#a13535}#message{min-height:24px;color:#895a0d}.stale{opacity:.45}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid #e1e6ee}code{overflow-wrap:anywhere;font-size:12px}.legend{display:flex;gap:15px;flex-wrap:wrap;font-size:13px}.legend span::before{content:'●';margin-right:5px}.entry{color:#cf7b16}.body{color:#2864c5}.exit{color:#238b61}.readout{font-variant-numeric:tabular-nums;font-size:14px;line-height:1.8;white-space:pre-wrap}.small{font-size:13px}#selection{width:100%}#details{overflow-wrap:anywhere}a{color:#235ec5}
@media(max-width:850px){body{padding:12px}.grid{grid-template-columns:1fr}.card{padding:14px}.toolbar{gap:7px}table{font-size:12px}th,td{padding:7px}svg{max-height:60vh}}
"""


EDITOR = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>笔画模板 · 离线复核</title><style>__CSS__</style>
<h1 id="title">笔画模板 · 离线复核</h1><div id="summary"></div>
<p class="muted">先确认每笔类型、方向与阶段。拖动圆点修改路径；可插入点、调整行笔边界，下载标注后重新运行 fit。字库先验和图像候选均不代表实测笔锋轨迹。</p>
<div class="grid"><main><section class="card">
<div class="toolbar"><button id="resetView">复位视图</button><label><input id="showImage" type="checkbox" checked>原图</label><label><input id="showAnnotation" type="checkbox" checked>参考候选</label><label><input id="showProposed" type="checkbox" checked>分段模板</label><label><input id="showBaseline" type="checkbox">整体缩放</label><label><input id="showWidths" type="checkbox">测宽样点</label></div>
<div class="legend"><span class="entry">起笔</span><span class="body">行笔</span><span class="exit">收笔</span><span style="color:#a95375">参考候选</span></div>
<svg id="canvas" aria-label="可编辑的笔画路径"></svg>
<p class="small muted">滚轮缩放；拖动背景平移；点击路径或圆点选择。阶段连接处保留重复坐标用于关联，不表示停顿。</p>
<div class="toolbar"><label>检查进度 <select id="phaseSelect"><option value="all">整笔 s</option><option value="entry">起笔 u</option><option value="body">行笔 u</option><option value="exit">收笔 u</option></select></label></div><input id="progress" type="range" min="0" max="1000" value="0"><div id="readout" class="readout"></div>
</section><section id="metricsCard" class="card"><h2>同一坐标系下的几何比较</h2><p class="small muted">参考是可编辑图像候选，可能与模板共享字体来源；这些数值不能证明书法质量或真实运动精度。</p><div id="metrics"></div></section></main>
<aside><section class="card"><label class="field">选择笔画<select id="selection"></select></label>
<label class="field">类型（heng / shu / 自定义英文标识）<input id="typeInput"></label><label class="field">写法变体<input id="variantInput"></label>
<label class="field">人工宽度提示（原图 px，可留空）<input id="widthInput" type="number" min="0" step="any"></label>
<div id="anchorInfo" class="readout"></div><div class="toolbar"><button id="bodyStart">选中点设为行笔起点</button><button id="bodyEnd">选中点设为行笔终点</button></div>
<div class="toolbar"><button id="insertPoint">插入路径点</button><button id="deletePoint">删除选中点</button><button id="reversePath">反转方向</button></div>
<label class="field">复核备注<input id="notesInput"></label><label><input id="confirmed" type="checkbox">此笔类型、路径和阶段已人工确认</label>
<div class="toolbar"><button id="addStroke">新增笔画</button><button id="deleteStroke">删除此笔</button></div><div id="message" role="status"></div>
<button id="download" class="primary">下载修正标注 JSON</button><div class="toolbar"><label>载入标注 <input id="import" type="file" accept=".json,application/json" style="max-width:250px"></label><button id="restore">恢复本报告初始标注</button></div>
</section><section class="card"><h2>当前笔画</h2><div id="details" class="readout small"></div></section></aside></div>
<script id="stroke-template-data" type="application/json">__DATA__</script>
<script>
'use strict';
const initial=JSON.parse(document.getElementById('stroke-template-data').textContent);
let annotation=structuredClone(initial.annotation), dirty=false, selected=0, pointIndex=0, inserting=false, drag=null;
const W=annotation.image_size_px[0], H=annotation.image_size_px[1], ns='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id), svg=$('canvas'); let view=[-.5,-.5,W,H];
const colors={entry:'#cf7b16',body:'#2864c5',exit:'#238b61'};
const phaseNames={entry:'起笔',body:'行笔',exit:'收笔'};
const sourceNames={font_prior:'字库结构先验',manual_image:'人工图像标注',synthetic_fixture:'解析几何夹具',teaching_rule_reconstruction:'教学规则重建'};
const evidenceNames={font_geometry_fixture:'字体几何夹具',synthetic_geometry_fixture:'解析几何夹具',manual_geometry_reviewed:'已复核的图像几何',unreviewed_geometry:'尚未复核的图像几何',teaching_rule_candidate:'教学规则重建候选'};
const flagNames={image_geometry_candidate_not_measured_motion:'路径为图像几何候选，尚无实测运动依据',physical_width_transfer_unverified:'跨宽度的物理书写效果尚未验证',outside_observed_reference_aspect_range:'主体长宽比超出参考样本覆盖范围',target_annotation_unreviewed:'输入标注尚未人工确认',template_not_manual_calligraphy_reference:'模板使用夹具或尚未复核的参考',generated_path_outside_image:'生成路径部分超出原图范围，请复核起收笔或布局'};
function element(name,attrs,parent=svg){const el=document.createElementNS(ns,name);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);parent.appendChild(el);return el;}
function coords(p){return[p[0],H-1-p[1]];}
function line(points,attrs){return element('polyline',{points:points.map(p=>coords(p).join(',')).join(' '),fill:'none','stroke-linejoin':'round','stroke-linecap':'round',...attrs});}
function fitted(){return initial.geometry?.strokes.find(s=>s.id===annotation.strokes[selected].id);}
function message(text){$('message').textContent=text;}
function markDirty(unreview=true){dirty=true;if(unreview)annotation.strokes[selected].review_status='unreviewed';$('metricsCard').classList.add('stale');}
function pointer(e){const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(svg.getScreenCTM().inverse());return[q.x,H-1-q.y];}
function checkLandmarks(s,a=s.anchors){const features=s.landmarks??[];if(!Array.isArray(features)||features.length>16)throw Error('折/钩特征点列表无效。');let previous=a[1];const names=new Set();for(const p of features){if(!p||Object.keys(p).sort().join(',')!=='index,name'||!/^[a-z][a-z0-9_]{0,63}$/.test(p.name)||names.has(p.name)||!Number.isInteger(p.index)||!(previous<p.index&&p.index<a[2]))throw Error('行笔边界必须包含有序且不重复的折/钩特征点。');previous=p.index;names.add(p.name);}}
function validate(){const ids=new Set();for(const s of annotation.strokes){if(!/^[a-z][a-z0-9_]{0,63}$/.test(s.type)||!/^[a-z][a-z0-9_]{0,63}$/.test(s.variant))throw Error('类型和变体须为小写英文标识。');if(ids.has(s.id))throw Error('笔画编号重复。');ids.add(s.id);const n=s.xy_px.length,a=s.anchors;if(n<4||n>2048||a[0]!==0||a[3]!==n-1||!(0<a[1]&&a[1]<a[2]&&a[2]<n-1))throw Error('每笔至少四点，行笔边界须位于首尾之间。');checkLandmarks(s);for(let i=0;i<n;i++){const p=s.xy_px[i];if(p.length!==2||!p.every(Number.isFinite)||p[0]<-.5||p[0]>W-.5||p[1]<-.5||p[1]>H-.5)throw Error('坐标超出原图。');if(i&&Math.hypot(p[0]-s.xy_px[i-1][0],p[1]-s.xy_px[i-1][1])<=1e-10)throw Error('相邻点重复。');}if(s.width_hint_px!=null&&!(Number.isFinite(s.width_hint_px)&&s.width_hint_px>0))throw Error('人工宽度须为正数。');}}
function draw(){svg.replaceChildren();svg.setAttribute('viewBox',view.join(' '));
 if($('showImage').checked)element('image',{x:-.5,y:-.5,width:W,height:H,href:initial.image_data_url,preserveAspectRatio:'none'});
 const radius=Math.max(view[2]/200,W/500), strokeWidth=Math.max(view[2]/500,W/1500);
 if(!dirty&&initial.geometry){for(const s of initial.geometry.strokes){if(s.status!=='candidate')continue;
  if($('showBaseline').checked)line(s.baseline_xy_px,{stroke:'#78879e','stroke-width':strokeWidth,'stroke-dasharray':`${strokeWidth*3} ${strokeWidth*2}`,'data-stroke':s.id});
  if($('showProposed').checked){for(const r of s.phase_ranges)line(s.xy_px.slice(r.first,r.last+1),{stroke:colors[r.phase_id],'stroke-width':strokeWidth*1.5,'data-stroke':s.id});}
  if($('showWidths').checked)for(const q of s.width_measurement.samples){const p=coords(q.xy_px);element('circle',{cx:p[0],cy:p[1],r:radius*.45,fill:q.width_px==null?'#d94545':'#337d62'});}
 }}
 if($('showAnnotation').checked)annotation.strokes.forEach((s,i)=>{line(s.xy_px,{stroke:'#a95375','stroke-width':strokeWidth,opacity:i===selected?.9:.4,'data-stroke':s.id});if(i===selected)s.xy_px.forEach((p,j)=>{const q=coords(p),a=s.anchors.indexOf(j);element('circle',{cx:q[0],cy:q[1],r:radius*(j===pointIndex?1.35:1),fill:a>=0?'#f6b64b':'#fff',stroke:j===pointIndex?'#172d51':'#a95375','stroke-width':strokeWidth*.7,'data-point':j,'data-stroke':s.id});});});
 const current=annotation.strokes[selected];$('selection').replaceChildren(...annotation.strokes.map((s,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${s.id} · ${s.type} · ${s.review_status==='confirmed'?'已确认':'待复核'}`;return o;}));$('selection').value=selected;
 $('typeInput').value=current.type;$('variantInput').value=current.variant;$('widthInput').value=current.width_hint_px??'';$('notesInput').value=current.notes??'';$('confirmed').checked=current.review_status==='confirmed';
 $('anchorInfo').textContent=`选中点 ${pointIndex} / ${current.xy_px.length-1}\n锚点 [${current.anchors.join(', ')}]`;
 $('summary').replaceChildren();const tag=document.createElement('span');tag.className='badge';tag.textContent=`${annotation.character} · ${annotation.strokes.length} 笔`;const status=document.createElement('span');status.className='badge warn';status.textContent=dirty?'标注已修改：旧拟合已隐藏，请下载后重新 fit':initial.geometry?(initial.geometry.complete?'完整几何候选':'部分几何候选，存在未支持笔画'):'候选标注，待人工复核';$('summary').append(tag,status);
 $('title').textContent=`${annotation.character} · 笔画模板离线复核`;
 const result=fitted();let detail=`原图坐标：X 向右，Y 向上，单位 px。\n来源：${sourceNames[annotation.provenance.source_kind]??annotation.provenance.source_kind}\n`;
 if(dirty)detail+='当前结果已过期，重新 fit 后查看对比。';else if(result?.generation_method==='manual_geometry_preserved')detail+='当前为人工修正 XY，重新加载时保留全部坐标。';else if(result?.status==='candidate')detail+=`模板：${evidenceNames[result.template_evidence.level]??result.template_evidence.level}\n主体伸缩：${result.parameters.body_stretch_ratio.toFixed(3)}\n宽度：${result.width==null?'缺失':result.width.toFixed(3)} ${initial.geometry.units}（${result.width_source==='manual_hint'?'人工提示':'图像法线测量候选'}）\n${result.review_flags.map(f=>flagNames[f]??f).join('\n')}`;else if(result)detail+=`${result.reason_code}\n${result.reason}`;
 if(!dirty&&result?.join_diagnostics)detail+=`\n连接处保留参考折角（平顺边界保持相切）\n起 / 收连接角：${result.join_diagnostics.adapted_rad.map(v=>(v*180/Math.PI).toFixed(1)+'°').join(' / ')}`;
 $('details').textContent=detail;drawMetrics();if(result?.generation_method==='manual_geometry_preserved')$('metrics').textContent='当前为人工修正 XY；不以自比误差评价模板效果。';drawMarker();}
function drawMetrics(){const box=$('metrics');box.replaceChildren();if(dirty){box.textContent='标注已变更。旧指标不再代表当前标注。';return;}const s=fitted();if(s?.status!=='candidate'){box.textContent=s?.reason??'生成模板适配结果后，在这里比较两种路径。';return;}const unit=initial.geometry.units,table=document.createElement('table');const rows=[['指标', '分段模板','整体缩放'],['平均距离',s.metrics.proposed['bidirectional_mean_distance_'+unit],s.metrics.baseline['bidirectional_mean_distance_'+unit]],['P95 距离',s.metrics.proposed['bidirectional_p95_distance_'+unit],s.metrics.baseline['bidirectional_p95_distance_'+unit]],['起点误差',s.metrics.proposed['start_error_'+unit],s.metrics.baseline['start_error_'+unit]],['终点误差',s.metrics.proposed['end_error_'+unit],s.metrics.baseline['end_error_'+unit]],['平均距离 / 笔宽',s.metrics.proposed.mean_distance_over_width,s.metrics.baseline.mean_distance_over_width]];
 rows.forEach((row,i)=>{const tr=document.createElement('tr');row.forEach(v=>{const td=document.createElement(i?'td':'th');td.textContent=typeof v==='number'?v.toFixed(4):v;tr.appendChild(td);});table.appendChild(tr);});box.appendChild(table);const p=document.createElement('p');p.className='small muted';p.textContent=`距离单位 ${unit}；没有内置合格阈值。`;box.appendChild(p);}
function drawMarker(){svg.querySelector('#progressMarker')?.remove();let path,progress,display,phase=$('phaseSelect').value;const s=fitted();
 if(!dirty&&s?.status==='candidate'){const ix=s.xy_px.map((_,i)=>i).filter(i=>phase==='all'||s.phase_id[i]===phase);path=ix.map(i=>s.xy_px[i]);display=ix.map(i=>s.xy[i]);progress=ix.map(i=>phase==='all'?s.s[i]:s.phase_u[i]);}
 else{const s=annotation.strokes[selected],k=['entry','body','exit'].indexOf(phase);path=k<0?s.xy_px:s.xy_px.slice(s.anchors[k],s.anchors[k+1]+1);display=path;progress=[0];for(let i=1;i<path.length;i++)progress.push(progress.at(-1)+Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]));const total=progress.at(-1);progress=progress.map(v=>v/total);}
 if(!path.length)return;const u=Number($('progress').value)/1000;let i=progress.findIndex(v=>v>=u);if(i<0)i=progress.length-1;let p=path[i],d=display[i];if(i>0&&progress[i]>progress[i-1]){const f=(u-progress[i-1])/(progress[i]-progress[i-1]);p=path[i-1].map((v,k)=>v+(path[i][k]-v)*f);d=display[i-1].map((v,k)=>v+(display[i][k]-v)*f);}const q=coords(p);element('circle',{id:'progressMarker',cx:q[0],cy:q[1],r:view[2]/120,fill:'#183959',stroke:'white','stroke-width':view[2]/600,'pointer-events':'none'});
 $('readout').textContent=`${phase==='all'?'整笔 s':phaseNames[phase]+'阶段行程 u'} = ${u.toFixed(3)}\nXY = (${d[0].toFixed(3)}, ${d[1].toFixed(3)}) ${!dirty&&s?.status==='candidate'?initial.geometry.units:'原图 px'}`;}
function applyEdit(action){try{action();markDirty();message('已修改；此笔需重新确认。');draw();}catch(e){message(e.message);}}
$('selection').onchange=()=>{selected=Number($('selection').value);pointIndex=0;draw();};
for(const id of ['showImage','showAnnotation','showProposed','showBaseline','showWidths'])$(id).onchange=draw;
$('typeInput').onchange=()=>applyEdit(()=>annotation.strokes[selected].type=$('typeInput').value.trim());
$('variantInput').onchange=()=>applyEdit(()=>annotation.strokes[selected].variant=$('variantInput').value.trim());
$('widthInput').onchange=()=>applyEdit(()=>annotation.strokes[selected].width_hint_px=$('widthInput').value===''?null:Number($('widthInput').value));
$('notesInput').onchange=()=>applyEdit(()=>annotation.strokes[selected].notes=$('notesInput').value);
$('confirmed').onchange=()=>{annotation.strokes[selected].review_status=$('confirmed').checked?'confirmed':'unreviewed';markDirty(false);draw();};
for(const[id,k]of [['bodyStart',1],['bodyEnd',2]])$(id).onclick=()=>applyEdit(()=>{const s=annotation.strokes[selected],a=[...s.anchors];if(!(pointIndex>a[k-1]&&pointIndex<a[k+1]))throw Error('所选点必须位于相邻阶段锚点之间。');a[k]=pointIndex;checkLandmarks(s,a);s.anchors=a;});
$('insertPoint').onclick=()=>{inserting=!inserting;message(inserting?'在图中点击，向当前笔画插入一点。':'已取消插点。');};
$('deletePoint').onclick=()=>applyEdit(()=>{const s=annotation.strokes[selected];if(s.anchors.includes(pointIndex))throw Error('阶段锚点不可直接删除，请先移动边界。');if(s.landmarks?.some(p=>p.index===pointIndex))throw Error('折/钩特征点不可直接删除，可以拖动其位置。');if(s.xy_px.length<=4)throw Error('每笔至少保留四个点。');s.xy_px.splice(pointIndex,1);s.anchors=s.anchors.map(i=>i>pointIndex?i-1:i);if(s.landmarks)s.landmarks=s.landmarks.map(p=>({...p,index:p.index>pointIndex?p.index-1:p.index}));pointIndex=Math.max(0,pointIndex-1);});
$('reversePath').onclick=()=>applyEdit(()=>{const s=annotation.strokes[selected],n=s.xy_px.length;s.xy_px.reverse();s.anchors=[0,n-1-s.anchors[2],n-1-s.anchors[1],n-1];if(s.landmarks)s.landmarks=s.landmarks.map(p=>({...p,index:n-1-p.index})).reverse();pointIndex=n-1-pointIndex;});
$('addStroke').onclick=()=>{if(annotation.strokes.length>=128){message('最多 128 笔。');return;}let i=1;while(annotation.strokes.some(s=>s.id===`s${String(i).padStart(2,'0')}`))i++;annotation.strokes.push({id:`s${String(i).padStart(2,'0')}`,type:'unknown',variant:'standard',xy_px:[[.35*W,.5*H],[.4*W,.5*H],[.6*W,.5*H],[.65*W,.5*H]],anchors:[0,1,2,3],review_status:'unreviewed',notes:'人工新增笔画'});selected=annotation.strokes.length-1;pointIndex=0;markDirty();draw();};
$('deleteStroke').onclick=()=>{if(annotation.strokes.length<=1){message('至少保留一笔。');return;}annotation.strokes.splice(selected,1);selected=Math.min(selected,annotation.strokes.length-1);pointIndex=0;markDirty();draw();};
$('download').onclick=()=>{try{validate();const data=structuredClone(annotation);delete data.annotation_id;data.review_flags=['edited_annotation_requires_refit'];const blob=new Blob([JSON.stringify(data,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${annotation.character}_annotation.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('已下载。使用原始图片和这份标注重新运行 fit；图片绑定保持不变。');}catch(e){message(e.message);}};
$('import').onchange=async()=>{try{const file=$('import').files[0];if(!file)return;if(file.size>20000000)throw Error('标注超过 20 MB。');const data=JSON.parse(await file.text());if(data.source_sha256!==annotation.source_sha256||JSON.stringify(data.image_size_px)!==JSON.stringify(annotation.image_size_px)||data.character!==annotation.character||data.role!=='stroke_annotation'||!Array.isArray(data.strokes)||!data.strokes.length)throw Error('请选择同一图片和字名的标注。');const old=annotation;annotation=data;try{validate();}catch(e){annotation=old;throw e;}selected=0;pointIndex=0;markDirty(false);draw();message('标注已载入，请重新拟合。');}catch(e){message(e.message);}};
$('restore').onclick=()=>{annotation=structuredClone(initial.annotation);dirty=false;selected=0;pointIndex=0;inserting=false;drag=null;$('metricsCard').classList.remove('stale');message('已恢复本报告初始标注。');draw();};
$('progress').oninput=drawMarker;$('phaseSelect').onchange=drawMarker;$('resetView').onclick=()=>{view=[-.5,-.5,W,H];draw();};
svg.addEventListener('wheel',e=>{e.preventDefault();const p=pointer(e),q=coords(p),f=e.deltaY>0?1.15:1/1.15,newWidth=view[2]*f;if(newWidth<W/40||newWidth>W*4)return;view=[q[0]-(q[0]-view[0])*f,q[1]-(q[1]-view[1])*f,newWidth,view[3]*f];draw();},{passive:false});
svg.addEventListener('pointerdown',e=>{const p=pointer(e),sid=e.target.dataset.stroke;if(sid&&!inserting){selected=annotation.strokes.findIndex(s=>s.id===sid);if(e.target.dataset.point!=null){pointIndex=Number(e.target.dataset.point);drag={kind:'point'};svg.setPointerCapture(e.pointerId);}draw();return;}
 if(inserting){const s=annotation.strokes[selected];let best=Infinity,index=1;for(let i=1;i<s.xy_px.length;i++){const a=s.xy_px[i-1],b=s.xy_px[i],dx=b[0]-a[0],dy=b[1]-a[1],f=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))),d=Math.hypot(p[0]-a[0]-f*dx,p[1]-a[1]-f*dy);if(d<best){best=d;index=i;}}if(p[0]<-.5||p[0]>W-.5||p[1]<-.5||p[1]>H-.5){message('插入点须在原图内。');return;}s.xy_px.splice(index,0,p);s.anchors=s.anchors.map(i=>i>=index?i+1:i);if(s.landmarks)s.landmarks=s.landmarks.map(p=>({...p,index:p.index>=index?p.index+1:p.index}));pointIndex=index;inserting=false;markDirty();draw();return;}
 drag={kind:'pan',start:[e.clientX,e.clientY],view:[...view]};svg.setPointerCapture(e.pointerId);});
svg.addEventListener('pointermove',e=>{if(!drag)return;if(drag.kind==='point'){const p=pointer(e);annotation.strokes[selected].xy_px[pointIndex]=[Math.max(-.5,Math.min(W-.5,p[0])),Math.max(-.5,Math.min(H-.5,p[1]))];markDirty();draw();}else{const rect=svg.getBoundingClientRect();view=[drag.view[0]-(e.clientX-drag.start[0])*drag.view[2]/rect.width,drag.view[1]-(e.clientY-drag.start[1])*drag.view[3]/rect.height,drag.view[2],drag.view[3]];draw();}});
for(const name of ['pointerup','pointercancel'])svg.addEventListener(name,()=>drag=null);
draw();
</script></html>'''


def write_annotation_report(annotation, prepared, destination, *, geometry=None):
    stream = io.BytesIO()
    prepared['image'].save(stream, format='PNG')
    payload = dict(annotation=annotation, geometry=geometry,
        image_data_url='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii'))
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    Path(destination).write_text(EDITOR.replace('__CSS__', CSS).replace('__DATA__', data), encoding='utf-8')


def write_template_report(template, destination):
    p = template['prototype']
    xy = np.asarray(p['xy'])
    low, high = xy.min(axis=0), xy.max(axis=0)
    pad = max(float(np.ptp(xy, axis=0).max())*.08, .5)
    view = [low[0]-pad, -high[1]-pad, *(high-low+2*pad)]
    paths = []
    for name, color, a, b in zip(('起笔', '行笔', '收笔'), ('#cf7b16', '#2864c5', '#238b61'), p['anchors'][:-1], p['anchors'][1:]):
        pts = ' '.join(f'{x:.8g},{-y:.8g}' for x, y in xy[a:b+1])
        paths.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="0.06"/><title>{name}</title>')
    rows = ''.join('<tr><td>'+html.escape(str(r.get('character', '')))+' / '+html.escape(r['stroke_id'])+
        '</td><td>'+html.escape(r['review_status'])+'</td><td>'+html.escape(r.get('width_source', 'unspecified'))+
        '</td><td><code>'+html.escape(r['reference_id'][:16])+'</code></td></tr>' for r in template['references'])
    text = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+f'<title>模板 {html.escape(template["type"])}</title><style>{CSS}</style>'
    text += f'<h1>{html.escape(template["type"])} · {html.escape(template["variant"])} · {html.escape(template["style_id"])}</h1>'
    text += '<p><span class="badge warn">'+html.escape(template['evidence']['level'])+'</span>几何原型；物理书写、宽度与磁响应迁移尚未验证。</p>'
    text += '<section class="card"><div class="legend"><span class="entry">起笔</span><span class="body">行笔</span><span class="exit">收笔</span></div><svg viewBox="'+' '.join(map(str, view))+'">'+''.join(paths)+'</svg><p>局部单位为参考笔宽；原型来自一个代表实例，没有平均合并起收笔。</p></section>'
    descriptors = ''.join('<tr><td>'+{'entry': '起笔', 'body': '行笔', 'exit': '收笔'}[d['phase_id']]+
        '</td><td>'+f'{d["arc_length"]:.3f}'+'</td><td>'+
        ('缺失' if d.get('mean_width_reference_width') is None else f'{d["mean_width_reference_width"]:.3f}')+
        '</td><td>'+str(d.get('visible_width_samples', 0))+'/65</td></tr>' for d in p['descriptors'])
    text += '<section class="card"><h2>分段形态特征</h2><p>长度与宽度均以参考行笔宽度归一化；缺失观测不补零。</p><table><tr><th>阶段</th><th>弧长</th><th>平均宽度</th><th>可见宽度样点</th></tr>'+descriptors+'</table></section>'
    text += '<section class="card"><p>样本覆盖的主体跨度 / 笔宽：'+html.escape(str(template['observed']['body_aspect_range']))+'</p><p>配置允许范围：'+html.escape(str(template['limits']['body_aspect_range']))+'；允许范围是工程设置，不是实验验证范围。</p><table><tr><th>参考</th><th>复核</th><th>宽度来源</th><th>版本</th></tr>'+rows+'</table></section>'
    text += '<p class="muted">template_id <code>'+template['template_id']+'</code></p></html>'
    Path(destination).write_text(text, encoding='utf-8')
