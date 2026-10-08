#!/usr/bin/env python3
"""Local Gerber visual review; raster preserves ordered dark/clear primitives.

Read-only bounded parser. Not a substitute for a factory CAM/DFM tool.
"""
import argparse
import math
from pathlib import Path
import zipfile
from PIL import Image, ImageDraw, ImageChops
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import fontManager
from audit_current_cam import layer
from audit_clone_connector_s_20260929 import drill


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--gerber',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True)
    a=ap.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
    fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf');plt.rcParams['font.family']='Arial Unicode MS'
    n=2200;lo=(12.5,-90);span=21
    def pt(p):return ((p[0]-lo[0])/span*n,(p[1]-lo[1])/span*n)
    def drawshape(im,s,fill):
        pen=ImageDraw.Draw(im)
        if 'rings' in s:
            mask=Image.new('1',im.size)
            for ring in s['rings']:
                one=Image.new('1',im.size);ImageDraw.Draw(one).polygon([pt(v) for v in ring],fill=1)
                mask=ImageChops.logical_xor(mask,one)
            im.paste(fill,(0,0),mask);return
        width=max(1,round(s['radius']*2/span*n))
        if 'arc' in s:
            c=s['center'];p,q=s['a'],s['b'];r=math.dist(c,p)
            start=math.atan2(p[1]-c[1],p[0]-c[0]);end=math.atan2(q[1]-c[1],q[0]-c[0])
            delta=(end-start)%(2*math.pi)
            if not s['clockwise_source_y_down']:delta=delta-2*math.pi
            points=[pt((c[0]+r*math.cos(start+delta*i/360),c[1]+r*math.sin(start+delta*i/360))) for i in range(361)]
            pen.line(points,fill=fill,width=width,joint='curve')
        else:
            p,q=pt(s['a']),pt(s['b']);pen.line([p,q],fill=fill,width=width)
            r=width/2
            for x,y in (p,q):pen.ellipse((x-r,y-r,x+r,y+r),fill=fill)
    names=[['Gerber_TopLayer.GTL','Gerber_InnerLayer1.G1','Gerber_InnerLayer2.G2','Gerber_BottomLayer.GBL'],
           ['Gerber_TopSolderMaskLayer.GTS','Gerber_BottomSolderMaskLayer.GBS','Gerber_TopPasteMaskLayer.GTP','Gerber_BottomPasteMaskLayer.GBP'],
           ['Gerber_TopSilkscreenLayer.GTO','Gerber_BottomSilkscreenLayer.GBO','Gerber_BoardOutlineLayer.GKO','Gerber_DocumentLayer.GDL']]
    # Verify actual exporter names instead of silently dropping a missing layer.
    with zipfile.ZipFile(a.gerber) as z:
        allnames=z.namelist();print(allnames)
        for group in names:
            for name in group:assert name in allnames,name
        parsed={name:layer(z.read(name).decode()) for group in names for name in group}
        holes=drill(z.read('Drill_PTH_Through.DRL').decode())+drill(z.read('Drill_NPTH_Through.DRL').decode())
    with PdfPages(out/'Gerber全层视觉核对_仅审核.pdf') as pdf:
        for i,group in enumerate(names):
            fig,axes=plt.subplots(2,2,figsize=(11.7,12.5))
            fig.suptitle('Gerber 全层视觉核对｜仅审核',fontsize=17,y=.97)
            for ax,name in zip(axes.flat,group):
                im=Image.new('RGB',(n,n),'white')
                for s in parsed[name]:drawshape(im,s,'white' if s['clear'] else '#284b55')
                # Actual finished hole/slot centres, independently parsed drill set.
                for h in holes:drawshape(im,{'a':h['a'],'b':h['b'],'radius':h['diameter']/2},'#edbbb4')
                # Use the actual parsed outline without an approximate aid circle.
                for s in parsed['Gerber_BoardOutlineLayer.GKO']:drawshape(im,s,'#be7222')
                ax.imshow(im);ax.set_title(name,fontsize=10,pad=8);ax.axis('off')
            fig.text(.5,.046,'所有层均为顶视投影，底层未镜像；粉色为钻孔/槽，橙色为实际板框。',ha='center',fontsize=10)
            fig.text(.5,.025,'几何差异由独立解析核对；此图检查输出层内容、开窗及明显缺项，不代替工厂公差与DFM。',ha='center',fontsize=9)
            fig.subplots_adjust(top=.92,bottom=.08,wspace=.08,hspace=.12);pdf.savefig(fig);fig.savefig(out/f'Gerber视觉核对_{i+1}.png',dpi=140);plt.close(fig)
    print(f'rendered 12 layers + {len(holes)} hole/slot overlays')


if __name__=='__main__':main()
