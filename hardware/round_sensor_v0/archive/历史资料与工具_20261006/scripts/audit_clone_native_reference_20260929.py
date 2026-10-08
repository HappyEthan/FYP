"""原生真实铜面对 RF/USB 的参考地采样，换层过渡区单列，不以声明铺铜验收。"""
from pathlib import Path
from audit_clone_native_ground_20260929 import *

def audit(path):
    d,p,c,h=parse(path);ts,vs,_=routes(d);rs=regions(d);report={}
    for net in ['RF_SOC','R30_2','USB_DM_SOC','USB_DP_SOC','USB_DM','USB_DP']:
        pts_by_layer={};transition=0
        ownvias=[v for v in vs if v['net'] in ('USB_DM_SOC','USB_DP_SOC','USB_DM','USB_DP')]
        sp=PlotPath(next(p['poly'] for p in c if p['ref']=='ANT1' and p['pin']=='1'))
        for t in ts:
            if t['net']!=net:continue
            layer='21' if t['layer']=='1' else '22';points=pts_by_layer.setdefault(layer,[])
            r=t['width']/2+.2982
            for a,b in zip(t['points'],t['points'][1:]):
                for f in np.linspace(0,1,max(2,math.ceil(math.dist(a,b)/.02))):
                    q=(a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1]))
                    if net=='R30_2' and sp.contains_point(q):continue
                    if net.startswith('USB_') and any(math.dist(q,batch.center(v))<.7 for v in ownvias):transition+=1;continue
                    points.append(q);points += [(q[0]+r*math.cos(a),q[1]+r*math.sin(a)) for a in np.linspace(0,2*math.pi,24,endpoint=False)]
        result={}
        for layer,pts in pts_by_layer.items():
            ok=np.zeros(len(pts),bool)
            for l,rings in rs:
                if l==layer:ok|=contains(rings,pts)
            result[layer]={'采样数':len(pts),'缺铜数':int(np.sum(~ok)),'缺铜示例_mm':np.array(pts)[~ok][:10].tolist()}
        report[net]={'参考面':result,'换层附近待单独核验的中心采样数':transition}
    print(json.dumps(report,ensure_ascii=False,indent=2));return report

if __name__=='__main__':audit(Path(sys.argv[1]))
