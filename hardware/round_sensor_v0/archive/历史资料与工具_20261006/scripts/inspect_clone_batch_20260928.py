"""补线候选分层目视图，不代替原生检查。"""
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.rcParams['font.family']=['Arial Unicode MS','sans-serif']
plt.rcParams['axes.unicode_minus']=False
from matplotlib.patches import Polygon,Circle
from check_pcb_a5 import parse,ROOT,xy,U
from audit_a5_routed_snapshot import routes
from repair_clone_batch_20260928 import OUT,SOURCE,PREFIX

def render(src=OUT):
    d,parts,c,h=parse(src);ts,vs,_=routes(d)
    fig,axes=plt.subplots(1,3,figsize=(21,12))
    colors={'GND':'#999999','USB_DP':'#169350','USB_DM':'#0d60bd','USB_DP_SOC':'#e87500','USB_DM_SOC':'#9929ca','3V3':'#cc2727','USB_5V':'#cc2727'}
    for ax,layer in zip(axes,('1','2','22')):
        ax.set_aspect('equal');ax.set_xlim(14,32.5);ax.set_ylim(-89,-70);ax.invert_yaxis();ax.grid(alpha=.15);ax.set_title({'1':'顶层','2':'底层（从顶面透视）','22':'第三层：内层布线'}[layer])
        for p in c:
            if p['layer'] not in (layer,'11'):continue
            ax.add_patch(Polygon(p['poly'],color=colors.get(p['net'],'#aaaacc'),alpha=.55))
            if p['net'].startswith('USB_'):ax.text(*center(p),p['ref']+'.'+p['pin'],fontsize=5)
        for t in ts:
            if t['layer']==layer:ax.plot(*zip(*t['points']),color=colors.get(t['net'],'#8888aa'),lw=1.4 if PREFIX in t['id'] else .6)
        for v in vs:ax.add_patch(Polygon(v['poly'],color=colors.get(v['net'],'#8888aa'),alpha=.75))
        for p in h:ax.add_patch(Polygon(p['poly'],color='black',alpha=.8))
        for ref,p in parts.items():
            if p['layer']==layer:ax.text(*p['center'],ref,fontsize=7,color='#111111')
        circle=next(s.split('~') for s in d['shape'] if s.startswith('CIRCLE~'))
        ax.add_patch(Circle(xy(circle[1],circle[2]),float(circle[3])*U,fill=False,color='purple'))
    fig.tight_layout();fig.savefig(ROOT/'easyeda_std/克隆板批量补线分层预检_20260928.png',dpi=160);plt.close(fig)

def center(p):return tuple((min(q[k] for q in p['poly'])+max(q[k] for q in p['poly']))/2 for k in (0,1))
if __name__=='__main__':render(SOURCE if '--source' in sys.argv else OUT)
