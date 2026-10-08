"""组合已通过的充电路径，仅重排冲突的 CC 支路，保留传感器/BOOT/复位。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from check_pcb_a5 import U,xy
configure();batch.STEP=.02
charge_inner='--charge-inner' in sys.argv
gold=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-ml3za3yg/before.json')
base=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-waumibfv/before.json')
charge=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-signal-j1r9q845/before.json')
doc,_,_,_=parse(gold);original,_,_,_=parse(base);charging,_,_,_=parse(charge)
r10=next(s for s in original['shape'] if s.startswith('LIB~') and ref(s)=='R10')
oldground={s for s in original['shape'] if s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='GND'}
doc['shape']=[r10 if s.startswith('LIB~') and ref(s)=='R10' else s for s in doc['shape']]
keep=[]
for s in doc['shape']:
    v=s.split('~');net=v[3] if v[0]=='TRACK' else v[4] if v[0]=='VIA' else None
    if net=='U4_C1' or (net=='J1_B5' and not charge_inner):continue
    if v[0]=='TRACK' and v[5]=='ggeUSB0928T254':continue
    if charge_inner and v[0]=='TRACK' and v[5]=='ggeUSB0928T279':continue
    if net=='GND' and PREFIX in s and s not in oldground:continue
    keep.append(s)
doc['shape']=keep
charging_shapes=[s for s in charging['shape'] if s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='U4_C1']
for t in routes({'shape':charging_shapes})[0]:
    if charge_inner and t['layer']=='1':continue
    batch.add_track(doc,t['net'],t['layer'],t['points'],t['width'])
for s in charging_shapes:
    v=s.split('~')
    if v[0]=='VIA':batch.add_via(doc,v[4],xy(v[1],v[2]),float(v[3])*U,2*float(v[5])*U)
_,parts,c,h=parse(doc);assert not local_check(doc,c,h),local_check(doc,c,h)
log=[]
for net in (['U4_C1','J1_A5','J1_B5'] if charge_inner else ['J1_B5','J1_A5']):
    blocked=set()
    for _ in range(12):
        groups=batch.island_contacts(doc,c,net)
        if len(groups)==1:break
        labels=[tuple(sorted({a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')})) for g in groups]
        opts=[]
        for i,a in enumerate(groups):
            for j,b in enumerate(groups[:i]):
                key=tuple(sorted((labels[i],labels[j])))
                if key not in blocked:opts.append((min(math.dist(batch.center(x),batch.center(y)) for x in a for y in b),key,a,b))
        if not opts:break
        # 先逃出 USB-C 密集引脚区，再接外侧下拉电阻，防止外侧支路封路。
        _,key,a,b=min(opts,key=lambda x:(not any('J1.B5' in ls for ls in x[1]),x[0],x[1]));size=len(doc['shape'])
        ok,info=batch.route(doc,c,h,net,a,b,*dimensions(doc,net))
        if ok and len(batch.island_contacts(doc,c,net))>=len(groups):doc['shape']=doc['shape'][:size];ok=False
        if not ok:blocked.add(key)
        log.append([net,key,ok,info]);print('CC',net,ok,info,flush=True)
source,_,oldc,_=parse(SOURCE)
loss={n:[sorted(g) for g in old_losses(source,oldc,doc,c,n)] for n in {p['net'] for p in c if p['net']!='GND'}}
loss={n:g for n,g in loss.items() if g}
errors=local_check(doc,c,h);print('LOSSES',loss,'ERRORS',errors,flush=True)
report=json.loads(REPORT.read_text());report['充电与CC组合精修']={'来源':str(gold),'充电路径来源':str(charge),'日志':log,'非地原连接退化':loss,'几何冲突':errors}
if not loss and not errors:
    report['移动元件']['R10']=parts['R10']['center'];save(doc)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
else:
    import tempfile
    p=Path(tempfile.mkdtemp(prefix='edausb-cc-'))/'candidate.json';p.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    print('REJECTED_LOCAL_ONLY',p,flush=True)
    raise RuntimeError('组合候选未通过，不覆盖当前文件')
