"""从现场克隆局部重布射频及挡路的电源/SDA；禁止自动覆盖云端。"""
import copy
import hashlib
import heapq
import json
import math
from pathlib import Path

import numpy as np

from check_pcb_a5 import ROOT, U, ORIGIN, parse, xy, distance, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from build_a5_usb_soc_fanout import pad_center
from repair_clone_inner_layer_20260928 import line_distance, poly_distance, simplify, path_text
from test_a5_usb_soc_fanout import connected_groups
from audit_a5_ufl_keepout import audit

SOURCE = Path('/Users/liuchunyu/Downloads/PCB_克隆板射频调整前_20260928.json')
SHA = '5600ae8c27b1693d1d2c93d95d7cdae51f684dae1233f73f76016094cac43045'
OUT = ROOT/'easyeda_std/PCB_克隆板射频短路径候选_20260928.json'
REPORT = ROOT/'easyeda_std/克隆板射频短路径检查_20260928.json'
PREFIX = 'ggeRF0928'
STEP = .025
GAP = .1524
RF_WIDTH = .1500124  # 完全沿用当前50Ω候选线宽；不重新定义层叠。


def add_track(doc, net, layer, points, width):
    ident = f'{PREFIX}T{len(doc["shape"])}'
    doc['shape'].append(f'TRACK~{width/U:.8f}~{layer}~{net}~{path_text(simplify(points))}~{ident}~0')


def add_via(doc, net, point, od, drill):
    x,y = path_text([point]).split()
    doc['shape'].append(f'VIA~{x}~{y}~{od/U:.8f}~{net}~{drill/2/U:.8f}~{PREFIX}V{len(doc["shape"])}~0')


