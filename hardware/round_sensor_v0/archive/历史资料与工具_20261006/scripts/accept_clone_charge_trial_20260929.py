"""原生 F 已人工读取 DRC26/未连接0；核对回读几何后纳入本地候选，不写云端。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import ground_groups

trialpath=Path('/Users/liuchunyu/Downloads/PCBUSBchargerTrial20260929.json')
nativepath=Path('/Users/liuchunyu/Downloads/PCBUSBnativeF20260929.json')
meta=json.loads(trialpath.with_suffix('.report.json').read_text())
assert hashlib.sha256(OUT.read_bytes()).hexdigest()==meta['原候选SHA256'],'本地候选已变化，禁止覆盖'
td,tp,tc,th=parse(trialpath);nd,np_,nc,nh=parse(nativepath)
assert set(tp)==set(np_) and len(tp)==43
# 实测原生 LIB 坐标保留4位、PAD中心保留3位 EDA 单位；
# 0.001 EDA单位为0.000254mm，二维舍入误差上界约0.00018mm。
TOL=.0002
for name in tp:assert math.dist(tp[name]['center'],np_[name]['center'])<TOL
for a,b in zip(tc,nc):
    assert (a['ref'],a['pin'],a['net'],a['layer'])==(b['ref'],b['pin'],b['net'],b['layer'])
    assert len(a['poly'])==len(b['poly']) and max(math.dist(x,y) for x,y in zip(a['poly'],b['poly']))<TOL
tt,tv,_=routes(td);nt,nv,_=routes(nd)
for aa,bb,key in [(tt,nt,'points'),(tv,nv,'poly')]:
    lookup={b['id']:b for b in bb};assert {a['id'] for a in aa}==set(lookup)
    for a in aa:
        b=lookup[a['id']];assert (a['net'],a['layer'])==(b['net'],b['layer'])
        assert len(a[key])==len(b[key]) and max(math.dist(x,y) for x,y in zip(a[key],b[key]))<TOL
assert len(ground_groups(nd,nc))==1
save(nd)
nativeout=OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json'
nativeout.write_bytes(nativepath.read_bytes())
r=json.loads(REPORT.read_text())
r['充电区接地原生F验收']={'U4位移_mm':[0,.18],'转角不变':True,'日志':meta['日志'],'离散地网变化':meta['离散地网变化_待原生铜面核验'],'实际原生铺铜地网组数':1,'原生DRC':26,'原生未连接':0,'原生文件':str(nativeout),'原生SHA256':hashlib.sha256(nativepath.read_bytes()).hexdigest(),'完整DRC通过':False,'云端保存':False,'仍须修复':['V290钻边距R1.1不足0.1mm','SW1板边间距','丝印板边','Q1原厂焊盘0.14mm间距','USB真实参考地及换层回流','PICO新增接地孔钢网避孔']}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print('已纳入本地候选；原生F26/0；未保存云端')
