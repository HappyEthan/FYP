"""独立显示新增RF及相邻迁线，供目视复核；不修改PCB。"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Circle
from check_pcb_a5 import parse, ROOT, xy, U
from audit_a5_routed_snapshot import routes
from repair_clone_rf_20260928 import OUT, PREFIX

def render():
    d,parts,c,h=parse(OUT);tracks,vias,_=routes(d)
    fig,axes=plt.subplots(1,2,figsize=(16,9))
    colors={'RF_SOC':'#d32f2f','R30_2':'#d32f2f','3V3':'#d48a00','GND':'#149161','I2C_SDA':'#2467df'}
    for ax,layer in zip(axes,('1','22')):
        ax.set_aspect('equal');ax.set_xlim(16,32);ax.set_ylim(-88,-78.7);ax.invert_yaxis();ax.grid(alpha=.15)
        ax.set_title('L1 top' if layer=='1' else 'L3 inner routing')
        for p in c:
            if p['layer'] not in (layer,'11'):continue
            ax.add_patch(Polygon(p['poly'],color=colors.get(p['net'],'#999999'),alpha=.4))
        for t in tracks:
            if t['layer']!=layer:continue
            new=t['id'].startswith(PREFIX)
            ax.plot(*zip(*t['points']),color=colors.get(t['net'],'#999999'),lw=1.8 if new else .7,alpha=1 if new else .45)
        for v in vias:
            ax.add_patch(Polygon(v['poly'],color=colors.get(v['net'],'#999999'),alpha=.9))
        circle=next(s.split('~') for s in d['shape'] if s.startswith('CIRCLE~'))
        ax.add_patch(Circle(xy(circle[1],circle[2]),float(circle[3])*U,fill=False,color='purple'))
        if layer=='1':
            for ref in ('C20','C21','C30','C31','R30','U1','ANT1'):
                ax.text(*parts[ref]['center'],ref,fontsize=9)
    fig.tight_layout();fig.savefig(ROOT/'easyeda_std/克隆板射频迁线预检_20260928.png',dpi=150);plt.close(fig)

if __name__=='__main__':render()
