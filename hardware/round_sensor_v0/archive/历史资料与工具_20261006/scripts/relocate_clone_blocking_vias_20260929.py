"""小范围移动现有信号过孔及相接端点，为短接地孔腾空间；只保存连通不退化候选。"""
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U,xy
from repair_clone_inner_layer_20260928 import path_text

configure();batch.STEP=.04
batch.THERMAL_VIA_PADS={('U1','57')}
doc,parts,c,h=parse(OUT);report=json.loads(REPORT.read_text());log=[]
targets=[('C5','2','ggeUSB0928V277'),('C2','2','ggeUSB0928V265')]
if '--charger' in sys.argv:
    targets=[('U4','C2','ggeUSB0928V275')]
    rule=copy.deepcopy(doc['DRCRULE']['Default']);rule.update(nets=['U4_C1'],viaHoleDiameter=.25/U,viaHoleD=.15/U)
    doc['DRCRULE']['充电设定小孔_025_015']=rule
for ref,pin,vid in targets:
    oldvia=next(v for v in routes(doc)[1] if v['id']==vid);old=batch.center(oldvia)
    deltas=sorted([(dx*.1,dy*.1) for dx in range(-7,8) for dy in range(-7,8) if 0<math.hypot(dx,dy)<=7],key=lambda q:math.hypot(*q))
    if '--charger-fine' in sys.argv:
        deltas=sorted([(dx*.01,dy*.01) for dx in range(10,20) for dy in range(-8,9)],key=lambda q:math.dist(q,(.13,0)))
    if '--charger-knee' in sys.argv:
        deltas=[(.12,0),(.11,0),(.1,0),(.12,-.02),(.12,.02)]
    accepted=False;legal=0
    for dx,dy in deltas:
        trial=copy.deepcopy(doc);new=(old[0]+dx,old[1]+dy);changed=[]
        for i,s in enumerate(trial['shape']):
            a=s.split('~');hit=False
            if a[0]=='VIA' and a[6]==vid:
                a[1],a[2]=path_text([new]).split();hit=True
                if '--charger' in sys.argv:a[3]=str(.25/U);a[5]=str(.15/2/U)
            elif a[0]=='TRACK' and a[3]==oldvia['net']:
                ns=list(map(float,a[4].split()));ps=[xy(*ns[j:j+2]) for j in range(0,len(ns),2)]
                if any(math.dist(p,old)<.001 for p in ps):
                    if '--charger-knee' in sys.argv and a[5]=='ggeUSB0928T271':
                        ps=[(p[0]+dx,p[1]+dy) if p[0]>22.9 else p for p in ps]
                    else:ps=[new if math.dist(p,old)<.001 else p for p in ps]
                    a[4]=path_text(ps);hit=True
            if hit:trial['shape'][i]='~'.join(a);changed.append(trial['shape'][i])
        drill=float(next(s for s in trial['shape'] if s.startswith('VIA~') and s.split('~')[6]==vid).split('~')[5])*2*U
        if any(distance([new],p['poly'])-drill/2<.1 for p in c if p['kind']=='pad' and p['layer'] in ('1','2')):continue
        if batch.check_new(trial,c,h,changed):continue
        legal+=1
        g=next(g for g in batch.island_contacts(trial,c,'GND') if any(a['id'].startswith(f'{ref}.{pin}:') for a in g))
        if '--charger' in sys.argv:
            goals=[a for q in batch.island_contacts(trial,c,'GND') if any(b['id'].startswith(('C7.2:','R9.2:','U4.B1:')) for b in q) for a in q]
            batch.STEP=.01;size=len(trial['shape'])
            ok,info=batch.route(trial,c,h,'GND',g,goals,*dimensions(trial,'GND'));batch.STEP=.04
            print('CHARGE_VIA_DIRECT',dx,dy,ok,info,flush=True)
            if ok and info['长度']<=2.5 and not any(old_losses(doc,c,trial,c,n) for n in {p['net'] for p in c if p['net']}):
                accepted=True;doc=trial;save(doc);log.append([ref,pin,vid,True,{'旧':old,'新':new,'接地直连':info}]);break
            trial['shape']=trial['shape'][:size]
        start=batch.center(g[0]);w,od,drill=dimensions(trial,'GND')
        xs,ys,free,vf=batch.obstacles(trial,c,h,'GND',w,od,drill,start)
        X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g])
        yy,xx=np.where(vf&(ds<1.5));loc=sorted(zip(yy,xx),key=lambda q:ds[q])
        goals=[{'id':f'移动后地孔{j}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l}
               for j,(y,x) in enumerate(loc) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
        if not goals:continue
        size=len(trial['shape']);ok,info=batch.route(trial,c,h,'GND',g,goals,w,od,drill)
        if not ok or info['长度']>1.5:continue
        batch.add_via(trial,'GND',info['终点'],od,drill)
        if batch.check_new(trial,c,h,trial['shape'][size:]):continue
        if any(old_losses(doc,c,trial,c,n) for n in {p['net'] for p in c if p['net']}):continue
        accepted=True;doc=trial;save(doc)
        log.append([ref,pin,vid,True,{'旧':old,'新':new,'短地线':info}]);print('VIA_ESCAPE',log[-1],flush=True);break
    if not accepted:
        log.append([ref,pin,vid,False,{'合法过孔移动候选数':legal}]);print('VIA_ESCAPE',log[-1],flush=True)
        if '--charger' in sys.argv:doc['DRCRULE'].pop('充电设定小孔_025_015',None)
report['局部移孔接地']={'日志':log,'原生复查':False}
report['候选几何冲突']=local_check(doc,c,h)
assert not report['候选几何冲突'],report['候选几何冲突']
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
