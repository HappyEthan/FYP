"""只修复已回读克隆板的两条内层1异网线；保留全部元件与其他布线。

局部网格搜索仅生成候选。独立铜间距/端点连通检查后仍须原生 DRC。
不铺未经避让的整板实心铜，不覆盖来源或自动同步云端。
"""
import copy
import hashlib
import heapq
import json
import math
from pathlib import Path

import numpy as np

from check_pcb_a5 import ROOT, U, ORIGIN, parse, xy, distance, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from test_a5_usb_soc_fanout import connected_groups

SOURCE = Path('/Users/liuchunyu/Downloads/PCB_PCB_圆形传感板_SCH_A5-copy_2026-09-28.json')
SHA = '84c07b1e9f9d279c34c4858e8f08a01691a59059aab6739dcfc5939640b7ecb0'
OUT = ROOT / 'easyeda_std/PCB_克隆板内层迁线候选_20260928.json'
REPORT = ROOT / 'easyeda_std/克隆板内层迁线检查_20260928.json'
PREFIX = 'ggeINNER0928'
STEP = .05
WIDTH = .2500122
VIA_OD = .40
VIA_DRILL = .20
GAP = .155  # 稍高于现规则0.152mm；不降低任何网络规则。
LAYERS = ('22', '1', '2')


def path_text(points):
    return ' '.join(f'{p[k]/U+ORIGIN[k]:.8f}' for p in points for k in (0, 1))


def line_distance(x, y, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    den = dx*dx+dy*dy
    t = np.clip(((x-a[0])*dx+(y-a[1])*dy)/den, 0, 1) if den else 0
    return np.hypot(x-a[0]-t*dx, y-a[1]-t*dy)


def poly_distance(x, y, poly):
    result = np.full(np.broadcast(x, y).shape, np.inf)
    hit = np.zeros(result.shape, bool)
    for a, b in zip(poly, poly[1:]+poly[:1]):
        result = np.minimum(result, line_distance(x, y, a, b))
        if abs(a[1]-b[1]) > 1e-12:
            hit ^= ((a[1]>y) != (b[1]>y)) & (x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])
    return np.where(hit, 0, result)


def simplify(points):
    out = []
    for p in points:
        if out and math.dist(p, out[-1]) < 1e-8:
            continue
        while len(out)>1:
            a, b = out[-2:]
            cross = (b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0])
            dot = (b[0]-a[0])*(p[0]-b[0])+(b[1]-a[1])*(p[1]-b[1])
            if abs(cross)>1e-8 or dot<0:
                break
            out.pop()
        out.append(p)
    return out


