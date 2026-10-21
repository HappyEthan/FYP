"""Inspectable rule reconstruction, source comparison and portable recipe exports."""
import base64
import copy
import html
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .report import CSS


def write_teaching_report(model,config,variants,source_raw,destination):
    from .teaching import ribbon
    variants=copy.deepcopy(variants)
    for variant in variants:
        stroke=variant['stroke']
        stroke['width_outline']=ribbon(stroke['xy'],stroke['relative_width']).tolist()
    with Image.open(io.BytesIO(source_raw)) as source:
        mime=Image.MIME[source.format]
    payload=dict(name=model['teaching']['name'],type=model['type'],variant=model['variant'],
        template_id=model['template_id'],sources=config['sources'],config=config,variants=variants,
        source_image='data:'+mime+';base64,'+base64.b64encode(source_raw).decode('ascii'))
    data=json.dumps(payload,ensure_ascii=False,allow_nan=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    Path(destination).write_text(PAGE.replace('__CSS__',CSS).replace('__DATA__',data),encoding='utf-8')


def write_library_report(entries,destination):
    groups={}
    for entry in entries:
        groups.setdefault(entry['type'],[]).append(entry)
    text='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    text+='<title>教学规则重建 · 基本笔画库</title><style>'+CSS+'.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}.cards .card{margin:0}.cards svg{height:240px}.category{margin-top:32px;scroll-margin-top:20px}.directory{display:flex;gap:8px;flex-wrap:wrap}.directory a{padding:6px 10px;border:1px solid #cbd8ea;border-radius:8px;background:white;text-decoration:none}</style>'
    text+=f'<h1>教学规则重建 · 基本笔画库</h1><p>本批 {len(groups)} 类基本笔画 · {len(entries)} 套写法候选。点击检查路径、阶段、相对宽度、笔法事件和原始教学图，并比较不同主体长度。</p>'
    text+='<p><span class="badge warn">教学规则重建候选 · 待人工复核</span></p><p>硬笔图供结构参考，毛笔文字供定性约束；曲线控制点和数值为人工设定。灰色轮廓表示相对宽度意图，实际墨迹与磁响应尚待验证。</p><nav class="directory" aria-label="基本笔画分类">'
    for kind,group in groups.items():
        category=group[0].get('category') or dict(name=group[0]['name'])
        text+='<a href="#category-'+html.escape(kind,quote=True)+'">'+html.escape(category['name'])+f'（{len(group)}）</a>'
    text+='</nav>'
    for kind,group in groups.items():
        category=group[0].get('category') or dict(name=group[0]['name'])
        title=(str(category['order'])+' · ' if 'order' in category else '')+category['name']
        text+='<section class="category" id="category-'+html.escape(kind,quote=True)+'"><h2>'+html.escape(title)+f' <small>· {len(group)} 种写法</small></h2><div class="cards">'
        for entry in group:
            model=json.loads((Path(destination).parent/'templates'/entry['id']/'template.json').read_text())
            xy=np.asarray(model['references'][0]['xy_px']);a=model['references'][0]['anchors']
            low=xy.min(axis=0);high=xy.max(axis=0);pad=max(float(np.ptp(xy,axis=0).max())*.15,5)
            view=[low[0]-pad,-high[1]-pad,*(high-low+2*pad)]
            text+='<article class="card"><h3>'+html.escape(entry['name'])+'</h3><svg viewBox="'+' '.join(map(str,view))+'">'
            for first,last,color in zip(a[:-1],a[1:],('#c67b20','#2868bd','#268568')):
                points=' '.join(f'{x:.8g},{-y:.8g}' for x,y in xy[first:last+1])
                text+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
            text+='</svg><p><a href="'+html.escape(entry['href'],quote=True)+'">检查模板与笔法依据 →</a></p></article>'
        text+='</div></section>'
    text+='<p class="small muted">新旧数据包各自保留版本。此页是生成结果快照，单页下载的修正配方需重新生成后才形成新版本。</p></html>'
    Path(destination).write_text(text,encoding='utf-8')


PAGE=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>教学笔画 · 模板检查</title><style>__CSS__
.layout{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:20px}.card{margin-top:0}#canvas{height:450px;max-height:60vh}#sourceImage{width:100%;height:auto;border:1px solid #dce3ec}.events{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}.events button.active{background:#e7effc;border-color:#245db9}#rules li{margin:8px 0;line-height:1.65}.source{margin:16px 0;line-height:1.7}.source small{display:block;color:#63748b}#readout{min-height:65px}.badge{margin-bottom:8px}select{max-width:100%}@media(max-width:850px){.layout{grid-template-columns:1fr}#canvas{height:340px}}
</style><h1 id="name"></h1><p><span class="badge warn">教学规则重建候选</span><span id="reviewBadge" class="badge"></span></p>
<p>检查结构、阶段与写法意图。曲线和数值由人工设定；教学图供参照，实际墨迹与运动尚待验证。</p>
<div class="layout"><main><section class="card"><div class="toolbar"><label>长度对照 <select id="variation"></select></label><label><input id="showWidth" type="checkbox" checked>相对宽度意图</label></div>
<svg id="canvas" aria-label="教学笔画路径及事件"></svg><div class="legend"><span class="entry">起笔</span><span class="body">行笔</span><span class="exit">收笔</span></div>
<div id="eventList" class="events"></div><label>整笔行程 s<input id="progress" type="range" min="0" max="1000" value="0"></label><div id="readout" class="readout"></div>
<p class="small muted">灰色范围是作者设定的相对宽度示意，不是毛笔墨迹仿真。长度对照只改变选中的主体跨度，起收笔及局部转折形态保持。对照范围为工程试验设置。</p></section>
<section class="card"><h2>原始教学图对照</h2><p class="small muted">硬笔示意图用于结构参考。表格中的阶段多为逐步完成的形态，未将各格路径拼接。以下保留完整原图和出处。</p><img id="sourceImage" alt="原始硬笔笔画教学表格"></section></main>
<aside><section class="card"><h2>笔法规则与假设</h2><ul id="rules"></ul><p class="small muted">方向和形态参考教学资料；曲线控制点、相对宽度数值、阶段位置为人工重建初值。笔法事件没有指定实际速度、停顿时间、Z 或磁目标。</p>
<label><input id="reviewed" type="checkbox">我已检查当前几何候选</label><div class="toolbar"><button id="exportRecipe" class="primary">下载当前配方</button><button id="exportCsv">导出当前 XY</button></div><div id="status" role="status" class="small"></div>
<p class="small">下载的配方可通过 teaching 命令生成新模板版本。确认几何仍保留“教学规则重建”来源。</p></section>
<section class="card"><h2>参考来源</h2><div id="sources"></div><p class="small">模板版本 <code id="templateId"></code></p><a href="template.json">原始模板 JSON</a></section></aside></div>
<script id="teaching-data" type="application/json">__DATA__</script><script>
'use strict';
const data=JSON.parse(document.getElementById('teaching-data').textContent),$=id=>document.getElementById(id),svg=$('canvas'),ns='http://www.w3.org/2000/svg';let selected=0,eventIndex=null;
const phases=['entry','body','exit'],colors=['#c67b20','#2868bd','#268568'],actions={touch_hint:'落笔提示',travel:'行笔',press_hint:'提按／调锋提示',lift_hint:'提锋提示',finish_hint:'收笔提示'},speeds={unspecified:'未设节拍',slower:'相对放慢提示',faster:'相对加快提示'};
function make(tag,attrs,parent=svg){const n=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);parent.appendChild(n);return n;}
function stroke(){return data.variants[selected].stroke;}function pts(path){return path.map(p=>[p[0],-p[1]].join(',')).join(' ');}
function draw(){const s=stroke(),xy=s.xy,a=s.anchors,outline=s.width_outline,x=outline.map(p=>p[0]),y=outline.map(p=>-p[1]),lo=[Math.min(...x),Math.min(...y)],hi=[Math.max(...x),Math.max(...y)],span=Math.max(hi[0]-lo[0],hi[1]-lo[1],1),pad=span*.18;svg.replaceChildren();svg.setAttribute('viewBox',[lo[0]-pad,lo[1]-pad,hi[0]-lo[0]+2*pad,hi[1]-lo[1]+2*pad].join(' '));
 if($('showWidth').checked)make('polygon',{points:pts(outline),fill:'#d3d9e1',opacity:.8});for(let i=0;i<3;i++)make('polyline',{points:pts(xy.slice(a[i],a[i+1]+1)),fill:'none',stroke:colors[i],'stroke-width':span/180,'stroke-linecap':'round','stroke-linejoin':'round'});
 s.events.forEach((e,i)=>{const circle=make('circle',{cx:e.xy[0],cy:-e.xy[1],r:span/100,fill:i===eventIndex?'#172e54':'#fff',stroke:'#596a83','stroke-width':span/300,'data-event':e.name});make('title',{},circle).textContent=e.label;});
 $('eventList').replaceChildren(...s.events.map((e,i)=>{const b=document.createElement('button');b.textContent=e.label;b.className=i===eventIndex?'active':'';b.onclick=()=>{eventIndex=i;$('progress').value=Math.round(e.s*1000);draw();};return b;}));
 let p,u,label;if(eventIndex!=null){const e=s.events[eventIndex];p=e.xy;u=e.s;label=e.label+' · '+actions[e.action]+' · '+speeds[e.speed_hint];}else{u=Number($('progress').value)/1000;let i=s.s.findIndex(v=>v>=u);if(i<0)i=xy.length-1;p=xy[i];if(i>0){const f=(u-s.s[i-1])/(s.s[i]-s.s[i-1]);p=xy[i-1].map((v,k)=>v+f*(xy[i][k]-v));}label='行程位置，尚未指定时间';}
 make('circle',{id:'progressMarker',cx:p[0],cy:-p[1],r:span/85,fill:'#183959',stroke:'white','stroke-width':span/400});$('readout').textContent=`${label}\ns = ${u.toFixed(3)} · XY = (${p[0].toFixed(3)}, ${p[1].toFixed(3)}) 参考笔宽单位`;
 $('reviewBadge').textContent=$('reviewed').checked?'当前几何已检查':'待人工检查';}
