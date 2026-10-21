"""Direct local XY revision: keep good strokes, export without a refit round trip."""
import base64
import copy
import io
import json
from pathlib import Path

import numpy as np

from .report import CSS
from .schema import fixture_kind


def review_annotation(annotation, geometry):
    """Convert generated geometry into editable paths without moving any point."""
    value = copy.deepcopy(annotation)
    by_id = {s['id']: s for s in geometry['strokes']}
    for stroke in value['strokes']:
        candidate = by_id[stroke['id']]
        if candidate['status'] != 'candidate':
            stroke['quick_review_origin'] = 'unmatched_prior'
            continue
        xy, mapping = [], []
        for p in candidate['xy_px']:
            if candidate.get('generation_method') == 'manual_geometry_preserved' or not xy or np.linalg.norm(np.asarray(p)-xy[-1]) > 1e-9:
                xy.append(p)
            mapping.append(len(xy)-1)
        stroke['xy_px'] = copy.deepcopy(xy)
        stroke['anchors'] = [0, mapping[candidate['phase_ranges'][0]['last']],
                             mapping[candidate['phase_ranges'][1]['last']], len(xy)-1]
        stroke['landmarks'] = [dict(name=p['name'], index=mapping[p['index']])
                               for p in candidate.get('feature_landmarks', [])]
        stroke['quick_review_origin'] = 'generated_geometry'
    value.pop('annotation_id', None)
    value['provenance'] = dict(source_kind='manual_geometry_revision',
        source_annotation_id=annotation['annotation_id'], source_geometry_id=geometry['geometry_id'],
        original_provenance=annotation['provenance'], image_kind=fixture_kind(annotation['provenance']) or annotation['provenance'].get('image_kind', 'unspecified'),
        physical_validation=False)
    return value


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>整字 XY · 快速修正</title><style>__CSS__
.layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:18px}.strokeButton{width:100%;text-align:left;margin:5px 0;border-left:5px solid var(--stroke)}.strokeButton.active{background:#eaf1ff}.mainCanvas{max-height:76vh;min-height:280px}#status{min-height:26px}#save{width:100%}.smallControls{display:flex;gap:8px;flex-wrap:wrap}.top{margin:10px 0}.help{font-size:14px;line-height:1.7}@media(max-width:800px){.layout{grid-template-columns:1fr}.mainCanvas{min-height:0}.strokeList{display:flex;gap:6px;flex-wrap:wrap}.strokeButton{width:auto;flex:1}aside.card{margin-top:0}}
</style><h1 id="title">整字 XY · 快速修正</h1>
<p class="help">正确的路径直接保留。点击有问题的一笔，在曲线上拖动即可只调整邻近的一小段；其余笔画不变。</p>
<div class="top"><span id="summary" class="badge"></span><span id="evidence" class="badge warn"></span></div>
<p id="imageConsistency" class="help"></p>
<p id="compositionInfo" class="help" hidden>当前整字由笔画库模板合成；布局参考仅用于位置和形状对照。<a id="compositionDetails" href="../report.html">查看每笔配方、参数与模板来源 →</a></p>
<div class="layout"><main class="card"><div class="toolbar"><button id="undo">撤销</button><button id="redo">重做</button><button id="resetStroke">恢复选中笔画</button><button id="resetView">复位视图</button><label><input id="imageLayer" type="checkbox" checked><span id="imageLayerLabel">原图</span></label><label><input id="baseLayer" type="checkbox">原路径对照</label></div>
<svg id="canvas" class="mainCanvas" aria-label="局部拖动修正笔画"></svg>
<div class="toolbar"><label>修正范围 <input id="radius" type="range" min="2" max="20" value="6"><span id="radiusLabel"></span></label></div><div id="status" class="help" role="status"></div>
<p class="small muted">滚轮缩放，拖动背景平移。修正范围按所选笔画的行程计算，不会牵动交叉处的其他笔画。</p></main>
<aside class="card"><h2>选择笔画</h2><div id="strokeList" class="strokeList"></div><p id="selectionInfo" class="help"></p>
<button id="save" class="primary">整字确认并保存 JSON</button><div class="toolbar"><button id="csv">导出当前 XY CSV</button></div><label class="field">继续上次修正<input id="importReview" type="file" accept=".json,application/json" style="max-width:100%"></label>
<p class="small muted">保存内容就是当前路径，无需再运行 fit 才能得到修正 XY。JSON 可用于后续处理，CSV 可直接查看坐标。</p><p class="small"><a href="report.html" target="_blank">高级模板标注（原始版本）</a></p></aside></div>
<script id="quick-review-data" type="application/json">__DATA__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('quick-review-data').textContent), initial=structuredClone(data.annotation);
let annotation=structuredClone(initial),selected=-1,history=[],future=[],drag=null,view=[-.5,-.5,initial.image_size_px[0],initial.image_size_px[1]];
const W=initial.image_size_px[0],H=initial.image_size_px[1],ns='http://www.w3.org/2000/svg',colors=['#2766c4','#c07817','#258565','#ae4f85','#6958b5','#237f91'];
const $=id=>document.getElementById(id),svg=$('canvas');
if(data.composition){$('compositionInfo').hidden=false;$('imageLayer').checked=Boolean(data.image_constraint);$('imageLayerLabel').textContent='布局参考';}
const names={dian:'点',hengzhegou:'横折钩',hengpie:'横撇',pie:'撇',na:'捺',heng:'横',shu:'竖',unknown:'待定笔画'};
function element(name,attrs,parent=svg){const e=document.createElementNS(ns,name);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);parent.appendChild(e);return e;}
function coords(p){return[p[0],H-1-p[1]];}function arc(path){let a=[0];for(let i=1;i<path.length;i++)a.push(a.at(-1)+Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]));return a;}
function changed(){return annotation.strokes.map((s,i)=>JSON.stringify(s.xy_px)!==JSON.stringify(initial.strokes[i]?.xy_px)?s.id:null).filter(Boolean);}
function tell(text){$('status').textContent=text;}function snapshot(){history.push(structuredClone(annotation));if(history.length>40)history.shift();future=[];}
function pointer(e,matrix=svg.getScreenCTM().inverse()){const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const q=p.matrixTransform(matrix);return[q.x,H-1-q.y];}
function draw(){svg.replaceChildren();svg.setAttribute('viewBox',view.join(' '));const width=Math.max(view[2]/350,W/1500);
 if($('imageLayer').checked)element('image',{x:-.5,y:-.5,width:W,height:H,href:data.image_data_url,preserveAspectRatio:'none'});
 const order=annotation.strokes.map((_,i)=>i).filter(i=>i!==selected);if(selected>=0)order.push(selected);
 order.forEach(i=>{const s=annotation.strokes[i],color=colors[i%colors.length],points=s.xy_px.map(p=>coords(p).join(',')).join(' ');
 if($('baseLayer').checked)element('polyline',{points:initial.strokes[i].xy_px.map(p=>coords(p).join(',')).join(' '),fill:'none',stroke:'#8894a8','stroke-width':width,'stroke-dasharray':`${width*3} ${width*2}`,'pointer-events':'none'});
 element('polyline',{points,fill:'none',stroke:color,'stroke-width':width*(selected===i?2:1.3),'stroke-linecap':'round','stroke-linejoin':'round','pointer-events':'none',opacity:selected<0||selected===i?1:.5});
 element('polyline',{points,fill:'none',stroke:'transparent','stroke-width':width*8,'data-stroke':i,'stroke-linejoin':'round','stroke-linecap':'round'});
 const p=coords(s.xy_px[0]);element('circle',{cx:p[0],cy:p[1],r:width*2.3,fill:color,'pointer-events':'none'});
 });
 const unmatched=annotation.strokes.filter(s=>s.quick_review_origin==='unmatched_prior').length;
 $('title').textContent=`${annotation.character} · 整字 XY 快速修正`;$('summary').textContent=`${annotation.strokes.length} 笔 · ${changed().length} 笔已修改${unmatched?' · '+unmatched+' 笔仅有先验路径':''}`;
 $('evidence').textContent=data.evidence_label+' · 尚未验证实际书写';
 const checks=data.image_consistency||[];$('imageConsistency').hidden=!checks.length;
 $('imageConsistency').textContent=changed().length?'路径修改后需重新核对轮廓贴合度；此处不沿用初始数值。':'整图轮廓内行程（1 px 容差）：'+checks.map(s=>`第 ${s.stroke_number} 笔 ${((1-s.outside_fraction)*100).toFixed(1)}%${s.outside_vertex_count?'（有轮廓外点）':''}`).join(' · ')+'。只检查参考轮廓叠加，不代表实际墨迹质量。';
 $('radiusLabel').textContent=`${$('radius').value}% 图宽`;
 $('strokeList').replaceChildren(...annotation.strokes.map((s,i)=>{const b=document.createElement('button');b.className='strokeButton'+(selected===i?' active':'');b.style.setProperty('--stroke',colors[i%colors.length]);b.textContent=`${i+1}. ${s.display_name||names[s.type]||s.type}${changed().includes(s.id)?' · 已改':''}`;b.onclick=()=>{selected=i;draw();tell('在选中笔画的曲线上拖动，调整局部。');};return b;}));
 $('selectionInfo').textContent=selected<0?'先整体查看；只选择需要修正的笔画。':`当前：第 ${selected+1} 笔 ${annotation.strokes[selected].display_name||names[annotation.strokes[selected].type]||annotation.strokes[selected].type}`;
 $('undo').disabled=!history.length;$('redo').disabled=!future.length;}
