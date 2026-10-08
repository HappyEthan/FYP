"""只读核查 S 实际钻孔/铜/阻焊输出。有限格式解析，未知语法即失败，不替代 CAM。"""
import hashlib
import copy
import json
import math
import re
import zipfile
from collections import Counter

from check_pcb_a5 import ROOT, U, parse, xy, rect, ellipse, oval, inside, point_seg, distance
from audit_a5_routed_snapshot import routes, track_gap

SRC = ROOT/'easyeda_std/PCB_克隆板GND孔距修正_云端回读_20260929.json'
ZIP = ROOT/'manufacturing/仅审核禁止生产/Gerber_圆形传感板_S_仅审核禁止生产_20260929.zip'
OUT = ROOT/'easyeda_std/克隆板S连接器孔与开窗审核_20260929.json'


def drill(text):
    assert 'METRIC,LZ,000.000' in text
    tools, out, active = {}, [], None
    for s in text.splitlines():
        if not s or s.startswith(';') or s in ['M48','METRIC,LZ,000.000','%','G05','G90','M30']:continue
        m = re.fullmatch(r'T(\d+)C([\d.]+)',s)
        if m:tools[m[1]]=float(m[2]);continue
        m = re.fullmatch(r'T(\d+)',s)
        if m:active=tools[m[1]];continue
        m = re.fullmatch(r'X(-?\d+)Y(-?\d+)(?:G85X(-?\d+)Y(-?\d+))?',s)
        assert m and active,s
        a=(int(m[1])/1000,-int(m[2])/1000)
        b=(int(m[3])/1000,-int(m[4])/1000) if m[3] else a
        out.append({'a':a,'b':b,'diameter':active})
    return out


def gerber(text):
    """解析本包直线/圆光圈走线/闪光/区域，保留极性；不实现通用布尔CAM。"""
    assert '%FSLAX45Y45*%' in text and '%MOMM*%' in text
    macros, aps, shapes, region, current, ap = {}, {}, [], None, None, None
    clear=False
    def emit(s):
        s['clear']=clear
        shapes.append(s)
    for raw in text.splitlines():
        s=raw.strip()
        if not s or s.startswith('G04'):continue
        m=re.fullmatch(r'%AM([^*]+)\*([^*]+)\*%',s)
        if m:macros[m[1]]=m[2];continue
        m=re.fullmatch(r'%ADD(\d+)([^,*]+)(?:,([^*]+))?\*%',s)
        if m:aps[m[1]]=(m[2],m[3]);continue
        if s in ['%LPD*%','%LPC*%']:clear=s=='%LPC*%';continue
        if s.startswith('%'):assert s in ['%FSLAX45Y45*%','%MOMM*%'],s;continue
        if s=='G36*':assert region is None;region=[];continue
        if s=='G37*':
            assert region and all(len(r)>=3 for r in region)
            emit({'rings':region});region=None;continue
        if s in ['G01*','G75*','M02*']:continue
        m=re.fullmatch(r'D(\d+)\*',s)
        if m:ap=aps[m[1]];continue
        m=re.fullmatch(r'X(-?\d+)Y(-?\d+)D0([123])\*',s)
        assert m,s
        q=(int(m[1])/1e5,-int(m[2])/1e5);mode=m[3]
        if region is not None:
            assert mode in ['1','2']
            if mode=='2':region.append([])
            assert region
            region[-1].append(q);current=q;continue
        if mode=='1':
            assert current is not None and ap[0]=='C',(s,ap)
            emit({'a':current,'b':q,'radius':float(ap[1])/2})
        elif mode=='3':
            name,param=ap;params=[float(v) for v in param.split('X')] if param else []
            if name=='C':emit({'a':q,'b':q,'radius':params[0]/2});current=q;continue
            if name=='R':poly=rect(*q,*params)
            elif name=='O':poly=oval(*q,*params,0)
            else:
                template=macros[name]
                for i,v in enumerate(params,1):template=template.replace('$'+str(i),str(v))
                v=[float(x) for x in template.split(',')];assert v[1]==1
                if v[0]==21:
                    assert len(v)==7 and v[4:6]==[0,0]
                    poly=rect(*q,v[2],v[3],-v[6])
                else:
                    assert v[0]==4 and v[-1]==0 and len(v)==3+2*(int(v[2])+1)+1
                    poly=[(q[0]+v[i],q[1]-v[i+1]) for i in range(3,len(v)-1,2)]
            emit({'rings':[poly]})
        current=q
    assert region is None
    return shapes


