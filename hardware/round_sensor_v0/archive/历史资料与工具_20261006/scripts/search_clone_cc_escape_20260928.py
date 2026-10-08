"""局部 CC 器件挪位搜索；保留已接通的 USB、充电与传感器网络。仅本地候选。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from search_clone_r10_pose_20260928 import pose
from build_a5_rf_clearance_layout import ref

def run():
    configure();batch.STEP=.02
    paired='--paired' in sys.argv
    path=Path('/var/folders/6b/_qmhvjlj1dj0tqz5lb5pfzf40000gn/T/edausb-cc-zlqmp4uz/candidate.json')
    doc,parts,c,h=parse(path)
    libs={ref(s):s for s in doc['shape'] if s.startswith('LIB~')}
    # 先只移动 D3。R2 到 D3 的旧支路撤回，留下原位置及其地连接。
    doc['shape']=[s for s in doc['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4]=='J1_B5')]
    ts,vs,_=routes(doc);others=[p for p in c if p['ref'] not in (('D3','R2') if paired else ('D3',))]
    def lower(a,b):
        return max(min(x for x,y in a)-max(x for x,y in b),min(x for x,y in b)-max(x for x,y in a),min(y for x,y in a)-max(y for x,y in b),min(y for x,y in b)-max(y for x,y in a),0)
    candidates=[(float(x),float(y),a) for a in (0,90) for y in np.arange(-76.8,-72.3,.25) for x in np.arange(19.5,27.1,.25)]
    # 从原位置附近开始，以降低地回路和装配改变。
    candidates.sort(key=lambda q:math.dist(q[:2],parts['D3']['center']))
    if paired:
        candidates=[(25.75,-75.3,0),(26.,-75.3,0),(26.,-75.05,0)]
        candidates=[(*q,(q[0]+dx,q[1]+dy),ra) for q in candidates for dx,dy in [(dx,dy) for dx in (-1.,-.75,0,.75,1.) for dy in (-1.,-.75,0,.75,1.) if dx or dy] for ra in (0,90)]
    tries=0
    for candidate in candidates:
        x,y,angle=candidate[:3]
        trial=copy.deepcopy(doc);trial['shape']=[pose(libs['D3'],(x,y),angle) if s.startswith('LIB~') and ref(s)=='D3' else s for s in doc['shape']]
        if paired:trial['shape']=[pose(libs['R2'],candidate[3],candidate[4]) if s.startswith('LIB~') and ref(s)=='R2' else s for s in trial['shape']]
        _,pp,cc,hh=parse(trial);bad=False
        moved=[p for p in cc if p['ref'] in (('D3','R2') if paired else ('D3',))]
        for p in moved:
            for q in others+vs+[q for q in moved if q['ref']!=p['ref']]:
                gap=max(.1 if q.get('kind')=='pad' else 0,batch.clearance(trial,p['net'],q['net']) if p['net']!=q['net'] else 0)
                if shared_layer(p,q) and lower(p['poly'],q['poly'])<gap and distance(p['poly'],q['poly'])<gap-1e-5:bad=True;break
            if bad:break
            for t in ts:
                gap=batch.clearance(trial,p['net'],t['net'])
                if t['layer']==p['layer'] and t['net']!=p['net'] and lower(p['poly'],t['points'])<gap+t['width']/2 and track_gap(t,p['poly'])<gap-1e-5:bad=True;break
            if bad:break
            if any(distance(p['poly'],q['poly'])<.2 for q in hh):bad=True;break
            if max(math.dist(v,(22.999954,-78.999842)) for v in p['poly'])>8.69998:bad=True;break
        if bad:continue
        tries+=1;log=[]
        for _ in range(2):
            groups=batch.island_contacts(trial,cc,'J1_B5')
            if len(groups)==1:break
            ga=next(g for g in groups if any(p['id'].startswith('J1.B5:') for p in g))
            opts=[g for g in groups if g is not ga]
            opts.sort(key=lambda g:min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in g))
            success=False
            for gb in opts:
                size=len(trial['shape']);ok,info=batch.route(trial,cc,hh,'J1_B5',ga,gb,*dimensions(trial,'J1_B5'))
                if ok and len(batch.island_contacts(trial,cc,'J1_B5'))>=len(groups):trial['shape']=trial['shape'][:size];ok=False
                log.append([ok,info])
                if ok:success=True;break
            if not success:break
        connected=len(connected_groups(trial,cc,'J1_B5'))==1
        print('POSE',candidate,connected,log,flush=True)
        if connected and not local_check(trial,cc,hh):
            source,_,oc,_=parse(SOURCE)
            losses={n:[sorted(g) for g in old_losses(source,oc,trial,cc,n)] for n in {p['net'] for p in cc if p['net']!='GND'}}
            losses={n:g for n,g in losses.items() if g}
            if losses:print('REJECT_LOSS',losses,flush=True);continue
            report=json.loads(REPORT.read_text());report['CC局部逃线']={'来源':str(path),'D3中心':[x,y],'相对旋转':angle,'日志':log,'非地原连接退化':losses,'原生验收':False}
            report['移动元件']['D3']=[x,y];report['移动元件']['R2']=pp['R2']['center'];report['移动元件']['R10']=pp['R10']['center']
            save(trial);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('LOCAL_CONNECTIVITY_PASS',flush=True);return
        if tries>=16:break
    print('NO_PASS',tries,flush=True)

if __name__=='__main__':run()
