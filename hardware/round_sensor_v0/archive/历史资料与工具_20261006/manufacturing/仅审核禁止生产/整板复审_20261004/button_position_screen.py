"""Read-only finite SW3 placement screen; never creates/edits a PCB candidate."""
from pathlib import Path
import sys,math,json,hashlib
sys.path[:0]=['/tmp/round-pcb-audit-libs',str(Path(__file__).resolve().parents[3]/'scripts')]
from shapely.geometry import Polygon,Point,LineString,box
from shapely.affinity import rotate,translate
from check_pcb_a5 import parse,xy
from audit_a5_routed_snapshot import routes
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
SRC=ROOT/'easyeda_std/最终审核_20261004/PCB_手焊禁钢网_保存重开_20261004.json'
d,parts,pads,_=parse(SRC);tracks,vias,_=routes(d)
mechanical=json.loads((ROOT/'manufacturing/仅审核禁止生产/最终审核_20261004/当前装配空间核验_仅审核.json').read_text())['bodies']
obs=[]
for p in pads+vias:
 if p.get('ref')=='SW3' or p['layer'] not in ['2','11']:continue
 obs.append((p.get('ref','')+'.'+p.get('pin',p.get('id','')),p['net'],Polygon(p['poly'])))
for t in tracks:
 if t['layer']!='2':continue
 obs.append((t['id'],t['net'],LineString(t['points']).buffer(t['width']/2,quad_segs=16)))
body_obs=[(ref,Polygon(v.get('max_polygon') or v['polygon'])) for ref,v in mechanical.items() if v['side']=='2' and ref!='SW3']
body_obs.extend((p['ref']+'.'+p['pin']+'_solder_access',Polygon(p['poly'])) for p in pads if p['kind']=='pad' and (p['layer']=='11' or p['ref'] in {'J2','J4','SW1'}))
base=parts['SW3']['center'];bp=[(p['pin'],p['net'],Polygon(p['poly'])) for p in pads if p['ref']=='SW3']
board=Point(22.999954,-78.999842).buffer(8.999982,quad_segs=512)
# Separate DRC .15 mm clearance from elective .20 mm body allowance.
rows=[];counts={'total':0,'pad_edge_rejected':0,'body_rejected':0,'pad_copper_rejected':0,'screen_clear':0}
for delta_angle in [0,90]:
 for ix in range(155,186):
  for iy in range(730,821):
   counts['total']+=1;c=(ix/10,-iy/10);dx,dy=c[0]-base[0],c[1]-base[1]
   pp=[(pin,net,translate(rotate(g,delta_angle,origin=base),dx,dy)) for pin,net,g in bp]
   if any(not board.buffer(-.30).covers(g) for _,_,g in pp):counts['pad_edge_rejected']+=1;continue
   w,h=(1.7,2.7) if delta_angle==0 else (2.7,1.7);body=box(c[0]-w/2,c[1]-h/2,c[0]+w/2,c[1]+h/2)
   if any(body.distance(g)<.20-1e-6 for ref,g in body_obs):counts['body_rejected']+=1;continue
   bad=[]
   for pin,net,g in pp:
    for oid,onet,og in obs:
     if onet and onet==net:continue
     gap=g.distance(og)
     if gap<.1499:bad.append((oid,gap));break
    if bad:break
   if bad:counts['pad_copper_rejected']+=1;continue
   counts['screen_clear']+=1
   rows.append({'candidate_source_center_mm':c,'CPL_xy_mm':[c[0],-c[1]],'rotation_delta_deg':delta_angle,'SW2_center_distance_mm':math.dist(c,parts['SW2']['center']),'minimum_body_gap_mm':min(body.distance(g) for _,g in body_obs),'minimum_different_net_discrete_copper_gap_mm':min(g.distance(og) for _,net,g in pp for _,onet,og in obs if not (onet and onet==net))})
rows.sort(key=lambda r:r['SW2_center_distance_mm'])
contact=[]
for pin,net,g in bp:
 for t in tracks:
  if t['layer']=='2' and g.intersects(LineString(t['points']).buffer(t['width']/2+.001,quad_segs=16)):contact.append({'pin':pin,'track':t['id'],'net':t['net'],'points_source_mm':t['points']})
result={'source_sha256':hashlib.sha256(SRC.read_bytes()).hexdigest(),'baseline_SW2_source_mm':parts['SW2']['center'],'baseline_SW3_source_mm':base,'baseline_distance_mm':math.dist(base,parts['SW2']['center']),'counts':counts,'by_rotation':{str(a):sum(r['rotation_delta_deg']==a for r in rows) for a in [0,90]},'best_candidates':rows[:15],'current_SW3_pad_connected_tracks':contact,'limits':['Only SW3 rigid-body translations/90 degree rotation, SW2 and all other parts remain fixed.','Candidate body envelope1.7x2.7mm max plus .20mm elective assembly margin to other bodies, J1 plated slot pads and J2/J4/SW1 handwire pads; board copper clearance .30mm and discrete different-net copper .15mm.','Uses actual PAD/TRACK/VIA geometry but excludes pours which would need regeneration. It does not test routing feasibility, reconnection, soldermask, silk, full 3D/enclosure/actuator access, or native DRC.','No PCB candidate generated. A screen-clear point is not an accepted layout or promise that buttons can be moved.']}
(OUT/'按键靠拢_有限空间筛查.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