def point_copper_gap(q,s):
    if 'radius' in s:return point_seg(q,s['a'],s['b'])-s['radius']
    rings=s['rings']
    if sum(inside(q,r) for r in rings)%2:return 0.
    return min(point_seg(q,a,b) for r in rings for a,b in zip(r,r[1:]+r[:1]))


def boundary_gap(q,s):
    assert 'rings' in s
    return min(point_seg(q,a,b) for r in s['rings'] for a,b in zip(r,r[1:]+r[:1]))


def final_copper_gap(q,shapes):
    """两种可证明的局部情况；其他布尔组合拒绝，不能冒充通用CAM。"""
    positive=[s for s in shapes if not s['clear']]
    negative=[s for s in shapes if s['clear']]
    nearest=min(point_copper_gap(q,s) for s in positive)
    if all(point_copper_gap(q,s)>nearest+.001 for s in negative):return nearest
    # NPTH被一个清除孔包围，孔外近邻完整地铜；证明附近无其他边界干预。
    cut=[s for s in negative if point_copper_gap(q,s)==0]
    assert len(cut)==1 and 'rings' in cut[0] and len(cut[0]['rings'])==1
    radius=boundary_gap(q,cut[0])
    assert all(point_copper_gap(q,s)>radius+.001 for s in negative if s is not cut[0])
    backing=[s for s in positive if 'rings' in s and point_copper_gap(q,s)==0 and boundary_gap(q,s)>radius+.001]
    assert backing,'没有证明完整正片背景'
    # 后绘制的正片不得覆盖这个清除孔（其自身背景必在清除前）。
    idx=next(i for i,s in enumerate(shapes) if s is cut[0])
    assert all(point_copper_gap(q,s)>radius+.001 for s in shapes[idx+1:] if not s['clear'])
    return radius


def hole_gap(a,b):
    return distance([a['a'],a['b']],[b['a'],b['b']])-(a['diameter']+b['diameter'])/2


