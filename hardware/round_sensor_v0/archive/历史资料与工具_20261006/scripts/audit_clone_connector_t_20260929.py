"""T接口局部修正的原生回读和实际制造输出核验；不是整板制造放行。"""
import hashlib
import json
import math
import re
import zipfile
from collections import Counter

from check_pcb_a5 import ROOT, U, parse, xy, inside
from audit_clone_connector_s_20260929 import drill, gerber, hole_gap, final_copper_gap, point_copper_gap
from audit_clone_native_ground_20260929 import ground_groups
from refine_clone_usb_20260928 import configure, old_losses, batch

ARCHIVE = ROOT/'archive/T接口修正与S恢复_20260929'
SOURCE = ROOT/'easyeda_std/PCB_克隆板USB接口工艺修正_云端回读_20260929.json'
ZIP = ROOT/'manufacturing/仅审核禁止生产/Gerber_圆形传感板_T_仅审核禁止生产_20260929.zip'
OUT = ROOT/'easyeda_std/克隆板T接口云端与制造核验_20260929.json'
OLDZIP = ROOT/'manufacturing/仅审核禁止生产/Gerber_圆形传感板_S_仅审核禁止生产_20260929.zip'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm(s):
    if s.startswith('COPPERAREA~'):
        f=s.split('~');f[10]='';s='~'.join(f)
    return re.sub(r'(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?',lambda m:str(round(float(m[0]),4)),s)


def region_area(s):
    assert 'rings' in s and len(s['rings'])==1 and not s['clear']
    p=s['rings'][0]
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(p,p[1:]+p[:1])))/2


def clean(raw):
    lines=raw.decode().splitlines()
    used={m[1] for s in lines if (m:=re.fullmatch(r'D(\d+)\*',s))}
    return '\n'.join(s for s in lines if not s.startswith(('G04',';')) and
                     not ((m:=re.match(r'%ADD(\d+)',s)) and m[1] not in used))


