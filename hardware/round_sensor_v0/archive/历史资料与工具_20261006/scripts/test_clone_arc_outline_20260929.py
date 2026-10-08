"""原圆框等几何改成四圆弧，仅用于核验原生圆框 DRC，不更改直径/铜。"""
import argparse,json,math,hashlib
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--line-width-mm',type=float);a=p.parse_args()
d=json.loads(a.source.read_text());circles=[s for s in d['shape'] if s.startswith('CIRCLE~') and s.split('~')[5]=='10'];assert len(circles)==1
v=circles[0].split('~');x,y,r=map(float,v[1:4]);arcs=[]
pts=[(x+r,y),(x,y+r),(x-r,y),(x,y-r),(x+r,y)]
for i,(start,end) in enumerate(zip(pts,pts[1:])):
    arcs.append(f'ARC~{v[4]}~10~~M {start[0]:8f} {start[1]:8f} A {r:.8f} {r:.8f} 0 0 1 {end[0]:.8f} {end[1]:.8f}~~ggeOUTLINE0929Q{i}~0')
if a.line_width_mm is not None:
    assert 0<a.line_width_mm<=.254
    v[4]=str(a.line_width_mm/.254)
    d['shape']=[('~'.join(v) if s==circles[0] else s) for s in d['shape']]
else:
    d['shape']=[s for s in d['shape'] if s!=circles[0]]+arcs
a.output.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'输入SHA':hashlib.sha256(a.source.read_bytes()).hexdigest(),'输出':str(a.output),'圆心原生单位':[x,y],'半径原生单位':r,'仅圆框表达改变':True,'原生验收':False},ensure_ascii=False))