def probe_local(d,c,h,npth):
    """内存中试算，不生成/覆盖PCB，不宣称器件焊盘改动可直接制造。"""
    from refine_clone_usb_20260928 import configure, batch, old_losses
    from repair_clone_inner_layer_20260928 import path_text
    configure()
    trials=[]
    for shift in [.04,.05,.06,.08,.10]:
        trial=copy.deepcopy(d);changed=[]
        for i,raw in enumerate(trial['shape']):
            if raw.startswith('LIB~') and '#@$TEXT~P~' in raw:
                items=raw.split('#@$')
                if not any(s.startswith('TEXT~P~') and s.split('~')[10]=='J1' for s in items):continue
                for j,item in enumerate(items):
                    f=item.split('~')
                    if f[0]!='PAD' or f[8] not in ['A1','B12','A12','B1']:continue
                    points=list(map(float,f[10].split()));maxy=max(points[1::2])
                    # 源矩形后沿仅内收0.05mm；保留针号、锚点、网络和其他边。
                    for k in range(1,len(points),2):
                        if abs(points[k]-maxy)<1e-8:points[k]-=.05/U
                    f[10]=' '.join(f'{v:.8f}' for v in points);items[j]='~'.join(f)
                trial['shape'][i]='#@$'.join(items)
            elif raw.startswith('TRACK~'):
                f=raw.split('~');coords=list(map(float,f[4].split()));pts=[xy(*coords[k:k+2]) for k in range(0,len(coords),2)]
                if f[5]=='ggeUSB0928T335':
                    pts[1]=(pts[1][0],pts[1][1]-shift);pts[2]=(pts[2][0],pts[2][1]-shift)
                elif f[5]=='ggeUSB0928T295':pts[1]=(pts[1][0]-2*shift,pts[1][1])
                else:continue
                f[4]=path_text(pts);trial['shape'][i]='~'.join(f);changed.append(trial['shape'][i])
        _,tp,tc,th=parse(trial)
        conflicts=batch.check_new(trial,tc,th,changed)
        ts,vs,_=routes(trial)
        clearances=[]
        for hole in npth:
            q=hole['a'];radius=hole['diameter']/2
            clearances.append(min(
                *(distance([q],p['poly'])-radius for p in tc+vs),
                *(track_gap(t,[q])-radius for t in ts if t['layer'] in ['1','2','21','22'])))
        losses={net:old_losses(d,c,trial,tc,net) for net in ['GND','USB_5V']}
        assert all(tp[r]['center']==parse(d)[1][r]['center'] for r in tp)
        trials.append({'局部移动参数_mm':shift,'铜边回收_mm':.05,
            '离散铜最小孔距_mm':clearances,'新增走线冲突':conflicts,
            '原连通退化':{n:[sorted(x) for x in rows] for n,rows in losses.items() if rows},
            '局部可行':not conflicts and not any(losses.values()) and min(clearances)>=.2,
            '限制':'不含重新铺铜、阻焊/锡膏联动、焊接接触面积及原生DRC；不导出PCB，不写云端。'})
    return trials


