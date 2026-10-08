import sys,json,csv,math,hashlib,zipfile
from pathlib import Path
from collections import Counter
sys.path.insert(0,'hardware/round_sensor_v0/scripts')
from check_pcb_a5 import parse,distance
from audit_a5_routed_snapshot import routes
from audit_current_cam import layer,encode,polarity_runs,shape_poly
from audit_clone_connector_s_20260929 import drill
root=Path('hardware/round_sensor_v0'); local=root/'easyeda_std/布局优化_20261004'; out=root/'manufacturing/仅审核禁止生产/按键收拢_20261004'; olddir=out.parent/'最终审核_20261004'
a,pa,pada,_=parse(local/'PCB_布局优化前_现场恢复_20261004.json');b,pb,padb,_=parse(local/'PCB_按键收拢_保存重开_20261004.json')
assert a['DRCRULE']==b['DRCRULE']
changed=[r for r in pa if pa[r]!=pb[r]];assert changed==['SW3'],changed
assert [(p['ref'],p['pin'],p['net'],p['layer']) for p in pada]==[(p['ref'],p['pin'],p['net'],p['layer']) for p in padb]
ta,va,_=routes(a);tb,vb,_=routes(b)
oldtracks={t['id']:t for t in ta};newtracks={t['id']:t for t in tb}
removed=sorted(set(oldtracks)-set(newtracks));added=sorted(set(newtracks)-set(oldtracks));assert all(oldtracks[k]==newtracks[k] for k in oldtracks.keys()&newtracks.keys())
assert removed==['ggeUSB0928T240','ggeUSB0928T244','ggeUSB0928T245']
assert set(added)=={'ggeLAY1004ENPair','ggeLAY1004ENFeed','ggeLAY1004ENMain','ggeLAY1004GNDPair'}
length=lambda t:sum(math.dist(x,y) for x,y in zip(t['points'],t['points'][1:]))
lengths={'old_EN_branch_mm':sum(length(oldtracks[k]) for k in ('ggeUSB0928T244','ggeUSB0928T245')),'new_EN_branch_mm':sum(length(newtracks[k]) for k in ('ggeLAY1004ENFeed','ggeLAY1004ENMain'))}
def readcsv(p):
 with p.open(encoding='utf-16',newline='') as f:return list(csv.DictReader(f,delimiter='\t'))
cb,ca=readcsv(out/'CPL_原生43件_仅审核_20261004.csv'),readcsv(olddir/'CPL_工作板_原生_仅审核_20261004.csv')
ca={x['Designator']:x for x in ca};cd=[{'ref':x['Designator'],'before':ca[x['Designator']],'after':x} for x in cb if x!=ca[x['Designator']]];assert [x['ref'] for x in cd]==['SW3']
bomold=readcsv(olddir/'BOM_工作板_原生_仅审核_20261004.csv');bomnew=readcsv(out/'BOM_原生43件_仅审核_20261004.csv');assert len(bomnew)==43
def expanded(rows):
 result={}
 for r in rows:
  for ref in r['Designator'].split(','):
   result[ref.strip()]={k:v for k,v in r.items() if k not in {'ID','Designator','Quantity'}}
 return result
bom_same=expanded(bomold)==expanded(bomnew)
assert bom_same,[(k,expanded(bomold).get(k),v) for k,v in expanded(bomnew).items() if expanded(bomold).get(k)!=v]
cam={};current={}
with zipfile.ZipFile(out/'Gerber_按键收拢_仅审核_20261004.zip') as z,zipfile.ZipFile(olddir/'Gerber_手焊禁钢网_保存重开_仅审核_20261004.zip') as old:
 assert set(z.namelist())==set(old.namelist())
 for n in z.namelist():
  if n.startswith('Gerber_'):
   aa,bb=layer(old.read(n).decode()),layer(z.read(n).decode());current[n]=bb
   ac,bc=Counter(map(encode,aa)),Counter(map(encode,bb));cam[n]={'removed':sum((ac-bc).values()),'added':sum((bc-ac).values()),'same_ordered_polarity_runs':polarity_runs(aa)==polarity_runs(bb)}
  elif n.endswith('.DRL'):
   aa,bb=drill(old.read(n).decode()),drill(z.read(n).decode());current[n]=bb
   ac,bc=Counter(map(encode,aa)),Counter(map(encode,bb));cam[n]={'old_count':len(aa),'new_count':len(bb),'removed':[json.loads(x) for x in (ac-bc).elements()],'added':[json.loads(x) for x in (bc-ac).elements()]}
assert cam['Gerber_TopPasteMaskLayer.GTP']['same_ordered_polarity_runs']
assert cam['Gerber_TopSolderMaskLayer.GTS']['same_ordered_polarity_runs']
assert cam['Gerber_TopSilkscreenLayer.GTO']['same_ordered_polarity_runs']
assert cam['Gerber_BoardOutlineLayer.GKO']['same_ordered_polarity_runs']
assert cam['Gerber_BottomPasteMaskLayer.GBP']['removed']==cam['Gerber_BottomPasteMaskLayer.GBP']['added']==4
assert cam['Gerber_BottomSolderMaskLayer.GBS']['removed']==cam['Gerber_BottomSolderMaskLayer.GBS']['added']==4
assert len(cam['Drill_PTH_Through.DRL']['added'])==len(cam['Drill_PTH_Through.DRL']['removed'])==1
paste=[shape_poly(s) for s in current['Gerber_BottomPasteMaskLayer.GBP']]
hand=[{'ref':p['ref'],'pin':p['pin'],'min_gap_mm':min(distance(p['poly'],q) for q in paste)} for p in padb if p['kind']=='pad' and p['ref'] in {'J2','J4','SW1'}];assert len(hand)==9 and all(p['min_gap_mm']>0 for p in hand)
result={'status':'仅审核；本地输出核验，不替代原生DRC与工厂DFM','changed_components':changed,'other_42_components_exact_equal':True,'pad_net_assignments_equal':True,'rules_equal':True,'tracks_removed':removed,'tracks_added':added,'other_tracks_equal':True,'via_counts_before_after':[len(va),len(vb)],'button_distance_before_after_mm':[math.dist(pa['SW2']['center'],pa['SW3']['center']),math.dist(pb['SW2']['center'],pb['SW3']['center'])],'EN_branch_lengths':lengths,'native_CPL_delta':cd,'native_BOM_43_positions_attributes_equal_after_expanding_merged_old_rows':bom_same,'CAM_delta':cam,'handwire_no_paste':hand,'hole_count':len(current['Drill_PTH_Through.DRL'])+len(current['Drill_NPTH_Through.DRL']),'production_released':False}
(out/'输出差异与制造核验_仅审核.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