function download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('name').textContent=data.name+' · 模板检查';document.title=data.name+' · 教学笔画模板';$('sourceImage').src=data.source_image;$('templateId').textContent=data.template_id;
$('variation').replaceChildren(...data.variants.map((v,i)=>{const o=document.createElement('option');o.value=i;o.textContent=v.label;return o;}));
$('variation').onchange=()=>{selected=Number($('variation').value);eventIndex=null;$('reviewed').checked=false;$('status').textContent='已切换长度候选，检查状态已清除。';draw();};$('showWidth').onchange=draw;$('progress').oninput=()=>{eventIndex=null;draw();};$('reviewed').checked=data.variants[0].recipe.review_status==='confirmed';$('reviewed').onchange=draw;
for(const rule of data.variants[0].recipe.rule_notes){const li=document.createElement('li');li.textContent=rule;$('rules').appendChild(li);}
for(const source of data.sources){const box=document.createElement('div');box.className='source';const a=document.createElement('a');a.href=source.url;a.textContent=source.title;a.target='_blank';a.rel='noopener';box.appendChild(a);const small=document.createElement('small');small.textContent=source.use+(source.access==='indexed_text_only_images_unverified'?'（仅核实索引正文，配图未核验）':'');box.appendChild(small);$('sources').appendChild(box);}
$('exportRecipe').onclick=()=>{const value=structuredClone(data.config),recipe=structuredClone(data.variants[selected].recipe);recipe.review_status=$('reviewed').checked?'confirmed':'unreviewed';value.strokes=[recipe];download(recipe.id+'_配方.json',JSON.stringify(value,null,2)+'\n','application/json');$('status').textContent='已下载当前配方；重新生成后形成新模板版本。';};
$('exportCsv').onclick=()=>{const s=stroke(),rows=['point_index,x_reference_width,y_reference_width,s,phase_id,relative_width_intent'];s.xy.forEach((p,i)=>rows.push([i,...p,s.s[i],s.phase_id[i],s.relative_width[i]].join(',')));download(data.type+'_候选XY.csv',rows.join('\n')+'\n','text/csv;charset=utf-8');$('status').textContent='已导出当前 XY 和相对宽度意图，没有时间或磁目标。';};draw();
</script></html>'''
