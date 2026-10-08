"""在 USB 候选上继续局部修复；不写云端。允许撤回挡路的旧地线，随后补短接地孔。"""
import copy,json,math,hashlib,sys
import numpy as np
from build_clone_usb_local_20260928 import SOURCE,OUT,REPORT,PREFIX,TARGETS,GROUND_ZONE,dimensions,save,local_check,routed_geometry
from check_pcb_a5 import parse,distance,shared_layer
from audit_a5_routed_snapshot import routes,track_gap
from test_a5_usb_soc_fanout import connected_groups
import repair_clone_batch_20260928 as batch
import build_a5_usb_front_candidate as check


def configure():
    batch.SOURCE=SOURCE;batch.PREFIX=PREFIX;batch.STEP=.02
    batch.KEEPOUT_SOURCE=OUT if OUT.exists() else SOURCE
    batch.RESERVED_GROUND=[('22',GROUND_ZONE)]
    check.PREFIX=PREFIX;check.DELTAS=TARGETS;check.routes=routed_geometry


def old_losses(source,oldc,doc,c,n):
    gs=connected_groups(doc,c,n)
    return [g for g in connected_groups(source,oldc,n) if not any(g<=s for s in gs)]


def restore(doc,c,h,net,ga,gb,report):
    w,od,drill=dimensions(doc,net)
    ok,info=batch.route(doc,c,h,net,ga,gb,w,od,drill)
    if ok:return ok,info
    trial=copy.deepcopy(doc)
    # 仅允许撤回旧底层地线，保留本轮 USB 回流短接和射频地连接。
    removable=[s for s in doc['shape'] if s.startswith('TRACK~') and s.split('~')[2]=='2' and
               s.split('~')[3]=='GND' and not s.split('~')[5].startswith((PREFIX,'ggeRF'))]
    trial['shape']=[s for s in trial['shape'] if s not in removable]
    size=len(trial['shape'])
    ok2,info2=batch.route(trial,c,h,net,ga,gb,w,od,drill)
    if not ok2:return False,[info,info2]
    added=trial['shape'][size:];newt,newv,_=routes({'shape':added});oldtracks,_,_=routes({'shape':removable})
    bad=set()
    for t in oldtracks:
        for q in newt:
            if t['layer']!=q['layer']:continue
            gap=min(distance([a,b],[x,y]) for a,b in zip(t['points'],t['points'][1:]) for x,y in zip(q['points'],q['points'][1:]))-(t['width']+q['width'])/2
            if gap<batch.clearance(doc,'GND',net)+1e-5:bad.add(t['id'])
        for v in newv:
            if track_gap(t,v['poly'])<batch.clearance(doc,'GND',net)+1e-5:bad.add(t['id'])
    removed=[s for s in removable if s.split('~')[5] in bad]
    doc['shape']=[s for s in doc['shape'] if s not in removed]
    # trial 的图元编号基于删除后的数量；在真实文档上重新分配，杜绝重复编号。
    newt,newv,_=routes({'shape':added});size=len(doc['shape'])
    for t in newt:batch.add_track(doc,t['net'],t['layer'],t['points'],t['width'])
    for s in added:
        v=s.split('~')
        if v[0]=='VIA':
            from check_pcb_a5 import xy,U
            batch.add_via(doc,v[4],xy(v[1],v[2]),float(v[3])*U,2*float(v[5])*U)
    issues=batch.check_new(doc,c,h,doc['shape'][size:])
    if issues:
        doc['shape']=doc['shape'][:size]+removed
        return False,issues
    report.setdefault('为恢复信号撤回旧地线',[]).extend(removed)
    return True,dict(info2,撤回旧地线数=len(removed))


