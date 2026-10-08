"""生成 USB/充电区重新摆位候选；不覆盖当前入口，不添加正式走线。"""
import copy
import hashlib
import json
import math
import re

from check_pcb_a5 import ROOT, U, parse, distance, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from build_a5_rf_clearance_layout import ref, fmt, pairs
from build_a5_usb_front_candidate import rotate_shift_180, pad_center

SOURCE = ROOT/'easyeda_std/PCB_A5_USB主控侧_云端重开回读_20260917.json'
SOURCE_SHA = 'c141e3ac3c2a1830652e99aaf9db58f33591925196debad1bfec956f78543533'
OUT = ROOT/'easyeda_std/PCB_A5_USB区域重新摆位候选_20260917.json'
REPORT = ROOT/'easyeda_std/pcb_a5_usb_zone_placement_check_20260917.json'
SVG = ROOT/'easyeda_std/PCB_A5_USB区域重新摆位对照.svg'
CLEARANCE = .1524
EDGE_CLEARANCE = .20

# 只动四颗：R3/R4保留原90°方向；U6追加180°，让D+/D-顺序同时匹配接口和电阻。
TARGETS = {
    'R3': {'center':(-.75,-1.10), 'rotate180':False},
    'R4': {'center':(.05,-1.10), 'rotate180':False},
    'U6': {'center':(-.60,-2.65), 'rotate180':True},
    'R10':{'center':(5.00,-4.50), 'rotate180':False},
}


def signature(copper):
    return sorted((p['ref'],p['pin'],p['net'],p['kind']) for p in copper)


def svg_translate(text,dx,dy):
    if not text.strip():return text
    num=r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    tokens=re.findall(r'[A-Za-z]|'+num,text);out=[];i=0
    counts={'M':2,'L':2,'T':2,'C':6,'S':4,'Q':4,'A':7,'H':1,'V':1,'Z':0}
    while i<len(tokens):
        cmd=tokens[i];i+=1;upper=cmd.upper();assert upper in counts,(cmd,text[:80])
        n=counts[upper];vals=list(map(float,tokens[i:i+n]));i+=n;assert len(vals)==n
        if upper in {'M','L','T','C','S','Q'}:
            for j in range(0,n,2):vals[j]+=dx;vals[j+1]+=dy
        elif upper=='A':vals[-2]+=dx;vals[-1]+=dy
        elif upper=='H':vals[0]+=dx
        elif upper=='V':vals[0]+=dy
        out += [cmd,*map(fmt,vals)]
    return ' '.join(out)


def node_translate(node,dx,dy):
    a=node.get('attrs',{})
    if 'c_origin' in a:a['c_origin']=pairs(a['c_origin'],dx,dy,True)
    if 'points' in a:a['points']=pairs(a['points'],dx,dy)
    for child in node.get('childNodes',[]):node_translate(child,dx,dy)


def shift_lib_safe(shape,delta):
    dx,dy=(v/U for v in delta);chunks=[s.split('~') for s in shape.split('#@$')];head=chunks[0]
    head[1],head[2]=fmt(float(head[1])+dx),fmt(float(head[2])+dy)
    for v in chunks[1:]:
        kind=v[0]
        if kind in {'TEXT','PAD'}:
            v[2],v[3]=fmt(float(v[2])+dx),fmt(float(v[3])+dy)
            if kind=='TEXT':v[11]=svg_translate(v[11],dx,dy)
            else:
                if v[10].strip():v[10]=pairs(v[10],dx,dy)
                if len(v)>19 and v[19].strip():v[19]=pairs(v[19],dx,dy,True)
        elif kind=='TRACK':v[4]=pairs(v[4],dx,dy)
        elif kind=='SOLIDREGION':v[3]=svg_translate(v[3],dx,dy)
        elif kind=='ARC':v[4]=svg_translate(v[4],dx,dy)
        elif kind in {'CIRCLE','HOLE'}:v[1],v[2]=fmt(float(v[1])+dx),fmt(float(v[2])+dy)
        elif kind=='SVGNODE':
            node=json.loads(v[1]);node_translate(node,dx,dy)
            v[1]=json.dumps(node,ensure_ascii=False,separators=(',',':'))
        else:raise ValueError(('未允许的实例图形',kind))
    return '#@$'.join('~'.join(v) for v in chunks)


def transform(shape, old_center, spec):
    dx=spec['center'][0]-old_center[0];dy=spec['center'][1]-old_center[1]
    return rotate_shift_180(shape,(dx,dy)) if spec['rotate180'] else shift_lib_safe(shape,(dx,dy))


