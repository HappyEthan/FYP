"""修复 J1 内移后 CC 过孔钻边距 R1 焊盘不足的问题；只局部移动现有孔。"""
from refine_clone_usb_20260928 import *
from repair_clone_inner_layer_20260928 import path_text
from check_pcb_a5 import xy,U

configure();doc,p,c,h=parse(OUT);vid='ggeUSB0928V290'
v=next(v for v in routes(doc)[1] if v['id']==vid);old=batch.center(v);log=[]
for dx,dy in [(-.12,0),(-.15,0),(-.10,.01),(-.14,-.01),(-.18,0)]:
    trial=copy.deepcopy(doc);new=(old[0]+dx,old[1]+dy);changed=[]
    for i,s in enumerate(trial['shape']):
        a=s.split('~');hit=False
        if a[0]=='VIA' and a[6]==vid:a[1],a[2]=path_text([new]).split();hit=True
        elif a[0]=='TRACK' and a[3]==v['net']:
            ns=list(map(float,a[4].split()));points=[xy(*ns[j:j+2]) for j in range(0,len(ns),2)]
            if any(math.dist(q,old)<.001 for q in points):
                a[4]=path_text([new if math.dist(q,old)<.001 else q for q in points]);hit=True
        if hit:trial['shape'][i]='~'.join(a);changed.append(trial['shape'][i])
    bad=batch.check_new(trial,c,h,changed)
    drill=next(float(s.split('~')[5])*2*U for s in trial['shape'] if s.startswith('VIA~') and s.split('~')[6]==vid)
    gaps=[(a['ref']+'.'+a['pin'],distance([new],a['poly'])-drill/2) for a in c if a['kind']=='pad' and a['layer'] in ('1','2')]
    tiny=[(r,g) for r,g in gaps if g<.1-1e-5]
    info={'位移_mm':[dx,dy],'几何冲突':bad[:5],'钻边不足':tiny,'最近焊盘':min(gaps,key=lambda a:a[1])}
    print('CC_VIA_TRIAL',info,flush=True);log.append(info)
    if bad or tiny or old_losses(doc,c,trial,c,v['net']):continue
    save(trial);report=json.loads(REPORT.read_text());report['CC过孔钻边间距修复']={'位号':vid,'原坐标':old,'新坐标':new,'日志':log,'原生复查':False};REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('CC_VIA_ACCEPT',new,flush=True);break
else:print('CC_VIA_NO_ACCEPT',flush=True)