def main():
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(SRC)=='44068c11869d448597dd402fda149b6a929255ddf088eb1769f0a28e4298a0c4'
    assert sha(ZIP)=='38efca8874731fa7c59af042fbb8200ef5a4931908754dd07d695cfb3cc2126d'
    # 解析与距离例测：圆、长槽、区域中的孔洞；拒绝不支持语法。
    assert abs(hole_gap({'a':(0,0),'b':(0,1),'diameter':.6},
                       {'a':(1,0),'b':(1,1),'diameter':.6})-.4)<1e-9
    assert abs(point_copper_gap((0,0),{'rings':[rect(0,0,4,4),rect(0,0,2,2)]})-1)<1e-9
    assert abs(final_copper_gap((0,0),[
        {'rings':[rect(0,0,4,4)],'clear':False},
        {'rings':[rect(0,0,1,1)],'clear':True}])-.5)<1e-9
    rejected=False
    try:gerber('%FSLAX45Y45*%\n%MOMM*%\nG02*')
    except AssertionError:rejected=True
    assert rejected,'未知弧线语法必须拒绝'
    d,p,c,h=parse(SRC);tracks,vias,_=routes(d)
    with zipfile.ZipFile(ZIP) as z:
        plated=drill(z.read('Drill_PTH_Through.DRL').decode())
        via_drill=drill(z.read('Drill_PTH_Through_Via.DRL').decode())
        npth=drill(z.read('Drill_NPTH_Through.DRL').decode())
        layers={k:gerber(z.read(v).decode()) for k,v in {
            '1':'Gerber_TopLayer.GTL','2':'Gerber_BottomLayer.GBL',
            '21':'Gerber_InnerLayer1.G1','22':'Gerber_InnerLayer2.G2',
            '顶阻焊':'Gerber_TopSolderMaskLayer.GTS','底阻焊':'Gerber_BottomSolderMaskLayer.GBS',
            '顶锡膏':'Gerber_TopPasteMaskLayer.GTP','底锡膏':'Gerber_BottomPasteMaskLayer.GBP'}.items()}
    circles=[v for v in plated if v['a']==v['b']];slots=[v for v in plated if v['a']!=v['b']]
    key=lambda v:(v['a'],v['b'],v['diameter'])
    assert Counter(map(key,circles))==Counter(map(key,via_drill))
    assert len(slots)==4 and len(npth)==2 and len(circles)==83
    slot_rows=[]
    for slot in slots:
        center=tuple((slot['a'][k]+slot['b'][k])/2 for k in [0,1])
        raw=min([x for x in p['J1']['items'] if x[0]=='PAD' and x[8]=='SH'],key=lambda x:math.dist(center,xy(x[2],x[3])))
        padcenter=xy(raw[2],raw[3]); copper=next(x for x in c if x['ref']=='J1' and x['pin']=='SH' and inside(padcenter,x['poly']))
        length=math.dist(slot['a'],slot['b'])+slot['diameter']
        points=list(map(float,raw[14].split()));sourcecenter=tuple((xy(*points[:2])[k]+xy(*points[2:])[k])/2 for k in [0,1])
        assert math.dist(center,sourcecenter)<.0008 and abs(length-float(raw[13])*U)<.0011
        # 垂直长圆槽/铜的最小包边，中心偏移仅沿Y；用实际输出孔与原生铜测量。
        assert abs(center[0]-padcenter[0])<.001
        ring=min((float(raw[4])*U-slot['diameter'])/2,
                 (float(raw[5])*U-length)/2-abs(center[1]-padcenter[1]))
        slot_rows.append({'图元':raw[12],'输出':slot,'总长_mm':length,
            '孔与铜中心偏移_mm':[center[k]-padcenter[k] for k in [0,1]],'最窄名义铜环_mm':ring,
            '源码与钻孔输出匹配':True})
    npth_rows=[]
    for i,hole in enumerate(npth):
        q=hole['a'];assert q==hole['b']
        gap={}
        for layer in ['1','2','21','22']:
            nearest=final_copper_gap(q,layers[layer])
            gap[layer]=nearest-hole['diameter']/2
        nearby_pads=sorted((distance([q],v['poly'])-hole['diameter']/2,v['ref']+'.'+v['pin'],v['layer']) for v in c)
        nearby_tracks=sorted((track_gap(t,[q])-hole['diameter']/2,t['id'],t['layer']) for t in tracks if t['layer'] in ['1','2','21','22'])
        npth_rows.append({'位置':'左' if i==0 else '右','实际钻孔':hole,'各铜层最小实际输出孔铜距_mm':gap,
            '源码小于0_20的焊盘':[v for v in nearby_pads if v[0]<.2],
            '源码小于0_20的走线':[v for v in nearby_tracks if v[0]<.2]})
    allholes=plated+npth
    pairs=sorted((hole_gap(a,b),i,j) for i,a in enumerate(allholes) for j,b in enumerate(allholes[:i]))
    pads=[x for x in p['J1']['items'] if x[0]=='PAD'];stakes=[xy(x[2],x[3]) for x in pads if x[8]=='SH']
    row=xy(pads[0][2],pads[0][3])[1];cx=sum(q[0] for q in stakes)/4
    # 当前顶视焊盘与原厂 component-side 图同向，长槽靠信号行，短槽靠开口。
    face=max(q[1] for q in stakes)+2.6
    assert abs(face-row-7.355)<.002
    assert abs(npth[1]['a'][0]-npth[0]['a'][0]-5.78)<.002
    assert all(abs(q['a'][1]-(face-6.28))<.002 for q in npth)
    pinmap={v[8]:v[7] for v in pads}
    assert all(pinmap[k]==v for k,v in {'A6':'USB_DP','B6':'USB_DP','A7':'USB_DM','B7':'USB_DM','A5':'J1_A5','B5':'J1_B5','A8':'','B8':'','A1':'GND','B1':'GND','A12':'GND','B12':'GND','A4':'USB_5V','B4':'USB_5V','A9':'USB_5V','B9':'USB_5V','SH':'GND'}.items())
    expected_x={'A1':-3.2,'B12':-3.2,'A4':-2.4,'B9':-2.4,'B8':-1.75,'A5':-1.25,
                'B7':-.75,'A6':-.25,'A7':.25,'B6':.75,'A8':1.25,'B5':1.75,
                'A9':2.4,'B4':2.4,'A12':3.2,'B1':3.2}
    assert all(abs(xy(v[2],v[3])[0]-cx-expected_x[v[8]])<.001 for v in pads if v[8]!='SH')
    opening_rows=[]
    for pad in c:
        if pad['kind']!='pad' or pad['ref'] not in ['J1','J2','J4','ANT1']:continue
        q=tuple(sum(x[k] for x in pad['poly'])/len(pad['poly']) for k in [0,1])
        # OVAL的离散弧端点有采样权重偏置，但仍在开窗内部；此项只检查中心覆盖。
        relevant=['顶','底'] if pad['layer']=='11' else ['顶' if pad['layer']=='1' else '底']
        assert all(not g['clear'] for s in relevant for kind in ['阻焊','锡膏'] for g in layers[s+kind])
        opening_rows.append({'焊盘':pad['ref']+'.'+pad['pin'],'网络':pad['net'],
            '阻焊中心覆盖':{s:any(point_copper_gap(q,g)<=0 for g in layers[s+'阻焊']) for s in relevant},
            '锡膏中心覆盖':{s:any(point_copper_gap(q,g)<=0 for g in layers[s+'锡膏']) for s in relevant}})
    report={'检查点':'S','源码SHA256':sha(SRC),'GerberSHA256':sha(ZIP),
        '原厂图纸SHA256':sha(ROOT/'references/usb4105.pdf'),
        '来源':['https://gct.co/connector/usb4105','https://www.jlc.com/portal/vtechnology.html'],
        '完整钻孔数量':{'过孔':len(circles),'有铜槽孔':len(slots),'无铜定位孔':len(npth),'合计':len(allholes)},
        '全部孔对数量':len(pairs),'全部孔对最小边距_mm':pairs[0][0],
        '槽孔输出核对':slot_rows,'定位孔铜距':npth_rows,
        'USB朝向':{'安装层':'顶层','开口朝向':'顶视坐标+y，即圆板下方外侧',
            '开口线_y_mm':face,'中心线_x_mm':cx,'顶视信号行_y_mm':row,
            '端子网名与原厂顶视脚序核对':True,'固定槽孔原厂尺寸匹配':True,
            '备注':'四槽孔宽0.600mm，长1.700/1.400mm；源铜与槽中心约0.060mm偏移，需独立复核，不能称整个封装精确匹配。'},
        '接口开窗中心检查':opening_rows,
        '局部避让试算_未应用':probe_local(d,c,h,npth),
        '发现':['两个NPTH定位孔存在小于0.20mm的孔到铜间距；包含焊盘与走线，不靠同网豁免。',
            '四个SH槽孔相对铜焊盘中心偏移约0.060mm，最窄名义铜环约0.140mm；原厂推荐为居中布局，未默认接受偏心。'],
        '下一步':'保持USB本体/定位孔基准，评估局部GND焊盘避孔及两条USB_5V线避让；槽孔偏心另做局部候选。不得通过缩小定位孔或挪整个插座掩盖。',
        '原生DRC本轮重跑':False,'云端改动':False,'允许生产':False,
        '边界':'全部89孔名义孔距及NPTH对四层实际铜输出已核查；圆/长圆光圈用64分段近似，走线/圆孔距离解析计算。阻焊仅接口焊盘中心覆盖，不是全开窗面积/阻焊桥/焊接合格；未审核所有芯片极性与贴装坐标。'}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['完整钻孔数量','全部孔对最小边距_mm','定位孔铜距','USB朝向','发现']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
