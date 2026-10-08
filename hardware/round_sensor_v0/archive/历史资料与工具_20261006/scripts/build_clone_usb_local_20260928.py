"""USB 优先局部重布实验；来源锁定，未验收候选不得覆盖云端。"""
import copy, hashlib, json, math, sys
from pathlib import Path
from check_pcb_a5 import ROOT, U, ORIGIN, parse, shared_layer, distance
from audit_a5_routed_snapshot import routes, track_gap
from build_a5_usb_zone_placement import shift_lib_safe
from build_a5_usb_front_candidate import rotate_shift_180, local_clearance
import build_a5_usb_front_candidate as check
from build_a5_rf_clearance_layout import ref
from build_a5_usb_soc_fanout import pad_center
from test_a5_usb_soc_fanout import connected_groups
import repair_clone_batch_20260928 as batch

SOURCE=ROOT/'easyeda_std/PCB_克隆板批量补线_原生回读_20260928.json'
SHA='9d75f1244549d9def425d98eda4fd0a8496061458a9061c360e269ae1f0c8068'
OUT=ROOT/'easyeda_std/PCB_克隆板USB局部重布_未验收候选_20260928.json'
REPORT=ROOT/'easyeda_std/克隆板USB局部重布检查_20260928.json'
PREFIX='ggeUSB0928'
TARGETS={'R3':(23.85,-78.4),'R4':(23.05,-78.4),'R6':(20.8,-78.4),
         'R1':(19.2,-78.4),'R10':(21.25,-76.9),'U6':(22.55,-76.8)}
GROUND_ZONE=[(21.3,-79.7),(24.15,-79.7),(24.3,-79.55),(24.3,-75.45),
             (22.65,-75.45),(22.65,-74.65),(21.3,-74.65)]

def routed_geometry(doc):
    ts,vs,unsupported=routes(doc)
    # 既有L2动态铺铜和U.FL挖空单独保留，旧几何助手只负责离散铜。
    assert set(unsupported)<= {'COPPERAREA','SOLIDREGION'}
    return ts,vs,[]

def save(doc):
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    return parse(OUT)

def dimensions(doc,net):
    rule=next((r for r in doc['DRCRULE'].values() if isinstance(r,dict) and net in r.get('nets',[])),doc['DRCRULE']['Default'])
    return tuple(rule[k]*U for k in ('trackWidth','viaHoleDiameter','viaHoleD'))

def local_check(doc,c,h):
    check.DELTAS=set(TARGETS)|{'R2','D3','C1','C5','C2','ANT1','C20','C21','C9','SW1','SW3','J1','U4'}
    ts,vs,_=routes(doc)
    nets={p['ref']+'.'+p['pin']:p['net'] for p in c}
    nets.update({t['id']:t['net'] for t in ts+vs})
    return [r for r in local_clearance(doc,c,h) if r[1] not in nets or r[2] not in nets or
            r[3]<batch.clearance(doc,nets[r[1]],nets[r[2]])-1e-5]

def salvage(doc,c,h,removed):
    """保留撤回长线中仍安全的部分，避免一个局部冲突撤掉整条跨板连接。"""
    ts,_,_=routes({'shape':removed})
    count=0
    def segment(t,a,b,depth=0):
        nonlocal count
        size=len(doc['shape']);batch.add_track(doc,t['net'],t['layer'],[a,b],t['width'])
        added=doc['shape'][size:]
        if not added:return
        zone_hit=t['layer']=='22' and t['net']!='GND' and distance([a,b],GROUND_ZONE)<t['width']/2+.2
        if not zone_hit and not batch.check_new(doc,c,h,added):count+=1;return
        doc['shape']=doc['shape'][:size]
        if math.dist(a,b)<.15 or depth>=8:return
        mid=tuple((x+y)/2 for x,y in zip(a,b))
        segment(t,a,mid,depth+1);segment(t,mid,b,depth+1)
    for t in ts:
        if t['net'].startswith('USB_D'):continue
        for a,b in zip(t['points'],t['points'][1:]):segment(t,a,b)
    return count

