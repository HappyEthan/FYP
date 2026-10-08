"""细查旧分类未解释缺铜的位置；只定位，不放宽验收或改变PCB。"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import numpy as np
from audit_clone_native_ground_20260929 import parse, routes, regions, contains, batch, distance

root=Path(__file__).resolve().parents[1]
src=root/'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'
d,p,c,h=parse(src);ts,vs,_=routes(d);rs=regions(d)
vg=[(v,batch.center(v),max(math.dist(z,batch.center(v)) for z in v['poly'])) for v in vs]
out={'来源':str(src),'SHA256':hashlib.sha256(src.read_bytes()).hexdigest(),
     '说明':'全路径0.02mm与三圈24方位采样；沿用原分类阈值0.201mm，不重命名或豁免缺口。距离是定位线索，不是信号完整性验收。',
     '网络':{},'USB已验收':False}
for net in sorted({t['net'] for t in ts if t['net'].startswith('USB_D')}):
    out['网络'][net]={}
    for layer in ['1','2']:
        rp='21' if layer=='1' else '22';points=[];kinds=[]
        for t in ts:
            if (t['net'],t['layer'])!=(net,layer):continue
            for a,b in zip(t['points'],t['points'][1:]):
                for f in np.linspace(0,1,max(2,math.ceil(math.dist(a,b)/.02))):
                    q=(a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1]))
                    points.append(q);kinds.append('中心线')
                    for radius in [t['width']/2,t['width']/2+.1491,t['width']/2+.2982]:
                        for angle in np.linspace(0,2*math.pi,24,endpoint=False):
                            points.append((q[0]+radius*math.cos(angle),q[1]+radius*math.sin(angle)));kinds.append('邻域')
        ok=np.zeros(len(points),bool)
        for l,rings in rs:
            if l==rp:ok|=contains(rings,points)
        unknown=[];hist=Counter()
        for i in np.flatnonzero(~ok):
            q=points[i]
            if any(v['net']!='GND' and math.dist(q,center)<radius+.201 for v,center,radius in vg):continue
            if any(distance([q],hole['poly'])<.201 for hole in h):continue
            nearest=min((math.dist(q,center),v['id'],v['net']) for v,center,radius in vg if v['net']!='GND')
            hist[nearest[1]]+=1
            unknown.append({'坐标':q,'类型':kinds[i],'最近非地孔':nearest})
        out['网络'][net][rp]={'未解释缺铜数':len(unknown),'邻近孔分布':dict(hist),
            '距最近非地孔最大_mm':max((x['最近非地孔'][0] for x in unknown),default=0),'采样':unknown}
dest=root/'easyeda_std/克隆板USB剩余参考地定位_20260929.json'
dest.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
for net,layers in out['网络'].items():
    for layer,x in layers.items():print(net,layer,{k:v for k,v in x.items() if k!='采样'})
