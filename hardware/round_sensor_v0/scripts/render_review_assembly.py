#!/usr/bin/env python3
"""Render actual pad positions and pin anchors, never a machine coordinate generator."""
import argparse
from datetime import date
from collections import Counter
import hashlib
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Circle
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties, fontManager
from check_pcb_a5 import parse, xy


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pcb',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--date',default=date.today().strftime('%Y%m%d'))
    a=ap.parse_args();d,parts,pads,_=parse(a.pcb)
    out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
    font_path='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
    fontManager.addfont(font_path)
    font=FontProperties(fname=font_path)
    plt.rcParams['font.family']=font.get_name()
    plt.rcParams['axes.unicode_minus']=False
    center=xy(4110.551,3092.977);cx,cy=center[0],-center[1]
    excluded={'C30','C31','J2','J4','SW1'}
    smt=Counter(p['layer'] for ref,p in parts.items() if ref not in excluded)
    def pos(p,side):return ((2*cx-p[0]) if side=='2' else p[0],-p[1])
    def drawpad(ax,p,side):
        color='#b78c32' if p['ref'] not in excluded else '#c6cad0'
        ax.add_patch(Polygon([pos(q,side) for q in p['poly']],facecolor=color,edgecolor='#575d63',linewidth=.35,zorder=2))
    def base(ax):
        ax.set_aspect('equal');ax.set_facecolor('#fafbfd');ax.tick_params(labelsize=8)
        ax.grid(alpha=.18);ax.set_xlabel('X / mm',fontsize=9);ax.set_ylabel('Y / mm',fontsize=9)
    def mark(ax,p,side,labels=False):
        if p['pin'] in {'1','A1'}:
            v=parts[p['ref']]['items'];raw=next(x for x in v if x[0]=='PAD' and x[8]==p['pin'])
            x,y=pos(xy(raw[2],raw[3]),side)
            ax.plot(x,y,'o',color='#bd252c',markersize=3,zorder=5)
            if labels:ax.text(x,y,p['pin'],fontsize=8,ha='center',va='center',color='#8e151c',bbox=dict(facecolor='white',edgecolor='none',alpha=.8,pad=.7),zorder=6)
    digest=hashlib.sha256(a.pcb.read_bytes()).hexdigest()
    pdf=out/f'装配定位与关键脚向_仅审核_{a.date}.pdf'
    with PdfPages(pdf) as book:
        fig,axes=plt.subplots(1,2,figsize=(14,8))
        fig.suptitle('圆形传感板｜装配定位（仅审核）',fontsize=18,y=.97)
        for ax,side in zip(axes,('1','2')):
            base(ax);ax.add_patch(Circle((cx,cy),9,facecolor='#edf4ef',edgecolor='#425b4d',linewidth=1.2,zorder=0))
            for p in pads:
                if p['kind']=='pad' and (parts[p['ref']]['layer']==side or p['layer']=='11'):
                    drawpad(ax,p,side);mark(ax,p,side)
            for ref,p in parts.items():
                if p['layer']!=side:continue
                x,y=pos(p['center'],side)
                label=ref+(' 不装' if ref in {'C30','C31'} else '')
                ax.text(x,y,label,ha='center',va='center',fontsize=7.5,color='#16324a',bbox=dict(facecolor='white',alpha=.92,edgecolor='none',pad=.8),zorder=8)
            ax.set_xlim(cx-10.5,cx+10.5);ax.set_ylim(cy-10.7,cy+10.7)
            ax.set_title('顶面：从元件面看' if side=='1' else '底面：翻板后从元件面看（本图左右镜像）',fontsize=11,pad=12)
            if side=='2':ax.set_xlabel('图示 X（底面镜像）/ mm',fontsize=9)
        fig.text(.5,.075,'红点＝1脚/A1；灰色＝DNP或手焊焊盘。只画实际铜焊盘和位号，未用近似3D外壳替代封装。',ha='center',fontsize=10)
        fig.text(.5,.047,'CPL保留原生坐标约定、不镜像底层；本图的底面镜像仅便于装配观察。USB开口在两图下方。',ha='center',fontsize=10)
        fig.text(.5,.018,'源 SHA256 '+digest[:24]+f'…；{sum(smt.values())}件SMT（顶{smt["1"]}/底{smt["2"]}）；保存重开源，工厂机器库及工艺待确认。',ha='center',fontsize=8,color='#666')
        fig.subplots_adjust(top=.88,bottom=.15,wspace=.2);book.savefig(fig);fig.savefig(out/'装配定位_仅审核.png',dpi=150);plt.close(fig)
        refs=[r for r in ['U1','U2','U3','U4','U5','U6','Q1','D4','ANT1','SW2','SW3','J4','J2'] if r in parts][:12]
        fig,axes=plt.subplots(3,4,figsize=(14,12))
        fig.suptitle('关键脚向｜均从该器件所在元件面观察（仅审核）',fontsize=17,y=.98)
        for ax,ref in zip(axes.flat,refs):
            p=parts[ref];side=p['layer'];items=[q for q in pads if q['ref']==ref and q['kind']=='pad'];base(ax)
            for q in items:
                drawpad(ax,q,side)
                raw=next(v for v in p['items'] if v[0]=='PAD' and v[8]==q['pin'])
                x,y=pos(xy(raw[2],raw[3]),side)
                # U1 has 56 peripheral pads: show quadrant anchors instead of unreadable text.
                if ref!='U1' or q['pin'] in {'1','14','15','28','29','42','43','56','57'}:
                    ax.text(x,y,q['pin'],fontsize=7 if ref=='U1' else 8,ha='center',va='center',color='#142c44',zorder=7)
                if q['pin'] in {'1','A1'}:
                    ax.plot(x,y,'o',ms=10,markerfacecolor='none',markeredgecolor='#bb202a',zorder=6)
            pts=[pos(v,side) for q in items for v in q['poly']];xs,ys=zip(*pts)
            margin=max(.25,.18*max(max(xs)-min(xs),max(ys)-min(ys)))
            ax.set_xlim(min(xs)-margin,max(xs)+margin);ax.set_ylim(min(ys)-margin,max(ys)+margin)
            ax.set_title(ref+(' 顶面' if side=='1' else ' 底面'),fontsize=11);ax.tick_params(labelsize=6)
            if side=='2':ax.set_xlabel('图示 X（底面镜像）/ mm',fontsize=8)
        fig.text(.5,.035,'红圈＝工程1脚/A1位置。Q1工程脚号1/2/3＝D/G/S；原厂以D/G/S标注。J4＝1/3V3、2/GND、3/SDA、4/SCL。',ha='center',fontsize=9)
        fig.text(.5,.015,'角度以原生CPL及此脚向双重核对；工厂按其料带/机器库换算，不能直接用3D模型角度。',ha='center',fontsize=9)
        fig.subplots_adjust(top=.93,bottom=.09,hspace=.55,wspace=.42);book.savefig(fig);fig.savefig(out/'关键脚向_仅审核.png',dpi=150);plt.close(fig)
    print(pdf)


if __name__=='__main__':main()
