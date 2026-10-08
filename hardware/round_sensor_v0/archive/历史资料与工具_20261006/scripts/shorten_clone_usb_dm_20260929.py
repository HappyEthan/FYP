"""局部缩短 USB D- 插座短接与下孔路径；失败试排不改当前候选。"""
from pathlib import Path
from refine_clone_usb_20260928 import *
from repair_clone_inner_layer_20260928 import path_text
from check_pcb_a5 import U,xy

src=Path('/Users/liuchunyu/Downloads/PCBUSBnativeI20260929.json')
assert hashlib.sha256(src.read_bytes()).hexdigest()=='b1b25a52608797553aa1cd16d67085820bb0a9cc74903496b8f03ac3788a395b'
configure();doc,p,c,h=parse(src);tracks={t['id']:t for t in routes(doc)[0]}
foreign_vias=[v for v in routes(doc)[1]+[a for a in c if a['kind']=='via'] if v['net']!='GND' and not v['net'].startswith('USB_D')]
ids={'ggeUSB0928T312','ggeUSB0928T313','ggeUSB0928T315','ggeUSB0928V314'}
base=copy.deepcopy(doc)
base['shape']=[s for s in base['shape'] if not ((s.startswith('TRACK~') and s.split('~')[5] in ids) or (s.startswith('VIA~') and s.split('~')[6] in ids))]
left=tracks['ggeUSB0928T312']['points'][-1];right=tracks['ggeUSB0928T312']['points'][0]
esd=tracks['ggeUSB0928T315']['points'][-1];w=tracks['ggeUSB0928T312']['width']
solutions=[];reasons={};tested=0
# J/K 的相邻信号孔避空合并留下中心线缺铜。L 将 D- 孔移至左侧，
# 预留两孔避空之间约 0.26mm 铜颈；这只是候选筛选，仍须原生重铺铜。
own_other_vias=[v for v in routes(doc)[1] if v['net'].startswith('USB_D') and v['id']!='ggeUSB0928V314']
for yy in [-75.54,-75.46,-75.38,-75.30]:
    for xx in np.arange(21.66,22.24,.02):
        tested+=1;trial=copy.deepcopy(base);q=(float(xx),yy+.40)
        if any(math.dist(q,batch.center(v)) < .91 for v in own_other_vias):continue
        if any(distance([q],a['poly'])-.075<.1 for a in c if a.get('kind')=='pad' and a['layer'] in ('1','2')):continue
        ttop=[left,(left[0],yy),(right[0],yy),right]
        stem=[(left[0],yy),q]
        tbot=[esd,(esd[0],q[1]-abs(xx-esd[0])),q]
        # 缩短路径不能侵入原先完整的参考地走廊；与独立审核使用同一3h门限。
        tb={'points':tbot,'width':w}
        if any(track_gap(tb,v['poly'])<.2982+batch.clearance(doc,v['net'],'GND')-1e-5 for v in foreign_vias):
            reasons['非USB过孔侵入参考地走廊']=reasons.get('非USB过孔侵入参考地走廊',0)+1
            continue
        shapes=[f'TRACK~{w/U:.8f}~1~USB_DM~{path_text(ttop)}~ggeUSB0928T312~0',
                f'TRACK~{w/U:.8f}~1~USB_DM~{path_text(stem)}~ggeUSB0928T313~0',
                f'TRACK~{w/U:.8f}~2~USB_DM~{path_text(tbot)}~ggeUSB0928T315~0',
                f'VIA~{path_text([q]).replace(" ","~")}~{.25/U:.8f}~USB_DM~{.075/U:.8f}~ggeUSB0928V314~0']
        trial['shape']+=shapes
        bad=batch.check_new(trial,c,h,shapes)
        if bad:
            k=str(bad[0]);reasons[k]=reasons.get(k,0)+1;continue
        if old_losses(doc,c,trial,c,'USB_DM'):continue
        # 从U6中心至插座两脚的几何路径；主控至U6不变。
        bot=sum(math.dist(a,b) for a,b in zip(tbot,tbot[1:]))+.8
        lens=[bot+math.dist(stem[0],q)+abs(left[0]-pin[0])+abs(pin[1]-yy) for pin in [left,right]]
        oldbot=sum(math.dist(a,b) for a,b in zip(tracks['ggeUSB0928T315']['points'],tracks['ggeUSB0928T315']['points'][1:]))+.8
        oldstem=sum(math.dist(a,b) for a,b in zip(tracks['ggeUSB0928T313']['points'],tracks['ggeUSB0928T313']['points'][1:]))
        oldleft=oldbot+oldstem+abs(left[1]-tracks['ggeUSB0928T312']['points'][-2][1])
        oldright=oldleft+abs(right[0]-left[0])
        # 左脚B7，右脚A7；评分只比较最大长度差，不增加D+蛇形线。
        signed=[1.3815131908-(oldleft-lens[0]),3.3815599911-(oldright-lens[1])]
        score=max(map(abs,signed))
        solutions.append((score,trial,{'过孔坐标':q,'短接线Y':yy,'B_A方向预计长度差_mm':signed,'减少走线图元':0,'过孔数量不变':True}))
print('tested',tested,'solutions',len(solutions),'first_failures',list(reasons.items())[:8],flush=True)
assert solutions,'无局部候选通过；原板未改动'
_,best,meta=min(solutions,key=lambda x:x[0])
for i,s in enumerate(best['shape']):
    if s.startswith('COPPERAREA~'):
        a=s.split('~');a[10]='';best['shape'][i]='~'.join(a)
out=Path('/Users/liuchunyu/Downloads/PCBUSBshortDMLTrial20260929.json')
out.write_text(json.dumps(best,ensure_ascii=False,indent=2)+'\n')
meta.update({'来源SHA256':hashlib.sha256(src.read_bytes()).hexdigest(),'源候选SHA256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'原生复查':False})
out.with_suffix('.report.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(meta,ensure_ascii=False,indent=2),flush=True)
print(json.dumps([s for s in best['shape'] if any(i in s for i in ids)],ensure_ascii=False))
