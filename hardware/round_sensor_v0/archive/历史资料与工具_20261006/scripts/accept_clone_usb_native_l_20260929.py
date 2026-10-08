"""纳入 L 本地检查点，不表示 USB 性能或制造放行；不操作云端。"""
from pathlib import Path
from collections import Counter
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import ground_groups

native=Path('/Users/liuchunyu/Downloads/PCBUSBnativeL20260929.json')
source=Path('/Users/liuchunyu/Downloads/PCBUSBnativeI20260929.json')
assert hashlib.sha256(OUT.read_bytes()).hexdigest()=='6ee2f54e87cba739b7fdd5aa28e699b7ff913034392bf683ac68b09f2d7abab6'
assert hashlib.sha256(native.read_bytes()).hexdigest()=='66bd2734de881f1fe879cff9712950e9c07a5f7689cf25396034a722a69544c8'
a,pa,ca,ha=parse(source);b,pb,cb,hb=parse(native)
assert len(pb)==43 and ca==cb and ha==hb
assert a['DRCRULE']==b['DRCRULE']
allowed={'ggeUSB0928T312','ggeUSB0928T313','ggeUSB0928T315','ggeUSB0928V314'}
def retained(d):
    result=[]
    for s in d['shape']:
        z=s.split('~')
        if z[0]=='COPPERAREA':
            z[10]='';result.append('~'.join(z))
        elif z[0]=='TRACK' and z[5] in allowed:continue
        elif z[0]=='VIA' and z[6] in allowed:continue
        else:result.append(s)
    return Counter(result)
assert retained(a)==retained(b),'非目标图元或铺铜边界变化'
assert len(ground_groups(b,cb))==1
detail_path=native.with_suffix('.reference.json')
detail=json.loads(detail_path.read_text())
assert detail['SHA256']==hashlib.sha256(native.read_bytes()).hexdigest()
assert all(not any(k.startswith('中心线/') and k!='中心线/USB信号孔避空' for k in layer['缺铜分类']) for n in detail['网络'].values() for layer in n.values())
configure()
changed=[s for s in b['shape'] if s not in a['shape'] and not s.startswith('COPPERAREA~')]
assert not batch.check_new(b,cb,hb,changed)
assert not old_losses(a,ca,b,cb,'USB_DM')
save(b)
(OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(native.read_bytes())
(OUT.parent/'克隆板USB换层回流细查_20260929.json').write_bytes(detail_path.read_bytes())
r=json.loads(REPORT.read_text())
r['USB缩短原生L复查']={'原生SHA256':detail['SHA256'],'原生DRC':1,'原生未连接':0,
    '实际地铜连通组':1,'修改图元':sorted(allowed),'其他图元规则铺铜边界不变':True,
    'USB_DM换层孔_mm':[22.0599,-75.140058],'正反插几何长度差_mm':[2.9497,.9496],
    '中心线除USB孔避空外缺铜采样':0,'最近回流地孔距离_mm':.61455,
    'USB总体已验收':False,'云端保存':False,
    '待办':['侧向3h邻域仍有缺铜含其他网络孔避空','插座换层回流与90欧姆阻抗','电源压降去耦','Q1沉金与PICO钢网制造审核']}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r['USB缩短原生L复查'],ensure_ascii=False,indent=2))
print('候选SHA256',hashlib.sha256(OUT.read_bytes()).hexdigest())
