"""在当前本地候选上继续补普通网络，不覆盖云端。失败的 CC 重排整批撤回。"""
from refine_clone_usb_20260928 import *

def finish(doc,c,h,net):
    log=[];blocked=set()
    for _ in range(10):
        groups=batch.island_contacts(doc,c,net)
        if len(groups)<=1:break
        labels=[tuple(sorted({a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')})) for g in groups]
        options=[]
        for i,g in enumerate(groups):
            for j,q in enumerate(groups[:i]):
                key=tuple(sorted((labels[i],labels[j])))
                if key not in blocked:options.append((min(math.dist(batch.center(a),batch.center(b)) for a in g for b in q),key,g,q))
        if not options:break
        _,key,g,q=min(options,key=lambda a:(a[0],a[1]));size=len(doc['shape'])
        w,od,drill=dimensions(doc,net)
        if net in ('BAT_P','VSYS','USB_5V','3V3'):w=max(w,.25)
        ok,info=batch.route(doc,c,h,net,g,q,w,od,drill)
        if ok and len(batch.island_contacts(doc,c,net))>=len(groups):doc['shape']=doc['shape'][:size];ok=False
        if not ok:blocked.add(key)
        log.append([net,key,ok,info]);print('ROUTE',log[-1],flush=True)
    return log

def run():
    configure();batch.STEP=.02;doc,parts,c,h=parse(OUT);report=json.loads(REPORT.read_text());trial=copy.deepcopy(doc)
    trial['shape']=[s for s in trial['shape'] if not(s.startswith(('TRACK~','VIA~')) and s.split('~')[3 if s.startswith('TRACK~') else 4] in ('J1_A5','J1_B5'))]
    log=finish(trial,c,h,'J1_B5')+finish(trial,c,h,'J1_A5')
    if all(len(connected_groups(trial,c,n))==1 for n in ('J1_A5','J1_B5')) and not local_check(trial,c,h):
        doc=trial;print('CC_PAIR_PASS',flush=True)
    else:print('CC_PAIR_REVERTED',flush=True)
    save(doc)
    for net in ['BAT_P','VSYS','USB_5V','3V3']:
        log+=finish(doc,c,h,net);save(doc)
    report['后续补线日志']=log;report['候选几何冲突']=local_check(doc,c,h)
    report['当前非地断点组']={n:[sorted(g) for g in connected_groups(doc,c,n)] for n in sorted({p['net'] for p in c if p['net'] and p['net']!='GND'}) if len(connected_groups(doc,c,n))>1}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('REMAIN',report['当前非地断点组'],'GEOMETRY',report['候选几何冲突'],flush=True)

if __name__=='__main__':run()