def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA
    source,parts,oldc,holes=parse(SOURCE);doc=copy.deepcopy(source)
    batch.SOURCE=SOURCE;batch.PREFIX=PREFIX
    for i,s in enumerate(doc['shape']):
        if s.startswith('LIB~') and ref(s) in TARGETS:
            r=ref(s);delta=tuple(TARGETS[r][k]-parts[r]['center'][k] for k in (0,1))
            doc['shape'][i]=(rotate_shift_180 if r=='U6' else shift_lib_safe)(s,delta)
    # 撤回所有接触被移动焊盘的旧导线，不让其误接新位置的其他焊盘。
    ts,vs,_=routes(source)
    touched={t['id'] for t in ts for p in oldc if p['ref'] in TARGETS and
             shared_layer(t,p) and t['net']==p['net'] and track_gap(t,p['poly'])<=1e-4}
    removed=[];kept=[]
    for s in doc['shape']:
        v=s.split('~')
        if v[0]=='TRACK' and (v[5] in touched or v[3] in ('USB_DP_SOC','USB_DM_SOC','USB_DP','USB_DM')):
            removed.append(s)
        else:kept.append(s)
    doc['shape']=kept
    _,_,c,h=save(doc)
    get=lambda r,p:pad_center(c,r,p)
    # 两个主控侧孔，均在焊盘外；禁止盘中孔。
    for net,r,p,v in [('USB_DP_SOC','R3','26',(23.85,-79.36)),
                      ('USB_DM_SOC','R4','25',(23.05,-79.36))]:
        start=get('U1',p);dx=v[0]-start[0]
        batch.add_track(doc,net,'1',[start,(start[0],v[1]+abs(dx)),v],.155)
        batch.add_via(doc,net,v,.4,.2)
        batch.add_track(doc,net,'2',[v,get(r,'2')],.155)
    # 主干中心距0.310mm；45度段按法向偏置，避免把水平间距误当斜线净距。
    dp=[get('R3','1'),(23.66,-77.7772),(23.66,-77.06),get('U6','1')]
    diagonal_sum=-53.4-.310*math.sqrt(2)
    dm=[get('R4','1'),(23.35,-77.6672),(23.35,diagonal_sum-23.35),
        (diagonal_sum+76.9,-76.9),(22.8,-76.9),get('U6','2')]
    batch.add_track(doc,'USB_DP','2',dp,.155);batch.add_track(doc,'USB_DM','2',dm,.155)
    # 插座正反插 D+ 分别下孔，在底层短接；D- 顶层短接后下孔。
    pa=(22.737,-75.90);pb=(23.737,-75.90);vm=(21.90,-75.0)
    for pin,v in [('A6',pa),('B6',pb)]:
        batch.add_track(doc,'USB_DP','1',[get('J1',pin),v],.155)
        batch.add_via(doc,'USB_DP',v,.4,.2)
    batch.add_track(doc,'USB_DP','2',[pb,pa,get('U6','1')],.155)
    batch.add_track(doc,'USB_DM','1',[get('J1','A7'),(23.237,-75.4),(22.237,-75.4),get('J1','B7')],.155)
    batch.add_track(doc,'USB_DM','1',[(22.237,-75.4),vm],.155)
    batch.add_via(doc,'USB_DM',vm,.4,.2)
    batch.add_track(doc,'USB_DM','2',[vm,(22.2,-75.3),get('U6','2')],.155)
    # 换层回流候选，铜面实际接入仍需原生重建后验证。
    for p in [(22.45,-79.4),(21.85,-79.4),(21.35,-75.12),(21.75,-73.95)]:batch.add_via(doc,'GND',p,.4,.2)
    batch.add_track(doc,'GND','2',[get('U6','3'),(22.1,-77.75),(22.1,-79.15),(21.85,-79.4)],.254)
    batch.add_track(doc,'GND','2',[get('R10','2'),(22.1498873,-76.9),get('U6','3')],.254)
    # 给被 USB 让路影响的普通网络提供经几何检查的短扇出，避免只能绕远。
    batch.add_via(doc,'I2C_SDA',(24.42,-79.90),.2500122,.1500124)
    batch.add_track(doc,'I2C_SDA','2',[get('R5','2'),(24.42,-79.9942),(24.42,-79.90)],.0899922)
    batch.add_via(doc,'MCU_EN',(24.15,-82.1),.2500122,.1500124)
    batch.add_track(doc,'MCU_EN','2',[get('C1','1'),(24.15,-82.237),(24.15,-82.1)],.0899922)
    w,od,drill=dimensions(doc,'U4_C1')
    batch.add_via(doc,'U4_C1',(23.27,-74.15),od,drill)
    batch.add_track(doc,'U4_C1','2',[get('U4','C1'),(22.406102,-74.93),(22.72,-75.243898),
                                    (22.98,-75.243898),(23.27,-74.953898),(23.27,-74.15)],w)
    # 只移除确实挡住新铜/移动焊盘的普通网络图元；不动射频或USB旧接口短接。
    check.PREFIX=PREFIX;check.DELTAS=TARGETS;check.routes=routed_geometry
    for _ in range(4):
        _,_,c,h=save(doc);issues=local_check(doc,c,h)
        ids={s.split('~')[5 if s.startswith('TRACK~') else 6]:s for s in doc['shape'] if s.startswith(('TRACK~','VIA~')) and PREFIX not in s}
        blocked={i for row in issues for i in row[1:3] if i in ids}
        protected=[i for i in blocked if ids[i].split('~')[3 if ids[i].startswith('TRACK~') else 4] in ('RF_SOC','R30_2','USB_DP','USB_DM')]
        assert not protected,('禁止自动移除关键线',protected)
        if not blocked:break
        removed += [ids[i] for i in sorted(blocked)]
        doc['shape']=[s for s in doc['shape'] if s not in {ids[i] for i in blocked}]
    # L3 留出实际地铜区域；信号导线及穿透该区域的非地旧孔均须撤回重布。
    ts,vs,_=routes(doc)
    blocked={t['id'] for t in ts if t['layer']=='22' and t['net']!='GND' and track_gap(t,GROUND_ZONE)<.2}
    blocked|={v['id'] for v in vs if v['net']!='GND' and not v['id'].startswith(PREFIX) and distance(v['poly'],GROUND_ZONE)<.2}
    for s in list(doc['shape']):
        v=s.split('~');i=5 if v[0]=='TRACK' else 6 if v[0]=='VIA' else None
        if i is not None and v[i] in blocked:removed.append(s);doc['shape'].remove(s)
    plane=next(s.split('~') for s in source['shape'] if s.startswith('COPPERAREA~'))
    plane[2]='22';plane[7]=PREFIX+'GNDL3';plane[10]='';plane[12]='USB底层局部参考地'
    pts=[(x/U+ORIGIN[0],y/U+ORIGIN[1]) for x,y in GROUND_ZONE]
    plane[4]='M '+' L '.join(f'{x:.8f} {y:.8f}' for x,y in pts)+' Z'
    doc['shape'].append('~'.join(plane));batch.RESERVED_GROUND=[('22',GROUND_ZONE)]
    _,newparts,c,h=save(doc);issues=local_check(doc,c,h)
    report={'来源SHA256':SHA,'移动元件':TARGETS,'撤回图元':removed,'候选几何冲突':issues,
            '云端保存':False,'原生DRC':False,'制造放行':False,'恢复日志':[]}
    print('GEOMETRY',json.dumps(issues,ensure_ascii=False),flush=True)
    if not issues and '--restore' in sys.argv:
        report['保留旧线安全段数']=salvage(doc,c,h,removed)
        print('SALVAGE',report['保留旧线安全段数'],flush=True)
        # 普通信号恢复只修复本轮退化的原连接组，不借机填满新的USB保留区。
        nets=['3V3','USB_5V','MCU_EN','REG_EN','U4_C1','I2C_SDA','I2C_SCL','J1_A5','J1_B5']
        for n in nets:
            old=connected_groups(source,oldc,n);blocked=set();count=0
            def lost():
                gs=connected_groups(doc,c,n)
                return [g for g in old if not any(g<=s for s in gs)]
            while lost() and count<12:
                islands=batch.island_contacts(doc,c,n);options=[]
                labels=[{a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')} for g in islands]
                for i,g in enumerate(islands):
                    for j,q in enumerate(islands[:i]):
                        # 只选被本轮拆开的同一个旧连接组，不绕去接旧有的未连端点。
                        if not any(labels[i]&s or labels[j]&s for s in lost()):continue
                        key=tuple(sorted((tuple(sorted(labels[i])),tuple(sorted(labels[j])))))
                        if key not in blocked:
                            dist=min(math.dist(batch.center(a),batch.center(b)) for a in g for b in q)
                            options.append((dist,key,g,q))
                if not options:break
                _,key,a,b=min(options,key=lambda x:(x[0],x[1]))
                w,od,drill=dimensions(doc,n)
                ok,info=batch.route(doc,c,h,n,a,b,w,od,drill)
                report['恢复日志'].append([n,key,ok,info]);count+=1
                print('RESTORE',n,ok,info,flush=True)
                if not ok:blocked.add(key)
            save(doc)
    _,newparts,c,h=save(doc)
    report['候选几何冲突']=local_check(doc,c,h)
    report['原连接退化']={}
    for n in {p['net'] for p in oldc if p['net']}:
        oldgroups=connected_groups(source,oldc,n);newgroups=connected_groups(doc,c,n)
        report['原连接退化'][n]=[sorted(g) for g in oldgroups if not any(g<=s for s in newgroups)]
    report['原连接退化']={n:g for n,g in report['原连接退化'].items() if g}
    report['USB端点连通组']={n:[sorted(g) for g in connected_groups(doc,c,n)] for n in ('USB_DP_SOC','USB_DM_SOC','USB_DP','USB_DM')}
    t,_,_=routes(doc)
    report['USB候选铜中心线长度_mm']={n:sum(math.dist(a,b) for q in t if q['net']==n and PREFIX in q['id'] for a,b in zip(q['points'],q['points'][1:])) for n in ('USB_DP_SOC','USB_DM_SOC','USB_DP','USB_DM')}
    assert source['DRCRULE']==doc['DRCRULE']
    assert sorted((p['ref'],p['pin'],p['net']) for p in c)==sorted((p['ref'],p['pin'],p['net']) for p in oldc)
    report['本地几何与连接准入']=not report['候选几何冲突'] and not report['原连接退化']
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('撤回图元','恢复日志')},ensure_ascii=False,indent=2),flush=True)
    return doc,report

if __name__=='__main__':build()
