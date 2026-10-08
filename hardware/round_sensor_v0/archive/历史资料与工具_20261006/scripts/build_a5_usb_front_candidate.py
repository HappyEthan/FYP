"""生成 USB-C 接口侧局部重布候选；不覆盖云端，不宣称阻抗或制造通过。"""
import copy
import hashlib
import json
import math
import re

from check_pcb_a5 import ROOT, U, ORIGIN, parse, distance, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from build_a5_rf_clearance_layout import ref, shift_lib, fmt, pairs
from test_a5_usb_soc_fanout import connected_groups

SOURCE = ROOT/'easyeda_std/PCB_A5_USB主控侧_云端重开回读_20260917.json'
SOURCE_SHA = 'c141e3ac3c2a1830652e99aaf9db58f33591925196debad1bfec956f78543533'
OUT = ROOT/'easyeda_std/PCB_A5_USB接口侧局部重布候选_20260917.json'
REPORT = ROOT/'easyeda_std/pcb_a5_usb_front_candidate_check_20260917.json'
PREFIX = 'ggeA5UsbFront'
CLEARANCE = .1524
WIDTH = .155
VIA_DIA = .45
VIA_HOLE = .20
DELTAS = {'R10':(1.80,-.40), 'U6':(.95,0), 'R9':(1.10,-.15)}


def coord(p):
    return ' '.join(f'{p[i]/U+ORIGIN[i]:.8f}' for i in (0,1))


def track(net,layer,points,index,width=WIDTH):
    return f'TRACK~{width/U:.8f}~{layer}~{net}~'+' '.join(map(coord,points))+f'~{PREFIX}T{index}~0'


def via(net,point,index):
    x,y=coord(point).split()
    return f'VIA~{x}~{y}~{VIA_DIA/U:.8f}~{net}~{VIA_HOLE/U/2:.8f}~{PREFIX}V{index}~0'