def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SHA
    source, parts, copper, holes = parse(SOURCE)
    doc = copy.deepcopy(source)
    ts, vs, _ = routes(source)
    target = {t['net']: t for t in ts if t['layer']=='21' and t['net']!='GND'}
    assert set(target) == {'3V3', 'MCU_EN'}
    changed = []
    for i, shape in enumerate(doc['shape']):
        v = shape.split('~')
        if v[0]=='TRACK' and v[5]==target['MCU_EN']['id']:
            v[2]='22'
            doc['shape'][i]='~'.join(v)
            changed.append({'id':v[5], 'net':'MCU_EN', 'old_layer':'21', 'new_layer':'22'})
    doc['shape']=[s for s in doc['shape'] if not (s.startswith('TRACK~') and s.split('~')[5]==target['3V3']['id'])]
    existing_tracks, existing_vias, _ = routes(doc)
    circle=next(s.split('~') for s in doc['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]); br=float(circle[3])*U
    xs=np.arange(math.floor((bc[0]-br)/STEP)*STEP, bc[0]+br+STEP, STEP)
    ys=np.arange(math.floor((bc[1]-br)/STEP)*STEP, bc[1]+br+STEP, STEP)
    X,Y=np.meshgrid(xs,ys)
    edge=br-np.hypot(X-bc[0],Y-bc[1])
    free=[]
    # 对网格线段的两个端点增加半格对角线余量，防止离散路径擦过障碍。
    margin=STEP*math.sqrt(2)/2+.001
    for layer in LAYERS:
        good=edge >= .30+WIDTH/2+margin
        for p in copper+existing_vias:
            if p['net']!='3V3' and p['layer'] in (layer,'11'):
                good &= poly_distance(X,Y,p['poly']) >= GAP+WIDTH/2+margin
        for t in existing_tracks:
            if t['net']!='3V3' and t['layer']==layer:
                for a,b in zip(t['points'],t['points'][1:]):
                    good &= line_distance(X,Y,a,b) >= GAP+(WIDTH+t['width'])/2+margin
        for hole in holes:
            good &= poly_distance(X,Y,hole['poly']) >= .20+WIDTH/2+margin
        free.append(good)
    via_free=edge >= .30+VIA_OD/2+margin
    for p in copper+existing_vias:
        if p['net']!='3V3':
            via_free &= poly_distance(X,Y,p['poly']) >= GAP+VIA_OD/2+margin
    for t in existing_tracks:
        if t['net']!='3V3':
            for a,b in zip(t['points'],t['points'][1:]):
                via_free &= line_distance(X,Y,a,b) >= GAP+VIA_OD/2+t['width']/2+margin
    for hole in holes:
        via_free &= poly_distance(X,Y,hole['poly']) >= .254+VIA_DRILL/2+margin
    # 保留现有局部实心GND；在其内打信号孔会造成短路，因此新增孔必须远离它。
    import re
    for s in source['shape']:
        v=s.split('~')
        if v[0]=='SOLIDREGION' and v[1]=='21' and v[2]=='GND':
            numbers=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',v[3])))
            poly=[xy(*numbers[i:i+2]) for i in range(0,len(numbers),2)]
            via_free &= poly_distance(X,Y,poly) >= GAP+VIA_OD/2+margin
    # U.FL全层中心净空，按当前连接器的审核包络防止新增铜侵入。
    from audit_a5_ufl_keepout import audit
    _, _, zones=audit(SOURCE)
    env=zones['本体全层净空候选']['板心坐标多边形_mm'][0]
    for i in range(len(free)):
        free[i] &= poly_distance(X,Y,env)>WIDTH/2+margin
    via_free &= poly_distance(X,Y,env)>VIA_OD/2+margin
    start_point,end_point=target['3V3']['points'][0],target['3V3']['points'][-1]
    grid=lambda p:(int(round((p[1]-ys[0])/STEP)),int(round((p[0]-xs[0])/STEP)))
    start=(0,*grid(start_point)); end=(0,*grid(end_point))
    for node in (start,end):
        assert free[node[0]][node[1],node[2]], ('端点网格不可用',node)
    height,width=X.shape
    moves=[(dy,dx,STEP*math.hypot(dx,dy)) for dx in (-1,0,1) for dy in (-1,0,1) if dx or dy]
    heuristic=lambda n:math.hypot(n[1]-end[1],n[2]-end[2])*STEP
    queue=[(heuristic(start),0.,start)]; costs={start:0.}; parent={}
    found=False
    while queue:
        _, cost, node=heapq.heappop(queue)
        if cost>costs[node]+1e-9:continue
        if node==end:found=True;break
        layer,y,x=node
        candidates=[]
        for dy,dx,stepcost in moves:
            ny,nx=y+dy,x+dx
            if not (0<=ny<height and 0<=nx<width and free[layer][ny,nx]):continue
            if dx and dy and (not free[layer][y,nx] or not free[layer][ny,x]):continue
            candidates.append(((layer,ny,nx),stepcost))
        if via_free[y,x]:
            for other in range(len(LAYERS)):
                if other!=layer and free[other][y,x]:candidates.append(((other,y,x),3.0))
        for nxt,stepcost in candidates:
            nc=cost+stepcost
            if nc+1e-9<costs.get(nxt,float('inf')):
                costs[nxt]=nc;parent[nxt]=node
                heapq.heappush(queue,(nc+heuristic(nxt),nc,nxt))
    assert found,'局部电源迁线未找到可行路径；不生成可用候选'
    nodes=[end]
    while nodes[-1]!=start:nodes.append(parent[nodes[-1]])
    nodes.reverse()
    segments=[]; active=nodes[0][0]; points=[start_point]; vias=[]
    for layer,y,x in nodes:
        point=(float(xs[x]),float(ys[y]))
        if layer!=active:
            segments.append((LAYERS[active],simplify(points)))
            vias.append(point);points=[point];active=layer
        else:points.append(point)
    points.append(end_point);segments.append((LAYERS[active],simplify(points)))
    def clear_path(points, layer):
        for a,b in zip(points,points[1:]):
            n=max(2,math.ceil(math.dist(a,b)/.01))
            xx=np.linspace(a[0],b[0],n);yy=np.linspace(a[1],b[1],n)
            ix=np.rint((xx-xs[0])/STEP).astype(int);iy=np.rint((yy-ys[0])/STEP).astype(int)
            if not np.all(free[LAYERS.index(layer)][iy,ix]):return False
        return True
    cleaned_segments=[]
    for layer,pts in segments:
        cleaned=[pts[0]];i=0
        while i<len(pts)-1:
            accepted=None
            for j in range(len(pts)-1,i,-1):
                a,b=pts[i],pts[j];dx,dy=b[0]-a[0],b[1]-a[1]
                d=min(abs(dx),abs(dy));sx=1 if dx>=0 else -1;sy=1 if dy>=0 else -1
                for elbow in ((a[0]+sx*d,a[1]+sy*d),(b[0]-sx*d,b[1]-sy*d)):
                    trial=simplify([a,elbow,b])
                    if clear_path(trial,layer):accepted=(j,trial);break
                if accepted:break
            assert accepted,'已有可行路径的整理失败'
            i,trial=accepted;cleaned.extend(trial[1:])
        cleaned_segments.append((layer,simplify(cleaned)))
    segments=cleaned_segments
    for i,(layer,points) in enumerate(segments):
        doc['shape'].append(f'TRACK~{WIDTH/U:.8f}~{layer}~3V3~{path_text(points)}~{PREFIX}T{i}~0')
    for i,p in enumerate(vias):
        x,y=path_text([p]).split()
        doc['shape'].append(f'VIA~{x}~{y}~{VIA_OD/U:.8f}~3V3~{VIA_DRILL/U/2:.8f}~{PREFIX}V{i}~0')
    # 用原生铺铜替换不具备异网孔避让的局部实心填充，实际铜由EDA重新计算。
    doc['shape']=[s for s in doc['shape'] if not s.startswith('SOLIDREGION~21~GND~')]
    perimeter=[(bc[0]+(br-.31)*math.cos(math.radians(a)),
                bc[1]+(br-.31)*math.sin(math.radians(a))) for a in range(0,360,2)]
    def svgpath(points):
        return 'M '+path_text([points[0]])+' '+' '.join('L '+path_text([p]) for p in points[1:])+' Z'
    doc['shape'].append(f'COPPERAREA~0.5~21~GND~{svgpath(perimeter)}~{.20/U:.8f}~solid~{PREFIX}GND~direct~none~~0~第二层连续参考地~1~1~1~{.30/U:.8f}~yes~0')
    doc['shape'].append(f'SOLIDREGION~21~~{svgpath(env)}~cutout~{PREFIX}UFL~~~~0')
    return source,doc,copper,holes,changed,segments,vias


def check(source,doc,copper,holes):
    tracks,vias,_=routes(doc)
    changed_tracks=[t for t in tracks if t['id'].startswith(PREFIX) or t['id']=='gge5173117']
    newvias=[v for v in vias if v['id'].startswith(PREFIX)]
    issues=[];minimum=float('inf')
    def test(kind,a,b,gap,limit=.1524):
        nonlocal minimum
        minimum=min(minimum,gap)
        if gap<limit-1e-5:issues.append([kind,a,b,round(gap,6),limit])
    for t in changed_tracks:
        for p in copper+vias:
            if shared_layer(t,p) and t['net']!=p['net']:
                test('线到焊盘或过孔',t['id'],p.get('id',p.get('ref','')+'.'+p.get('pin','')),track_gap(t,p['poly']))
        for q in tracks:
            if t['layer']==q['layer'] and t['net']!=q['net']:
                gap=min(distance([a,b],[x,y]) for a,b in zip(t['points'],t['points'][1:]) for x,y in zip(q['points'],q['points'][1:]))-(t['width']+q['width'])/2
                test('线到线',t['id'],q['id'],gap)
        for h in holes:test('线到机械孔',t['id'],h['ref'],track_gap(t,h['poly']),.20)
    for v in newvias:
        for p in copper+vias:
            if v['net']!=p['net']:test('孔到焊盘或过孔',v['id'],p.get('id',p.get('ref','')+'.'+p.get('pin','')),distance(v['poly'],p['poly']))
        for t in tracks:
            if v['net']!=t['net']:test('孔到线',v['id'],t['id'],track_gap(t,v['poly']))
        for h in holes:test('孔到机械孔',v['id'],h['ref'],distance(v['poly'],h['poly']),.254)
    connections={}
    for net in ('3V3','MCU_EN'):
        old=connected_groups(source,copper,net);new=connected_groups(doc,copper,net)
        lost=[sorted(g) for g in old if not any(g<=n for n in new)]
        connections[net]={'原连通组数':len(old),'现连通组数':len(new),'退化连接组':lost}
        if lost:issues.append(['原有端点连接退化',net,lost])
    lib=lambda d:[s for s in d['shape'] if s.startswith('LIB~')]
    assert lib(source)==lib(doc),'元件或封装改变'
    assert source['DRCRULE']==doc['DRCRULE'],'设计规则改变'
    assert not [t for t in tracks if t['layer']=='21' and t['net']!='GND']
    return {'新增铜几何冲突':issues,'新增铜最小异网间距_mm':minimum,'受影响网络连通':connections,
            '全部元件逐字保持':True,'设计规则逐字保持':True,'内层1异网走线数':0}


def main():
    source,doc,c,h,changed,segments,vias=build()
    report=check(source,doc,c,h)
    report.update(来源=str(SOURCE),来源SHA256=SHA,迁线=changed,
                  电源新路径=[{'层':l,'坐标_mm':p} for l,p in segments],新增电源过孔坐标_mm=vias,
                  原生DRC已验证=False,云端已保存=False,全板连续地已完成=False,
                  第二层铺铜定义='新增原生GND铺铜及U.FL局部挖空；异网间距0.20mm，板边0.30mm，去孤岛。尚须EDA重建和回读确认实际铜。',制造放行=False,
                  下一步='原生验证迁线并完善L2避让铺铜；射频及USB继续局部重布。')
    assert not report['新增铜几何冲突'], report['新增铜几何冲突']
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    report['候选SHA256']=hashlib.sha256(OUT.read_bytes()).hexdigest()
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
