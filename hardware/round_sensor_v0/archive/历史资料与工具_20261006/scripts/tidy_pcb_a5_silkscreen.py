"""按当前原生快照整理丝印；仅改位号和无极性 R/C 外框所在层。"""
import copy
import hashlib
import json
import math
import random
import re
from check_pcb_a5 import ROOT, U, ORIGIN, parse, xy
from tidy_pcb_a5_labels import bounds, overlap

SOURCE = ROOT/'easyeda_std/PCB_A5_silk_before_20260916.json'
OUT = ROOT/'easyeda_std/PCB_A5_silk_candidate_20260916.json'
NUM = re.compile(r'-?\d+(?:\.\d+)?')
SIZE, STROKE = .65, .12


def graphic_box(v):
    if v[0] == 'TRACK':
        nums = list(map(float, v[4].split()))
        pts = [xy(x,y) for x,y in zip(nums[::2],nums[1::2])]
        b = bounds(pts)
        half = float(v[1])*U/2
    elif v[0] == 'CIRCLE':
        x,y = xy(v[1],v[2]); r = float(v[3])*U
        b = x-r,y-r,x+r,y+r
        half = float(v[4])*U/2
    elif v[0] == 'ARC':
        # 本板保留的弧均是连接器脚一环；用完整圆包络保守避让。
        nums = list(map(float,NUM.findall(v[4])))
        x,y = xy(nums[0],nums[1]); r = max(nums[2],nums[3])*U
        b = x-2*r,y-2*r,x+2*r,y+2*r
        half = float(v[1])*U/2
    else:
        raise ValueError(v)
    return b[0]-half,b[1]-half,b[2]+half,b[3]+half


def layer_index(v):
    return {'TRACK':2,'ARC':2,'CIRCLE':5}.get(v[0])


def text_shape(t):
    ns = list(map(float,NUM.findall(t[11])))
    a = math.radians(float(t[5] or 0)); pts=[]
    for x,y in zip(ns[::2],ns[1::2]):
        x-=float(t[2]); y-=float(t[3])
        pts.append((x*math.cos(a)-y*math.sin(a),x*math.sin(a)+y*math.cos(a)))
    return pts,bounds(pts)


