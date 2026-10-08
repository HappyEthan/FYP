"""从Q生成MLX去耦R局部试验，不覆盖当前工程；须原生重铺铜验证。"""
import copy,hashlib,json,math
from pathlib import Path
from refine_clone_usb_20260928 import parse,configure,batch,old_losses
from check_pcb_a5 import ROOT,distance,shared_layer
from audit_a5_routed_snapshot import routes,track_gap
from build_a5_usb_front_candidate import rotate_shift_180
from build_a5_rf_clearance_layout import ref
from repair_clone_inner_layer_20260928 import path_text

source=Path('/Users/liuchunyu/Downloads/PCBMLXBeforeR20260929.json')
assert hashlib.sha256(source.read_bytes()).hexdigest()=='26cdf1c80dbe3e5bc43660953d9f6fdb41da61ddeb4cee2725395cdcbd236eb8'
d,p,c,h=parse(source);configure();q=copy.deepcopy(d)
vpos=(19.3,-83.55);cx,cy=(19.6,-83.0)
paths={
 'ggeUSB0928T345':[(20.193254,-84.8132416),(20.193254,-84.5732624),(19.3,-83.6800084),vpos],
 'ggeUSB0928T242':[(24.3298218,-84.2289908),(24.0898172,-83.9890116),(19.769836,-83.9890116),(19.64,-83.8591756),(19.64,-83.1400166),(18.4494424,-83.1400166)],
 'ggeUSB0928T343':[(cx-.4200017,cy),(cx-.4200017,-81.9)],
 'ggeUSB0928T346':[(cx+.4200144,cy),(20.5700144,-83.55),(22.7899214,-83.55),(23.264114,-84.0240128),(23.264114,-84.54898)],
 'ggeUSB0928T344':[(19.7499732,-81.8998108),(19.9099424,-82.05978),(20.049998,-82.1998356),(20.109942,-82.1998356)],
 'ggeUSB0928T355':[(19.7499478,-81.4997354),(20.0498964,-81.4997354),(20.269962,-81.719801),(20.269962,-81.8698134),(20.429982,-82.029808),(20.429982,-82.0898028),(20.4499718,-82.109818),(20.4499718,-82.4098174),(20.3399644,-82.5197994),(20.3399644,-82.78005),(cx+.4200144,cy)],
}
for i,s in enumerate(q['shape']):
 f=s.split('~')
 if f[0]=='LIB' and ref(s)=='C2':q['shape'][i]=rotate_shift_180(s,(cx-p['C2']['center'][0],cy-p['C2']['center'][1]))
 elif f[0]=='VIA' and f[6]=='ggeUSB0928V265':f[1],f[2]=path_text([vpos]).split();q['shape'][i]='~'.join(f)
 elif f[0]=='TRACK' and f[5] in paths:f[4]=path_text(paths[f[5]]);q['shape'][i]='~'.join(f)
 elif f[0]=='TRACK' and f[5]=='ggeUSB0928T264':
  points=next(t for t in routes(d)[0] if t['id']==f[5])['points'];f[4]=path_text([vpos,(19.74,-83.55),(20.0,-83.29),*points[1:]]);q['shape'][i]='~'.join(f)
_,np_,nc,nh=parse(q);ts,vs,_=routes(q);changed=[s for s in q['shape'] if s not in d['shape']]
bad=batch.check_new(q,nc,nh,changed)
for a in nc:
 if a['ref']!='C2':continue
 for b in nc+vs:
  if b.get('ref')=='C2' or not shared_layer(a,b):continue
  gap=distance(a['poly'],b['poly'])
  if gap<.15-1e-5:bad.append(['移动焊盘',a['pin'],b.get('ref',b.get('id')),gap])
 for t in ts:
  if t['layer']==a['layer'] and t['net']!=a['net'] and track_gap(t,a['poly'])<batch.clearance(q,t['net'],a['net'])-1e-5:bad.append(['移动焊盘对线',a['pin'],t['id'],track_gap(t,a['poly'])])
loss={n:old_losses(d,c,q,nc,n) for n in {a['net'] for a in c if a['net']}}
print(json.dumps({'间距问题':bad,'退化':{n:v for n,v in loss.items() if v}},ensure_ascii=False,indent=2,default=sorted),flush=True)
if bad or any(loss.values()):raise SystemExit(1)
for i,s in enumerate(q['shape']):
 f=s.split('~')
 if f[0]=='COPPERAREA':f[10]='';q['shape'][i]='~'.join(f)
dest=Path('/Users/liuchunyu/Downloads/PCBMLXRTrial20260929.json')
dest.write_text(json.dumps(q,ensure_ascii=False,indent=2)+'\n')
print(dest)
