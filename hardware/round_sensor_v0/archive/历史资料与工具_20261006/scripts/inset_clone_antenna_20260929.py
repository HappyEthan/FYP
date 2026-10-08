"""用户授权 ANT1 向板内微移；保留右上顶层 FPC 方案，完整检查后才写候选。"""
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref,svg_path
from build_a5_usb_zone_placement import shift_lib_safe
from repair_clone_inner_layer_20260928 import path_text
from check_pcb_a5 import U,xy
from audit_a5_ufl_keepout import audit
from pathlib import Path
import tempfile

configure();doc,parts,c,h=parse(OUT);trial=copy.deepcopy(doc);delta=(-.15,.03)
oldpads=[a for a in c if a['ref']=='ANT1'];centers=[batch.center(a) for a in oldpads]
for i,s in enumerate(trial['shape']):
    if s.startswith('LIB~') and ref(s)=='ANT1':trial['shape'][i]=shift_lib_safe(s,delta)
    elif s.startswith('TRACK~'):
        a=s.split('~');ns=list(map(float,a[4].split()));pts=[xy(*ns[j:j+2]) for j in range(0,len(ns),2)]
        if a[3] in {'GND','R30_2'} and any(math.dist(q,z)<.001 for q in pts for z in centers):
            pts=[tuple(q[j]+delta[j] for j in [0,1]) if any(math.dist(q,z)<.001 for z in centers) else q for q in pts]
            a[4]=path_text(pts);trial['shape'][i]='~'.join(a)
    elif s.startswith('SOLIDREGION~') and 'UFL' in s:
        a=s.split('~');a[3]=svg_path(a[3],delta[0]/U,delta[1]/U);trial['shape'][i]='~'.join(a)
_,np_,nc,nh=parse(trial);TARGETS['ANT1']=np_['ANT1']['center']
bad=local_check(trial,nc,nh)
if bad:print('ANT_REJECT',bad[:10]);sys.exit(0)
assert not any(old_losses(doc,c,trial,nc,n) for n in {a['net'] for a in c if a['net']})
with tempfile.TemporaryDirectory(prefix='ant-check-') as td:
    p=Path(td)/'candidate.json';p.write_text(json.dumps(trial));ar,_,zones=audit(p)
env=zones['本体全层净空候选']['板心坐标多边形_mm'][0]
xs=np.arange(min(p[0] for p in env),max(p[0] for p in env),.005)
ys=np.arange(min(p[1] for p in env),max(p[1] for p in env),.005);X,Y=np.meshgrid(xs,ys)
inside=batch.poly_distance(X,Y,env)==0;cut=inside.copy()
for a in nc:
    if a['ref']=='ANT1':cut&=batch.poly_distance(X,Y,a['poly'])>0
ts,vs,_=routes(trial);off=[]
for t in ts:
    if track_gap(t,env)>.001:continue
    mask=cut if t['layer']=='1' else inside
    if any(np.any(mask&(batch.line_distance(X,Y,a,b)<t['width']/2)) for a,b in zip(t['points'],t['points'][1:])):off.append(t['id'])
for v in vs:
    if distance(v['poly'],env)<1e-7:off.append(v['id'])
off+=zones['本体全层净空候选']['现有焊盘过孔相交']
if off:print('ANT_KEEPOUT_REJECT',off);sys.exit(0)
ctr=(22.999954,-78.999842);rad=8.999982
gap=min(rad-max(math.dist(ctr,p) for p in a['poly']) for a in nc if a['ref']=='ANT1')
assert gap>.325,gap
save(trial);r=json.loads(REPORT.read_text());r['天线连接器授权内移']={'位移_mm':delta,'铜到板框中心线最小距离_mm':gap,'离散铜净空检查':True,'走线净空采样步长_mm':.005,'原生铺铜射频复查':False,'原生验收':False}
REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print('ANT_ACCEPT',gap)
