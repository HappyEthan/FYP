"""修正铜焊盘至圆板边距离的局部试排。保留原封装、网络及板径。"""
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from build_a5_usb_zone_placement import shift_lib_safe
from repair_clone_inner_layer_20260928 import path_text
from check_pcb_a5 import xy

configure();doc,parts,c,h=parse(OUT);report=json.loads(REPORT.read_text());log=[]
if '--reroute' in sys.argv:batch.STEP=.01
opts=[('C20',(0,.1)),('C21',(0,.05)),('C9',(-.2,0)),('SW1',(.08,.15)),('SW3',(-.18,-.18)),('J1',(0,-.06))]
if len(sys.argv)>=4:opts=[(sys.argv[1],(float(sys.argv[2]),float(sys.argv[3])))]
for target,delta in opts:
    trial=copy.deepcopy(doc);oldpads=[a for a in c if a['ref']==target];centers=[batch.center(a) for a in oldpads]
    via_ids={'ggeUSB0928V290'} if target=='J1' else set()
    if target=='SW1' and '--reroute' in sys.argv:via_ids={'ggeRF0928V248'}
    via_delta=(-.45,.3) if target=='SW1' else delta
    moves=[(z,delta) for z in centers]+[(batch.center(v),via_delta) for v in routes(doc)[1] if v['id'] in via_ids]
    before=min(8.999982-max(math.dist((22.999954,-78.999842),q) for q in a['poly']) for a in oldpads)
    if before>=.325:continue
    for i,s in enumerate(trial['shape']):
        if s.startswith('LIB~') and ref(s)==target:trial['shape'][i]=shift_lib_safe(s,delta)
        elif s.startswith('VIA~') and s.split('~')[6] in via_ids:
            a=s.split('~');point=xy(a[1],a[2]);a[1],a[2]=path_text([tuple(point[k]+via_delta[k] for k in (0,1))]).split();trial['shape'][i]='~'.join(a)
        elif s.startswith('TRACK~'):
            a=s.split('~');ns=list(map(float,a[4].split()));pts=[xy(*ns[j:j+2]) for j in range(0,len(ns),2)]
            if any(math.dist(q,z)<.001 for q in pts for z,dxy in moves):
                if target=='SW1' and a[5] in {'ggeRF0928T245','ggeRF0928T246'}:
                    via_old=next(z for z,dxy in moves if dxy==via_delta);new=tuple(via_old[k]+via_delta[k] for k in (0,1));elbow=(new[0],via_old[1])
                    expanded=[]
                    for index,q in enumerate(pts):
                        if math.dist(q,via_old)<.001:expanded.extend([new,elbow,q] if index==0 else [q,elbow,new])
                        else:expanded.append(q)
                    pts=expanded
                else:pts=[next((tuple(q[j]+dxy[j] for j in [0,1]) for z,dxy in moves if math.dist(q,z)<.001),q) for q in pts]
                a[4]=path_text(pts);trial['shape'][i]='~'.join(a)
    _,np_,nc,nh=parse(trial);TARGETS[target]=np_[target]['center']
    after=min(8.999982-max(math.dist((22.999954,-78.999842),q) for q in a['poly']) for a in nc if a['ref']==target)
    original_shapes=set(doc['shape'])
    changed_copper=lambda:[s for s in trial['shape'] if s.startswith(('TRACK~','VIA~')) and s not in original_shapes]
    bad=local_check(trial,nc,nh)+batch.check_new(trial,nc,nh,changed_copper())
    reroutes=[]
    if '--reroute' in sys.argv:print('EDGE_INITIAL_BAD',bad,flush=True)
    if bad and '--reroute' in sys.argv:
        allowed={'线-焊盘','移动焊盘-线'}
        trackids={r[1] if r[0]=='线-焊盘' else r[2] for r in bad if r[0] in allowed}
        if target=='SW1':trackids.add('ggeUSB0928T347')
        ts,_,_=routes(trial);nets={t['net'] for t in ts if t['id'] in trackids}
        if all(r[0] in allowed for r in bad) and nets<={'REG_EN','3V3'}:
            trial['shape']=[s for s in trial['shape'] if not(s.startswith('TRACK~') and s.split('~')[5] in trackids)]
            routing_ok=True
            for net in sorted(nets,key=lambda n:0 if n=='REG_EN' else 1):
                for _ in range(8):
                    groups=batch.island_contacts(trial,nc,net)
                    if len(groups)==1:break
                    pairs=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb) for i,ga in enumerate(groups) for gb in groups[:i]],key=lambda a:a[0]);ok=False
                    for _,ga,gb in pairs:
                        size=len(trial['shape']);ok,ri=batch.route(trial,nc,nh,net,ga,gb,*dimensions(trial,net))
                        if ok and ri['长度']>(6 if net=='3V3' else 12):trial['shape']=trial['shape'][:size];ok=False
                        print('EDGE_RESTORE',net,ok,ri,flush=True)
                        if ok:reroutes.append([net,ri]);break
                    if not ok:routing_ok=False;break
                if not routing_ok:break
            bad=local_check(trial,nc,nh)+batch.check_new(trial,nc,nh,changed_copper()) if routing_ok else [('局部网络无法恢复',)]
    for v in routes(trial)[1]:
        if v['id'] not in via_ids:continue
        raw=next(s.split('~') for s in trial['shape'] if s.startswith('VIA~') and s.split('~')[6]==v['id'])
        from check_pcb_a5 import U
        drill=float(raw[5])*2*U
        for pad in nc:
            if pad['kind']=='pad' and pad['layer'] in ('1','2'):
                gap=distance([batch.center(v)],pad['poly'])-drill/2
                if gap<.1-1e-5:bad.append(['钻边-焊盘',v['id'],pad['ref']+'.'+pad['pin'],gap])
    losses={n:old_losses(doc,c,trial,nc,n) for n in {a['net'] for a in c if a['net']}} if not bad else {}
    ok=after>=.325 and not bad and not any(losses.values())
    info={'元件':target,'位移_mm':delta,'旧板边距离':before,'新板边距离':after,'保留':ok,'局部重布':reroutes,'几何错误':bad[:8],'连接退化':{n:[sorted(g) for g in v] for n,v in losses.items() if v}}
    print('EDGE_INSET',info,flush=True);log.append(info)
    if ok:doc=trial;parts=np_;c=nc;h=nh;save(doc)
    report['局部板边内移']={'日志':log,'原生验收':False,'机械装配复核':False};REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
report['局部板边内移']={'日志':log,'原生验收':False,'机械装配复核':False};REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