function validate(value){if(value.role!=='stroke_annotation'||value.source_sha256!==initial.source_sha256||value.character!==initial.character||JSON.stringify(value.image_size_px)!==JSON.stringify(initial.image_size_px)||!Array.isArray(value.strokes)||value.strokes.length!==initial.strokes.length)throw Error('请选择同一图片、同一字的快速修正 JSON。');
 value.strokes.forEach((s,i)=>{if(s.id!==initial.strokes[i].id||s.xy_px.length!==initial.strokes[i].xy_px.length)throw Error('笔画或点数不一致，请使用对应的原始修正页面。');if(!/^[a-z][a-z0-9_]{0,63}$/.test(s.type)||!/^[a-z][a-z0-9_]{0,63}$/.test(s.variant))throw Error('笔画类型或变体无效。');const a=s.anchors;if(!Array.isArray(a)||a.length!==4||a.some(v=>!Number.isInteger(v))||a[0]!==0||a[3]!==s.xy_px.length-1||!(a[0]<a[1]&&a[1]<a[2]&&a[2]<a[3]))throw Error('阶段边界无效。');s.xy_px.forEach((p,j)=>{if(!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite)||p[0]<-.5||p[0]>W-.5||p[1]<-.5||p[1]>H-.5)throw Error('坐标超出图片范围。');if(j&&Math.hypot(p[0]-s.xy_px[j-1][0],p[1]-s.xy_px[j-1][1])<=1e-10)throw Error('相邻点重合，请撤销上一步。');});});}
