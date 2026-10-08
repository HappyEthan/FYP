"""在已回读克隆上批量补线。只生成本地候选，不自动上传或放宽规则。"""
import copy
import collections
import heapq
import json
import math
from pathlib import Path
import numpy as np
from check_pcb_a5 import ROOT, U, parse, xy, distance, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from repair_clone_inner_layer_20260928 import line_distance, poly_distance, simplify, path_text
from test_a5_usb_soc_fanout import connected_groups
from audit_a5_ufl_keepout import audit

SOURCE = Path('/Users/liuchunyu/Downloads/PCB_克隆板批量布线前_20260928.json')
BASE = ROOT/'easyeda_std/PCB_克隆板射频短路径_云端重开_20260928.json'
OUT = ROOT/'easyeda_std/PCB_克隆板批量补线候选_20260928.json'
REPORT = ROOT/'easyeda_std/克隆板批量补线检查_20260928.json'
PREFIX = 'ggeBATCH0928'
LAYERS = ('1','2','22')
STEP = .04
GAP = .1524
RESERVED_GROUND = []  # 本轮调用者可预留 (层号, 多边形)，不改变原生设计规则。
THERMAL_VIA_PADS = set()  # 仅显式指定同网接地大焊盘；钢网/焊接另行验收。
MAX_SEARCH_NODES = 500000
NEW_VIA_COST = 2.5
KEEPOUT_SOURCE = None

def clearance(doc,a,b):
    def value(net):
        rule=next((r for r in doc['DRCRULE'].values() if isinstance(r,dict) and net in r.get('nets',[])),doc['DRCRULE']['Default'])
        return rule['clearance']*U
    return max(value(a),value(b))

def center(p):
    return tuple((min(q[k] for q in p['poly'])+max(q[k] for q in p['poly']))/2 for k in (0,1))

def unique_id(doc,kind):
    existing={s.split('~')[5 if s.startswith('TRACK~') else 6] for s in doc['shape'] if s.startswith(('TRACK~','VIA~'))}
    i=len(doc['shape'])
    while f'{PREFIX}{kind}{i}' in existing:i+=1
    return f'{PREFIX}{kind}{i}'

def add_track(doc, net, layer, points, width):
    ps=simplify(points)
    if len(ps)>1:
        doc['shape'].append(f'TRACK~{width/U:.8f}~{layer}~{net}~{path_text(ps)}~{unique_id(doc,"T")}~0')

def add_via(doc, net, point, od, drill):
    x,y=path_text([point]).split()
    doc['shape'].append(f'VIA~{x}~{y}~{od/U:.8f}~{net}~{drill/2/U:.8f}~{unique_id(doc,"V")}~0')

