"""纳入已在临时标签完成 DRC 的 G 回读；严格核对候选，不写云端。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import ground_groups

native = Path('/Users/liuchunyu/Downloads/PCBUSBnativeG20260929.json')
expected = 'e234a01c5de31e4bc775c09200e6870e6fa4603a5cdd9edffa694bbcfdf75d39'
assert hashlib.sha256(OUT.read_bytes()).hexdigest() == expected, '候选已变化，禁止覆盖'
td,tp,tc,th = parse(OUT)
nd,np_,nc,nh = parse(native)
assert set(tp) == set(np_) and len(tp) == 43
tol = .0002  # 原生坐标编码舍入，不放宽制造规则。
for name in tp:
    assert math.dist(tp[name]['center'], np_[name]['center']) < tol
assert len(tc) == len(nc)
for a,b in zip(tc,nc):
    assert (a['ref'],a['pin'],a['net'],a['layer']) == (b['ref'],b['pin'],b['net'],b['layer'])
    assert len(a['poly']) == len(b['poly'])
    assert max(math.dist(x,y) for x,y in zip(a['poly'],b['poly'])) < tol
for aa,bb,key in [(routes(td)[0],routes(nd)[0],'points'),(routes(td)[1],routes(nd)[1],'poly')]:
    lookup = {b['id']:b for b in bb}
    assert {a['id'] for a in aa} == set(lookup)
    for a in aa:
        b=lookup[a['id']]
        assert (a['net'],a['layer']) == (b['net'],b['layer'])
        assert len(a[key]) == len(b[key])
        assert max(math.dist(x,y) for x,y in zip(a[key],b[key])) < tol
assert nd['DRCRULE'] == td['DRCRULE']
assert len(ground_groups(nd,nc)) == 1
save(nd)
dest=OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json'
dest.write_bytes(native.read_bytes())
r=json.loads(REPORT.read_text())
r['板边及钻边原生G验收']={
    '原生文件':str(dest),'原生SHA256':hashlib.sha256(native.read_bytes()).hexdigest(),
    '原生DRC':1,'原生未连接':0,'剩余DRC':'Q1 原厂焊盘 0.14/0.15 mm；用户已选择沉金，制造待审',
    '实际原生铺铜地网组数':1,'SW1内移_mm':[0,.15],
    'V290钻边间距修复':True,'丝印整理仅改非铜':True,
    '完整DRC通过':False,'USB参考地通过':False,'云端保存':False,
    '仍待审核':['USB真实参考地与换层回流','电源压降和去耦回路','Q1阻焊与钢网','PICO新增地孔钢网避孔','国内工厂工艺确认']}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(r['板边及钻边原生G验收'],ensure_ascii=False,indent=2))
