"""细间距电源脚短颈扇出，主干仍 >=0.25mm，异网间距不变；需原生与压降复核。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from complete_clone_remaining_20260929 import finish
from check_pcb_a5 import U

configure();batch.STEP=.02
source=Path('/Users/liuchunyu/Downloads/PCBUSBnativeB20260929.json')
neck='--neck-only' in sys.argv
if neck:source=OUT
doc,parts,c,h=parse(source);report=json.loads(REPORT.read_text());log=[]
doc['DRCRULE']['电源']['trackWidth']=.1/U
if '--small-via' in sys.argv:
    doc['DRCRULE']['电源'].update(viaHoleDiameter=.25/U,viaHoleD=.15/U)
targets=[('Q1','2'),('Q1','3'),('U4','A1'),('U2','6')]
for ref,pin in targets:
    pad=next(p for p in c if p['ref']==ref and p['pin']==pin);net=pad['net'];w=.1
    group=next(g for g in batch.island_contacts(doc,c,net) if any(a['id'].startswith(f'{ref}.{pin}:') for a in g))
    if len(connected_groups(doc,c,net))==1:continue
    start=batch.center(pad);_,od,drill=dimensions(doc,net)
    xs,ys,free,vf=batch.obstacles(doc,c,h,net,w,od,drill,start);X,Y=np.meshgrid(xs,ys);ds=np.hypot(X-start[0],Y-start[1])
    if neck:
        _,_,wide,_=batch.obstacles(doc,c,h,net,.25,od,drill,start)
        vf=wide[batch.LAYERS.index(pad['layer'])] & (ds>.20)
    yy,xx=np.where(vf & (ds<1.0));locations=sorted(zip(yy,xx),key=lambda q:ds[q])[:150]
    goals=[{'id':f'短颈终点{i}','poly':[(float(xs[x]),float(ys[y]))],'layer':pad['layer']} for i,(y,x) in enumerate(locations) if free[batch.LAYERS.index(pad['layer'])][y,x]]
    if not goals:log.append([ref,pin,False,'1mm内无合法引出终点']);print('ESCAPE',log[-1],flush=True);continue
    size=len(doc['shape']);ok,info=batch.route(doc,c,h,net,group,goals,w,od,drill)
    if ok and info['长度']>1.0:ok=False;info={'拒绝长细电源线':info}
    if ok:
        if not neck:batch.add_via(doc,net,info['终点'],od,drill)
        issues=batch.check_new(doc,c,h,doc['shape'][size:])
        if issues:ok=False;info=issues
    if not ok:doc['shape']=doc['shape'][:size]
    log.append([ref,pin,ok,info]);print('ESCAPE',log[-1],flush=True)
for net in ['BAT_P','VSYS','USB_5V','3V3']:
    log+=finish(doc,c,h,net)
report['电源短颈试验']={'来源':str(source),'短颈最大长度_mm':1.0,'主干最小线宽_mm':.25,'电源过孔外径内径_mm':list(dimensions(doc,'VSYS')[1:]),'异网间距不变':True,'日志':log,'原生复查':False,'电源压降验收':False}
report['候选几何冲突']=local_check(doc,c,h)
for i,s in enumerate(doc['shape']):
    if s.startswith('COPPERAREA~'):
        a=s.split('~');a[10]='';doc['shape'][i]='~'.join(a)
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('GEOMETRY',report['候选几何冲突'],flush=True)
