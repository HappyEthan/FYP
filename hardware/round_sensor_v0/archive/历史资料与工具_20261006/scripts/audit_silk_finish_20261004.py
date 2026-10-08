"""Read-only comparison of native manufacturing-finish output with adopted button output."""
from pathlib import Path
import sys, json, ast, math, zipfile, hashlib
from collections import Counter
R=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(R/'scripts'),'/tmp/round-pcb-audit-libs']
from check_pcb_a5 import parse
from audit_current_cam import layer
from shapely.geometry import Polygon, Point, LineString, GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
t=ast.parse((R/'manufacturing/仅审核禁止生产/整板复审_20261004/independent_manufacturing_geometry.py').read_text())
exec(compile(ast.Module(body=[n for n in t.body if isinstance(n,ast.FunctionDef) and n.name in {'geom','merge'}],type_ignores=[]),'<pure geometry helpers>','exec'))
O=R/'manufacturing/仅审核禁止生产/丝印终检_20261004'
P=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else R/'easyeda_std/制造收尾_20261004/PCB_finish_saved_reopened_20261004.json'
G=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else O/'Gerber_制造局部收尾_仅审核_20261004.zip'
B=R/'manufacturing/仅审核禁止生产/同步与制造收尾_20261004/Gerber_制造收尾R2_仅审核_20261004.zip'
def signature(x):return Counter(json.dumps(s,sort_keys=True) for s in x)
result={'status':'REVIEW ONLY; finite native-output delta check, not factory DFM','sha256':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [P,G,B]},'layers':[]}
with zipfile.ZipFile(G) as za,zipfile.ZipFile(B) as zb:
 assert set(za.namelist())==set(zb.namelist())
 layers={}
 for n in za.namelist():
  a=za.read(n);b=zb.read(n)
  if n.startswith('Gerber_'):
   la=layer(a.decode());lb=layer(b.decode());sa=signature(la);sb=signature(lb)
   row={'name':n,'primitives_equal':sa==sb,'added':sum((sa-sb).values()),'removed':sum((sb-sa).values())}
   layers[n]=(la,lb)
   if n not in ['Gerber_TopSilkscreenLayer.GTO','Gerber_BottomSilkscreenLayer.GBO','Gerber_DocumentLayer.GDL']:assert sa==sb,n
   result['layers'].append(row)
  elif n.endswith('.DRL'):
   # Native timestamp/export UUID comments differ; every machine instruction must match in order.
   instructions=lambda raw:[s for s in raw.decode().splitlines() if not s.startswith(';')]
   assert instructions(a)==instructions(b),n
   result['layers'].append({'name':n,'drill_instructions_equal':True})
 gs={n:merge(v[0]) for n,v in layers.items() if 'Mask' in n or 'Silkscreen' in n}
 result['silkscreen']=[]
 for side,ss,ms in [('Top','TO','TS'),('Bottom','BO','BS')]:
  sn=f'Gerber_{side}SilkscreenLayer.G{ss}';mn=f'Gerber_{side}SolderMaskLayer.G{ms}'
  old=merge(layers[sn][1]);new=gs[sn];mask=gs[mn]
  result['silkscreen'].append({'side':side,'overlap_before_mm2':old.intersection(mask).area,'overlap_after_mm2':new.intersection(mask).area,'within_0_15mm_after_mm2':new.intersection(mask.buffer(.15)).area})
 _,parts,pads,_=parse(P)
 result['DNP_and_handwire_paste']=[]
 for p in pads:
  if p['kind']!='pad' or p['ref'] not in {'C30','C31','J2','J4','SW1'}:continue
  side,suf=('Top','TP') if p['layer']=='1' else ('Bottom','BP')
  area=Polygon(p['poly']).intersection(gs[f'Gerber_{side}PasteMaskLayer.G{suf}']).area
  assert area<1e-9,(p['ref'],p['pin'],area)
  result['DNP_and_handwire_paste'].append({'ref':p['ref'],'pin':p['pin'],'paste_overlap_mm2':area})
 assert len(result['DNP_and_handwire_paste'])==13
 result['remaining_silk_pad_overlaps']=[]
 for p in pads:
  if p['kind']!='pad':continue
  for side,suf in ([('Top','TO'),('Bottom','BO')] if p['layer']=='11' else [('Top','TO')] if p['layer']=='1' else [('Bottom','BO')]):
   a=Polygon(p['poly']).intersection(gs[f'Gerber_{side}SilkscreenLayer.G{suf}']).area
   if a>1e-5:result['remaining_silk_pad_overlaps'].append({'ref':p['ref'],'pin':p['pin'],'side':side,'overlap_mm2':a})
(O/'丝印终检输出差异_仅审核.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))

# Review image; no copper or output modifications.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as Patch
fig,axs=plt.subplots(1,2,figsize=(11,6))
for ax,side,ss,ms in [(axs[0],'Top','TO','TS'),(axs[1],'Bottom','BO','BS')]:
 def draw(g,color):
  if g.is_empty:return
  if g.geom_type=='Polygon':
   ax.add_patch(Patch([(x,-y) for x,y in g.exterior.coords],closed=True,color=color,lw=0))
   for ring in g.interiors:ax.add_patch(Patch([(x,-y) for x,y in ring.coords],closed=True,color='white',lw=0))
  elif hasattr(g,'geoms'):
   for q in g.geoms:draw(q,color)
 mask=gs[f'Gerber_{side}SolderMaskLayer.G{ms}'];silk=gs[f'Gerber_{side}SilkscreenLayer.G{ss}']
 draw(mask,'#dce4ec');draw(silk,'#193e65');draw(mask.intersection(silk),'#e43838')
 for ref,p in parts.items():
  if p['layer']!=('1' if side=='Top' else '2'):continue
  x,y=p['center'];ax.text(x,-y,ref,fontsize=6,color='#59616b')
 ax.set_xlim(13.4,32.6);ax.set_ylim(88.6,69.4);ax.set_aspect('equal');ax.grid(alpha=.15);ax.set_title(side+' - unmirrored review projection')
fig.suptitle('REVIEW ONLY - residual silk on mask apertures in red')
fig.tight_layout();fig.savefig(O/'丝印终检开窗对照_仅审核.png',dpi=180);plt.close(fig)
