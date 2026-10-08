"""细分真实 USB 参考面采样；过孔避空分类不是信号完整性豁免。"""
from audit_clone_native_ground_20260929 import *
from collections import Counter
from check_pcb_a5 import ROOT

def audit(src, output=None):
    d,p,c,h=parse(src); ts,vs,_=routes(d); rs=regions(d)
    usb=[v for v in vs if v['net'].startswith('USB_D')]
    grounds=[v for v in vs if v['net']=='GND']
    # LIB 内的 PICO 通孔也计入候选，但必须同时接入两个参考面的真实铜。
    for a in c:
        if a['layer']=='11' and a['net']=='GND':grounds.append(dict(a,id=a['ref']+'.'+a['pin']))
    def covered(layer,pts):
        ok=np.zeros(len(pts),bool)
        for l,r in rs:
            if l==layer:ok|=contains(r,pts)
        return ok
    via_geometry=[(v,batch.center(v),max(math.dist(z,batch.center(v)) for z in v['poly'])) for v in vs]
    def cause(q):
        near=sorted((math.dist(q,center),v['id'],v,radius) for v,center,radius in via_geometry)
        for dist,vid,v,radius in near:
            if v['net']!='GND' and dist<radius+.201:
                return ('USB信号孔避空' if v in usb else '其他网络孔附近',vid)
        for hole in h:
            if distance([q],hole['poly'])<.201:return ('机械孔附近',hole['ref'])
        return ('未解释缺铜','')
    report={'来源':str(src),'SHA256':hashlib.sha256(src.read_bytes()).hexdigest(),
            '说明':'全路径采样，不跳过换层附近；0.2mm来自原生内层铺铜间距。避空归因不是验收；中心线及3h邻域分开统计。',
            'USB参考地验收':False,'网络':{},'换层回流':[]}
    for net in sorted({t['net'] for t in ts if t['net'].startswith('USB_D')}):
        data={}
        for layer in ['1','2']:
            rp='21' if layer=='1' else '22'; pts=[];kind=[]
            for t in ts:
                if (t['net'],t['layer'])!=(net,layer):continue
                for a,b in zip(t['points'],t['points'][1:]):
                    for f in np.linspace(0,1,max(2,math.ceil(math.dist(a,b)/.02))):
                        q=(a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1]))
                        pts.append(q);kind.append('中心线')
                        for radius in [t['width']/2,t['width']/2+.1491,t['width']/2+.2982]:
                            for angle in np.linspace(0,2*math.pi,24,endpoint=False):
                                pts.append((q[0]+radius*math.cos(angle),q[1]+radius*math.sin(angle)));kind.append('邻域')
            ok=covered(rp,pts);counts=Counter();examples={}
            for i in np.flatnonzero(~ok):
                cat,obj=cause(pts[i]); key=kind[i]+'/'+cat
                counts[key]+=1
                if len(examples.setdefault(key,[]))<5:examples[key].append({'坐标':pts[i],'邻近对象':obj})
            data[rp]={'总采样':len(pts),'缺铜分类':dict(counts),'示例':examples}
        report['网络'][net]=data
    for v in usb:
        choices=[]
        for g in grounds:
            center=batch.center(g)
            # 不靠孔中心是否填铜判定：孔中心可能是制造钻孔，采样铜环。
            rad=max(math.dist(z,center) for z in g['poly'])*.85
            ring=[(center[0]+rad*math.cos(a),center[1]+rad*math.sin(a)) for a in np.linspace(0,2*math.pi,16,endpoint=False)]
            if not all(np.any(covered(l,ring)) for l in ['21','22']):continue
            choices.append((math.dist(batch.center(v),center),g['id'],center))
        report['换层回流'].append({'信号孔':v['id'],'网络':v['net'],'坐标':batch.center(v),'最近同时接L2L3地孔':sorted(choices)[:2]})
    out=Path(output) if output else ROOT/'easyeda_std/克隆板USB换层回流细查_20260929.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    for n,x in report['网络'].items():print(n,{l:z['缺铜分类'] for l,z in x.items()})
    print(json.dumps(report['换层回流'],ensure_ascii=False,indent=2));return report

if __name__=='__main__':audit(Path(sys.argv[1]), sys.argv[2] if len(sys.argv)>2 else None)