def conflicts(doc, copper, holes):
    tracks,vias,unsupported=routes(doc);assert not unsupported
    moved=[p for p in copper if p['ref'] in TARGETS]
    found=[]
    def add(kind,a,b,gap):
        if gap<CLEARANCE-1e-5:found.append([kind,a,b,round(gap,6)])
    for p in moved:
        for q in copper:
            if p is q or p['ref']==q['ref'] or p['net']==q['net'] or not shared_layer(p,q):continue
            add('移动焊盘-焊盘',p['ref']+'.'+p['pin'],q['ref']+'.'+q['pin'],distance(p['poly'],q['poly']))
        for t in tracks:
            if p['layer']==t['layer'] and p['net']!=t['net']:
                add('移动焊盘-线',p['ref']+'.'+p['pin'],t['id'],track_gap(t,p['poly']))
        for v in vias:
            if p['net']!=v['net']:add('移动焊盘-孔',p['ref']+'.'+p['pin'],v['id'],distance(p['poly'],v['poly']))
        for i,h in enumerate(holes):add('移动焊盘-机械孔',p['ref']+'.'+p['pin'],h['ref']+':'+str(i),distance(p['poly'],h['poly']))
        for x,y in p['poly']:
            edge=9-math.hypot(x,y)
            if edge<EDGE_CLEARANCE-1e-5:found.append(['移动焊盘-板边',p['ref']+'.'+p['pin'],'圆板',round(edge,6)])
    unique=[];seen=set()
    for item in found:
        key=tuple(item)
        if key not in seen:seen.add(key);unique.append(item)
    return unique


def virtual_lane_conflicts(doc,copper,holes):
    # 只验证 U6 到 R3/R4 的底层预留通道；图元不写入PCB。
    r=lambda name,pin:pad_center(copper,name,pin)
    lanes=[
        {'name':'D+预留通道','net':'USB_DP','layer':'2','width':.155,
         'points':[r('U6','1'),(-1.00,-3.30),(-1.00,-2.30),(-1.00,-1.53),r('R3','1')]},
        {'name':'D-预留通道','net':'USB_DM','layer':'2','width':.155,
         'points':[r('U6','2'),(.35,-3.00),(.35,-2.20),(.45,-1.80),r('R4','1')]},
    ]
    tracks,vias,_=routes(doc);issues=[]
    for lane in lanes:
        for p in copper:
            if p['layer']!=lane['layer'] or p['net']==lane['net'] or p['ref'] in {'U6','R3','R4'}:continue
            gap=track_gap(lane,p['poly'])
            if gap<CLEARANCE-1e-5:issues.append([lane['name'],'焊盘',p['ref']+'.'+p['pin'],round(gap,6)])
        for t in tracks:
            if t['layer']!=lane['layer'] or t['net']==lane['net']:continue
            gap=min(distance([a,b],[c,d]) for a,b in zip(lane['points'],lane['points'][1:])
                    for c,d in zip(t['points'],t['points'][1:]))-(lane['width']+t['width'])/2
            if gap<CLEARANCE-1e-5:issues.append([lane['name'],'走线',t['id'],round(gap,6)])
        for v in vias:
            if v['net']==lane['net']:continue
            gap=track_gap(lane,v['poly'])
            if gap<CLEARANCE-1e-5:issues.append([lane['name'],'过孔',v['id'],round(gap,6)])
        for i,h in enumerate(holes):
            gap=track_gap(lane,h['poly'])
            if gap<CLEARANCE-1e-5:issues.append([lane['name'],'机械孔',h['ref']+':'+str(i),round(gap,6)])
    return lanes,issues


