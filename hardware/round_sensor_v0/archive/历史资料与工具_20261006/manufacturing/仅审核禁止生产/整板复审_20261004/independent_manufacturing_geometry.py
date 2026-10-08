"""Read-only extended CAM checks; standalone run only writes this audit directory."""
from pathlib import Path
import sys,json,math,hashlib,csv,itertools,zipfile
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'scripts'),'/tmp/round-pcb-audit-libs']
from shapely.geometry import Polygon,Point,LineString,GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
from check_pcb_a5 import parse,xy
from audit_current_cam import layer
from audit_clone_connector_s_20260929 import drill
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
PCB=ROOT/'easyeda_std/最终审核_20261004/PCB_手焊禁钢网_保存重开_20261004.json'
GERBER=ROOT/'manufacturing/仅审核禁止生产/最终审核_20261004/Gerber_手焊禁钢网_保存重开_仅审核_20261004.zip'
CPL=ROOT/'manufacturing/仅审核禁止生产/最终审核_20261004/CPL_38件SMT_中心校正_仅审核_20261004.csv'
d,parts,pads,_=parse(PCB)
def geom(s):
 if 'rings' in s:
  g=GeometryCollection()
  for ring in s['rings']:g=g.symmetric_difference(make_valid(Polygon(ring)))
  return g
 if s.get('arc'):
  c=s['center'];a=math.atan2(s['a'][1]-c[1],s['a'][0]-c[0]);b=math.atan2(s['b'][1]-c[1],s['b'][0]-c[0]);r=math.dist(s['a'],c)
  delta=(b-a)%(2*math.pi) if s['clockwise_source_y_down'] else -((a-b)%(2*math.pi))
  if abs(delta)<1e-9:delta=2*math.pi
  pts=[(c[0]+r*math.cos(a+delta*i/2048),c[1]+r*math.sin(a+delta*i/2048)) for i in range(2049)]
  return LineString(pts).buffer(s['radius'],quad_segs=64)
 return (Point(s['a']) if s['a']==s['b'] else LineString([s['a'],s['b']])).buffer(s['radius'],quad_segs=128)
def merge(shapes):
 g=GeometryCollection();runs=[]
 for s in shapes:
  if not runs or runs[-1][0]!=s['clear']:runs.append((s['clear'],[]))
  runs[-1][1].append(geom(s))
 for clear,seq in runs:
  q=unary_union(seq);g=g.difference(q) if clear else g.union(q)
 return g
with zipfile.ZipFile(GERBER) as z:
 ls={n:layer(z.read(n).decode()) for n in z.namelist() if n.startswith('Gerber_')}
 drills={n:drill(z.read(n).decode()) for n in z.namelist() if n.endswith('.DRL')}
 gs={n:merge(s) for n,s in ls.items()}