def obstacles(doc,copper,holes,net,width,od,drill,start):
    tracks,vias,_=routes(doc)
    circle=next(s.split('~') for s in doc['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]);br=float(circle[3])*U
    xs=np.arange(start[0]+math.floor((bc[0]-br-start[0])/STEP)*STEP,bc[0]+br+STEP,STEP)
    ys=np.arange(start[1]+math.floor((bc[1]-br-start[1])/STEP)*STEP,bc[1]+br+STEP,STEP)
    X,Y=np.meshgrid(xs,ys);edge=br-np.hypot(X-bc[0],Y-bc[1])
    margin=STEP*math.sqrt(2)/2+.001
    free=[edge>=.3+width/2+margin for l in LAYERS]
    vf=edge>=.3+od/2+margin
    # 只在障碍物附近算距离，避免每个多边形扫描整板。
    def region(poly,r):
        xx=[p[0] for p in poly];yy=[p[1] for p in poly]
        ix=np.where((xs>=min(xx)-r)&(xs<=max(xx)+r))[0]
        iy=np.where((ys>=min(yy)-r)&(ys<=max(yy)+r))[0]
        if not len(ix) or not len(iy):return None
        return np.s_[iy[0]:iy[-1]+1,ix[0]:ix[-1]+1]
    def blockpoly(mask,poly,r):
        sl=region(poly,r+STEP)
        if sl is not None:mask[sl] &= poly_distance(X[sl],Y[sl],poly)>=r
    def blockline(mask,ps,r):
        for a,b in zip(ps,ps[1:]):
            sl=region([a,b],r+STEP)
            if sl is not None:mask[sl] &= line_distance(X[sl],Y[sl],a,b)>=r
    for p in copper+vias:
        if p['net']!=net:
            gap=clearance(doc,net,p['net'])
            for i,l in enumerate(LAYERS):
                if p['layer'] in (l,'11'):blockpoly(free[i],p['poly'],gap+width/2+margin)
            blockpoly(vf,p['poly'],gap+od/2+margin)
        elif p.get('kind')=='pad':
            if net=='GND' and (p['ref'],p['pin']) in THERMAL_VIA_PADS:
                sl=region(p['poly'],drill/2+.1+margin+STEP)
                if sl is not None:
                    ds=poly_distance(X[sl],Y[sl],p['poly'])
                    ep=p['poly']+[p['poly'][0]]
                    ed=np.minimum.reduce([line_distance(X[sl],Y[sl],a,b) for a,b in zip(ep,ep[1:])])
                    vf[sl]&=(ds>=drill/2+.1+margin)|((ds==0)&(ed>=od/2+.1+margin))
            else:blockpoly(vf,p['poly'],drill/2+.1+margin)
        if p.get('kind')=='via' or p in vias:
            # 各种孔径统一采用保守孔环间隔，不允许同网孔相挤。
            blockpoly(vf,p['poly'],od/2+.054+margin)
    for t in tracks:
        if t['net']!=net:
            gap=clearance(doc,net,t['net'])
            if t['layer'] in LAYERS:blockline(free[LAYERS.index(t['layer'])],t['points'],gap+(width+t['width'])/2+margin)
            blockline(vf,t['points'],gap+(od+t['width'])/2+margin)
        if net!='GND' and t['net'] in ('RF_SOC','R30_2'):
            blockline(vf,t['points'],t['width']/2+.2982+.20+od/2+margin)
    for h in holes:
        for f in free:blockpoly(f,h['poly'],.2+width/2+margin)
        blockpoly(vf,h['poly'],.254+od/2+margin)
    _,_,zones=audit(KEEPOUT_SOURCE or SOURCE)
    env=zones['本体全层净空候选']['板心坐标多边形_mm'][0]
    for f in free:blockpoly(f,env,width/2+margin)
    blockpoly(vf,env,od/2+margin)
    if net!='GND':
        # 预留真实 USB 投影 + 3h + 地铜避让宽度，不把整个多边形当作禁布区。
        # 允许远离 USB 的局部信号穿过参考地多边形边缘，实际铜面仍须重建核验。
        if RESERVED_GROUND:
            for t in tracks:
                if t['layer']=='2' and t['net'].startswith('USB_D'):
                    blockline(free[LAYERS.index('22')],t['points'],t['width']/2+.2982+.2+width/2+margin)
                    blockline(vf,t['points'],t['width']/2+.2982+clearance(doc,net,'GND')+od/2+margin)
    return xs,ys,free,vf

def route(doc,copper,holes,net,a,b,width,od,drill):
    aa=a if isinstance(a,list) else [a];bb=b if isinstance(b,list) else [b]
    start,end=center(aa[0]),center(bb[0])
    xs,ys,free,vf=obstacles(doc,copper,holes,net,width,od,drill,start)
    grid=lambda p:(int(round((p[1]-ys[0])/STEP)),int(round((p[0]-xs[0])/STEP)))
    H,W=free[0].shape
    def contacts(items):
        result={}
        for item in items:
            p=center(item);n=(LAYERS.index(item['layer']),*grid(p))
            if 0<=n[1]<H and 0<=n[2]<W and free[n[0]][n[1],n[2]]:result[n]=p
        return result
    start_nodes=contacts(aa);end_nodes=contacts(bb)
    if not start_nodes or not end_nodes:return False,'端点网格间距不足'
    samevias=[v for v in routes(doc)[1]+[p for p in copper if p['kind']=='via'] if v['net']==net]
    existing={grid(center(v)) for v in samevias}
    ymin,ymax=min(n[1] for n in end_nodes),max(n[1] for n in end_nodes)
    xmin,xmax=min(n[2] for n in end_nodes),max(n[2] for n in end_nodes)
    heuristic=lambda n:math.hypot(max(ymin-n[1],0,n[1]-ymax),max(xmin-n[2],0,n[2]-xmax))*STEP
    queue=[(heuristic(n),0,n) for n in start_nodes];heapq.heapify(queue)
    costs={n:0 for n in start_nodes};parent={}
    moves=[(dy,dx,STEP*math.hypot(dx,dy)) for dx in (-1,0,1) for dy in (-1,0,1) if dx or dy]
    while queue:
        _,cost,n=heapq.heappop(queue)
        if cost>costs[n]+1e-9:continue
        if n in end_nodes:break
        l,y,x=n;opts=[]
        for dy,dx,dc in moves:
            ny,nx=y+dy,x+dx
            if not(0<=ny<H and 0<=nx<W and free[l][ny,nx]):continue
            if dx and dy and(not free[l][y,nx] or not free[l][ny,x]):continue
            opts.append(((l,ny,nx),dc))
        if vf[y,x] or (y,x) in existing:
            for ll in range(3):
                if ll!=l and free[ll][y,x]:opts.append(((ll,y,x),.1 if (y,x) in existing else NEW_VIA_COST))
        for nn,dc in opts:
            nc=cost+dc
            if nc+1e-9<costs.get(nn,float('inf')):
                costs[nn]=nc;parent[nn]=n;heapq.heappush(queue,(nc+heuristic(nn),nc,nn))
        if len(costs)>MAX_SEARCH_NODES:return False,'搜索预算到达，未强行走线'
    else:return False,'固定布局未找到路径'
    nodes=[n]
    while nodes[-1] in parent:nodes.append(parent[nodes[-1]])
    nodes.reverse();start=start_nodes[nodes[0]];end=end_nodes[nodes[-1]]
    segments=[];active=nodes[0][0];pts=[start];newvias=[]
    for l,y,x in nodes:
        p=(float(xs[x]),float(ys[y]))
        if l!=active:
            segments.append((active,simplify(pts)));pts=[p];active=l
            if(y,x) not in existing:newvias.append(p)
        else:pts.append(p)
    pts.append(end);segments.append((active,simplify(pts)))
    def clear(ps,l):
        for aa,bb in zip(ps,ps[1:]):
            n=max(2,math.ceil(math.dist(aa,bb)/.01))
            xx=np.rint((np.linspace(aa[0],bb[0],n)-xs[0])/STEP).astype(int)
            yy=np.rint((np.linspace(aa[1],bb[1],n)-ys[0])/STEP).astype(int)
            if not np.all(free[l][yy,xx]):return False
        return True
    size=len(doc['shape'])
    for l,ps in segments:
        cleaned=[ps[0]];i=0
        while i<len(ps)-1:
            accepted=None
            for j in range(len(ps)-1,i,-1):
                aa,bb=ps[i],ps[j];dx,dy=bb[0]-aa[0],bb[1]-aa[1];m=min(abs(dx),abs(dy));sx=1 if dx>=0 else -1;sy=1 if dy>=0 else -1
                for elbow in ((aa[0]+sx*m,aa[1]+sy*m),(bb[0]-sx*m,bb[1]-sy*m)):
                    test=simplify([aa,elbow,bb])
                    if clear(test,l):accepted=(j,test);break
                if accepted:break
            if accepted is None:
                doc['shape']=doc['shape'][:size];return False,'路径简化失败'
            i,ps2=accepted;cleaned+=ps2[1:]
        add_track(doc,net,LAYERS[l],cleaned,width)
    for p in newvias:add_via(doc,net,p,od,drill)
    issues=check_new(doc,copper,holes,doc['shape'][size:])
    if issues:
        doc['shape']=doc['shape'][:size];return False,issues[:2]
    return True,{'孔数':len(newvias),'长度':round(sum(math.dist(x,y) for _,ps in segments for x,y in zip(ps,ps[1:])),3),
                 '起点':start,'终点':end,'起点层':LAYERS[nodes[0][0]],'终点层':LAYERS[nodes[-1][0]],
                 '换层点':newvias}

def check_new(doc,copper,holes,shapes):
    ids={s.split('~')[5 if s.startswith('TRACK~') else 6] for s in shapes if s.startswith(('TRACK~','VIA~'))}
    tracks,vias,_=routes(doc);bad=[]
    for t in tracks:
        if t['id'] not in ids:continue
        for p in copper+vias:
            if shared_layer(t,p) and t['net']!=p['net'] and track_gap(t,p['poly'])<clearance(doc,t['net'],p['net'])-1e-5:bad.append(['线-焊盘',t['id'],p.get('id',p.get('ref')),track_gap(t,p['poly'])])
        for q in tracks:
            if t['net']!=q['net'] and t['layer']==q['layer']:
                gap=min(distance([a,b],[x,y]) for a,b in zip(t['points'],t['points'][1:]) for x,y in zip(q['points'],q['points'][1:]))-(t['width']+q['width'])/2
                if gap<clearance(doc,t['net'],q['net'])-1e-5:bad.append(['线-线',t['id'],q['id'],gap])
        for h in holes:
            if track_gap(t,h['poly'])<.2-1e-5:bad.append(['线-孔',t['id'],h['ref']])
    for v in vias:
        if v['id'] not in ids:continue
        for p in copper+vias:
            if v['net']!=p['net'] and distance(v['poly'],p['poly'])<clearance(doc,v['net'],p['net'])-1e-5:bad.append(['过孔-铜',v['id'],p.get('id',p.get('ref'))])
        for t in tracks:
            if v['net']!=t['net'] and track_gap(t,v['poly'])<clearance(doc,v['net'],t['net'])-1e-5:bad.append(['过孔-线',v['id'],t['id']])
        for h in holes:
            if distance(v['poly'],h['poly'])<.254-1e-5:bad.append(['过孔-孔',v['id'],h['ref']])
    return bad

def build():
    source,parts,copper,holes=parse(SOURCE)
    baseline=json.loads(BASE.read_text())
    assert collections.Counter(source['shape'])==collections.Counter(baseline['shape'])
    assert source['DRCRULE']==baseline['DRCRULE']
    doc=copy.deepcopy(source);log=[]
    # USB 为成对约束，单独人工确定路径；此循环仅补普通信号及电源。
    nets=['BOOT_N','MCU_EN','IMU_INT','I2C_SCL','I2C_SDA','REG_EN','J1_A5','BAT_P','VSYS','USB_5V','3V3']
    for net in nets:
        old=len(connected_groups(doc,copper,net));blocked=set();count=0
        while True:
            gs=connected_groups(doc,copper,net)
            if len(gs)<=1:break
            contacts=island_contacts(doc,copper,net)
            options=[]
            for i,g in enumerate(contacts):
                for h in contacts[:i]:
                    for a in g:
                        for b in h:
                            key=tuple(sorted((a['id'],b['id'])))
                            if key in blocked:continue
                            options.append((math.dist(center(a),center(b)),key,a,b))
            if not options:break
            _,key,a,b=min(options,key=lambda x:(x[0],x[1]))
            power=net in ('3V3','VSYS','BAT_P','USB_5V')
            width=.2500122 if power else .1000 if net=='J1_A5' else .0899922
            od,drill=(.4,.2) if power or net=='J1_A5' else (.2500122,.1500124)
            ok,info=route(doc,copper,holes,net,a,b,width,od,drill)
            print(net,a['id'],b['id'],ok,info,flush=True)
            log.append({'网络':net,'起点':a['id'],'终点':b['id'],'成功':ok,'详情':info})
            if not ok:blocked.add(key)
            else:count+=1
            # 单网多次失败时保留已通过部分，不无界重复搜索。
            if len(blocked)>=15:break
        print('NET',net,old,'->',len(connected_groups(doc,copper,net)),flush=True)
        OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    result={'日志':log,'新增几何冲突':check_new(doc,copper,holes,[s for s in doc['shape'] if PREFIX in s]),'端点连通组':{n:[len(connected_groups(source,copper,n)),len(connected_groups(doc,copper,n))] for n in nets},'原生DRC':False,'云端保存':False,'制造放行':False}
    for i,s in enumerate(doc['shape']):
        if s.startswith('COPPERAREA~'):
            v=s.split('~');v[10]='';doc['shape'][i]='~'.join(v)
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    assert not result['新增几何冲突']

def island_contacts(doc,copper,net):
    """接已有导线/过孔，而不是强迫每条新线绕回原焊盘。"""
    tracks,vias,_=routes(doc)
    nodes=[dict(p,id=p['ref']+'.'+p['pin']) for p in copper if p['net']==net]
    nodes += [dict(t,kind='track') for t in tracks if t['net']==net]
    nodes += [dict(v,kind='via') for v in vias if v['net']==net]
    def bounds(n):
        ps=n['points'] if n['kind']=='track' else n['poly'];r=n.get('width',0)/2
        return min(x for x,y in ps)-r,max(x for x,y in ps)+r,min(y for x,y in ps)-r,max(y for x,y in ps)+r
    boxes=[bounds(n) for n in nodes]
    parent=list(range(len(nodes)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def gap(a,b):
        if a['kind']=='track' and b['kind']=='track':return min(distance([x,y],[u,v]) for x,y in zip(a['points'],a['points'][1:]) for u,v in zip(b['points'],b['points'][1:]))-(a['width']+b['width'])/2
        if a['kind']=='track':return track_gap(a,b['poly'])
        if b['kind']=='track':return track_gap(b,a['poly'])
        return distance(a['poly'],b['poly'])
    for i,a in enumerate(nodes):
        for j,b in enumerate(nodes[:i]):
            x0,x1,y0,y1=boxes[i];u0,u1,v0,v1=boxes[j]
            if max(x0-u1,u0-x1,y0-v1,v0-y1)>1e-5:continue
            if shared_layer(a,b) and gap(a,b)<=1e-5:parent[root(i)]=root(j)
    groups={};haspad=set()
    for i,n in enumerate(nodes):
        r=root(i)
        if n['kind']=='pad':haspad.add(r)
        ps=n['points'] if n['kind']=='track' else [center(n)]
        layers=LAYERS if n['layer']=='11' else (n['layer'],)
        for pi,p in enumerate(ps):
            for l in layers:
                if l in LAYERS:groups.setdefault(r,[]).append({'id':n['id']+':'+str(pi)+':'+l,'poly':[p],'layer':l})
    return [v for k,v in groups.items() if k in haspad]

if __name__=='__main__':build()