function saveFile(name,text,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('save').onclick=()=>{try{validate(annotation);const value=structuredClone(annotation);value.provenance.editor='local_xy_quick_review_v1';value.provenance.edited_stroke_ids=changed();value.provenance.whole_character_confirmation=true;value.strokes.forEach(s=>{s.path_mode='preserve';s.review_status='confirmed';});delete value.annotation_id;saveFile(`${value.character}_修正路径.json`,JSON.stringify(value,null,2)+'\n','application/json');tell('已保存当前整字 XY。以后载入此 JSON 可继续修改。');}catch(e){tell(e.message);}};
$('csv').onclick=()=>{try{validate(annotation);const factor=data.transform.units_per_pixel,origin=data.transform.origin_original_cartesian_px,unit=data.units,rows=[`stroke_id,type,point_index,x_${unit},y_${unit},arc_length_${unit},s,phase_id,phase_u`];
 annotation.strokes.forEach(s=>{const a=arc(s.xy_px),anchors=s.anchors;s.xy_px.forEach((p,i)=>{const phase=i<anchors[1]?0:i<anchors[2]?1:2,first=anchors[phase],last=anchors[phase+1],u=(a[i]-a[first])/(a[last]-a[first]);rows.push([s.id,s.type,i,(p[0]-origin[0])*factor,(p[1]-origin[1])*factor,a[i]*factor,a[i]/a.at(-1),['entry','body','exit'][phase],u].join(','));});});saveFile(`${annotation.character}_修正XY.csv`,rows.join('\n')+'\n','text/csv;charset=utf-8');tell('已导出当前整字坐标；无需重新拟合。');}catch(e){tell(e.message);}};
$('importReview').onchange=async()=>{try{const file=$('importReview').files[0];if(!file)return;if(file.size>20000000)throw Error('文件过大。');const value=JSON.parse(await file.text());validate(value);if(value.provenance?.source_geometry_id!==initial.provenance.source_geometry_id)throw Error('此文件来自不同版本的初始路径，请打开对应页面。');snapshot();annotation=value;draw();tell('已载入上次修正。');}catch(e){tell(e.message);}};
$('undo').onclick=()=>{if(!history.length)return;future.push(structuredClone(annotation));annotation=history.pop();draw();tell('已撤销，其他笔画保持不变。');};
$('redo').onclick=()=>{if(!future.length)return;history.push(structuredClone(annotation));annotation=future.pop();draw();};
$('resetStroke').onclick=()=>{if(selected<0){tell('请先选择一笔。');return;}snapshot();annotation.strokes[selected]=structuredClone(initial.strokes[selected]);draw();tell('已恢复此笔的初始路径。');};
for(const id of ['imageLayer','baseLayer','radius'])$(id).oninput=draw;
$('resetView').onclick=()=>{view=[-.5,-.5,W,H];draw();};
svg.addEventListener('wheel',e=>{e.preventDefault();const q=coords(pointer(e)),f=e.deltaY>0?1.15:1/1.15;if(view[2]*f<W/30||view[2]*f>4*W)return;view=[q[0]-(q[0]-view[0])*f,q[1]-(q[1]-view[1])*f,view[2]*f,view[3]*f];draw();},{passive:false});
svg.addEventListener('pointerdown',e=>{const index=e.target.dataset.stroke,matrix=svg.getScreenCTM().inverse(),p=pointer(e,matrix);svg.setPointerCapture(e.pointerId);
 if(index==null){drag={kind:'pan',matrix,start:p,view:[...view]};return;}selected=Number(index);const path=structuredClone(annotation.strokes[selected].xy_px),a=arc(path);let center=0,best=Infinity;for(let i=1;i<path.length;i++){const q=path[i-1],dx=path[i][0]-q[0],dy=path[i][1]-q[1],t=Math.max(0,Math.min(1,((p[0]-q[0])*dx+(p[1]-q[1])*dy)/(dx*dx+dy*dy))),d=Math.hypot(q[0]+t*dx-p[0],q[1]+t*dy-p[1]);if(d<best){best=d;center=a[i-1]+t*(a[i]-a[i-1]);}}const radius=W*Number($('radius').value)/100;if(!a.some(v=>Math.abs(v-center)<radius)){drag=null;draw();tell('该段采样稀疏，范围内没有路径点。请增大修正范围、拖动端点，或在高级标注中插点。');return;}drag={kind:'local',start:p,path,arc:a,center,radius,saved:false};draw();});
svg.addEventListener('pointermove',e=>{if(!drag)return;if(drag.kind==='pan'){const p=pointer(e,drag.matrix);view=[drag.view[0]-(p[0]-drag.start[0]),drag.view[1]+(p[1]-drag.start[1]),drag.view[2],drag.view[3]];draw();return;}
 const p=pointer(e),delta=[p[0]-drag.start[0],p[1]-drag.start[1]];if(Math.hypot(...delta)<.05)return;const moved=drag.path.map((q,i)=>{const distance=Math.abs(drag.arc[i]-drag.center);if(distance>=drag.radius)return [...q];const weight=(1-(distance/drag.radius)**2)**2;return[q[0]+delta[0]*weight,q[1]+delta[1]*weight];});if(moved.some(q=>q[0]<-.5||q[0]>W-.5||q[1]<-.5||q[1]>H-.5)){tell('已到图片边界；缩小修正范围后再拖动。');return;}if(!drag.saved){snapshot();drag.saved=true;}annotation.strokes[selected].xy_px=moved;annotation.strokes[selected].review_status='unreviewed';draw();tell(`只调整了第 ${selected+1} 笔的局部；其余笔画保持原样。`);});
for(const event of ['pointerup','pointercancel'])svg.addEventListener(event,()=>drag=null);
draw();tell('可先直接查看；只有局部不对时才需要拖动。');
</script></html>'''


def write_quick_review(annotation, prepared, geometry, destination):
    stream = io.BytesIO(); prepared['image'].save(stream, format='PNG')
    payload = dict(annotation=review_annotation(annotation, geometry), units=geometry['units'],
        composition=annotation['provenance'].get('source_kind')=='template_composition',
        image_constraint=annotation['provenance'].get('image_constraint'),
        image_consistency=[dict(s['image_consistency'],stroke_number=i+1) for i,s in enumerate(geometry['strokes']) if 'image_consistency' in s],
        evidence_label={'teaching_reconstruction':'教学规则重建候选','font_fixture': '字库几何原型', 'synthetic_fixture': '解析几何测试样本'}.get(fixture_kind(annotation['provenance']), '图像几何候选'),
        transform=geometry['transform'], image_data_url='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode('ascii'))
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    Path(destination).write_text(PAGE.replace('__CSS__', CSS).replace('__DATA__', data), encoding='utf-8')
