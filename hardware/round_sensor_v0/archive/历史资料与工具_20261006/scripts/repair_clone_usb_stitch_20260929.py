"""从 G 检查点局部补 USB 回流孔，生成独立本地试验，不覆盖当前候选。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from audit_clone_native_ground_20260929 import regions,contains,PlotPath
from check_pcb_a5 import U
from repair_clone_inner_layer_20260928 import path_text

src=Path('/Users/liuchunyu/Downloads/PCBUSBnativeG20260929.json')
assert hashlib.sha256(src.read_bytes()).hexdigest()=='81b13e07c406a5ec4dc76c1df81702f5c10ede20dd76da72c92ebbf8eeef6f23'
configure();doc,p,c,h=parse(src);rs=regions(doc);log=[];start_size=len(doc['shape'])
# 仅扩大现有 L3 地铜的局部边界，内层异网避让仍为原来的 0.20 mm。
expanded=[(21.05,-79.95),(24.85,-79.95),(24.85,-74.00),(22.65,-74.00),(22.65,-73.70),(21.05,-73.70)]
for i,s in enumerate(doc['shape']):
    if s.startswith('COPPERAREA~') and s.split('~')[7]=='ggeUSB0928GNDL3':
        a=s.split('~');coords=path_text(expanded).split();a[4]='M '+' L '.join(' '.join(coords[j:j+2]) for j in range(0,len(coords),2))+' Z';doc['shape'][i]='~'.join(a)
batch.THERMAL_VIA_PADS=set()  # 本次不在芯片/器件焊盘内增加孔。
for vid in ['ggeUSB0928V300','ggeUSB0928V308','ggeUSB0928V310']:
    v=next(v for v in routes(doc)[1] if v['id']==vid);target=batch.center(v)
    xs,ys,free,vf=batch.obstacles(doc,c,h,'GND',.1,.25,.15,target)
    X,Y=np.meshgrid(xs,ys);dd=np.hypot(X-target[0],Y-target[1])
    iy,ix=np.where(vf & (dd<1.8))
    candidates=sorted(zip(iy,ix),key=lambda a:dd[a])
    rejected={'网格合法候选':len(candidates),'钻边':0,'地铜覆盖':0,'铜间距':0};available=[]
    chosen=None
    for y,x in candidates:
        q=(float(xs[x]),float(ys[y]))
        if any(distance([q],a['poly'])-.075<.1 for a in c if a.get('kind')=='pad' and a['layer'] in ('1','2')):rejected['钻边']+=1;continue
        available.append(q)
        ring=[(q[0]+.11*math.cos(a),q[1]+.11*math.sin(a)) for a in np.linspace(0,2*math.pi,24,endpoint=False)]
        # L2 仍要求原生铜全覆盖；L3 属于扩大后的范围，必须原生重建核对才能接纳。
        if not np.all(np.logical_or.reduce([contains(r,ring) for l,r in rs if l=='21'])) or not np.all(PlotPath(expanded).contains_points(ring)):
            rejected['地铜覆盖']+=1;continue
        trial=copy.deepcopy(doc);batch.add_via(trial,'GND',q,.25,.15)
        bad=batch.check_new(trial,c,h,trial['shape'][len(doc['shape']):])
        if bad:rejected['铜间距']+=1;continue
        chosen=q;doc=trial;break
    log.append({'目标信号孔':vid,'新增地孔':chosen,'距离_mm':math.dist(target,chosen) if chosen else None})
    print(log[-1],rejected,'可布孔坐标示例',available[:5],flush=True)
assert not batch.check_new(doc,c,h,doc['shape'][start_size:])
out=Path('/Users/liuchunyu/Downloads/PCBUSBstitchTrial20260929.json')
for i,s in enumerate(doc['shape']):
    if s.startswith('COPPERAREA~'):
        a=s.split('~');a[10]='';doc['shape'][i]='~'.join(a)
out.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
out.with_suffix('.report.json').write_text(json.dumps({'来源':str(src),'来源SHA256':hashlib.sha256(src.read_bytes()).hexdigest(),'日志':log,'原生复查':False,'云端保存':False},ensure_ascii=False,indent=2)+'\n')
print('候选',out,'新增孔数',len(doc['shape'])-start_size,flush=True)