def transform_pair_string(text,cx,cy,dx,dy,comma=False):
    values=list(map(float,re.findall(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?',text)))
    assert len(values)%2==0
    out=[]
    for i in range(0,len(values),2):
        out += [fmt(2*cx-values[i]+dx),fmt(2*cy-values[i+1]+dy)]
    return (',' if comma else ' ').join(out)


def transform_svg_180(text,cx,cy,dx,dy):
    if not text.strip(): return text
    num=r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    tokens=re.findall(r'[A-Za-z]|'+num,text); out=[];i=0
    counts={'M':2,'L':2,'C':6,'Q':4,'A':7,'Z':0}
    while i<len(tokens):
        cmd=tokens[i];i+=1; assert cmd in counts,(cmd,text[:80])
        n=counts[cmd];v=list(map(float,tokens[i:i+n]));i+=n;assert len(v)==n
        if cmd in {'M','L','C','Q'}:
            for j in range(0,n,2):
                v[j]=2*cx-v[j]+dx;v[j+1]=2*cy-v[j+1]+dy
        elif n:
            v[-2]=2*cx-v[-2]+dx;v[-1]=2*cy-v[-1]+dy
        out += [cmd,*map(fmt,v)]
    return ' '.join(out)


def rotate_shift_180(shape,delta):
    chunks=[s.split('~') for s in shape.split('#@$')]
    h=chunks[0];cx,cy=float(h[1]),float(h[2]);dx,dy=(v/U for v in delta)
    h[1],h[2]=fmt(cx+dx),fmt(cy+dy);h[4]=fmt((float(h[4] or 0)+180)%360)
    for v in chunks[1:]:
        kind=v[0]
        if kind in {'TEXT','PAD'}:
            v[2],v[3]=fmt(2*cx-float(v[2])+dx),fmt(2*cy-float(v[3])+dy)
            if kind=='TEXT':
                v[5]=fmt((float(v[5] or 0)+180)%360)
                v[11]=transform_svg_180(v[11],cx,cy,dx,dy)
            else:
                if v[10].strip():v[10]=transform_pair_string(v[10],cx,cy,dx,dy)
                v[11]=fmt((float(v[11] or 0)+180)%360)
                if len(v)>19 and v[19].strip():v[19]=transform_pair_string(v[19],cx,cy,dx,dy,True)
        elif kind=='TRACK':v[4]=transform_pair_string(v[4],cx,cy,dx,dy)
        elif kind=='SOLIDREGION':v[3]=transform_svg_180(v[3],cx,cy,dx,dy)
        elif kind=='ARC':v[4]=transform_svg_180(v[4],cx,cy,dx,dy)
        elif kind=='CIRCLE':
            v[1],v[2]=fmt(2*cx-float(v[1])+dx),fmt(2*cy-float(v[2])+dy)
        elif kind=='SVGNODE':
            node=json.loads(v[1]);a=node['attrs']
            if 'c_origin' in a:a['c_origin']=transform_pair_string(a['c_origin'],cx,cy,dx,dy,True)
            if 'c_rotation' in a:
                rot=a['c_rotation'].split(',');rot[-1]=fmt((float(rot[-1])+180)%360);a['c_rotation']=','.join(rot)
            stack=list(node.get('childNodes',[]))
            while stack:
                q=stack.pop();b=q.get('attrs',{})
                if 'points' in b:b['points']=transform_pair_string(b['points'],cx,cy,dx,dy)
                stack += q.get('childNodes',[])
            v[1]=json.dumps(node,ensure_ascii=False,separators=(',',':'))
        else:raise ValueError(('未允许的U6实例图形',kind))
    return '#@$'.join('~'.join(v) for v in chunks)


def pad_center(copper,refname,pin):
    p=next(p for p in copper if p['ref']==refname and p['pin']==pin)
    xs,ys=zip(*p['poly']);return ((min(xs)+max(xs))/2,(min(ys)+max(ys))/2)


def local_clearance(doc,copper,holes):
    ts,vs,unsupported=routes(doc);assert not unsupported
    fresh_t=[t for t in ts if t['id'].startswith(PREFIX)]
    fresh_v=[v for v in vs if v['id'].startswith(PREFIX)]
    changed_pads=[p for p in copper if p['ref'] in DELTAS]
    conflicts=[]
    def add(kind,a,b,gap):
        if gap<CLEARANCE-1e-5: conflicts.append([kind,a,b,round(gap,6)])
    for t in fresh_t:
        for p in copper:
            if shared_layer(t,p) and t['net']!=p['net']:add('线-焊盘',t['id'],p['ref']+'.'+p['pin'],track_gap(t,p['poly']))
        for b in ts:
            if t['id']==b['id'] or t['layer']!=b['layer'] or t['net']==b['net']:continue
            gap=min(distance([a,z],[u,v]) for a,z in zip(t['points'],t['points'][1:]) for u,v in zip(b['points'],b['points'][1:]))-(t['width']+b['width'])/2
            add('线-线',t['id'],b['id'],gap)
        for v in vs:
            if t['net']!=v['net']:add('线-孔',t['id'],v['id'],track_gap(t,v['poly']))
        for i,h in enumerate(holes):add('线-机械孔',t['id'],h['ref']+':'+str(i),track_gap(t,h['poly']))
    for v in fresh_v:
        for p in copper:
            if v['net']!=p['net']:add('孔-焊盘',v['id'],p['ref']+'.'+p['pin'],distance(v['poly'],p['poly']))
        for t in ts:
            if v['net']!=t['net']:add('孔-线',v['id'],t['id'],track_gap(t,v['poly']))
        for b in vs:
            if v['id']!=b['id'] and v['net']!=b['net']:add('孔-孔',v['id'],b['id'],distance(v['poly'],b['poly']))
        for i,h in enumerate(holes):add('孔-机械孔',v['id'],h['ref']+':'+str(i),distance(v['poly'],h['poly']))
    for p in changed_pads:
        for q in copper:
            if p is not q and p['ref']!=q['ref'] and shared_layer(p,q) and p['net']!=q['net']:
                add('移动焊盘-焊盘',p['ref']+'.'+p['pin'],q['ref']+'.'+q['pin'],distance(p['poly'],q['poly']))
        for t in ts:
            if p['layer']==t['layer'] and p['net']!=t['net']:add('移动焊盘-线',p['ref']+'.'+p['pin'],t['id'],track_gap(t,p['poly']))
        for v in vs:
            if p['net']!=v['net']:add('移动焊盘-孔',p['ref']+'.'+p['pin'],v['id'],distance(p['poly'],v['poly']))
    # 同一对对象只保留一项，方便迭代。
    unique=[];seen=set()
    for x in conflicts:
        key=(x[0],x[1],x[2],x[3])
        if key not in seen:seen.add(key);unique.append(x)
    return unique


def build():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SOURCE_SHA,'来源已变化，禁止套用候选'
    source=json.loads(SOURCE.read_text());doc=copy.deepcopy(source)
    moved=[]
    for i,s in enumerate(doc['shape']):
        if not s.startswith('LIB~'):continue
        r=ref(s)
        if r=='R10':doc['shape'][i]=rotate_shift_180(s,DELTAS[r]);moved.append(r)
        elif r=='U6':doc['shape'][i]=rotate_shift_180(s,DELTAS[r]);moved.append(r)
        elif r=='R9':doc['shape'][i]=shift_lib(s,DELTAS[r]);moved.append(r)
    assert set(moved)==set(DELTAS)
    # USB接口旧线全部撤回；R10原位置向下的单端GND线撤回；内层GND线另行避让。
    removed=[];kept=[]
    for s in doc['shape']:
        v=s.split('~')
        drop=(v[0]=='TRACK' and (v[3] in {'USB_DP','USB_DM'} or v[5] in {
            'gge1020741','gge1020534','gge1020525','gge1020522','gge1020519',
            'gge1020642','gge1020639','gge1020636',
            'gge1020591','gge1020588','gge1020585','gge1020885'}))
        if drop:removed.append(s)
        else:kept.append(s)
    doc['shape']=kept
    temp=ROOT/'easyeda_std/.a5_usb_front_components.json';temp.write_text(json.dumps(doc,ensure_ascii=False))
    try:_,parts,copper,holes=parse(temp)
    finally:temp.unlink(missing_ok=True)
    j=lambda pin:pad_center(copper,'J1',pin)
    u=lambda pin:pad_center(copper,'U6',pin)
    r10=lambda pin:pad_center(copper,'R10',pin)
    r=lambda name,pin:pad_center(copper,name,pin)
    dp_b=(-.90,-3.20);dp_a=(.28,-2.75);dm=(.70,-3.22);dp_out=(-5.20,-3.85)
    additions=[
        # 顶层：D+各自下孔；D-在顶层合并后下孔。
        track('USB_DP','1',[j('B6'),(-.75,-2.65),dp_b],0),
        track('USB_DP','1',[j('A6'),(.25,-2.65),dp_a],1),
        track('USB_DM','1',[j('A7'),(-.25,-3.22),dm],2),
        track('USB_DM','1',[j('B7'),(.75,-3.05),dm],3),
        # 内层2合并两个D+接口脚，并把D+送到R3左侧；内层1留给连续地。
        track('USB_DP','22',[dp_a,(-.10,-2.70),dp_b,(-2.20,-3.50),(-3.50,-3.85),dp_out],4),
        # 底层短支路：接口换层孔到ESD信号脚，再分别送往串联电阻。
        track('USB_DP','2',[dp_a,u('1')],5),
        track('USB_DM','2',[dm,u('2')],6),
        track('USB_DP','2',[dp_out,(-5.20,-1.43),r('R3','1')],11),
        track('USB_DM','2',[dm,(-1.05,-3.30),(-1.05,-2.05),(-1.50,-2.05),(-1.50,-1.43),r('R4','1')],12),
        # U6地脚用宽线接入现有R1地网；连续地和近端地孔仍需原生阶段落实。
        track('GND','2',[u('3'),(.60,-1.45),r('R1','2')],7,.40),
        # R10仍靠近充电区，只挪出USB换层区。
        track('U4_C1','2',[r('U4','C1'),(.70,-3.80),r10('1')],8,.15),
        track('GND','2',[r('U4','B1'),(.45,-4.25)],9,.15),
        track('GND','2',[r10('2'),(2.55,-3.50),(2.55,-2.28)],10,.254),
        # R9只向右下平移，恢复原有两条电气连接，不改变阻值或网络。
        track('GND','2',[r('R9','2'),(4.10,-3.50),(4.10,-2.55),(2.55,-2.28)],13,.254),
        track('USB_5V','2',[r('R9','1'),(4.70,-2.55),(3.25,-2.28)],14,.254),
    ]
    additions += [via('USB_DP',dp_b,0),via('USB_DP',dp_a,1),via('USB_DM',dm,2),via('USB_DP',dp_out,3),via('GND',(.45,-4.25),4)]
    doc['shape'] += additions
    usb_rule=copy.deepcopy(source['DRCRULE']['Default'])
    usb_rule.update({'trackWidth':.15/U,'viaHoleDiameter':VIA_DIA/U,'viaHoleD':VIA_HOLE/U,
                     'nets':['USB_DM','USB_DP']})
    doc['DRCRULE']['USB接口扇出候选']=usb_rule
    fine=copy.deepcopy(source['DRCRULE']['Default'])
    fine.update({'trackWidth':.15/U,'nets':['U4_C1']})
    doc['DRCRULE']['细间距扇出候选']=fine
    OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    parsed,parts,copper,holes=parse(OUT)
    conflicts=local_clearance(parsed,copper,holes)
    groups={net:[sorted(g) for g in connected_groups(parsed,copper,net)]
            for net in ('USB_DP','USB_DM','USB_DP_SOC','USB_DM_SOC')}
    connected=all(len(v)==1 for v in groups.values())
    result={'日期':'2026-09-17','源文件':SOURCE.name,'源SHA256':SOURCE_SHA,'候选文件':OUT.name,
            '状态':'本地实验候选已否决；网络虽连通但局部间距未清零，未导入原生编辑器，禁止生产',
            '判定':{'USB四网各单组':connected,'局部冲突清零':not conflicts,
                    '允许导入原生编辑器':connected and not conflicts,
                    '结论':'需要重新安排USB/充电区元件与已有过孔，不能继续以坐标微调替代布局'},
            '移动':{'R10':{'平移_mm':DELTAS['R10'],'追加旋转_deg':180},'U6':{'平移_mm':DELTAS['U6'],'追加旋转_deg':180},
                    'R9':{'平移_mm':DELTAS['R9'],'追加旋转_deg':0}},
            '未移动元件':38,'板径_mm':18,'主控电源传感器方案不变':True,
            '小孔制造候选':{'外径_mm':VIA_DIA,'钻径_mm':VIA_HOLE,'尚未取得板厂确认':True},
            '删除旧图元':removed,'新增图元':additions,'新增局部冲突':conflicts,
            'USB连通组':groups,
            '限制':['0.45/0.20mm孔是小体积制造候选，不等于嘉立创工艺已确认',
                    '内层1预留连续地；内层2短接USB，仍须实际层叠阻抗复核',
                    'U6地线已加宽接现有地网，但近端地孔和完整地平面仍未落实',
                    '未处理全板其余未连接与原有3项间距，不是可投板版本']}
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    result=build();print(json.dumps({'候选':result['候选文件'],'冲突数':len(result['新增局部冲突']),
                                     'USB连通组数':{k:len(v) for k,v in result['USB连通组'].items()}},ensure_ascii=False,indent=2))