res={'input_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (PCB,GERBER,CPL)},'limits':'Finite native Gerber grammar, actual ordered polarity, polygon buffers approximate circular arcs. No fabrication tolerance or machine library validation.'}
pr=[]
for p in pads:
 if p['kind']!='pad':continue
 pg=Polygon(p['poly']);side='Top' if p['layer']=='1' else 'Bottom'
 if p['layer']=='11':side='Top'
 mask=gs[f'Gerber_{side}SolderMaskLayer.G'+('TS' if side=='Top' else 'BS')]
 paste=gs[f'Gerber_{side}PasteMaskLayer.G'+('TP' if side=='Top' else 'BP')]
 pr.append({'ref':p['ref'],'pin':p['pin'],'side':side,'copper_area_mm2':pg.area,'soldermask_exposed_fraction':pg.intersection(mask).area/pg.area,'paste_to_pad_area_ratio':pg.intersection(paste).area/pg.area,'pad_center_mm':list(pg.centroid.coords)[0]})
res['all_pad_mask_and_paste']=pr
res['paste_pad_coverage_summary']={ref:{'count':len(rr:=[p for p in pr if p['ref']==ref]),'min':min(p['paste_to_pad_area_ratio'] for p in rr),'max':max(p['paste_to_pad_area_ratio'] for p in rr)} for ref in parts}
res['silkscreen']=[]
for side,suf,muf in [('Top','TO','TS'),('Bottom','BO','BS')]:
 silk=gs[f'Gerber_{side}SilkscreenLayer.G{suf}'];mask=gs[f'Gerber_{side}SolderMaskLayer.G{muf}']
 res['silkscreen'].append({'side':side,'total_area_mm2':silk.area,'over_soldermask_apertures_area_mm2':silk.intersection(mask).area,'within_0_15mm_mask_aperture_area_mm2':silk.intersection(mask.buffer(.15)).area,'silk_primitives_below_0_10_stroke_count':sum('radius' in s and 2*s['radius']<.0999 for s in ls[f'Gerber_{side}SilkscreenLayer.G{suf}'])})
res['silk_opening_overlap_pads']=[]
for p in pads:
 if p['kind']!='pad':continue
 for side,suf,muf in ([('Top','TO','TS'),('Bottom','BO','BS')] if p['layer']=='11' else [('Top','TO','TS')] if p['layer']=='1' else [('Bottom','BO','BS')]):
  silk=gs[f'Gerber_{side}SilkscreenLayer.G{suf}'];pg=Polygon(p['poly']);g=pg.intersection(silk)
  if g.area>1e-5:res['silk_opening_overlap_pads'].append({'ref':p['ref'],'pin':p['pin'],'side':side,'overlap_mm2':g.area})
res['switch_keepout']=[]
for ref in ['SW2','SW3']:
 cx,cy=parts[ref]['center'];keepout=Polygon([(cx-.8,cy-1),(cx+.8,cy-1),(cx+.8,cy+1),(cx-.8,cy+1)])
 mask=gs['Gerber_BottomSolderMaskLayer.GBS'];copper=gs['Gerber_BottomLayer.GBL'];paste=gs['Gerber_BottomPasteMaskLayer.GBP']
 res['switch_keepout'].append({'ref':ref,'keepout_mm':list(keepout.bounds),'mask_opening_area_mm2':keepout.intersection(mask).area,'exposed_copper_mm2':keepout.intersection(mask).intersection(copper).area,'paste_area_mm2':keepout.intersection(paste).area,'drill_centers_in_keepout':[h for h in drills['Drill_PTH_Through.DRL'] if keepout.intersects(Point(h['a']))]})
res['copper_layer_edges']=[]
board=Point(22.999954,-78.999842).buffer(8.999982,quad_segs=2048)
for n in ['Gerber_TopLayer.GTL','Gerber_BottomLayer.GBL','Gerber_InnerLayer1.G1','Gerber_InnerLayer2.G2']:
 g=gs[n];res['copper_layer_edges'].append({'name':n,'outside_board_area_mm2':g.difference(board).area,'copper_to_outline_mm':g.distance(board.boundary),'polygons':len(g.geoms) if hasattr(g,'geoms') else 1})
res['stencil_area_ratio_at_thickness']=[]
for side,suf in [('Top','TP'),('Bottom','BP')]:
 for s in ls[f'Gerber_{side}PasteMaskLayer.G{suf}']:
  g=geom(s);center=g.centroid
  hit=[p for p in pads if p['kind']=='pad' and p['layer'] in ('1' if side=='Top' else '2','11') and Polygon(p['poly']).intersects(center)]
  res['stencil_area_ratio_at_thickness'].append({'side':side,'ref':[p['ref']+'.'+p['pin'] for p in hit],'area_mm2':g.area,'perimeter_mm':g.length,'area_ratios':{str(t):g.area/(g.length*t) for t in [.07,.08,.09,.1,.12]}})
# All symmetric pad patterns: center is array symmetry center, not a machine/nozzle guarantee.
rows=list(csv.DictReader(CPL.open(encoding='utf-8-sig')));cr=[]
for row in rows:
 ref=row['Designator'];p=parts[ref];pp=[xy(v[2],v[3]) for v in p['items'] if v[0]=='PAD'];pc=[(min(q[k] for q in pp)+max(q[k] for q in pp))/2 for k in (0,1)];mid=[float(row['Mid X'].replace('mm','')),-float(row['Mid Y'].replace('mm',''))]
 r={'ref':ref,'CPL_source_xy_mm':mid,'LIB_source_xy_mm':p['center'],'pad_array_bbox_center_mm':pc,'CPL_minus_LIB_mm':[mid[k]-p['center'][k] for k in (0,1)],'CPL_rotation':row['Rotation'],'LIB_rotation':p['rotation'],'side':row['Layer']}
 if ref=='J1':
  stakes=[xy(v[2],v[3]) for v in p['items'] if v[0]=='PAD' and v[8]=='SH'];face=max(q[1] for q in stakes)+2.6;body=[sum(q[0] for q in stakes)/4,face-7.35/2]
  r.update({'official_body_center_mm':body,'CPL_minus_body_mm':[mid[k]-body[k] for k in (0,1)],'suggested_body_center_CPL_mm':[round(body[0],2),round(-body[1],2)],'evidence':'GCT USB4105 Rev B4 p1 shell7.35 and front stake row2.6 from face, plus current pad/stake/NPTH registration. No manufacturer pick point seen in retained sheet; machine offset remains unresolved.'})
 elif ref=='ANT1':r.update({'body_axis_mm':p['center'],'evidence':'Hirose U.FL catalogue p12 ground pad centerline coax axis, retained correction matches.'})
 else:r['evidence']='Symmetric footprint pad-array center matches LIB. This validates coordinate rounding/geometric self-consistency only; not manufacturer machine library or tape/nozzle orientation.'
 cr.append(r)
res['all_CPL_centers']=cr
res['CPL_summary']={'rows':len(cr),'rotation_rule_matches_all':all(float(r['CPL_rotation'])==(float(r['LIB_rotation'] or 0)+(180 if r['side']=='B' else 0))%360 for r in cr),'coordinate_rounding_max_mm':max(max(map(abs,r['CPL_minus_LIB_mm'])) for r in cr),'manufacturer_machine_origins_verified':False}
vr=[]
for h in drills['Drill_PTH_Through_Via.DRL']:
 g=Point(h['a']).buffer(h['diameter']/2,quad_segs=128)
 hit=[p['ref']+'.'+p['pin'] for p in pads if p['kind']=='pad' and Polygon(p['poly']).intersects(g)]
 exposure={side:g.intersection(gs[f'Gerber_{side}SolderMaskLayer.G'+suf]).area/g.area for side,suf in [('Top','TS'),('Bottom','BS')]}
 if hit or max(exposure.values())>.001:vr.append({'drill':h,'overlapping_pads':hit,'exposed_hole_fraction_by_side':exposure})
res['vias_touching_pads_or_exposed']=vr
(OUT/'manufacturing_geometry.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in res.items() if k not in ['all_pad_mask_and_paste','all_CPL_centers','stencil_area_ratio_at_thickness']},ensure_ascii=False,indent=2))
# Quantitative visual evidence: actual final Gerber, no CAD edits.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MP
fig,axs=plt.subplots(1,2,figsize=(12,7))
for ax,side,suf,maskname,coppername in [(axs[0],'Top','TO','Gerber_TopSolderMaskLayer.GTS','Gerber_TopLayer.GTL'),(axs[1],'Bottom','BO','Gerber_BottomSolderMaskLayer.GBS','Gerber_BottomLayer.GBL')]:
 def draw(g,color,alpha=1):
  if g.is_empty:return
  if g.geom_type=='Polygon':
   ax.add_patch(MP([(x,-y) for x,y in g.exterior.coords],closed=True,facecolor=color,edgecolor='none',alpha=alpha))
   for ring in g.interiors:ax.add_patch(MP([(x,-y) for x,y in ring.coords],closed=True,facecolor='white',edgecolor='none'))
  elif hasattr(g,'geoms'):
   for q in g.geoms:draw(q,color,alpha)
 mask=gs[maskname];silk=gs[f'Gerber_{side}SilkscreenLayer.G{suf}'];draw(mask,'#ccd9e0');draw(silk,'#163a69');draw(mask.intersection(silk),'#e22222')
 ax.set_xlim(13.4,32.6);ax.set_ylim(88.6,69.4);ax.set_aspect('equal');ax.set_title(side+' Gerber: red=silk on mask openings');ax.grid(alpha=.15)
 for ref,p in parts.items():
  if p['layer']!=('1' if side=='Top' else '2'):continue
  x,y=p['center'];ax.text(x,-y,ref,fontsize=6,color='#444')
fig.suptitle('Independent final Gerber overlap review - review only; viewing projection unmirrored')
fig.tight_layout();fig.savefig(OUT/'silkscreen_mask_overlap.png',dpi=180);plt.close(fig)
