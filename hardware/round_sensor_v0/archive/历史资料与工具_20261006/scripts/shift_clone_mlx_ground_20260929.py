"""小范围平移 MLX 及局部重连试排；完整检查通过才写入本地候选。"""
from refine_clone_usb_20260928 import *
from build_a5_rf_clearance_layout import ref
from build_a5_usb_zone_placement import shift_lib_safe as shift_lib

def labels(g):return {a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')}
def connect(doc,c,h,net,wlimit=5):
    log=[]
    for _ in range(10):
        gs=batch.island_contacts(doc,c,net)
        if len(gs)==1:return True,log
        opts=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb) for i,ga in enumerate(gs) for gb in gs[:i]],key=lambda v:v[0])
        found=False
        for _,ga,gb in opts:
            for w in ([.15,.1] if net=='3V3' else [dimensions(doc,net)[0]]):
                size=len(doc['shape']);_,od,drill=dimensions(doc,net)
                ok,info=batch.route(doc,c,h,net,ga,gb,w,od,drill)
                if ok and info['长度']>wlimit:ok=False
                if not ok:doc['shape']=doc['shape'][:size]
                else:found=True;log.append([net,info]);break
            if found:break
        if not found:return False,log
    return False,log

def attempt(base,oldc,dx,dy):
    trial=copy.deepcopy(base);ts,_,_=routes(base)
    pins=[p for p in oldc if p['ref']=='U2']
    ids={t['id'] for t in ts for p in pins if shared_layer(t,p) and t['net']==p['net'] and track_gap(t,p['poly'])<.0001}
    trial['shape']=[s for s in trial['shape'] if not(s.startswith('TRACK~') and s.split('~')[5] in ids)]
    for i,s in enumerate(trial['shape']):
        if s.startswith('LIB~') and ref(s)=='U2':trial['shape'][i]=shift_lib(s,(dx,dy))
    _,parts,c,h=parse(trial);TARGETS['U2']=parts['U2']['center']
    bad=local_check(trial,c,h)
    if bad:return False,['移动后冲突',bad[:3]]
    log=[]
    # Restore the tight signal escapes before providing a nearby ground via.
    for net in ['I2C_SDA','I2C_SCL','MLX_INT','3V3']:
        ok,info=connect(trial,c,h,net);log.extend(info)
        if not ok:return False,['信号恢复失败',net,log]
    for pin in ['U2.1','U2.2','U2.4','U2.5','U2.9','C2.2']:
        gs=batch.island_contacts(trial,c,'GND');g=next(g for g in gs if pin in labels(g))
        # A through via already provides access to the continuous L2 plane.
        layerids={}
        for a in g:layerids.setdefault(a['id'].rsplit(':',1)[0],set()).add(a['layer'])
        if any(len(v)>1 for v in layerids.values()):continue
        w,od,drill=dimensions(trial,'GND');start=batch.center(g[0])
        xs,ys,free,vf=batch.obstacles(trial,c,h,'GND',w,od,drill,start)
        X,Y=np.meshgrid(xs,ys);ds=np.minimum.reduce([np.hypot(X-batch.center(a)[0],Y-batch.center(a)[1]) for a in g]);yy,xx=np.where(vf&(ds<1.5))
        goals=[{'id':f'局部地孔{i}:{l}','poly':[(float(xs[x]),float(ys[y]))],'layer':l} for i,(y,x) in enumerate(zip(yy,xx)) for li,l in enumerate(batch.LAYERS) if free[li][y,x]]
        if not goals:return False,['接地无孔位',pin]
        ok,info=batch.route(trial,c,h,'GND',g,goals,w,od,drill)
        if not ok or info['长度']>2:return False,['接地失败',pin,info]
        batch.add_via(trial,'GND',info['终点'],od,drill);log.append([pin,info])
    # Preserve discrete ground groups too, not only plane-level connectivity.
    loss={n:old_losses(base,oldc,trial,c,n) for n in {a['net'] for a in c if a['net']}}
    if any(loss.values()):return False,['原连接退化',{n:[sorted(g) for g in v] for n,v in loss.items() if v}]
    bad=local_check(trial,c,h)
    if bad:return False,['重连冲突',bad[:3]]
    save(trial);r=json.loads(REPORT.read_text());r['MLX局部平移']={'位移_mm':[dx,dy],'日志':log,'原生验收':False};REPORT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    return True,log

if __name__=='__main__':
    configure();batch.THERMAL_VIA_PADS={('U1','57')};base,p,c,h=parse(OUT)
    for d in [(0.3,0),(.5,0),(.7,0),(.3,-.2),(.5,-.2),(.7,-.2)]:
        ok,info=attempt(base,c,*d);print('MLX_SHIFT',d,ok,info,flush=True)
        if ok:break
