"""固定布局上的射频首段候选；不覆盖来源，核查铜几何与局部参考地。"""
import copy
import hashlib
import json
import math
from collections import Counter

from check_pcb_a5 import ROOT, U, ORIGIN, parse, xy, distance, inside, point_seg, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from audit_a5_ufl_keepout import audit as ufl_audit
from build_a5_usb_soc_fanout import pad_center
from test_a5_usb_soc_fanout import connected_groups

SOURCE = ROOT/'easyeda_std/PCB_射频布线前现场备份_20260918.json'
SHA = '49911ce6a0e6e46d64e5e532874f1a15b71698ceed2585abeb67ecbf15b6db79'
OUT = ROOT/'easyeda_std/PCB_射频首段候选_20260918.json'
REPORT = ROOT/'easyeda_std/射频首段检查_20260918.json'
WIDTH = .14986  # 嘉立创当前计算器：3313、50Ω单端外层、5.9mil。
VIA_D = .40
VIA_H = .20
PREFIX = 'ggeA5RF0918'


def coord(p):
    return ' '.join(f'{p[i]/U+ORIGIN[i]:.8f}' for i in (0, 1))


def ui(x, y):
    return (x, -y)


def track(net, points, i, width=WIDTH):
    return f'TRACK~{width/U:.8f}~1~{net}~'+ ' '.join(map(coord,points))+f'~{PREFIX}T{i}~0'


def via(point, i):
    x,y=coord(point).split()
    return f'VIA~{x}~{y}~{VIA_D/U:.8f}~GND~{VIA_H/U/2:.8f}~{PREFIX}V{i}~0'


def polygon(points, i):
    path='M '+coord(points[0])+' '+' '.join('L '+coord(p) for p in points[1:])+' Z'
    return f'SOLIDREGION~21~GND~{path}~solid~{PREFIX}P{i}~~~~0'


def polygon_gap(a,b):
    # 支持非凸参考地边界；旧distance仅支持凸多边形，不能用于整块参考地。
    if any(inside(p,b) for p in a) or any(inside(p,a) for p in b):
        return 0.
    return min(distance([p,q],[r,s]) for p,q in zip(a,a[1:]+a[:1])
               for r,s in zip(b,b[1:]+b[:1]))


def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA, '来源变化，停止'
    source,parts,copper,holes=parse(SOURCE)
    doc=copy.deepcopy(source)
    p=lambda ref,pin:pad_center(copper,ref,pin)
    # 元件、焊盘和封装工艺参数完全保持。
    specs=[
        ('RF_SOC',[p('U1','1'),ui(17.85,84.34),ui(17.55,84.64),ui(17.55,85.13),
                   ui(18.15,85.73),ui(24.75,85.73),ui(25.10,85.38),
                   ui(26.24,85.38),p('C30','1')]),
        ('RF_SOC',[p('C30','1'),ui(27.23,84.40),p('R30','1')]),
        ('R30_2',[p('R30','2'),p('C31','1')]),
        ('R30_2',[p('C31','1'),ui(29.03,83.10),ui(29.30,82.83),p('ANT1','1')]),
    ]
    additions=[track(net,points,i) for i,(net,points) in enumerate(specs)]
    grounds=[('C30','2',ui(27.55,83.05)),('C31','2',ui(30.35,83.25)),
             ('ANT1','3',ui(26.90,80.70)),('ANT1','2',ui(31.05,81.95))]
    for i,(ref,pin,end) in enumerate(grounds):
        start=p(ref,pin)
        if ref=='ANT1' and pin=='2':
            points=[start,ui(31.05,80.70),end]
        elif ref=='C31':
            points=[start,ui(30.10,83.50),end]
        else:
            points=[start,end]
        additions.extend([track('GND',points,4+i,.254),via(end,i)])
    # 局部L2参考地接入主控九个既有地孔。后续全板铺地与此区域合并。
    # 右侧凹口退出U.FL全层净空；末端仅在连接器自身信号焊盘内失去参考地。
    plane=list(map(lambda p:ui(*p),[
        (17.05,79.60),(17.05,85.20),(18.15,86.30),(25.90,86.30),
        (27.80,85.50)]))
    circle=next(s.split('~') for s in source['shape'] if s.startswith('CIRCLE~'))
    bc=xy(circle[1],circle[2]); br=float(circle[3])*U-.205
    plane += [(bc[0]+br*math.cos(math.radians(a)),bc[1]-br*math.sin(math.radians(a)))
              for a in range(38,14,-1)]
    plane += list(map(lambda p:ui(*p),[(30.82,81.276),(30.82,82.30),(27.75,82.30),(27.75,79.60)]))
    additions.append(polygon(plane,0))
    doc['shape']+=additions
    for i,row in enumerate(doc['layers']):
        v=row.split('~')
        if v[0] in {'21','22'}:
            v[3:6]=['false','false','true']
            doc['layers'][i]='~'.join(v)
    rf=copy.deepcopy(source['DRCRULE']['Default'])
    rf.update(trackWidth=WIDTH/U,nets=['RF_SOC','R30_2'])
    doc['DRCRULE']['射频50欧姆_3313']=rf
    ground=copy.deepcopy(source['DRCRULE']['Default'])
    ground.update(viaHoleDiameter=VIA_D/U,viaHoleD=VIA_H/U,nets=['GND'])
    doc['DRCRULE']['接地过孔_040_020']=ground
    return source,doc,parts,copper,holes,plane


