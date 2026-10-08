"""USB 局部实铜俯视图；底层为透视而非翻板视图，不代替原生 DRC。"""
import sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from check_pcb_a5 import ROOT, parse
from audit_a5_routed_snapshot import routes

plt.rcParams['font.family']=['Arial Unicode MS','sans-serif']
plt.rcParams['axes.unicode_minus']=False

def render(src, out, bounds=(18.7,26.4,-81.2,-75.5)):
    d,parts,c,h=parse(src)
    ts,vs,_=routes(d)
    fig,axs=plt.subplots(1,3,figsize=(21,10))
    colors={'GND':'#999999','USB_DP':'#149043','USB_DM':'#1d6fde',
            'USB_DP_SOC':'#f18c12','USB_DM_SOC':'#a126c1','3V3':'#ca4242','USB_5V':'#b72d33'}
    for ax,layer in zip(axs,('1','2','22')):
        xmin,xmax,ymin,ymax=bounds
        ax.set_aspect('equal');ax.set_xlim(xmin,xmax);ax.set_ylim(ymin,ymax);ax.invert_yaxis()
        ax.grid(alpha=.2);ax.set_title({'1':'顶层','2':'底层（顶面透视）','22':'第三层'}[layer])
        for p in c:
            if p['layer'] not in (layer,'11'):continue
            ax.add_patch(Polygon(p['poly'],color=colors.get(p['net'],'#818bad'),alpha=.6))
            x,y=tuple((min(q[k] for q in p['poly'])+max(q[k] for q in p['poly']))/2 for k in (0,1))
            if xmin<x<xmax and ymin<y<ymax:ax.text(x,y,p['ref']+'.'+p['pin'],fontsize=5,ha='center')
        for t in ts:
            if t['layer']!=layer:continue
            # Data-coordinate width represented by a real buffered line polygon.
            for a,b in zip(t['points'],t['points'][1:]):
                import math
                length=math.dist(a,b)
                if not length:continue
                dx,dy=(b[0]-a[0])/length*t['width']/2,(b[1]-a[1])/length*t['width']/2
                ax.add_patch(Polygon([(a[0]-dy,a[1]+dx),(b[0]-dy,b[1]+dx),(b[0]+dy,b[1]-dx),(a[0]+dy,a[1]-dx)],color=colors.get(t['net'],'#767fac'),alpha=.7))
        for v in vs:ax.add_patch(Polygon(v['poly'],color=colors.get(v['net'],'#808bb6'),alpha=.7))
        for p in h:ax.add_patch(Polygon(p['poly'],color='black',alpha=.8))
        for ref,p in parts.items():
            x,y=p['center']
            if p['layer']==layer and xmin<x<xmax and ymin<y<ymax:ax.text(x,y-.23,ref,fontsize=9,fontweight='bold')
    fig.tight_layout();fig.savefig(out,dpi=160);plt.close(fig)

if __name__=='__main__':
    src=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'easyeda_std/PCB_克隆板批量补线_原生回读_20260928.json'
    out=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/'easyeda_std/克隆板USB局部预检_20260928.png'
    render(src,out)
