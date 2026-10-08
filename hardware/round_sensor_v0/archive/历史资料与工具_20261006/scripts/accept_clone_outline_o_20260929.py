"""核验等几何圆弧板框及原生Gerber，将云端O纳入唯一工作版本。"""
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path

from check_pcb_a5 import U, xy
from refine_clone_usb_20260928 import OUT, REPORT, parse, save, routes
from audit_clone_native_ground_20260929 import ground_groups

downloads = Path('/Users/liuchunyu/Downloads')
source = downloads / 'PCBUSBcloudReopenN20260929.json'
native = downloads / 'PCBUSBcloudReopenO20260929.json'
gerber = downloads / 'Gerber_圆形传感板_O_仅审核禁止生产_20260929.zip'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(OUT) == '5fbe3058d5e5f2cbb2079d8cac6bad30a47f338e6c542a579d53f9fbc3e2e108'
assert sha(source) == 'f998ec51c0e39f8677129d6a72361ed6ccfdadbf1a4a4367d3309032408a1c45'
assert sha(native) == '50cc5d7c2417931c8f61c0baab8dde430b13e5a49fc2826c03c5c9560b2952b4'
a, pa, ca, ha = parse(source)
b, pb, cb, hb = parse(native)
assert {k:v for k,v in a.items() if k!='shape'} == {k:v for k,v in b.items() if k!='shape'}
old = list((Counter(a['shape']) - Counter(b['shape'])).elements())
new = list((Counter(b['shape']) - Counter(a['shape'])).elements())
assert len(old) == 1 and old[0].startswith('CIRCLE~') and old[0].split('~')[5]=='10'
assert len(new) == 4 and all(s.startswith('ARC~') and s.split('~')[2]=='10' for s in new)
o = old[0].split('~')
cx, cy, radius = map(float, o[1:4])
expected = [(cx+radius,cy),(cx,cy+radius),(cx-radius,cy),(cx,cy-radius),(cx+radius,cy)]
for i, s in enumerate(sorted(new, key=lambda x: x.split('~')[6])):
    f=s.split('~'); assert f[1]==o[4]
    n=list(map(float,re.findall(r'-?\d+(?:\.\d+)?', f[4])))
    assert all(abs(x-y)<1e-8 for x,y in zip(n[:2],expected[i])) and n[2:4] == [radius,radius]
    assert n[4:7] == [0,0,1] and all(abs(x-y)<1e-8 for x,y in zip(n[7:],expected[i+1]))
assert pa==pb and ca==cb and ha==hb and len(pb)==43
assert len(ground_groups(b,cb))==1
center=xy(cx,cy); r=radius*U; ts,vs,_=routes(b)
edges=[]
for t in ts:
    edges.append((r-max(math.dist(center,q) for q in t['points'])-t['width']/2,t['id']))
for v in vs:
    edges.append((r-max(math.dist(center,q) for q in v['poly']),v['id']))
for p in cb:
    edges.append((r-max(math.dist(center,q) for q in p['poly']),p['ref']+'.'+p['pin']))
assert min(edges)[0] > .30
with zipfile.ZipFile(gerber) as z:
    text=z.read('Gerber_BoardOutlineLayer.GKO').decode()
    assert '%FSLAX45Y45*%' in text and '%MOMM*%' in text
    moves=re.findall(r'X(-?\d+)Y(-?\d+)D02\*',text)
    arcs=re.findall(r'X(-?\d+)Y(-?\d+)I(-?\d+)J(-?\d+)D01\*',text)
    assert len(moves)==len(arcs)==4 and text.count('G02*')==4
    starts=[tuple(int(v)/1e5 for v in p) for p in moves]
    ends=[tuple(int(v)/1e5 for v in p[:2]) for p in arcs]
    assert all(ends[i]==starts[(i+1)%4] for i in range(4))
    centers=[(starts[i][0]+int(p[2])/1e5,starts[i][1]+int(p[3])/1e5) for i,p in enumerate(arcs)]
    assert all(math.dist(c,(center[0],-center[1]))<.00003 for c in centers)
    assert all(abs(math.dist(starts[i],centers[i])-r)<.00003 for i in range(4))
    dims=[max(p[k] for p in starts)-min(p[k] for p in starts) for k in range(2)]
    assert all(abs(x-18)<.0001 for x in dims)
    assert '%ADD10C,0.0500*%' in text
save(b)
(OUT.parent/'PCB_克隆板USB局部重布_原生回读_20260929.json').write_bytes(native.read_bytes())
report={
    '目标PCB':'PCB_圆形传感板_SCH_A5 copy','文档ID':'cca094630ebf453c98ae64b900f0d7f0',
    '当前检查点':'O','原生云端重开文件':str(native),'原生SHA256':sha(native),
    '候选SHA256':sha(OUT),'恢复点':str(source),'恢复SHA256':sha(source),
    '修复':'同圆心同半径同线宽的CIRCLE换为四段闭合ARC，不改铜、元件或规则',
    '圆心_mm':center,'半径_mm':r,'线宽_mm':float(o[4])*U,
    '图元差异仅板框':True,'独立铜距板边最小_mm':min(edges),
    '临时标签DRC':1,'云端保存关闭重开DRC':1,'未连接':0,'实际地网组数':1,
    '板框DRC提示_前后':[20,0],'剩余DRC':'Q1原厂焊盘0.14mm/规则0.15mm，按已选沉金待制造审核',
    '结论边界':'对照支持圆形对象的重开DRC处理存在表达相关差异；未审计EDA内部代码，不推断具体软件缺陷实现',
    'Gerber审核包':str(gerber),'GerberSHA256':sha(gerber),'Gerber板框闭合':True,
    'Gerber板框圆弧数':4,'Gerber板框尺寸_mm':dims,
    'Gerber全面制造验收':False,'USB性能验收':False,'允许生产':False,
    '云端已保存重开':True,'原版未修改':True,'新增云端PCB':False,
    '下一步':['USB侧向参考地与90欧姆阻抗','电源载流压降及去耦','Q1沉金与PICO钢网制造审核'],
}
(OUT.parent/'克隆板圆板框重开修复核验_20260929.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
d=json.loads(REPORT.read_text());d['当前本地检查点']='O';d['当前候选SHA256']=sha(OUT)
d['当前云端保存状态']=report;d['圆板框原生O复查']=report
REPORT.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