def main(source=SOURCE, out=OUT, tag='silkscreen'):
    doc, parts, copper, holes = parse(source)
    candidate=copy.deepcopy(doc)
    removed=[]; changes=[]; positions={}
    for layer in ('1','2'):
        silk=str(int(layer)+2)
        obs=[]
        for ref,p in parts.items():
            if p['layer'] != layer:
                continue
            # 完整器件焊盘外包络也作为不可放文字区，避免装配后被本体遮挡。
            pts=[q for a in copper if a['ref']==ref and a['kind']=='pad' for q in a['poly']]
            obs.append(bounds(pts))
            for v in p['items']:
                k=layer_index(v)
                if k is None or v[k] != silk:
                    continue
                if re.fullmatch(r'[RC]\d+',ref) and v[0] in ('TRACK','ARC'):
                    removed.append({'ref':ref,'kind':v[0], 'id':v[5] if v[0]=='TRACK' else v[6], 'layer':silk})
                else:
                    obs.append(graphic_box(v))
        obs += [bounds(v['poly']) for v in copper if v['layer']=='11']
        obs += [bounds(v['poly']) for v in holes]
        options={}
        for ref,p in parts.items():
            if p['layer'] != layer:
                continue
            if re.fullmatch(r'[RC]\d+',ref):
                continue
            t=next(v for v in p['items'] if v[:2]==['TEXT','P'])
            pts,b=text_shape(t)
            factor=(SIZE/U)/float(t[9])
            w,h=(b[2]-b[0])*factor*U+STROKE,(b[3]-b[1])*factor*U+STROKE
            px,py=p['center']; opts=[]
            for angle in (0,90):
                ww,hh=(w,h) if angle==0 else (h,w)
                for ix in range(-60,61):
                    for iy in range(-60,61):
                        dx,dy=ix*.1,iy*.1
                        cx,cy=px+dx,py+dy
                        box=(cx-ww/2,cy-hh/2,cx+ww/2,cy+hh/2)
                        if max(math.hypot(x,y) for x in (box[0],box[2]) for y in (box[1],box[3]))>8.75:
                            continue
                        if any(overlap(box,o,.20) for o in obs):
                            continue
                        score=dx*dx+dy*dy+.2*min(abs(dx),abs(dy))+(1.0 if angle else 0)
                        opts.append((score,cx,cy,box,angle))
            assert opts,ref
            options[ref]=sorted(opts)
        # 多种确定性顺序，避免先到的文字占掉中心元件仅有的近处空间。
        rng=random.Random(16); best=None
        for trial in range(100):
            order=sorted(options,key=lambda r:(len(options[r])+rng.uniform(-100,100)))
            assigned={}; cost=0
            for ref in order:
                chosen=next((o for o in options[ref] if not any(overlap(o[3],v[3],.22) for v in assigned.values())),None)
                if chosen is None:
                    break
                assigned[ref]=chosen
                cost+=chosen[0]**1.4
            if len(assigned)==len(options) and (best is None or cost<best[0]):
                best=(cost,assigned)
        assert best, ('无法安排全部位号',layer,[(r,len(v)) for r,v in options.items()],len(assigned))
        for ref,(_,cx,cy,box,angle) in best[1].items():
            t=next(v for v in parts[ref]['items'] if v[:2]==['TEXT','P'])
            pts,b=text_shape(t); factor=(SIZE/U)/float(t[9])
            if angle:
                pts=[(y,-x) for x,y in pts];b=bounds(pts)
            x=ORIGIN[0]+cx/U-(b[0]+b[2])/2*factor
            y=ORIGIN[1]+cy/U-(b[1]+b[3])/2*factor
            coords=iter(v for px,py in pts for v in (x+px*factor,y+py*factor))
            path=NUM.sub(lambda m:format(next(coords),'.4f'),t[11])
            changes.append({'ref':ref,'id':t[13], 'x':x,'y':y,'path':path,'angle':angle})
            positions[ref]={'center_mm':[cx,cy],'bbox_mm':box,
                            'distance_mm':round(math.dist((cx,cy),parts[ref]['center']),3)}
    moved={v['id']:v for v in removed}; texts={c['id']:c for c in changes}
    replacements=[]
    for i,shape in enumerate(candidate['shape']):
        if not shape.startswith('LIB~'):
            continue
        chunks=shape.split('#@$')
        for j in range(1,len(chunks)):
            v=chunks[j].split('~'); old=chunks[j]
            if v[0]=='TEXT' and v[1]=='P':
                if re.fullmatch(r'[RC]\d+',v[10]):
                    v[7]='12'
                else:
                    c=texts[v[13]]
                    for k,value in {2:c['x'],3:c['y'],4:STROKE/U,5:c['angle'],9:SIZE/U,11:c['path'],12:''}.items():
                        v[k]=str(value)
            elif v[0] in ('TRACK','ARC'):
                gid=v[5] if v[0]=='TRACK' else v[6]
                if gid in moved:
                    v[2]='12'
            chunks[j]='~'.join(v)
            if old!=chunks[j]:
                replacements.append([old,chunks[j]])
        candidate['shape'][i]='#@$'.join(chunks)
    out.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n')
    # 先逐一比较当前全部图元，防止覆盖用户导出后继续移动的元件。
    script="""// 仅丝印整理：保护当前元件布局、电气、铜、阻焊、钢网。
(function(){
var d=api('getSource',{type:'compress'});if(typeof d==='string')d=JSON.parse(d);
var expected=EXPECTED, rep=REPLACEMENTS;
function signature(s){return s.replace(/-?\\d+(?:\\.\\d+)?/g,function(v){return String(Math.round(Number(v)*100)/100);});}
var actual=d.shape.map(signature).sort(), base=expected.map(signature).sort();
if(JSON.stringify(actual)!==JSON.stringify(base))throw Error('当前布局已变化，停止，须重新读取；没有修改任何内容');
var map={};rep.forEach(function(r){map[signature(r[0])]=r[1];});var n=0;
d.shape=d.shape.map(function(s){return s.split('#@$').map(function(v){var t=map[signature(v)];if(t!==undefined){n++;return t;}return v;}).join('#@$');});
if(n!==rep.length)throw Error('修改数量不符，停止');
api('applySource',{source:JSON.stringify(d),createNew:false});
})();
""".replace('EXPECTED',json.dumps(doc['shape'],ensure_ascii=False)).replace('REPLACEMENTS',json.dumps(replacements,ensure_ascii=False))
    (ROOT/f'scripts/tidy_pcb_a5_{tag}.js').write_text(script)
    report={'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'font_mm':SIZE,'stroke_mm':STROKE,
            'moved_outlines':removed,'labels':positions,'max_label_distance_mm':max(v['distance_mm'] for v in positions.values()),
            'scope':f'保留25个R/C文档层位号；本轮转文档层外框图元{len(removed)}个；重排16个其他位号；未改铜、布局、封装脚号与网络。非制造放行。'}
    (ROOT/f'easyeda_std/pcb_a5_{tag}_plan.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('位号',len(changes),'外框图元',len(removed),'最远位号中心距离',report['max_label_distance_mm'])
    preview(out)
    assembly(out)


def preview(path, output=None):
    d,parts,copper,holes=parse(path)
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="760" viewBox="0 0 1400 760"><rect width="1400" height="760" fill="#101926"/>']
    for i,layer in enumerate(('1','2')):
        sign=1 if layer=='1' else -1; sx=350+i*700; sy=385; scale=34
        svg.append(f'<text x="{sx}" y="40" text-anchor="middle" fill="white" font-size="24">'+('顶面' if i==0 else '底面（翻板视图）')+'</text>')
        svg.append(f'<g transform="translate({sx},{sy}) scale({sign*scale},{scale})"><circle r="9" fill="#063e78"/>')
        for c in copper:
            if c['layer'] in (layer,'11'):
                svg.append('<polygon fill="#dfb641" points="'+' '.join(f'{x},{y}' for x,y in c['poly'])+'"/>')
        for h in holes:
            svg.append('<polygon fill="#101926" points="'+' '.join(f'{x},{y}' for x,y in h['poly'])+'"/>')
        svg.append(f'<g transform="scale({U}) translate({-ORIGIN[0]},{-ORIGIN[1]})" fill="none" stroke="white" stroke-linecap="round" stroke-linejoin="round">')
        # 同时绘制独立文字；接线功能标记不属于库内 N/P 位号。
        display_parts=list(parts.values())+[{'items':[s.split('~') for s in d['shape'] if not s.startswith('LIB~')]}]
        for p in display_parts:
            for v in p['items']:
                if v[0]=='TEXT' and v[7]==str(int(layer)+2) and v[12]!='none':
                    svg.append(f'<path d="{v[11]}" stroke-width="{v[4]}"/>')
                k=layer_index(v)
                if k is None or v[k]!=str(int(layer)+2):continue
                if v[0]=='TRACK':
                    svg.append(f'<polyline points="{v[4]}" stroke-width="{v[1]}"/>')
                elif v[0]=='CIRCLE':
                    svg.append(f'<circle cx="{v[1]}" cy="{v[2]}" r="{v[3]}" stroke-width="{v[4]}"/>')
                elif v[0]=='ARC':
                    svg.append(f'<path d="{v[4]}" stroke-width="{v[1]}"/>')
        svg.append('</g></g>')
    svg.append('<text x="700" y="735" text-anchor="middle" font-size="20" fill="white">丝印阅读检查 · 未布线，不可投板</text></svg>')
    (output or ROOT/'easyeda_std/PCB_A5_丝印预览.svg').write_text('\n'.join(svg))


def assembly(path):
    """不印在板上的独立装配定位图；位号在板外引出，端点指向元件原点。"""
    _,parts,copper,holes=parse(path)
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1900" height="1040" viewBox="0 0 1900 1040">',
         '<rect width="1900" height="1040" fill="#f6f8fb"/>',
         '<style>text{font-family:Arial,"PingFang SC",sans-serif}</style>',
         '<text x="50" y="44" font-size="26" fill="#172b46">A5 装配定位图 · 全部 41 个位号</text>',
         '<text x="50" y="76" font-size="16" fill="#52677e">仅用于识别元件位置，不是板上丝印；引线端点指元件原点。未布线，不可投板。</text>']
    for i,layer in enumerate(('1','2')):
        sx=475+i*950; sy=550; sc=34; sign=1 if i==0 else -1
        svg.append(f'<text x="{sx}" y="120" text-anchor="middle" font-size="23">'+('顶面' if i==0 else '底面（翻板视图）')+'</text>')
        svg.append(f'<circle cx="{sx}" cy="{sy}" r="{9*sc}" fill="#e0eaf3" stroke="#6b8298" stroke-width="2"/>')
        for c in copper:
            if c['layer'] in (layer,'11'):
                pts=' '.join(f'{sx+sign*x*sc},{sy+y*sc}' for x,y in c['poly'])
                svg.append(f'<polygon points="{pts}" fill="#cfb572" stroke="#947431" stroke-width=".5"/>')
        for h in holes:
            pts=' '.join(f'{sx+sign*x*sc},{sy+y*sc}' for x,y in h['poly'])
            svg.append(f'<polygon points="{pts}" fill="#f6f8fb" stroke="#758594"/>')
        rows=[(r,sign*p['center'][0],p['center'][1]) for r,p in parts.items() if p['layer']==layer]
        for side in (-1,1):
            group=sorted([v for v in rows if (v[1]<0)==(side<0)],key=lambda v:(v[2],v[1]))
            for j,(ref,x,y) in enumerate(group):
                yy=sy+(j-(len(group)-1)/2)*40
                x1=sx+side*370; x2=sx+side*390; px=sx+x*sc; py=sy+y*sc
                color='#217583' if re.fullmatch(r'[RC]\d+',ref) else '#643987'
                svg.append(f'<path d="M {px},{py} L {x1},{yy} L {x2},{yy}" stroke="{color}" stroke-width="1.3" fill="none" opacity=".8"/>')
                svg.append(f'<circle cx="{px}" cy="{py}" r="3.2" fill="{color}" stroke="white" stroke-width="1"/>')
                anchor='end' if side<0 else 'start'
                svg.append(f'<text x="{x2+side*7}" y="{yy+6}" text-anchor="{anchor}" fill="{color}" font-size="20" font-weight="600">{ref}</text>')
    svg.append('<text x="50" y="996" font-size="17" fill="#52677e">青色：电阻、电容（位号及外框只保留在文档层）　紫色：芯片、接口等。元件继续移动后须重新生成本图。</text></svg>')
    (ROOT/'easyeda_std/PCB_A5_装配定位图.svg').write_text('\n'.join(svg))


if __name__=='__main__':
    main()
