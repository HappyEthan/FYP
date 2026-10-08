"""无极性 C2 翻转试排，优先缩短 MLX90393 地回路；全网不退化才保存。"""
from refine_clone_usb_20260928 import *
from pathlib import Path
from build_a5_usb_front_candidate import rotate_shift_180
from build_a5_rf_clearance_layout import ref

configure();batch.THERMAL_VIA_PADS={('U1','57')};doc,p,c,h=parse(OUT);trial=copy.deepcopy(doc)
oldpads=[q for q in c if q['ref']=='C2'];ts,_,_=routes(doc)
ids={t['id'] for t in ts for q in oldpads if shared_layer(t,q) and t['net']==q['net'] and track_gap(t,q['poly'])<.0001}
trial['shape']=[s for s in trial['shape'] if not(s.startswith('TRACK~') and s.split('~')[5] in ids)]
for i,s in enumerate(trial['shape']):
    if s.startswith('LIB~') and ref(s)=='C2':trial['shape'][i]=rotate_shift_180(s,(0,0))
_,_,nc,nh=parse(trial)
g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C2.2:') for a in g))
q=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('U2.5:') for a in g))
ok,info=batch.route(trial,nc,nh,'GND',g,q,*dimensions(trial,'GND'));print('MLX_GND_JOIN',ok,info,flush=True)
if not ok or info['长度']>2.5:sys.exit(0)
g=next(g for g in batch.island_contacts(trial,nc,'GND') if any(a['id'].startswith('C2.2:') for a in g))
start=batch.center(g[0]);w,od,drill=dimensions(trial,'GND');xs,ys,free,vf=batch.obstacles(trial,nc,nh,'GND',w,od,drill,start)
X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g]);yy,xx=np.where(vf&(ds<1.5))
goals=[{'id':f'MLX地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l} for i,(y,x) in enumerate(zip(yy,xx)) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
if not goals:print('MLX_NO_VIA');sys.exit(0)
ok,info2=batch.route(trial,nc,nh,'GND',g,goals,w,od,drill);print('MLX_GND_VIA',ok,info2,flush=True)
if not ok or info2['长度']>1.5:sys.exit(0)
batch.add_via(trial,'GND',info2['终点'],od,drill)
power=[]
for _ in range(4):
    groups=batch.island_contacts(trial,nc,'3V3')
    if len(groups)==1:break
    ok=False
    pairs=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb) for i,ga in enumerate(groups) for gb in groups[:i]],key=lambda v:v[0])
    for _,ga,gb in pairs:
        for w in [.25,.15,.1]:
            size=len(trial['shape']);_,od,drill=dimensions(trial,'3V3');ok,inf=batch.route(trial,nc,nh,'3V3',ga,gb,w,od,drill)
            if not ok and w==.1:
                batch.STEP=.01
                ok,inf=batch.route(trial,nc,nh,'3V3',ga,gb,w,od,drill)
                batch.STEP=.02
            # Only a low-current MLX/C2 branch may use a longer narrow escape.
            labels={a['id'].split(':')[0] for a in ga+gb if not a['id'].startswith('gge')}
            limit=6 if w!=.1 else (6 if 'C2.1' in labels else 3)
            if ok and inf['长度']>limit:ok=False;trial['shape']=trial['shape'][:size]
            print('MLX_POWER',w,ok,inf,flush=True)
            if ok:power.append(inf);break
        if ok:break
    if not ok:
        if '--debug' in sys.argv:
            from inspect_clone_usb_20260928 import render
            render(trial,Path('/Users/liuchunyu/Downloads/MLX_ground_debug.png'),bounds=(18,23,-84,-80))
        sys.exit(0)
if any(old_losses(doc,c,trial,nc,n) for n in {a['net'] for a in c if a['net']}):raise RuntimeError('连接退化')
TARGETS['C2']=p['C2']['center'];bad=local_check(trial,nc,nh);assert not bad,bad
save(trial);r=json.loads(REPORT.read_text());r['MLX去耦电容翻转接地']={'元件':'C2','无极性电容翻转180度':True,'接地连接':info,'接地孔':info2,'电源重连':power,'原生验收':False,'钢网避孔待确认':True};REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
print('MLX_ACCEPT',flush=True)
