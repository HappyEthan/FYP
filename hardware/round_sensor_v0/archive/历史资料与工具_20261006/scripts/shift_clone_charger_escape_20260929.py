"""微移充电芯片、联动短线端点，寻找不改规则的接地出口。"""
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from build_a5_usb_zone_placement import shift_lib_safe
from repair_clone_inner_layer_20260928 import path_text
from check_pcb_a5 import xy,U

configure();base,p,c,h=parse(OUT);batch.STEP=.01;oldpads=[q for q in c if q['ref']=='U4'];centers=[batch.center(q) for q in oldpads]
for delta in [(-.1,0),(-.15,0),(-.2,0),(-.25,0),(-.15,-.05),(-.15,.05),(-.2,-.1),(-.2,.1)]:
    trial=copy.deepcopy(base);changed=[]
    for i,s in enumerate(trial['shape']):
        if s.startswith('LIB~') and ref(s)=='U4':trial['shape'][i]=shift_lib_safe(s,delta)
        elif s.startswith('TRACK~'):
            a=s.split('~');ns=list(map(float,a[4].split()));ps=[xy(*ns[j:j+2]) for j in range(0,len(ns),2)]
            if any(math.dist(q,z)<.001 for q in ps for z in centers):
                ps=[tuple(q[j]+delta[j] for j in [0,1]) if any(math.dist(q,z)<.001 for z in centers) else q for q in ps];a[4]=path_text(ps);trial['shape'][i]='~'.join(a);changed.append(trial['shape'][i])
    _,np_,nc,nh=parse(trial);ts,vs,_=routes(trial);bad=batch.check_new(trial,nc,nh,changed)
    for q in [q for q in nc if q['ref']=='U4']:
        for a in nc+vs:
            if a.get('ref')=='U4' or a['net']==q['net'] or not shared_layer(q,a):continue
            if distance(q['poly'],a['poly'])<batch.clearance(trial,q['net'],a['net'])-1e-5:bad.append(['pad',q['pin'],a.get('id',a.get('ref'))])
        for t in ts:
            if t['net']!=q['net'] and shared_layer(q,t) and track_gap(t,q['poly'])<batch.clearance(trial,q['net'],t['net'])-1e-5:bad.append(['track',q['pin'],t['id']])
    if bad:print('CHARGE_SHIFT',delta,False,bad[:3],flush=True);continue
    g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('U4.C2:') for a in g));w,od,drill=dimensions(trial,'GND')
    xs,ys,free,vf=batch.obstacles(trial,nc,nh,'GND',w,od,drill,batch.center(g[0]));X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g]);yy,xx=np.where(vf&(ds<1.5))
    goals=[{'id':f'充电近地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l} for i,(y,x) in enumerate(zip(yy,xx)) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
    ok,info=batch.route(trial,nc,nh,'GND',g,goals,w,od,drill) if goals else (False,'无合法孔位')
    print('CHARGE_SHIFT_ROUTE',delta,ok,info,flush=True)
    if not ok or info['长度']>1.5:continue
    batch.add_via(trial,'GND',info['终点'],od,drill)
    if any(old_losses(base,c,trial,nc,n) for n in {a['net'] for a in nc if a['net']}):continue
    TARGETS['U4']=np_['U4']['center'];bad=local_check(trial,nc,nh)
    if bad:print('CHARGE_SHIFT_FINAL_REJECT',bad[:3],flush=True);continue
    save(trial);r=json.loads(REPORT.read_text());r['充电芯片局部微移接地']={'位移_mm':delta,'接地':info,'原生验收':False};REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print('CHARGE_SHIFT_ACCEPT',flush=True);break
