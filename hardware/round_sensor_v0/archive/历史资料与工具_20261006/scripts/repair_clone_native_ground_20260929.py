"""按原生铜面找孤立地网，补短回路；不会写云端，不接受长绕行。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import ground_groups,regions,contains
from check_pcb_a5 import U

def run():
    configure();batch.STEP=.02
    path=Path('/Users/liuchunyu/Downloads/PCBUSBnative20260929.json')
    doc,parts,c,h=parse(path);gs=ground_groups(doc,c);log=[]
    small='--small-local' in sys.argv
    if small:
        rule=doc['DRCRULE'].pop('接地过孔_040_020')
        rule.update(trackWidth=.15/U,viaHoleDiameter=.25/U,viaHoleD=.15/U)
        doc['DRCRULE']['接地短引出_025_015']=rule
        rule=copy.deepcopy(doc['DRCRULE']['Default']);rule.update(nets=['J1_A5','J1_B5'],viaHoleDiameter=.25/U,viaHoleD=.15/U)
        doc['DRCRULE']['CC小孔_025_015']=rule
        islands=batch.island_contacts(doc,c,'J1_B5')
        if len(islands)==2:
            ok,info=batch.route(doc,c,h,'J1_B5',islands[0],islands[1],*dimensions(doc,'J1_B5'))
            print('CC_SMALL',ok,info,flush=True)
    l2=[r for layer,r in regions(doc) if layer=='21'];assert len(l2)==1
    for g in gs:
        labels=sorted({a['id'].split(':')[0] for a in g if not a['id'].startswith('gge')})
        if 'U1.57' in labels:continue
        w,od,drill=dimensions(doc,'GND');start=batch.center(g[0])
        xs,ys,free,vf=batch.obstacles(doc,c,h,'GND',w,od,drill,start)
        X,Y=np.meshgrid(xs,ys);ds=np.full(X.shape,np.inf)
        for a in g:
            p=batch.center(a);ds=np.minimum(ds,np.hypot(X-p[0],Y-p[1]))
        iy,ix=np.where(vf & (ds<1.2))
        locations=sorted(zip(iy,ix),key=lambda q:ds[q])[:200]
        goals=[]
        for y,x in locations:
            pt=(float(xs[x]),float(ys[y]))
            if not contains(l2[0],[pt])[0]:continue
            for li,l in enumerate(batch.LAYERS):
                if free[li][y,x]:goals.append({'id':f'局部接地{len(goals)}','poly':[pt],'layer':l})
        if not goals:log.append([labels,False,'无合法短接地孔位置']);print('GROUND',log[-1],flush=True);continue
        size=len(doc['shape']);ok,info=batch.route(doc,c,h,'GND',g,goals,w,od,drill)
        if ok and info['长度']>1.2:ok=False;info={'拒绝长接地路径':info}
        if ok:
            batch.add_via(doc,'GND',info['终点'],od,drill)
            errors=batch.check_new(doc,c,h,doc['shape'][size:])
            if errors:ok=False;info=errors
        if not ok:doc['shape']=doc['shape'][:size]
        log.append([labels,ok,info]);print('GROUND',log[-1],flush=True)
    report=json.loads(REPORT.read_text())
    report['原生后接地精修']={'来源':str(path),'日志':log,'原生复查':False}
    if small:report['局部小孔试验']={'异网间距不变':True,'GND短引出线宽_mm':.15,'CC与GND新孔外径内径_mm':[.25,.15],'依据':'https://m.jlc.com/portal/q7i38752.html','本板普通信号已有相同孔径':True,'制造验收':False}
    report['原生临时检查']={'总数':67,'未连接':21,'地断点':12,'云端保存':False,'对应文件':str(path)}
    report['候选几何冲突']=local_check(doc,c,h)
    for i,s in enumerate(doc['shape']):
        if s.startswith('COPPERAREA~'):
            a=s.split('~');a[10]='';doc['shape'][i]='~'.join(a)
    save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('GEOMETRY',report['候选几何冲突'],flush=True)

if __name__=='__main__':run()