def write_svg(parts,copper,holes,lanes):
    scale=45;cx=455;cy=455
    pts=lambda poly:' '.join(f'{cx+x*scale:.2f},{cy+y*scale:.2f}' for x,y in poly)
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="910" height="980" viewBox="0 0 910 980">',
         '<rect width="910" height="980" fill="#f4f7fa"/>',
         '<style>text{font-family:Arial,"PingFang SC",sans-serif}</style>',
         '<text x="35" y="42" font-size="25" fill="#172336">PCB-A5 · USB区域重新摆位候选（底面顶视）</text>',
         f'<circle cx="{cx}" cy="{cy}" r="{9*scale}" fill="#dfeaf3" stroke="#526b7d" stroke-width="2"/>']
    for p in copper:
        if p['layer'] not in {'2','11'}:continue
        moved=p['ref'] in TARGETS
        fill='#f59e0b' if moved else ('#94a3b8' if p['layer']=='11' else '#c5d2dc')
        out.append(f'<polygon points="{pts(p["poly"])}" fill="{fill}" stroke="#fff" stroke-width=".7"/>')
    for h in holes:out.append(f'<polygon points="{pts(h["poly"])}" fill="#f4f7fa" stroke="#64748b" stroke-width="1"/>')
    colors={'D+预留通道':'#2563eb','D-预留通道':'#dc2626'}
    for lane in lanes:
        xy=' '.join(f'{cx+x*scale:.2f},{cy+y*scale:.2f}' for x,y in lane['points'])
        out.append(f'<polyline points="{xy}" fill="none" stroke="{colors[lane["name"]]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    for name in TARGETS:
        x,y=parts[name]['center'];out.append(f'<circle cx="{cx+x*scale:.2f}" cy="{cy+y*scale:.2f}" r="5" fill="#111827"/>')
        out.append(f'<text x="{cx+x*scale+8:.2f}" y="{cy+y*scale-8:.2f}" font-size="18" fill="#111827">{name}</text>')
    out += ['<text x="35" y="910" font-size="17" fill="#334155">橙色：本轮移动焊盘；蓝/红：仅用于净空检查的D+/D-预留通道，不是正式走线。</text>',
            '<text x="35" y="940" font-size="17" fill="#334155">18 mm、41元件、网络签名不变；未导入嘉立创、未运行原生DRC、禁止生产。</text>','</svg>']
    SVG.write_text('\n'.join(out)+'\n')


def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SOURCE_SHA,'来源已变化，停止生成'
    source=json.loads(SOURCE.read_text());doc=copy.deepcopy(source)
    _,source_parts,source_copper,_=parse(SOURCE)
    moved=[]
    for i,s in enumerate(doc['shape']):
        if not s.startswith('LIB~'):continue
        name=ref(s)
        if name in TARGETS:
            doc['shape'][i]=transform(s,source_parts[name]['center'],TARGETS[name]);moved.append(name)
    assert set(moved)==set(TARGETS)

    # 移走器件后撤回所有接触旧焊盘的走线；其余用户走线完整保留。
    source_tracks,_,unsupported=routes(source);assert not unsupported
    old_pads=[p for p in source_copper if p['ref'] in TARGETS]
    touched={t['id'] for t in source_tracks for p in old_pads
             if t['layer']==p['layer'] and t['net']==p['net'] and track_gap(t,p['poly'])<=1e-4}
    kept=[];removed=[]
    for s in doc['shape']:
        v=s.split('~')
        if v[0]=='TRACK' and (v[5] in touched or v[3] in {'USB_DP','USB_DM'}):removed.append(s)
        else:kept.append(s)
    doc['shape']=kept
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')

    parsed,parts,copper,holes=parse(OUT)
    static_poses={r:(source_parts[r]['center'],source_parts[r]['rotation']) for r in source_parts if r not in TARGETS}
    assert all((parts[r]['center'],parts[r]['rotation'])==pose for r,pose in static_poses.items())
    assert signature(copper)==signature(source_copper)
    placement_issues=conflicts(parsed,copper,holes)
    lanes,lane_issues=virtual_lane_conflicts(parsed,copper,holes)
    write_svg(parts,copper,holes,lanes)
    result={
        '日期':'2026-09-17','源文件':SOURCE.name,'源SHA256':SOURCE_SHA,'候选文件':OUT.name,
        '状态':'本地USB区域摆位候选；未导入原生编辑器、未增加正式走线、禁止生产',
        '目标位置':TARGETS,'移动元件数':len(TARGETS),'未移动元件数':len(parts)-len(TARGETS),
        '板径_mm':18,'元件总数':len(parts),'网络焊盘签名不变':True,
        '撤回旧走线ID':sorted(s.split('~')[5] for s in removed),'撤回图元数':len(removed),
        '摆位局部冲突':placement_issues,'USB电阻侧预留通道':lanes,'预留通道冲突':lane_issues,
        '判定':{'摆位局部冲突清零':not placement_issues,'电阻侧预留通道清零':not lane_issues,
                '允许进入接口扇出设计':not placement_issues and not lane_issues},
        '限制':['预留通道仅验证U6至R3/R4，不是正式USB布线',
                '尚未验证J1交错脚扇出、90欧姆、连续参考地或ESD近端回流',
                '未运行嘉立创原生DRC、未保存云端、未确认0.45/0.20mm过孔工艺']}
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    result=build()
    print(json.dumps({'候选':result['候选文件'],'摆位冲突':len(result['摆位局部冲突']),
                      '通道冲突':len(result['预留通道冲突']),'判定':result['判定']},ensure_ascii=False,indent=2))