def route(doc, copper, holes, net, start_point, end_point, rf, env, width, od, drill):
    """有限区域多层候选搜索；不走L2。结果仍需独立几何和原生检查。"""
    tracks,vias,_ = routes(doc)
    circle=next(s.split('~') for s in doc['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]);br=float(circle[3])*U
    # 本轮仅在主控上半部处理，不触碰USB区。
    # 起点对齐网格，避免QFN引脚中心舍入后误侵占相邻脚的间距余量。
    xs=np.arange(16.+start_point[0]%STEP,30.5+STEP,STEP)
    ys=np.arange(-88.+start_point[1]%STEP,-81.+STEP,STEP)
    X,Y=np.meshgrid(xs,ys);edge=br-np.hypot(X-bc[0],Y-bc[1])
    layers=('1','22');free=[];m=STEP*math.sqrt(2)/2+.001
    for layer in layers:
        good=edge>=.30+width/2+m
        for p in copper+vias:
            if p['net']!=net and p['layer'] in (layer,'11'):
                good &= poly_distance(X,Y,p['poly'])>=GAP+width/2+m
        for t in tracks:
            if t['net']!=net and t['layer']==layer:
                for a,b in zip(t['points'],t['points'][1:]):
                    good &= line_distance(X,Y,a,b)>=GAP+(width+t['width'])/2+m
        for h in holes:good &= poly_distance(X,Y,h['poly'])>=.20+width/2+m
        good &= poly_distance(X,Y,env)>width/2+m
        free.append(good)
    vf=edge>=.30+od/2+m
    for p in copper+vias:
        limit=GAP+od/2+m if p['net']!=net else drill/2+.10+m
        # 同网新过孔也不落在表贴焊盘上，避免新增未审核的盘中孔。
        if p['net']!=net or p.get('kind')=='pad':vf &= poly_distance(X,Y,p['poly'])>=limit
    for t in tracks:
        if t['net']!=net:
            for a,b in zip(t['points'],t['points'][1:]):
                vf &= line_distance(X,Y,a,b)>=GAP+od/2+t['width']/2+m
    for h in holes:vf &= poly_distance(X,Y,h['poly'])>=.254+drill/2+m
    vf &= poly_distance(X,Y,env)>od/2+m
    # 信号孔在L2会挖空：避开RF线宽+3h参考地带，包含铺铜0.20mm间隙。
    for t in rf:
        for a,b in zip(t['points'],t['points'][1:]):
            vf &= line_distance(X,Y,a,b)>=RF_WIDTH/2+.2982+od/2+.20+m
    grid=lambda p:(int(round((p[1]-ys[0])/STEP)),int(round((p[0]-xs[0])/STEP)))
    starts=(0,*grid(start_point));ends=(0,*grid(end_point));H,W=X.shape
    for n in (starts,ends):assert free[n[0]][n[1],n[2]],('端点被阻挡',net,n)
    existing=set()
    for v in vias:
        if v['net']==net:
            p=tuple(sum(q[k] for q in v['poly'])/len(v['poly']) for k in (0,1));g=grid(p)
            if 0<=g[0]<H and 0<=g[1]<W:existing.add(g)
    heuristic=lambda n:math.hypot(n[1]-ends[1],n[2]-ends[2])*STEP
    queue=[(heuristic(starts),0,starts)];costs={starts:0};parent={}
    moves=[(dy,dx,STEP*math.hypot(dx,dy)) for dx in (-1,0,1) for dy in (-1,0,1) if dx or dy]
    while queue:
        _,cost,n=heapq.heappop(queue)
        if cost>costs[n]+1e-9:continue
        if n==ends:break
        l,y,x=n;opts=[]
        for dy,dx,dc in moves:
            ny,nx=y+dy,x+dx
            if not(0<=ny<H and 0<=nx<W and free[l][ny,nx]):continue
            if dx and dy and(not free[l][y,nx] or not free[l][ny,x]):continue
            opts.append(((l,ny,nx),dc))
        if (vf[y,x] or (y,x) in existing) and free[1-l][y,x]:
            opts.append(((1-l,y,x),.05 if (y,x) in existing else 3.))
        for nn,dc in opts:
            nc=cost+dc
            if nc+1e-9<costs.get(nn,float('inf')):
                costs[nn]=nc;parent[nn]=n;heapq.heappush(queue,(nc+heuristic(nn),nc,nn))
    else:raise AssertionError(('无法找到局部迁线路径',net,start_point,end_point))
    nodes=[ends]
    while nodes[-1]!=starts:nodes.append(parent[nodes[-1]])
    nodes.reverse();segments=[];active=0;pts=[start_point];newvias=[]
    for l,y,x in nodes:
        p=(float(xs[x]),float(ys[y]))
        if l!=active:
            segments.append((active,simplify(pts)));pts=[p];active=l
            if(y,x) not in existing:newvias.append(p)
        else:pts.append(p)
    pts.append(end_point);segments.append((active,simplify(pts)))
    def clear(ps,l):
        for a,b in zip(ps,ps[1:]):
            n=max(2,math.ceil(math.dist(a,b)/.01))
            xx=np.rint((np.linspace(a[0],b[0],n)-xs[0])/STEP).astype(int)
            yy=np.rint((np.linspace(a[1],b[1],n)-ys[0])/STEP).astype(int)
            if not np.all(free[l][yy,xx]):return False
        return True
    for l,ps in segments:
        cleaned=[ps[0]];i=0
        while i<len(ps)-1:
            accepted=None
            for j in range(len(ps)-1,i,-1):
                a,b=ps[i],ps[j];dx,dy=b[0]-a[0],b[1]-a[1];m=min(abs(dx),abs(dy));sx=1 if dx>=0 else -1;sy=1 if dy>=0 else -1
                for elbow in ((a[0]+sx*m,a[1]+sy*m),(b[0]-sx*m,b[1]-sy*m)):
                    test=simplify([a,elbow,b])
                    if clear(test,l):accepted=(j,test);break
                if accepted:break
            assert accepted
            i,ps2=accepted;cleaned+=ps2[1:]
        add_track(doc,net,layers[l],cleaned,width)
    for p in newvias:add_via(doc,net,p,od,drill)
    print('迁线',net,start_point,end_point,'新增过孔',newvias,flush=True)


def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA
    source,parts,copper,holes=parse(SOURCE);doc=copy.deepcopy(source)
    p=lambda ref,pin:pad_center(copper,ref,pin)
    removed={'gge5173006','gge5172997','gge5172994','gge5172991','gge5172988','gge5172964','gge5172961','gge5172958','gge5172955','gge5172919','gge5172916','gge5173150'}
    doc['shape']=[s for s in doc['shape'] if not(s.startswith('TRACK~') and (s.split('~')[5] in removed or s.split('~')[3]=='RF_SOC'))]
    add_track(doc,'RF_SOC','1',[p('U1','1'),(17.85,-84.3399126),(17.55,-84.6399126),(17.55,-85.13),(18.15,-85.73),(24.75,-85.73),(25.10,-85.38),(25.7840655,-85.38),p('C30','1')],RF_WIDTH)
    add_track(doc,'RF_SOC','1',[p('C30','1'),(27.0,-84.7480648),(27.03904,-84.7090254),p('R30','1')],RF_WIDTH)
    rf=[t for t in routes(doc)[0] if t['net'] in ('RF_SOC','R30_2')]
    _,_,zones=audit(SOURCE);env=zones['本体全层净空候选']['板心坐标多边形_mm'][0]
    route(doc,copper,holes,'I2C_SDA',p('U1','6'),(26.9523718,-86.5797354),rf,env,.0899922,.25,.15)
    # 相邻同电源脚先在表层连接，再跨RF走廊连到现有电容。
    route(doc,copper,holes,'3V3',p('U1','55'),p('U1','56'),rf,env,.2500122,.40,.20)
    route(doc,copper,holes,'3V3',p('U1','56'),p('C20','1'),rf,env,.2500122,.40,.20)
    route(doc,copper,holes,'3V3',p('C21','1'),p('C20','1'),rf,env,.2500122,.40,.20)
    route(doc,copper,holes,'3V3',p('U1','46'),p('U1','56'),rf,env,.2500122,.40,.20)
    for ref,pin in [('C30','2'),('C31','2'),('ANT1','3'),('ANT1','2')]:
        ground_via(doc,copper,holes,p(ref,pin),ref+'.'+pin,env)
    # 清空缓存；必须由原生编辑器重建信号孔避让。
    for i,s in enumerate(doc['shape']):
        if s.startswith('COPPERAREA~'):
            v=s.split('~');v[10]='';doc['shape'][i]='~'.join(v)
    return source,doc,copper,holes


def ground_via(doc,copper,holes,start,label,env):
    tracks,vias,_=routes(doc)
    circle=next(s.split('~') for s in doc['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]);br=float(circle[3])*U
    xs=np.arange(start[0]-1.5,start[0]+1.51,.05);ys=np.arange(start[1]-1.5,start[1]+1.51,.05)
    X,Y=np.meshgrid(xs,ys);good=br-np.hypot(X-bc[0],Y-bc[1])>=.505
    for p in copper+vias:
        if p['net']!='GND':good &= poly_distance(X,Y,p['poly'])>=GAP+.205
        elif p.get('kind')=='pad':good &= poly_distance(X,Y,p['poly'])>=.205
    for t in tracks:
        if t['net']!='GND':
            gap=.3048 if t['net'] in ('RF_SOC','R30_2') else GAP
            for a,b in zip(t['points'],t['points'][1:]):good &= line_distance(X,Y,a,b)>=gap+.205+t['width']/2
    for p in vias+[q for q in copper if q.get('kind')=='via']:
        center=tuple(sum(q[i] for q in p['poly'])/len(p['poly']) for i in (0,1))
        good &= np.hypot(X-center[0],Y-center[1])>=.505
    for h in holes:good &= poly_distance(X,Y,h['poly'])>=.359
    good &= poly_distance(X,Y,env)>=.205
    positions=sorted([(math.dist(start,(float(X[y,x]),float(Y[y,x]))),(float(X[y,x]),float(Y[y,x]))) for y,x in zip(*np.where(good))])
    for _,end in positions:
        dx,dy=end[0]-start[0],end[1]-start[1];d=min(abs(dx),abs(dy));sx=1 if dx>=0 else -1;sy=1 if dy>=0 else -1
        for elbow in ((start[0]+sx*d,start[1]+sy*d),(end[0]-sx*d,end[1]-sy*d)):
            pts=simplify([start,elbow,end]);t={'points':pts,'width':.254};ok=True
            for p in copper+vias:
                if p['net']!='GND' and p['layer'] in ('1','11') and track_gap(t,p['poly'])<GAP:ok=False;break
            if not ok:continue
            for other in tracks:
                if other['layer']!='1' or other['net']=='GND':continue
                gap=min(distance([a,b],[x,y]) for a,b in zip(pts,pts[1:]) for x,y in zip(other['points'],other['points'][1:]))-(.254+other['width'])/2
                need=.3048 if other['net'] in ('RF_SOC','R30_2') else GAP
                if gap<need:ok=False;break
            if ok and all(track_gap(t,h['poly'])>=.2 for h in holes):
                add_track(doc,'GND','1',pts,.254);add_via(doc,'GND',end,.4,.2)
                print('接地',label,end,flush=True);return
    raise AssertionError(('未找到可审核的接地过孔',label))


def check(source,doc,copper,holes):
    tracks,vias,_=routes(doc);issues=[];mins=[]
    ts=[t for t in tracks if t['id'].startswith(PREFIX)];vs=[v for v in vias if v['id'].startswith(PREFIX)]
    def test(kind,a,b,gap,limit=GAP):
        mins.append((gap,kind,a,b))
        if gap<limit-1e-5:issues.append([kind,a,b,round(gap,6),limit])
    circle=next(s.split('~') for s in doc['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]);br=float(circle[3])*U
    _,_,zones=audit(SOURCE);env=zones['本体全层净空候选']['板心坐标多边形_mm'][0]
    for t in ts:
        test('线到板边',t['id'],'圆板',br-max(math.dist(p,bc) for p in t['points'])-t['width']/2,.30)
        for p in copper+vias:
            if shared_layer(t,p) and t['net']!=p['net']:test('线到焊盘/孔',t['id'],p.get('id',p.get('ref','')+'.'+p.get('pin','')),track_gap(t,p['poly']))
        for q in tracks:
            if t['layer']==q['layer'] and t['net']!=q['net']:
                gap=min(distance([a,b],[x,y]) for a,b in zip(t['points'],t['points'][1:]) for x,y in zip(q['points'],q['points'][1:]))-(t['width']+q['width'])/2
                test('线到线',t['id'],q['id'],gap)
        for h in holes:test('线到机械孔',t['id'],h['ref'],track_gap(t,h['poly']),.20)
    for v in vs:
        test('孔到板边',v['id'],'圆板',br-max(math.dist(p,bc) for p in v['poly']),.30)
        test('孔到UFL净空',v['id'],'UFL',distance(v['poly'],env),.001)
        for p in copper+vias:
            if v['net']!=p['net']:test('孔到焊盘/孔',v['id'],p.get('id',p.get('ref','')+'.'+p.get('pin','')),distance(v['poly'],p['poly']))
        for t in tracks:
            if v['net']!=t['net']:test('孔到线',v['id'],t['id'],track_gap(t,v['poly']))
        for h in holes:test('孔到机械孔',v['id'],h['ref'],distance(v['poly'],h['poly']),.254)
        for other in vias+[p for p in copper if p.get('kind')=='via']:
            if other.get('id')==v['id']:continue
            # 铜环之间保留0.054mm时，对当前0.40/0.20孔相当于孔壁0.254mm。
            # 对0.25/0.15信号孔更严格；保守初筛，非制造孔表替代。
            test('孔环到孔环',v['id'],other.get('id',other.get('pin')),distance(v['poly'],other['poly']),.054)
    for n in {p['net'] for p in copper if p['net']}:
        old=connected_groups(source,copper,n);new=connected_groups(doc,copper,n)
        lost=[sorted(g) for g in old if not any(g<=q for q in new)]
        if lost:issues.append(['端点连接退化',n,lost])
    lib=lambda d:[s for s in d['shape'] if s.startswith('LIB~')]
    assert lib(source)==lib(doc) and source['DRCRULE']==doc['DRCRULE']
    assert not [t for t in tracks if t['layer']=='21' and t['net']!='GND']
    for n in ('RF_SOC','R30_2'):
        if len(connected_groups(doc,copper,n))!=1:issues.append(['射频端点未完整连接',n])
    for v in vs:
        if v['net']=='GND':continue
        for t in tracks:
            if t['net'] in ('RF_SOC','R30_2'):
                test('信号孔到射频参考地带',v['id'],t['id'],track_gap(t,v['poly']),.20+.2982)
    lens={n:sum(math.dist(a,b) for t in tracks if t['net']==n for a,b in zip(t['points'],t['points'][1:])) for n in ('RF_SOC','R30_2')}
    return {'冲突':issues,'最小间距项':sorted(mins)[:8],'射频长度_mm':lens,'新增过孔数':len(vs),'元件及规则保持':True,'原生DRC':False,'云端保存':False,'制造放行':False,
            '未完成':['C20/C21接地过孔局部候选未找到，不降低间距硬塞；其原有连接不改','完整RF屏蔽和电源去耦回路仍需整板审核','原生重建参考地与实际铜避让未验证']}


if __name__=='__main__':
    source,doc,c,h=build();result=check(source,doc,c,h)
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2));assert not result['冲突']
