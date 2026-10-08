"""原生 B 地铜为定位依据，当前候选为编辑源；新增短地线后仍需原生重建。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import ground_groups,regions,contains
from check_pcb_a5 import U

configure();doc,parts,c,h=parse(OUT);report=json.loads(REPORT.read_text())
if '--fine-grid' in sys.argv:batch.STEP=.01
if '--pico-thermal' in sys.argv:
    batch.THERMAL_VIA_PADS={('U1','57')}
if '--fine-neck' in sys.argv:
    doc['DRCRULE']['接地短引出_025_015']['trackWidth']=.1/U
native,_,nc,_=parse(Path('/Users/liuchunyu/Downloads/PCBUSBnativeC20260929.json'))
gs=ground_groups(native,nc);main=next(g for g in gs if any(a['id'].startswith('U1.57:') for a in g))
labels=lambda g:{a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')}
known=labels(main);pending=[labels(g) for g in gs if g is not main];log=[]
if '--join-nearby' in sys.argv:
    pending_ids=set().union(*pending)
    groups=[g for g in batch.island_contacts(doc,c,'GND') if labels(g)&pending_ids and not labels(g)&known]
    pairs=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb)
                  for i,ga in enumerate(groups) for gb in groups[:i]],key=lambda q:q[0])
    for dist,ga,gb in pairs:
        if dist>1.5:continue
        size=len(doc['shape']);ok,info=batch.route(doc,c,h,'GND',ga,gb,*dimensions(doc,'GND'))
        if ok and info['长度']>2:ok=False
        if not ok:doc['shape']=doc['shape'][:size]
        log.append([sorted(labels(ga)|labels(gb)),ok,info]);print('NEAR_GROUND',log[-1],flush=True)
    save(doc)
for wanted in pending:
    groups=batch.island_contacts(doc,c,'GND')
    g=next((g for g in groups if labels(g)&wanted),None)
    if g is None or labels(g)&known:continue
    viaids={}
    for a in g:
        if a['id'].startswith(PREFIX+'V'):viaids.setdefault(a['id'].rsplit(':',1)[0],set()).add(a['layer'])
    if any(len(v)>1 for v in viaids.values()):continue
    goals=[a for q in groups if labels(q)&known for a in q
           if min(math.dist(batch.center(a),batch.center(b)) for b in g)<2.5]
    w,od,drill=dimensions(doc,'GND');size=len(doc['shape'])
    if goals:ok,info=batch.route(doc,c,h,'GND',g,goals,w,od,drill)
    else:ok,info=False,'2mm内无已有主地网端点'
    if ok and info['长度']>2.5:ok=False;info={'拒绝长地线':info}
    if not ok:doc['shape']=doc['shape'][:size]
    else:known|=wanted
    if not ok:
        start=batch.center(g[0]);xs,ys,free,vf=batch.obstacles(doc,c,h,'GND',w,od,drill,start)
        X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g])
        yy,xx=np.where(vf&(ds<1.6));loc=sorted(zip(yy,xx),key=lambda q:ds[q])
        goals=[{'id':f'近地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l}
               for i,(y,x) in enumerate(loc) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
        if goals:ok,info=batch.route(doc,c,h,'GND',g,goals,w,od,drill)
        if ok and info['长度']>1.6:ok=False;info={'拒绝长孔引出':info}
        if ok:
            batch.add_via(doc,'GND',info['终点'],od,drill)
            bad=batch.check_new(doc,c,h,doc['shape'][size:])
            if bad:ok=False;info=bad
        if not ok:doc['shape']=doc['shape'][:size]
        else:known|=wanted
    log.append([sorted(wanted),ok,info]);print('LOCAL_GND',log[-1],flush=True)
    save(doc)
report['原生B后局部接地']={'日志':log,'原生复查':False}
if '--pico-thermal' in sys.argv:
    report['PICO大地焊盘内新增接地孔候选']={'允许对象':['U1.57'],'仅GND':True,'孔径不引入新工艺':True,'钢网避孔与焊接尚未验收':True,'依据':'PICO Pin57 为中央地焊盘；本封装已使用9个接地通孔。新增孔须另行核对钢网，不自动豁免普通SMT焊盘。'}
report['候选几何冲突']=local_check(doc,c,h)
assert not report['候选几何冲突'],report['候选几何冲突']
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
