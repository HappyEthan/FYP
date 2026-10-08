"""保存本地 I 检查点；不把原生连通/采样通过等同于 USB 性能验收。"""
from pathlib import Path
from collections import Counter
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import ground_groups

src=Path('/Users/liuchunyu/Downloads/PCBUSBnativeG20260929.json')
native=Path('/Users/liuchunyu/Downloads/PCBUSBnativeI20260929.json')
assert hashlib.sha256(OUT.read_bytes()).hexdigest()=='cd151531a38e7dbe3f66f94c71a5d748700ef2415a4c0e4b4bdd13385a944358','主候选变化，停止纳入'
assert hashlib.sha256(native.read_bytes()).hexdigest()=='b1b25a52608797553aa1cd16d67085820bb0a9cc74903496b8f03ac3788a395b'
a,pa,ca,ha=parse(src);b,pb,cb,hb=parse(native)
assert len(pb)==43 and ca==cb and ha==hb
unchanged=lambda d:Counter(s for s in d['shape'] if not s.startswith(('VIA~','COPPERAREA~')))
assert unchanged(a)==unchanged(b),'不得改变器件、线路、丝印或板框'
av={s.split('~')[6]:s.split('~') for s in a['shape'] if s.startswith('VIA~')}
bv={s.split('~')[6]:s.split('~') for s in b['shape'] if s.startswith('VIA~')}
assert set(bv)-set(av)=={'ggeUSB0928V326','ggeUSB0928V327','ggeUSB0928V328'}
for vid,x in av.items():
    y=bv[vid]
    if not x[4].startswith('USB_D'):assert x==y
    else:assert [v for i,v in enumerate(x) if i not in (3,5)]==[v for i,v in enumerate(y) if i not in (3,5)]
for k,v in a['DRCRULE'].items():
    if k!='usb':assert v==b['DRCRULE'][k]
    else:
        for key in v:
            if key not in ('viaHoleDiameter','viaHoleD'):assert v[key]==b['DRCRULE'][k][key]
assert len(ground_groups(b,cb))==1
save(b)
dest=OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json';dest.write_bytes(native.read_bytes())
detail=json.loads((OUT.parent/'克隆板USB换层回流细查_20260929.json').read_text())
assert detail['SHA256']==hashlib.sha256(native.read_bytes()).hexdigest()
assert all(not any(k.startswith('中心线/') and k!='中心线/USB信号孔避空' for k in layer['缺铜分类']) for n in detail['网络'].values() for layer in n.values())
r=json.loads(REPORT.read_text());r['USB回流原生I复查']={
    '原生SHA256':detail['SHA256'],'原生DRC':1,'原生未连接':0,'实际地铜连通组':1,
    '新增地孔':list(sorted(set(bv)-set(av))),'五个USB孔外径孔径_mm':[.25,.15],
    '元件信号线板框丝印未变':True,'全局间距与USB线宽间距未变':True,
    '主控右侧最近回流孔距离_mm':[1.4006,.5143],'插座右侧最近回流孔距离_mm':[2.5500,1.6265],
    '走线中心线除USB自身避空外缺铜采样点':0,
    'USB总体已验收':False,'云端保存':False,
    '待办':['插座换层回流距离仍需优化审核','侧向3h参考面仍有缺口含U4_C1过孔避空','USB正反插路径差与90欧姆阻抗','电源压降去耦与钢网','Q1沉金制造审核']}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r['USB回流原生I复查'],ensure_ascii=False,indent=2))
