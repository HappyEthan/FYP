"""交换相邻 C1/C5 位置试排，复位电容靠近上拉，3V3 去耦靠近下方供电。"""
from refine_clone_usb_20260928 import *
from build_a5_usb_zone_placement import shift_lib_safe
from build_a5_rf_clearance_layout import ref

configure();batch.THERMAL_VIA_PADS={('U1','57')};doc,p,c,h=parse(OUT);trial=copy.deepcopy(doc)
oldpads=[q for q in c if q['ref'] in ('C1','C5')];ts,_,_=routes(doc)
ids={t['id'] for t in ts for q in oldpads if shared_layer(t,q) and t['net']==q['net'] and track_gap(t,q['poly'])<.0001}
ids|={'ggeUSB0928V277','ggeUSB0928T276'}
trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[5 if s.startswith('TRACK~') else 6] in ids)]
for i,s in enumerate(trial['shape']):
    if not s.startswith('LIB~'):continue
    name=ref(s)
    if name not in ('C1','C5'):continue
    other='C5' if name=='C1' else 'C1';delta=tuple(p[other]['center'][k]-p[name]['center'][k] for k in (0,1));trial['shape'][i]=shift_lib_safe(s,delta)
_,np_,nc,nh=parse(trial)
g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C1.2:') for a in g))
q=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C5.2:') for a in g))
ok,info=batch.route(trial,nc,nh,'GND',g,q,*dimensions(trial,'GND'));print('SWAP_GND_JOIN',ok,info,flush=True)
if not ok or info['长度']>2:sys.exit(0)
g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C1.2:') for a in g))
start=batch.center(g[0]);w,od,drill=dimensions(trial,'GND');xs,ys,free,vf=batch.obstacles(trial,nc,nh,'GND',w,od,drill,start)
X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g]);yy,xx=np.where(vf&(ds<1.5))
goals=[{'id':f'交换电容地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l} for i,(y,x) in enumerate(zip(yy,xx)) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
if not goals:print('SWAP_NO_VIA');sys.exit(0)
ok,info2=batch.route(trial,nc,nh,'GND',g,goals,w,od,drill);print('SWAP_GND_VIA',ok,info2,flush=True)
if not ok or info2['长度']>1.5:sys.exit(0)
batch.add_via(trial,'GND',info2['终点'],od,drill)
log=[]
for net in ['MCU_EN','3V3']:
    for _ in range(5):
        groups=batch.island_contacts(trial,nc,net)
        if len(groups)==1:break
        _,ga,gb=min([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb) for i,ga in enumerate(groups) for gb in groups[:i]],key=lambda v:v[0])
        ok=False
        for w in ([dimensions(trial,net)[0]] if net=='MCU_EN' else [.25,.15]):
            size=len(trial['shape']);_,od,drill=dimensions(trial,net);ok,inf=batch.route(trial,nc,nh,net,ga,gb,w,od,drill)
            if ok and inf['长度']>8:ok=False;trial['shape']=trial['shape'][:size]
            print('SWAP_RESTORE',net,w,ok,inf,flush=True)
            if ok:log.append([net,inf]);break
        if not ok:sys.exit(0)
if any(old_losses(doc,c,trial,nc,n) for n in {a['net'] for a in c if a['net']}):raise RuntimeError('连接退化')
for name in ('C1','C5'):TARGETS[name]=np_[name]['center']
bad=local_check(trial,nc,nh);assert not bad,bad
save(trial);r=json.loads(REPORT.read_text());r['复位与去耦电容交换位置']={'元件':['C1','C5'],'接地连接':info,'接地孔':info2,'其他重连':log,'原生验收':False,'钢网避孔待确认':True};REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print('SWAP_ACCEPT',flush=True)
