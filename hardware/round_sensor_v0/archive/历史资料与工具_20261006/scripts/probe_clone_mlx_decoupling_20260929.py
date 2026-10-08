"""P版MLX去耦局部试排。只生成独立试验，不覆盖工程或云端。"""
import copy
import hashlib
import json
import sys
from pathlib import Path
from refine_clone_usb_20260928 import parse, configure, batch, old_losses
from check_pcb_a5 import ROOT, distance, shared_layer
from audit_a5_routed_snapshot import routes, track_gap
from build_a5_usb_front_candidate import rotate_shift_180
from build_a5_rf_clearance_layout import ref, shift_lib
from repair_clone_inner_layer_20260928 import path_text

scan_q='--scan-q' in sys.argv
SOURCE = Path('/Users/liuchunyu/Downloads/PCBpowerCloudReopenQ20260929.json' if scan_q else '/Users/liuchunyu/Downloads/PCBpowerBeforeQ20260929.json')
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == ('4c2f7eeebbbbab424b2b52b8b5b9ec208d7bb90887e41c63603540249dbf39a1' if scan_q else '6290d0e973c52c67595c322b69f22d619a93941f7d6f21a56f51854f1904d319')
d,p,c,h = parse(SOURCE)
configure()
removed = {'ggeUSB0928T343','ggeUSB0928T346','ggeUSB0928T355'}
base = copy.deepcopy(d)
base['shape'] = [s for s in base['shape'] if not (s.startswith('TRACK~') and s.split('~')[5] in removed)]
idx = next(i for i,s in enumerate(base['shape']) if s.startswith('LIB~') and ref(s)=='C2')

def track(net, points, ident, width=.1):
    return f'TRACK~{width/.254:.10f}~2~{net}~{path_text(points)}~{ident}~0'

def pad_bad(doc, copper):
    ts,vs,_=routes(doc)
    bad=[]
    for a in copper:
        if a['ref']!='C2':continue
        for b in copper+vs:
            if b.get('ref')=='C2' or not shared_layer(a,b):continue
            gap=distance(a['poly'],b['poly'])
            # Keep separation even from other components on the same supply.
            if gap < .15-1e-5:bad.append(('焊盘',b.get('ref',b.get('id')),gap))
        for t in ts:
            if t['layer']==a['layer'] and t['net']!=a['net']:
                gap=track_gap(t,a['poly'])
                if gap<batch.clearance(doc,a['net'],t['net'])-1e-5:bad.append(('导线',t['id'],gap))
    return bad

if scan_q:
    good=[]
    for rot in [0,180]:
        for ix in range(8):
            for iy in range(19):
                x,y=19.2+.2*ix,-83.4+.2*iy
                delta=(x-p['C2']['center'][0],y-p['C2']['center'][1])
                trial=copy.deepcopy(base)
                trial['shape'][idx]=(rotate_shift_180 if rot else shift_lib)(base['shape'][idx],delta)
                _,_,nc,_=parse(trial)
                if not pad_bad(trial,nc):good.append([rot,x,y])
    result={'来源SHA256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'组合数':304,
            '范围_mm':{'x':[19.2,20.6],'y':[-83.4,-79.8],'步长':.2,'相对旋转':[0,180]},
            '可行铜焊盘位置':good,'排除原导线':sorted(removed),'PCB未修改':True,
            '限制':'仅此网格和两种方向，未试90度/更细网格/联动挪其他元件；铜焊盘可行也不等于能布线或本体可装配。不能证明全局无解。'}
    (ROOT/'easyeda_std/克隆板Q_MLX去耦空间初筛_20260929.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2));sys.exit(0)

results=[]
for x,y in [(20.12,-83.55),(20.02,-83.60),(20.02,-83.50),(19.92,-83.60)]:
    trial=copy.deepcopy(base)
    trial['shape'][idx]=rotate_shift_180(base['shape'][idx],(x-p['C2']['center'][0],y-p['C2']['center'][1]))
    _,_,nc,nh=parse(trial)
    bad=pad_bad(trial,nc)
    row={'位置':[x,y],'焊盘初筛':bad}
    if bad:results.append(row);continue
    power=batch.center(next(a for a in nc if a['ref']=='C2' and a['pin']=='1'))
    ground=batch.center(next(a for a in nc if a['ref']=='C2' and a['pin']=='2'))
    added=[
      track('GND',[ground,(19.91,y+.21),(19.91,-82.05978),(19.7499732,-81.8998108)],'ggeMLXQG'),
      track('3V3',[power,(20.50,y),(20.50,-82.16),(19.83981,-81.4997354),(19.7499478,-81.4997354)],'ggeMLXQP'),
      track('3V3',[power,(22.7899214,y),(23.264114,-84.0240128),(23.264114,-84.54898)],'ggeMLXQF'),
    ]
    trial['shape']+=added
    row['导线初筛']=batch.check_new(trial,nc,nh,added)
    row['移动焊盘复筛']=pad_bad(trial,nc)
    row['连接退化']={n:old_losses(d,c,trial,nc,n) for n in ['3V3','GND']}
    if not row['导线初筛'] and not row['移动焊盘复筛'] and not any(row['连接退化'].values()):
        dest=Path('/Users/liuchunyu/Downloads/PCBMLXQTrial20260929.json')
        for i,s in enumerate(trial['shape']):
            f=s.split('~')
            if f[0]=='COPPERAREA':f[10]='';trial['shape'][i]='~'.join(f)
        dest.write_text(json.dumps(trial,ensure_ascii=False,indent=2)+'\n')
        row['未验收试验文件']=str(dest)
    results.append(row)
print(json.dumps(results,ensure_ascii=False,indent=2))
