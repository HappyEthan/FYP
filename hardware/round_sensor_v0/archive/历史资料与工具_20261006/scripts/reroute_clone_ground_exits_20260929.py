"""局部撤回阻挡地孔的控制线支路，接地后原网重新接回；原网络不得退化。"""
from refine_clone_usb_20260928 import *

configure();batch.THERMAL_VIA_PADS={('U1','57')}
doc,p,c,h=parse(OUT);report=json.loads(REPORT.read_text());log=[]
cases=[('C5','2','MCU_EN',{'ggeUSB0928T275','ggeUSB0928V277','ggeUSB0928T276'}),
       ('C2','2','REG_EN',{'ggeUSB0928T263','ggeUSB0928V265'})]
for ref,pin,net,ids in cases:
    trial=copy.deepcopy(doc)
    trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[5 if s.startswith('TRACK~') else 6] in ids)]
    g=next(g for g in batch.island_contacts(trial,c,'GND') if any(a['id'].startswith(f'{ref}.{pin}:') for a in g))
    batch.STEP=.02;start=batch.center(g[0]);w,od,drill=dimensions(trial,'GND')
    xs,ys,free,vf=batch.obstacles(trial,c,h,'GND',w,od,drill,start)
    X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g])
    yy,xx=np.where(vf&(ds<1.8))
    goals=[{'id':f'让路地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l}
           for i,(y,x) in enumerate(zip(yy,xx)) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
    if not goals:print('NO_GND_GOAL',ref,flush=True);continue
    ok,info=batch.route(trial,c,h,'GND',g,goals,w,od,drill)
    print('GND_EXIT',ref,ok,info,flush=True)
    if not ok or info['长度']>1.8:continue
    batch.add_via(trial,'GND',info['终点'],od,drill)
    groups=batch.island_contacts(trial,c,net);assert len(groups)==2,(net,len(groups))
    batch.STEP=.04
    ok2,info2=batch.route(trial,c,h,net,groups[0],groups[1],*dimensions(trial,net))
    print('CONTROL_RESTORE',net,ok2,info2,flush=True)
    if not ok2 or info2['长度']>15:continue
    if local_check(trial,c,h) or any(old_losses(doc,c,trial,c,n) for n in {a['net'] for a in c if a['net']}):continue
    doc=trial;save(doc);log.append([ref,pin,net,info,info2]);print('EXIT_ACCEPT',ref,flush=True)
report['接地出口局部重布']={'日志':log,'原生验收':False,'新增大焊盘孔需钢网复核':True}
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
