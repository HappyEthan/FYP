"""同位置旋转充电芯片180度的局部候选，不变更电路和工艺。"""
from refine_clone_usb_20260928 import *
from build_a5_usb_front_candidate import rotate_shift_180
from build_a5_rf_clearance_layout import ref
from check_pcb_a5 import U
from build_a5_usb_zone_placement import shift_lib_safe
import re
from pathlib import Path

def quarter_turn_u4(shape, angle):
    """仅适用此处已检查的 U4：圆焊盘、折线、圆圈；文字留原位。"""
    chunks=[s.split('~') for s in shape.split('#@$')];head=chunks[0]
    cx,cy=map(float,head[1:3]);rad=math.radians(angle)
    def pair(x,y):
        x,y=float(x)-cx,float(y)-cy
        return (cx+x*math.cos(rad)-y*math.sin(rad),cy+x*math.sin(rad)+y*math.cos(rad))
    def string(v,sep=' '):
        nums=list(map(float,re.findall(r'-?\d+(?:\.\d+)?',v)))
        return sep.join(f'{a:.8f}' for j in range(0,len(nums),2) for a in pair(*nums[j:j+2]))
    head[4]=str((float(head[4])+angle)%360)
    for v in chunks[1:]:
        if v[0]=='PAD':
            assert v[1]=='ELLIPSE' and abs(float(v[4])-float(v[5]))<1e-6
            v[2],v[3]=map(str,pair(v[2],v[3]));v[11]=str((float(v[11])+angle)%360)
            assert not v[10]
            if v[19]:v[19]=string(v[19],',')
        elif v[0]=='TRACK':v[4]=string(v[4])
        elif v[0]=='CIRCLE':v[1],v[2]=map(str,pair(v[1],v[2]))
        elif v[0]=='TEXT':pass
        else:raise ValueError(v[0])
    return '#@$'.join('~'.join(v) for v in chunks)

configure();doc,p,c,h=parse(OUT);trial=copy.deepcopy(doc)
batch.STEP=.01
oldpads=[q for q in c if q['ref']=='U4'];ts,_,_=routes(doc)
ids={t['id'] for t in ts for q in oldpads if shared_layer(t,q) and t['net']==q['net'] and track_gap(t,q['poly'])<.0001}
trial['shape']=[s for s in trial['shape'] if not(s.startswith('TRACK~') and s.split('~')[5] in ids)]
if '--rip-iref' in sys.argv:
    trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='U4_C1')]
if '--rip-power-local' in sys.argv:
    ts,vs,_=routes(trial);center=p['U4']['center']
    blocked={t['id'] for t in ts if t['net'] in ('BAT_P','USB_5V') and track_gap(t,[center])<.8}
    blocked|={v['id'] for v in vs if v['net'] in ('BAT_P','USB_5V') and math.dist(batch.center(v),center)<.8}
    trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[5 if s.startswith('TRACK~') else 6] in blocked)]
for i,s in enumerate(trial['shape']):
    if s.startswith('LIB~') and ref(s)=='U4' and '--no-rotate' not in sys.argv:trial['shape'][i]=quarter_turn_u4(s,90 if '--90' in sys.argv else 270) if ('--90' in sys.argv or '--270' in sys.argv) else rotate_shift_180(s,(0,0))
    if s.startswith('LIB~') and ref(s)=='U4' and '--shift-right' in sys.argv:trial['shape'][i]=shift_lib_safe(trial['shape'][i],(.2 if '--shift-more' in sys.argv else .1,0))
    if s.startswith('LIB~') and ref(s)=='U4' and '--shift-down' in sys.argv:trial['shape'][i]=shift_lib_safe(trial['shape'][i],(0,.18))
rule=copy.deepcopy(trial['DRCRULE']['Default']);rule.update(nets=['U4_C1'],viaHoleDiameter=.25/U,viaHoleD=.15/U);trial['DRCRULE']['充电设定小孔_025_015']=rule
_,np_,nc,nh=parse(trial);log=[]
if '--inspect' in sys.argv:
    for q in [a for a in nc if a['ref']=='U4']:
        ts,vs,_=routes(trial)
        bad=[]
        for a in nc+vs:
            if a is q or a.get('ref')=='U4' or a['net']==q['net'] or not shared_layer(q,a):continue
            gap=distance(q['poly'],a['poly'])
            if gap<batch.clearance(trial,q['net'],a['net']):bad.append([a.get('id',a.get('ref')),a['net'],gap])
        for t in ts:
            if t['net']!=q['net'] and shared_layer(q,t):
                gap=track_gap(t,q['poly'])
                if gap<batch.clearance(trial,q['net'],t['net']):bad.append([t['id'],t['net'],gap])
        print(q['pin'],batch.center(q),bad,flush=True)
    sys.exit(0)
