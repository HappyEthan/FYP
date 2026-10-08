"""T局部候选：USB定位孔避铜与SH槽居中；不写云端、不覆盖源。"""
import copy
import hashlib
import json
import math
from collections import Counter

from check_pcb_a5 import ROOT,U,xy,parse,distance
from audit_a5_routed_snapshot import routes,track_gap
from repair_clone_inner_layer_20260928 import path_text
from refine_clone_usb_20260928 import configure,batch,old_losses

ARCHIVE=ROOT/'archive/T接口修正与S恢复_20260929'
SOURCE=ARCHIVE/'PCB_接口修正前S_20260929.json'
OUT=ARCHIVE/'PCB_接口局部T_未原生验收_20260929.json'
SHA='44068c11869d448597dd402fda149b6a929255ddf088eb1769f0a28e4298a0c4'


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==SHA
    d,p,c,h=parse(SOURCE);t=copy.deepcopy(d);changed=[];pad_changes=[];slot_changes=[]
    for i,s in enumerate(t['shape']):
        if s.startswith('LIB~') and any(v.startswith('TEXT~P~') and v.split('~')[10]=='J1' for v in s.split('#@$')):
            items=s.split('#@$')
            for j,item in enumerate(items):
                f=item.split('~')
                if f[0]!='PAD':continue
                if f[8] in ['A1','B12','A12','B1']:
                    a=list(map(float,f[10].split()));maxy=max(a[1::2]);oldheight=maxy-min(a[1::2])
                    for k in range(1,len(a),2):
                        if abs(a[k]-maxy)<1e-8:a[k]-=.05/U
                    f[10]=' '.join(f'{v:.8f}' for v in a)
                    # 原自动锡膏、阻焊扩展设置保留；实际输出必须复核其随新铜形变化。
                    assert f[16]=='0' and f[17]=='0'
                    pad_changes.append({'脚号':f[8],'铜边回收_mm':.05,'剩余铜面积比':1-.05/(oldheight*U)})
                elif f[8]=='SH':
                    a=list(map(float,f[14].split()));dx=float(f[2])-(a[0]+a[2])/2;dy=float(f[3])-(a[1]+a[3])/2
                    a=[v+(dx if k%2==0 else dy) for k,v in enumerate(a)]
                    f[14]=' '.join(f'{v:.8f}' for v in a)
                    f[19]=f[2]+','+f[3]
                    slot_changes.append({'图元':f[12],'钻孔位移_mm':[dx*U,dy*U]})
                else:continue
                items[j]='~'.join(f)
            t['shape'][i]='#@$'.join(items)
        elif s.startswith('TRACK~'):
            f=s.split('~');a=list(map(float,f[4].split()));points=[xy(*a[k:k+2]) for k in range(0,len(a),2)]
            if f[5]=='ggeUSB0928T335':
                points[1]=(points[1][0],points[1][1]-.08);points[2]=(points[2][0],points[2][1]-.08)
            elif f[5]=='ggeUSB0928T295':points[1]=(points[1][0]-.16,points[1][1])
            else:continue
            f[4]=path_text(points);t['shape'][i]='~'.join(f);changed.append(t['shape'][i])
    assert len(changed)==2 and len(pad_changes)==4 and len(slot_changes)==4
    _,tp,tc,th=parse(t);configure();errors=batch.check_new(t,tc,th,changed);assert not errors,errors
    assert len(tp)==43 and all(tp[r]['center']==p[r]['center'] and tp[r]['layer']==p[r]['layer'] for r in p)
    assert all(tp[r]==p[r] for r in p if r!='J1') and h==th
    losses={n:old_losses(d,c,t,tc,n) for n in {v['net'] for v in c} if n};assert not any(losses.values()),losses
    ts,vs,_=routes(t)
    # 保留两个定位孔，按导出0.651mm孔径加上0.001mm中心舍入保护检查离散铜。
    npth=[]
    for raw in tp['J1']['items']:
        if raw[0]!='HOLE':continue
        q=xy(raw[1],raw[2]);r=.651/2
        gap=min(*(distance([q],v['poly'])-r for v in tc+vs),
                *(track_gap(v,[q])-r for v in ts if v['layer'] in ['1','2','21','22']))
        assert gap>.201,gap
        npth.append({'中心_mm':q,'离散铜最小距_mm':gap})
    # 槽孔宽/长不变，中心回到铜中心；铜本身不变。重新检查全部孔对。
    from audit_clone_connector_s_20260929 import hole_gap
    holes=[]
    for shape in t['shape']:
        for item in shape.split('#@$'):
            f=item.split('~')
            if f[0]=='VIA':holes.append({'a':xy(f[1],f[2]),'b':xy(f[1],f[2]),'diameter':2*float(f[5])*U})
            elif f[0]=='HOLE':holes.append({'a':xy(f[1],f[2]),'b':xy(f[1],f[2]),'diameter':2*float(f[3])*U})
            elif f[0]=='PAD' and f[8]=='SH':
                a=list(map(float,f[14].split()));center=xy(f[2],f[3]);length=float(f[13])*U;dia=2*float(f[9])*U
                assert math.dist(center,tuple((xy(*a[:2])[k]+xy(*a[2:])[k])/2 for k in [0,1]))<1e-6
                # 源holePoints与中心方向一致，但端点长度是旧图形辅助字段；用正式总长减直径。
                half=(length-dia)/2
                holes.append({'a':(center[0],center[1]-half),'b':(center[0],center[1]+half),'diameter':dia})
    gap=min(hole_gap(a,b) for i,a in enumerate(holes) for b in holes[:i]);assert len(holes)==89 and gap>.2
    removed=list((Counter(d['shape'])-Counter(t['shape'])).elements());added=list((Counter(t['shape'])-Counter(d['shape'])).elements())
    assert len(removed)==len(added)==3
    for i,s in enumerate(t['shape']):
        if s.startswith('COPPERAREA~'):
            f=s.split('~');f[10]='';t['shape'][i]='~'.join(f)
    OUT.write_text(json.dumps(t,ensure_ascii=False,indent=2)+'\n')
    report={'来源SHA256':SHA,'候选SHA256':hashlib.sha256(OUT.read_bytes()).hexdigest(),
        '改动':'仅J1内部四个槽孔居中、两物理GND焊盘内收0.05mm及两条USB_5V线避孔；43元件位置/规则/网络不变。',
        '焊盘铜改变':pad_changes,'槽孔改变':slot_changes,'定位孔':npth,'全部89孔最小名义孔距_mm':gap,
        '本地新增铜距错误':errors,'全部原连通组无退化':True,
        '阻焊锡膏设置':'随多边形PAD自动输出，未另添加图形，待原生实际Gerber核验。',
        '焊接边界':'两地焊盘保留约95.65%面积，固定焊盘铜不变；这不是焊接强度或制造可贴承诺。',
        '原生已验证':False,'云端已保存':False,'允许生产':False}
    OUT.with_suffix('.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
