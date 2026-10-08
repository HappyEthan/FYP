"""限长细间距电源支线候选；保持主干，不把长细线作为连通解。"""
from refine_clone_usb_20260928 import *
from check_pcb_a5 import U

configure()
doc,parts,c,h=parse(OUT)
report=json.loads(REPORT.read_text())
log=[]
# 原生四位小数回读会使几何比名义最小值小约 0.000025mm。
# 修正几何至规则值，不降低规则或放大检查容差。
for i,s in enumerate(doc['shape']):
    a=s.split('~')
    if a[0]=='TRACK' and a[5].startswith(PREFIX):
        w,_,_=dimensions(doc,a[3])
        if float(a[1])*U<w and w-float(a[1])*U<.0001:
            a[1]=f'{(w+.0000001)/U:.9f}'
    elif a[0]=='VIA' and a[6].startswith(PREFIX):
        _,od,drill=dimensions(doc,a[4])
        if float(a[3])*U<od and od-float(a[3])*U<.0001:a[3]=f'{(od+.0000001)/U:.9f}'
        if 2*float(a[5])*U<drill and drill-2*float(a[5])*U<.0001:a[5]=f'{(drill+.0000001)/2/U:.9f}'
    doc['shape'][i]='~'.join(a)
for net in ['BAT_P','USB_5V','3V3']:
    for width,limit in [(0.20,3.0),(.15,2.5),(.10,2.0)]:
        batch.STEP=.02
        groups=batch.island_contacts(doc,c,net)
        if len(groups)==1:break
        pairs=sorted([(min(math.dist(batch.center(a),batch.center(b)) for a in ga for b in gb),ga,gb)
                      for i,ga in enumerate(groups) for gb in groups[:i]],key=lambda q:q[0])
        for dist,ga,gb in pairs:
            if dist>limit:continue
            size=len(doc['shape']);_,od,drill=dimensions(doc,net)
            ok,info=batch.route(doc,c,h,net,ga,gb,width,od,drill)
            if ok and (info['长度']>limit or len(batch.island_contacts(doc,c,net))>=len(groups)):
                ok=False;info={'拒绝超长或未合并支线':info}
            if not ok:doc['shape']=doc['shape'][:size]
            else:groups=batch.island_contacts(doc,c,net)
            log.append([net,width,ok,info]);print('LOCAL_POWER',log[-1],flush=True)
            if ok:break
    save(doc)
report['限长电源支线候选']={'日志':log,'载流压降未验收':True,'未放宽异网间距':True}
report['当前非地断点组']={n:[sorted(g) for g in connected_groups(doc,c,n)] for n in sorted({p['net'] for p in c if p['net'] and p['net']!='GND'}) if len(connected_groups(doc,c,n))>1}
report['候选几何冲突']=local_check(doc,c,h)
assert not report['候选几何冲突'],report['候选几何冲突']
save(doc);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('REMAIN',report['当前非地断点组'],flush=True)
