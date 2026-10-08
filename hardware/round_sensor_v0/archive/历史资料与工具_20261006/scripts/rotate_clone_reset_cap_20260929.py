"""仅翻转无极性复位电容 C1，改善接地/复位支路交叉；网络全部核验。"""
from refine_clone_usb_20260928 import *
from build_a5_usb_front_candidate import rotate_shift_180
from build_a5_rf_clearance_layout import ref

configure();batch.THERMAL_VIA_PADS={('U1','57')};doc,p,c,h=parse(OUT);trial=copy.deepcopy(doc)
oldpads=[q for q in c if q['ref']=='C1'];ts,_,_=routes(doc)
ids={t['id'] for t in ts for q in oldpads if shared_layer(t,q) and t['net']==q['net'] and track_gap(t,q['poly'])<.0001}
ids|={'ggeUSB0928V277','ggeUSB0928T276'}
trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[5 if s.startswith('TRACK~') else 6] in ids)]
for i,s in enumerate(trial['shape']):
    if s.startswith('LIB~') and ref(s)=='C1':trial['shape'][i]=rotate_shift_180(s,(0,0))
_,_,nc,nh=parse(trial)
g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C1.2:') for a in g))
q=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C5.2:') for a in g))
ok,info=batch.route(trial,nc,nh,'GND',g,q,*dimensions(trial,'GND'));print('CAP_GND_JOIN',ok,info,flush=True)
if not ok or info['长度']>2.5:sys.exit(0)
g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C1.2:') for a in g))
start=batch.center(g[0]);w,od,drill=dimensions(trial,'GND');xs,ys,free,vf=batch.obstacles(trial,nc,nh,'GND',w,od,drill,start)
X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g]);yy,xx=np.where(vf&(ds<1.5))
goals=[{'id':f'电容地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l} for i,(y,x) in enumerate(zip(yy,xx)) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
if not goals:print('CAP_NO_VIA');sys.exit(0)
ok,info2=batch.route(trial,nc,nh,'GND',g,goals,w,od,drill);print('CAP_GND_VIA',ok,info2,flush=True)
if not ok or info2['长度']>1.5:sys.exit(0)
batch.add_via(trial,'GND',info2['终点'],od,drill)
groups=batch.island_contacts(trial,nc,'MCU_EN');assert len(groups)==2
batch.STEP=.04;ok,info3=batch.route(trial,nc,nh,'MCU_EN',groups[0],groups[1],*dimensions(trial,'MCU_EN'));print('CAP_RESET',ok,info3,flush=True)
if not ok or info3['长度']>8:sys.exit(0)
if any(old_losses(doc,c,trial,nc,n) for n in {a['net'] for a in c if a['net']}):raise RuntimeError('连接退化')
TARGETS['C1']=p['C1']['center']
bad=local_check(trial,nc,nh);assert not bad,bad
save(trial);r=json.loads(REPORT.read_text());r['复位电容翻转接地']={'元件':'C1','无极性电容翻转180度':True,'接地连接':info,'接地孔':info2,'复位重连':info3,'原生验收':False,'钢网避孔待确认':True};REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print('CAP_ACCEPT',flush=True)