def check(doc,copper,holes,plane):
    ts,vs,unsupported=routes(doc)
    assert unsupported==['SOLIDREGION']
    ufl,_,zones=ufl_audit(SOURCE)
    central=zones['中心禁走线区']['板心坐标多边形_mm']
    envelope=zones['本体全层净空候选']['板心坐标多边形_mm'][0]
    circle=next(s.split('~') for s in doc['shape'] if s.startswith('CIRCLE~'))
    center=xy(circle[1],circle[2]); radius=float(circle[3])*U
    issues=[]; all_gaps=[]
    def add(kind,a,b,gap,limit=.1524):
        all_gaps.append((gap,kind,a,b))
        if gap < limit-1e-5: issues.append([kind,a,b,round(gap,6),limit])
    for t in ts:
        for p in copper:
            if shared_layer(t,p) and t['net']!=p['net']:
                add('线-焊盘',t['id'],p['ref']+'.'+p['pin'],track_gap(t,p['poly']))
        for h in holes: add('线-机械孔',t['id'],h['ref'],track_gap(t,h['poly']),.2)
        add('线-板边',t['id'],'圆板',radius-max(math.dist(q,center) for q in t['points'])-t['width']/2,.2)
        for q in central:
            if track_gap(t,q)<-1e-6: issues.append(['U.FL中心禁区',t['id']])
    for i,t in enumerate(ts):
        for b in ts[:i]:
            if t['layer']==b['layer'] and t['net']!=b['net']:
                gap=min(distance([a,c],[d,e]) for a,c in zip(t['points'],t['points'][1:])
                        for d,e in zip(b['points'],b['points'][1:]))-(t['width']+b['width'])/2
                add('线-线',t['id'],b['id'],gap)
    for i,v in enumerate(vs):
        for p in copper:
            if v['net']!=p['net']:add('孔-焊盘',v['id'],p['ref']+'.'+p['pin'],distance(v['poly'],p['poly']))
        for t in ts:
            if v['net']!=t['net']:add('孔-线',v['id'],t['id'],track_gap(t,v['poly']))
        for b in vs[:i]:
            # 铜环同网可接，但钻孔仍须保证孔壁间距。
            ca=tuple(sum(p[k] for p in v['poly'])/len(v['poly']) for k in (0,1))
            cb=tuple(sum(p[k] for p in b['poly'])/len(b['poly']) for k in (0,1))
            add('钻孔-钻孔',v['id'],b['id'],math.dist(ca,cb)-VIA_H,.254)
        add('孔-板边',v['id'],'圆板',radius-max(math.dist(q,center) for q in v['poly']),.2)
        if distance(v['poly'],envelope)<1e-6:issues.append(['U.FL全层净空',v['id']])
        if not all(inside(q,plane) for q in v['poly']):issues.append(['过孔未完整落在参考地内',v['id']])
    if polygon_gap(plane,envelope)<1e-6:issues.append(['参考地侵入U.FL净空'])
    add('参考地-板边','L2','圆板',radius-max(math.dist(q,center) for q in plane),.2)
    for h in holes:add('参考地-机械孔','L2',h['ref'],polygon_gap(plane,h['poly']),.2)
    # 地平面连通主控既有地孔；没有信号过孔穿越本区域。
    mcu_vias=[p for p in copper if p['ref']=='U1' and p['kind']=='via']
    assert len(mcu_vias)==9 and all(p['net']=='GND' for p in mcu_vias)
    assert all(all(inside(q,plane) for q in p['poly']) for p in mcu_vias)
    uncovered=[]
    ant=next(p for p in copper if p['ref']=='ANT1' and p['pin']=='1')['poly']
    for t in ts:
        if t['net']=='GND':continue
        for a,b in zip(t['points'],t['points'][1:]):
            n=max(1,math.ceil(math.dist(a,b)/.02))
            for i in range(n+1):
                p=tuple(a[k]+(b[k]-a[k])*i/n for k in (0,1))
                # 仅对信号焊盘自身允许参考地退出；其他位置检验线宽外加3h=0.2982mm。
                if inside(p,ant):continue
                r=t['width']/2+.2982
                for j in range(24):
                    q=(p[0]+r*math.cos(j*math.pi/12),p[1]+r*math.sin(j*math.pi/12))
                    if not inside(q,plane):uncovered.append([t['id'],list(p)]);break
    if uncovered:issues.append(['参考地3h边距不足',uncovered[:5],len(uncovered)])
    groups={n:[sorted(g) for g in connected_groups(doc,copper,n)] for n in ('RF_SOC','R30_2')}
    if any(len(g)!=1 for g in groups.values()):issues.append(['RF网络未连接',groups])
    lengths={n:sum(math.dist(a,b) for t in ts if t['net']==n for a,b in zip(t['points'],t['points'][1:]))
             for n in ('RF_SOC','R30_2')}
    return {'局部冲突':issues,'射频端点连通组':groups,'射频中心线长度_mm':lengths,
            '最小异网线到焊盘间距_mm':min(v[0] for v in all_gaps if v[1]=='线-焊盘'),
            '参考地检查':'局部内层1实心GND，连接主控九个地孔；射频除U.FL信号焊盘本体外检查3h余量',
            '射频信号过孔数':sum(v['net']!='GND' for v in vs),'新增接地过孔数':len(vs),
            '新增图元':dict(Counter(s.split('~')[0] for s in doc['shape'] if PREFIX in s))}


def main():
    source,doc,parts,copper,holes,plane=build()
    result=check(doc,copper,holes,plane)
    # 候选即使失败也输出并明确标记，便于审计；失败时绝不作为云端入口。
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    result.update(来源=SOURCE.name,来源SHA256=SHA,候选=OUT.name,
                  候选SHA256=hashlib.sha256(OUT.read_bytes()).hexdigest(),
                  元件封装位置网络逐字保持=source['shape']==doc['shape'][:len(source['shape'])],
                  全局规则保持=source['DRCRULE']['Default']==doc['DRCRULE']['Default'],
                  原生DRC=False,云端保存=False,制造放行=False,
                  阻抗='官方计算输入已核对；0.14986mm为单端外层模型。后续顶层铺地距RF线边至少0.3048mm，局部焊盘不连续性和整机RF待验证',
                  限制=['内层1目前仅射频及主控局部参考地，后续须合并到全板GND',
                        '两个内层已启用，内层2暂空；0.8mm层叠和铜厚需制造订单指定',
                        '仅本轮新增铜按0.2mm板边初筛；整体工艺表0.3mm条款差异待最终统一'])
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    assert not result['局部冲突']


if __name__=='__main__': main()