if '--pre-power' in sys.argv:
    for net in ['BAT_P','USB_5V']:
        for _ in range(8):
            gs=batch.island_contacts(trial,nc,net)
            if len(gs)==1:break
            pairs=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb) for i,ga in enumerate(gs) for gb in gs[:i]],key=lambda z:z[0]);ok=False
            for _,ga,gb in pairs:
                for w in [.25,.15,.1]:
                    size=len(trial['shape']);_,od,drill=dimensions(trial,net)
                    ok,info=batch.route(trial,nc,nh,net,ga,gb,w,od,drill)
                    if ok and info['长度']>(4 if w==.1 else 10):ok=False;trial['shape']=trial['shape'][:size]
                    print('CHIP_PRE_POWER',net,w,ok,info,flush=True)
                    if ok:log.append([net,info]);break
                if ok:break
            if not ok:sys.exit(0)
if '--pre-iref' in sys.argv:
    gs=batch.island_contacts(trial,nc,'U4_C1');assert len(gs)==2
    ok,info=batch.route(trial,nc,nh,'U4_C1',gs[0],gs[1],*dimensions(trial,'U4_C1'))
    print('CHIP_PRE_IREF',ok,info,flush=True)
    if not ok or info['长度']>10:sys.exit(0)
    log.append(['U4_C1',info])
for pin in ['B1','C2']:
    gs=batch.island_contacts(trial,nc,'GND');g=next(g for g in gs if any(a['id'].startswith(f'U4.{pin}:') for a in g))
    if any(a['id'].startswith(('C6.2:','C7.2:','R9.2:')) for a in g):continue
    goals=[a for q in gs if any(b['id'].startswith(('C6.2:','C7.2:','R9.2:')) for b in q) for a in q]
    ok,info=batch.route(trial,nc,nh,'GND',g,goals,*dimensions(trial,'GND'));print('CHIP_GND',pin,ok,info,flush=True)
    # B1 为电压选择逻辑脚；C2 才是功率地。仅 B1 接地允许至 3 mm。
    if not ok or info['长度']>(3.0 if pin=='B1' else 2.5):sys.exit(0)
    log.append(['GND',pin,info])
for net in (['BAT_P','USB_5V','U4_C1'] if '--power-first' in sys.argv else ['U4_C1','BAT_P','USB_5V']):
    for _ in range(5):
        groups=batch.island_contacts(trial,nc,net)
        if len(groups)==1:break
        pairs=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb) for i,ga in enumerate(groups) for gb in groups[:i]],key=lambda v:v[0]);ok=False
        for _,ga,gb in pairs:
            for w in ([dimensions(trial,net)[0]] if net=='U4_C1' else [.25,.15,.1]):
                size=len(trial['shape']);_,od,drill=dimensions(trial,net);ok,info=batch.route(trial,nc,nh,net,ga,gb,w,od,drill)
                if ok and info['长度']>(4 if w<=.1 and net!='U4_C1' else 10):ok=False;trial['shape']=trial['shape'][:size]
                print('CHIP_RESTORE',net,w,ok,info,flush=True)
                if ok:log.append([net,info]);break
            if ok:break
        if not ok:sys.exit(0)
losses={n:[sorted(g) for g in old_losses(doc,c,trial,nc,n)] for n in {a['net'] for a in c if a['net']}}
losses={n:v for n,v in losses.items() if v};print('CHIP_LOSSES',losses,flush=True)
if losses and not ('--native-trial' in sys.argv and set(losses)=={'GND'}):raise RuntimeError('连接退化')
TARGETS['U4']=np_['U4']['center'];bad=local_check(trial,nc,nh);assert not bad,bad
if '--native-trial' in sys.argv:
    path=Path('/Users/liuchunyu/Downloads/PCBUSBchargerTrial20260929.json')
    path.write_text(json.dumps(trial,ensure_ascii=False,indent=2)+'\n')
    path.with_suffix('.report.json').write_text(json.dumps({'原候选SHA256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'源文件':str(OUT),'新中心':np_['U4']['center'],'日志':log,'离散地网变化_待原生铜面核验':losses,'局部几何':bad,'原生验收':False},ensure_ascii=False,indent=2)+'\n')
    print('NATIVE_TRIAL_ONLY',path,flush=True);sys.exit(0)
save(trial);r=json.loads(REPORT.read_text());r['充电芯片局部转向']={'元件':'U4','旋转度数':0 if '--no-rotate' in sys.argv else 90 if '--90' in sys.argv else 270 if '--270' in sys.argv else 180,'中心':np_['U4']['center'],'日志':log,'原生验收':False};REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print('CHIP_ACCEPT',flush=True)