def main():
    old=json.loads((ARCHIVE/'PCB_接口修正前S_20260929.json').read_text())
    candidate=json.loads((ARCHIVE/'PCB_接口局部T_未原生验收_20260929.json').read_text())
    native=json.loads((ARCHIVE/'PCB_接口局部T_原生回读_20260929.json').read_text())
    d,p,c,h=parse(SOURCE)
    assert sha(SOURCE)=='da4c0f91b4f801b84ef4a8f01209e901b6120975983f225b010f202953042699'
    assert Counter(d['shape'])==Counter(native['shape'])
    assert {k:v for k,v in d.items() if k!='shape'}=={k:v for k,v in native.items() if k!='shape'}
    assert Counter(map(norm,candidate['shape']))==Counter(map(norm,d['shape']))
    assert len(p)==43 and len(ground_groups(d,c))==1
    _,_,oc,_=parse(old);configure()
    losses={n:old_losses(old,oc,d,c,n) for n in {v['net'] for v in oc} if n}
    assert not any(losses.values())
    changed_tracks=[s for s in d['shape'] if s.startswith('TRACK~') and s.split('~')[5] in ['ggeUSB0928T335','ggeUSB0928T295']]
    assert not batch.check_new(d,c,h,changed_tracks)
    inner={}
    for layer in ['21','22']:
        get=lambda doc:[s.split('~')[10] for s in doc['shape'] if s.startswith('COPPERAREA~') and s.split('~')[2]==layer]
        inner[layer]=get(old)==get(d);assert inner[layer]
    files={'1':'Gerber_TopLayer.GTL','2':'Gerber_BottomLayer.GBL','21':'Gerber_InnerLayer1.G1','22':'Gerber_InnerLayer2.G2',
           '顶阻焊':'Gerber_TopSolderMaskLayer.GTS','底阻焊':'Gerber_BottomSolderMaskLayer.GBS',
           '顶锡膏':'Gerber_TopPasteMaskLayer.GTP','底锡膏':'Gerber_BottomPasteMaskLayer.GBP'}
    with zipfile.ZipFile(ZIP) as z,zipfile.ZipFile(OLDZIP) as oz:
        plated=drill(z.read('Drill_PTH_Through.DRL').decode());npth=drill(z.read('Drill_NPTH_Through.DRL').decode())
        via=drill(z.read('Drill_PTH_Through_Via.DRL').decode())
        layers={k:gerber(z.read(v).decode()) for k,v in files.items()}
        oldlayers={k:gerber(oz.read(v).decode()) for k,v in files.items()}
        unchanged=[n for n in z.namelist() if n in oz.namelist() and clean(z.read(n))==clean(oz.read(n))]
        changed=[n for n in z.namelist() if n in oz.namelist() and n not in unchanged]
    circles=[x for x in plated if x['a']==x['b']];slots=[x for x in plated if x['a']!=x['b']]
    key=lambda v:(v['a'],v['b'],v['diameter'])
    assert Counter(map(key,circles))==Counter(map(key,via))
    assert len(circles)==83 and len(slots)==4 and len(npth)==2
    assert 'Gerber_BoardOutlineLayer.GKO' in unchanged
    assert 'Drill_PTH_Through_Via.DRL' in unchanged and 'Drill_NPTH_Through.DRL' in unchanged
    semantic={}
    for layer in files:
        encode=lambda s:json.dumps(s,sort_keys=True)
        a=Counter(map(encode,oldlayers[layer]));b=Counter(map(encode,layers[layer]))
        removed=list((a-b).elements());added=list((b-a).elements())
        semantic[layer]={'旧图元':len(removed),'新图元':len(added)}
        expected={'1':4,'2':3,'21':0,'22':3,'顶阻焊':4,'底阻焊':0,'顶锡膏':4,'底锡膏':0}[layer]
        assert len(removed)==len(added)==expected,(layer,semantic[layer])
        if layer in ['1','顶阻焊','顶锡膏']:
            for item in removed+added:
                s=json.loads(item);assert 'rings' in s and not s['clear']
                assert all(19.4<=v[0]<=26.6 and -78<=v[1]<=-76.5 for r in s['rings'] for v in r)
        if layer=='2':
            oldregion=[json.loads(s) for s in removed if 'rings' in json.loads(s)]
            newregion=[json.loads(s) for s in added if 'rings' in json.loads(s)]
            assert len(oldregion)==len(newregion)==1
            vertices=lambda s:Counter(tuple(v) for r in s['rings'] for v in r)
            a=vertices(oldregion[0]);b=vertices(newregion[0])
            assert all(24.7<x<25.7 and -77.6<y<-76.5 for x,y in list((a-b).elements())+list((b-a).elements()))
    hole_rows=[]
    for q in npth:
        gaps={l:final_copper_gap(q['a'],layers[l])-q['diameter']/2 for l in ['1','2','21','22']}
        assert min(gaps.values())>=.20,gaps
        hole_rows.append({'孔':q,'四层实际孔铜距_mm':gaps})
    slot_rows=[]
    for s in slots:
        center=tuple((s['a'][k]+s['b'][k])/2 for k in [0,1])
        raw=min([x for x in p['J1']['items'] if x[0]=='PAD' and x[8]=='SH'],key=lambda x:math.dist(center,xy(x[2],x[3])))
        pc=xy(raw[2],raw[3]);length=math.dist(s['a'],s['b'])+s['diameter']
        assert math.dist(center,pc)<.001
        assert abs(length-float(raw[13])*U)<.0011 and abs(s['diameter']-.6)<.0001
        ring=min((float(raw[4])*U-s['diameter'])/2-abs(pc[0]-center[0]),(float(raw[5])*U-length)/2-abs(pc[1]-center[1]))
        assert ring>=.199
        slot_rows.append({'图元':raw[12],'输出':s,'槽总长_mm':length,'孔铜中心偏移_mm':math.dist(center,pc),'最窄名义铜环_mm':ring})
    holes=plated+npth;pairs=[hole_gap(a,b) for i,a in enumerate(holes) for b in holes[:i]]
    assert min(pairs)>.2
    # 新锡膏必须与修后的地焊盘完全重合，而非仅中心覆盖；自动阻焊用全边界采样辅助。
    paste_rows=[]
    for pin in ['A1','A12']:
        pad=next(x for x in c if x['ref']=='J1' and x['pin']==pin)
        q=tuple(sum(v[k] for v in pad['poly'])/len(pad['poly']) for k in [0,1])
        select=lambda shapes:[s for s in shapes if not s['clear'] and point_copper_gap(q,s)<=0]
        ns=select(layers['顶锡膏']);os=select(oldlayers['顶锡膏'])
        # A1/B12、A12/B1别名各输出两份完全重叠的正片，不能把面积相加。
        assert len(ns)==len(os)==2 and ns[0]==ns[1] and os[0]==os[1]
        area=region_area(ns[0]);oldarea=region_area(os[0]);poly=pad['poly']
        actual=ns[0]['rings'][0]
        assert all(min(math.dist(v,w) for w in actual)<.0001 for v in poly)
        assert all(min(math.dist(v,w) for w in poly)<.0001 for v in actual)
        samples=[(a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1])) for a,b in zip(poly,poly[1:]+poly[:1]) for f in [k/20 for k in range(21)]]
        assert all(any(not s['clear'] and point_copper_gap(v,s)<=.0001 for s in layers['顶阻焊']) for v in samples)
        assert .955<area/oldarea<.958
        paste_rows.append({'焊盘':pin,'锡膏面积_mm2':area,'相对S面积比':area/oldarea,'锡膏与新铜边界一致_误差小于0_0001mm':True,'阻焊覆盖铜边界采样':True})
    j4=[]
    for pad in [v for v in c if v['ref']=='J4']:
        q=tuple(sum(v[k] for v in pad['poly'])/len(pad['poly']) for k in [0,1])
        assert not any(not s['clear'] and point_copper_gap(q,s)<=0 for s in layers['底锡膏'])
        j4.append(pad['pin'])
    report={'检查点':'T','来源':str(SOURCE),'源码SHA256':sha(SOURCE),'GerberSHA256':sha(ZIP),
        '云端关闭重开后与临时原生图元及非shape字段一致':True,'仅shape排序变化':True,
        '元件数':43,'网络数':21,'地网连通组数':1,'L2L3铺铜缓存与S一致':inner,
        '云端回读全部网络原连通组无退化':True,'两条5V线新增局部间距错误':0,
        '原生DRC':'1项，Q1两焊盘0.14mm/规则0.15mm；无未完成连接项',
        '孔数':{'圆过孔':83,'固定槽孔':4,'定位孔':2,'合计':89},'全部孔对数量':len(pairs),'最小实际孔边距_mm':min(pairs),
        '定位孔铜距':hole_rows,'槽孔居中':slot_rows,'两物理地焊盘锡膏与阻焊':paste_rows,'J4无底锡膏中心的脚号':j4,
        '去除注释与未调用光圈后输出未变文件':unchanged,'输出变化文件':changed,
        '解析图元实际差异计数':semantic,
        '底阻焊与底锡膏说明':'文本编码变化但解析后的全图元多重集合相同；没有新增或改变实际开窗。',
        '底层铺铜局部变化':'仅T295周围一片地铜边界重建，差异顶点局限于x24.7至25.7/y-77.6至-76.5mm。',
        '允许生产':False,'边界':'有限格式解析，不替代完整CAM；圆/长圆宏含多边形近似。仅两改动地盘作锡膏全边界核对，阻焊为边界离散采样；不是钢网厚度、焊接强度或全部阻焊桥验收。Q1/盘中孔填孔盖帽/双面贴片及器件采购/电源USB实测仍待确认。'}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