def ground_islands(doc,c,h,report):
    """未通过通孔接地的离散铜岛，就近下地孔；实际平面接入仍需原生重建。"""
    done=set()
    for _ in range(20):
        pending=[]
        for g in batch.island_contacts(doc,c,'GND'):
            layers={}
            for a in g:layers.setdefault(a['id'].rsplit(':',1)[0],set()).add(a['layer'])
            if any(len(ls)>1 for ls in layers.values()):continue
            labels=tuple(sorted({a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')}))
            if labels and labels not in done:pending.append((labels,g))
        if not pending:break
        labels,g=min(pending,key=lambda x:(len(x[0]),x[0]));done.add(labels)
        w,od,drill=dimensions(doc,'GND');start=batch.center(g[0])
        xs,ys,free,vf=batch.obstacles(doc,c,h,'GND',w,od,drill,start)
        X,Y=np.meshgrid(xs,ys);dist=np.full(X.shape,np.inf)
        for a in g:
            p=batch.center(a);dist=np.minimum(dist,np.hypot(X-p[0],Y-p[1]))
        iy,ix=np.where(vf & (dist<1.2))
        candidates=sorted(zip(iy,ix),key=lambda q:dist[q])[:80]
        goals=[{'id':f'接地候选{j}','poly':[(float(xs[x]),float(ys[y]))],'layer':'2'} for j,(y,x) in enumerate(candidates) if free[1][y,x]]
        if not goals:
            report.setdefault('接地精修日志',[]).append([labels,False,'1.2mm内无合法孔位']);continue
        size=len(doc['shape']);ok,info=batch.route(doc,c,h,'GND',g,goals,w,od,drill)
        if ok:
            if not any(v['net']=='GND' and math.dist(batch.center(v),info['终点'])<1e-4 for v in routes(doc)[1]):
                batch.add_via(doc,'GND',info['终点'],od,drill)
            errors=batch.check_new(doc,c,h,doc['shape'][size:])
            if errors:doc['shape']=doc['shape'][:size];ok=False;info=errors
        print('GROUND',labels,ok,info,flush=True)
        report.setdefault('接地精修日志',[]).append([labels,ok,info]);save(doc)


def refine():
    configure();source,parts,oldc,_=parse(SOURCE);doc,parts,c,h=parse(OUT)
    report=json.loads(REPORT.read_text());assert report['来源SHA256']==hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    for net in ['3V3','USB_5V','MCU_EN','BOOT_N','REG_EN','U4_C1','I2C_SDA','I2C_SCL','J1_A5','J1_B5']:
        blocked=set()
        for attempt in range(10):
            loss=old_losses(source,oldc,doc,c,net)
            if not loss:break
            islands=batch.island_contacts(doc,c,net)
            labels=[{a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')} for g in islands]
            opts=[]
            for i,g in enumerate(islands):
                for j,q in enumerate(islands[:i]):
                    if not any(labels[i]&s or labels[j]&s for s in loss):continue
                    key=tuple(sorted((tuple(sorted(labels[i])),tuple(sorted(labels[j])))))
                    if key in blocked:continue
                    opts.append((min(math.dist(batch.center(a),batch.center(b)) for a in g for b in q),key,g,q))
            if not opts:break
            _,key,ga,gb=min(opts,key=lambda x:(x[0],x[1]))
            ok,info=restore(doc,c,h,net,ga,gb,report)
            print(net,ok,info,flush=True)
            report.setdefault('精修日志',[]).append([net,key,ok,info])
            if not ok:blocked.add(key)
            save(doc)
    if '--ground' in sys.argv:ground_islands(doc,c,h,report)
    report['原连接退化']={n:[sorted(g) for g in old_losses(source,oldc,doc,c,n)] for n in {p['net'] for p in c if p['net']}}
    report['原连接退化']={n:g for n,g in report['原连接退化'].items() if g}
    report['候选几何冲突']=local_check(doc,c,h)
    report['本地几何与连接准入']=not report['原连接退化'] and not report['候选几何冲突']
    for i,s in enumerate(doc['shape']):
        if s.startswith('COPPERAREA~'):
            v=s.split('~');v[10]='';doc['shape'][i]='~'.join(v)
    save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('LOSSES',json.dumps(report['原连接退化'],ensure_ascii=False),flush=True)
    print('GEOMETRY',report['候选几何冲突'],flush=True)


if __name__=='__main__':refine()
