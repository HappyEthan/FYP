"""Read-only verification of the saved external-charge change and native CAM exports.

Only writes review reports/filtered BOM and CPL. Never edits CAD or contacts a factory.
"""
from pathlib import Path
from collections import Counter
import sys
sys.path.insert(0, '/tmp/round-pcb-audit-libs')
import csv
import hashlib
import html
import json
import math
import re
import zipfile
from shapely.geometry import Polygon, Point, LineString, GeometryCollection
from shapely.ops import unary_union
from shapely.validation import make_valid
from check_pcb_a5 import parse, distance, xy
from audit_current_cam import layer
from audit_clone_connector_s_20260929 import drill
from audit_current_netlist import schematic_geometry

R = Path(__file__).resolve().parents[1]
S = R / 'easyeda_std/板外充电_20261005'
O = R / 'manufacturing/仅审核禁止生产/板外充电_20261005'
P = S / 'PCB_板外充电_保存重开_20261005.json'
H = S / 'SCH_板外充电_五页保存重开_20261005.json'
G = O / 'Gerber_板外充电_仅审核_20261005.zip'
B = R / 'manufacturing/仅审核禁止生产/丝印终检_20261004/Gerber_丝印终检_仅审核_20261004.zip'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(P) == '57b67d2d0f2de9a4fe2511a1069ec17852bed81a3e244c796b008095251f0849'
assert sha(H) == '33a756e0a405092a7462858422c94fb38097e295949b13e5b2eb54ae46d1a6f7'
def sid(s): return re.search(r'~(gge[^~#^]+)', s).group(1)
def dump(name, v): (O / name).write_text(json.dumps(v, ensure_ascii=False, indent=2)+'\n')
def readcsv(p):
    raw=p.read_bytes(); t=raw.decode('utf-16' if raw[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8-sig')
    return list(csv.DictReader(t.splitlines(), delimiter='\t' if '\t' in t.splitlines()[0] else ','))
def writecsv(name, rows):
    with (O / name).open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

d, parts, pads, _ = parse(P)
old=json.loads((S/'PCB_板外充电改动前_20261005.json').read_text())
cand=json.loads((S/'PCB_板外充电候选_仅审核_20261005.json').read_text())
before={sid(s):s for s in old['shape']}; after={sid(s):s for s in d['shape']}
removed=set(before)-set(after); added=set(after)-set(before)
expected={'ggeA5669','ggeA5697','ggeUSB0928V324','ggeUSB0928V325'}|{f'ggeUSB0928T{i}' for i in range(348,355)}
assert removed==expected and not added
changed=[i for i in before.keys()&after.keys() if before[i]!=after[i]]
assert len(changed)==4 and 'ggeA5739' in changed
assert all(after[i].startswith('COPPERAREA~') for i in changed if i!='ggeA5739')
assert all(d[k]==cand[k] for k in cand if k!='shape')
assert Counter(s for s in d['shape'] if not s.startswith('COPPERAREA~'))==Counter(s for s in cand['shape'] if not s.startswith('COPPERAREA~'))

def norm_shape(s):
    items=s.split('#@$'); f=items[0].split('~')
    if f[0]=='LIB': f[10]='';items[0]='~'.join(f)
    return html.unescape('#@$'.join(q[:-7] if q.endswith('~pinpart') else q for q in items))
sch=json.loads(H.read_text()); candidate_sch=json.loads((S/'SCH_板外充电候选_仅审核_20261005.json').read_text())
assert len(sch['schematics'])==5
normalizations=[]
for a,b in zip(candidate_sch['schematics'],sch['schematics']):
    assert a['title']==b['title']
    assert Counter(map(norm_shape,a['dataStr']['shape']))==Counter(map(norm_shape,b['dataStr']['shape']))
    for k in a['dataStr']:
        if k not in ('shape','colors'): assert a['dataStr'][k]==b['dataStr'][k]
    normalizations.append({'page':b['title'],'shapes':len(b['dataStr']['shape']),'only_native_LIB_metadata_pinpart_empty_colors_and_HTML_entities':True})
def sch_nets(doc):
    pins,refs,nc,groups,names,find=schematic_geometry(doc)
    return {k:'' if p in nc else next(iter(names[find(p)])) if names[find(p)] else tuple(sorted(groups[find(p)])) for k,p in pins.items()}
old_nets=sch_nets(json.loads((S/'SCH_板外充电改动前_20261005.json').read_text()));new_nets=sch_nets(sch)
assert all(old_nets[k]==v for k,v in new_nets.items())
models=sum(any(q.startswith('SVGNODE~') for q in s.split('#@$')) for s in d['shape'] if s.startswith('LIB~'))
dump('保存重开与差异核验_仅审核.json', {'date':'2026-10-05','pcb_sha256':sha(P),'schematic_sha256':sha(H),'removed_shape_ids':sorted(removed),'retained_shapes_changed':changed,'retained_components':41,'models':models,'retained_pin_nets_unchanged':True,'schematic_page_normalization':normalizations,'native_checks':{'pcb_components':41,'pcb_networks':'20/20','schematic_components':41,'schematic_networks':'20/20','DRC':[{'pads':['gge2100','gge2115'],'display_mm':.14,'rule_display_mm':.15}],'unconnected_errors':0,'full_electrical_type_ERC':False},'save_reopen':'Original schematic and unique PCB saved without star, closed without unsaved warning, reopened from original project tree and exported. All five pages reopened individually before full export.','repaired_native_apply_error':'Applying five-page source to existing single schematic page wrote the last page into page4. Detected via reopen export and duplicate refs; repaired with single-page source, saved/reopened, then all-five source and native netlist verified. Abnormal single-page export retained explicitly as prohibited recovery.','production_released':False})

native_bom=readcsv(O/'BOM_板外充电_原生全位置_仅审核_20261005.csv')
native_cpl=readcsv(O/'CPL_板外充电_原生全位置_仅审核_20261005.csv')
assert {r['Designator'] for r in native_bom}==set(parts)=={r['Designator'] for r in native_cpl}
old_dir=R/'manufacturing/仅审核禁止生产/按键收拢_20261004'
old_cpl={r['Designator']:r for r in readcsv(old_dir/'CPL_原生43件_仅审核_20261004.csv')}
assert all(r==old_cpl[r['Designator']] for r in native_cpl)
excluded={'C30','C31','J2','J4','SW1'};sm_refs=set(parts)-excluded
accurate=[r for r in readcsv(old_dir/'BOM_38件准确料号_仅审核_20261004.csv') if r['位号'] not in {'U4','R10'}]
assert {r['位号'] for r in accurate}==sm_refs and len(accurate)==36
raw_cpl={r['Designator']:r for r in native_cpl}
for r in accurate:
    n=raw_cpl[r['位号']]
    assert r['封装']==n['Footprint'] and r['贴装面']==n['Layer'] and float(r['原生贴装角度'])==float(n['Rotation'])
corrected=[dict(r) for r in native_cpl if r['Designator'] in sm_refs]
for r in corrected:
    if r['Designator']=='ANT1': r['Mid Y']=r['Ref Y']
old_corrected={r['Designator']:r for r in readcsv(old_dir/'CPL_38件SMT_中心校正_仅审核_20261004.csv')}
assert all(r==old_corrected[r['Designator']] for r in corrected)
writecsv('BOM_36件准确料号_仅审核_20261005.csv',accurate)
writecsv('CPL_36件SMT_中心校正_仅审核_20261005.csv',corrected)
dump('BOM与坐标增量核验_仅审核.json',{'date':'2026-10-05','native_rows':41,'SMT':36,'sides':dict(Counter(r['贴装面'] for r in accurate)),'unique_MPN':len({r['完整料号'] for r in accurate}),'removed':['U4','R10'],'all_retained_native_CPL_rows_equal_to_button_baseline':True,'all_retained_accurate_BOM_and_corrected_CPL_equal_to_previous':True,'excluded':sorted(excluded),'ANT1_only_review_correction':'Mid Y=Ref Y=80.67mm; previous verified footprint symmetry center reused','J1_machine_origin':'Existing about 1.30mm origin/body-center difference retained for factory confirmation','C9':'Still original 1uF/10V GRM155R61A105KE15D; 4.7uF recommendation not implemented','purchase_stock_or_factory_acceptance_refreshed':False,'native_files_sha256':{p.name:sha(p) for p in O.glob('*原生全位置*csv')},'production_released':False})

def geom(s):
    if 'rings' in s:
        g=GeometryCollection()
        for ring in s['rings']:g=g.symmetric_difference(make_valid(Polygon(ring)))
        return g
    if s.get('arc'):
        c=s['center'];a=math.atan2(s['a'][1]-c[1],s['a'][0]-c[0]);b=math.atan2(s['b'][1]-c[1],s['b'][0]-c[0]);r=math.dist(s['a'],c)
        delta=(b-a)%(2*math.pi) if s['clockwise_source_y_down'] else -((a-b)%(2*math.pi))
        if abs(delta)<1e-9:delta=2*math.pi
        return LineString([(c[0]+r*math.cos(a+delta*i/2048),c[1]+r*math.sin(a+delta*i/2048)) for i in range(2049)]).buffer(s['radius'],quad_segs=64)
    return (Point(s['a']) if s['a']==s['b'] else LineString([s['a'],s['b']])).buffer(s['radius'],quad_segs=128)
def merge(seq):
    g=GeometryCollection();runs=[]
    for s in seq:
        if not runs or runs[-1][0]!=s['clear']:runs.append((s['clear'],[]))
        runs[-1][1].append(geom(s))
    for clear,run in runs:
        q=unary_union(run);g=g.difference(q) if clear else g.union(q)
    return g
def signature(ss):return Counter(json.dumps(s,sort_keys=True) for s in ss)
comparisons=[];layers={};drills={};past_layers={};past_drills={}
with zipfile.ZipFile(G) as z,zipfile.ZipFile(B) as old_z:
    assert set(z.namelist())==set(old_z.namelist())
    for n in z.namelist():
        if n.startswith('Gerber_'):
            now=layer(z.read(n).decode());past=layer(old_z.read(n).decode());a,b=signature(now),signature(past)
            comparisons.append({'file':n,'primitives_equal':a==b,'added':sum((a-b).values()),'removed':sum((b-a).values())});layers[n]=now;past_layers[n]=past
        elif n.endswith('.DRL'):
            now=drill(z.read(n).decode());past=drill(old_z.read(n).decode());drills[n]=now;past_drills[n]=past
            a,b=signature(now),signature(past);comparisons.append({'file':n,'added':sum((a-b).values()),'removed':sum((b-a).values()),'after':len(now)})
gs={n:merge(v) for n,v in layers.items() if 'Mask' in n or 'Silkscreen' in n}
_,_,old_pads,_=parse(old)
allowed=[]
for p in old_pads:
    if p['ref'] in {'U4','R10'}:allowed.append(Polygon(p['poly']).buffer(.5))
removed_vias=[]
for i in removed:
    f=before[i].split('~')
    if f[0]=='TRACK':
        coords=list(map(float,f[4].split()));pts=[xy(*coords[k:k+2]) for k in range(0,len(coords),2)]
        allowed.append(LineString(pts).buffer(float(f[1])*.254/2+.5))
    elif f[0]=='VIA':
        center=xy(f[1],f[2]);allowed.append(Point(center).buffer(float(f[3])*.254/2+.5));removed_vias.append({'a':center,'b':center,'diameter':2*float(f[5])*.254})
allowed=unary_union(allowed);local_deltas=[]
for n in ['Gerber_TopLayer.GTL','Gerber_BottomLayer.GBL','Gerber_InnerLayer1.G1','Gerber_InnerLayer2.G2','Gerber_BottomPasteMaskLayer.GBP','Gerber_BottomSolderMaskLayer.GBS']:
    now_geom=merge(layers[n]);past_geom=merge(past_layers[n])
    change=now_geom.symmetric_difference(past_geom);outside=change.difference(allowed)
    # Native Gerber units are 0.00001mm. Permit two output units around an
    # unchanged boundary only; record the area separately from circuit removal.
    residual=outside.difference(past_geom.boundary.buffer(.00002))
    fragments=list(outside.geoms) if hasattr(outside,'geoms') else [outside]
    remote=[{'area_mm2':q.area,'bounds_mm':list(q.bounds),'direction':'added' if now_geom.covers(q.representative_point()) else 'removed'} for q in fragments if q.area>1e-7]
    # Keep real nonlocal changes visible. Native rebuilding changed one tiny
    # bottom GND fragment and one Inner2 GND fragment; these are not rounding.
    # All trace/pad source strings are independently proven unchanged above,
    # and the saved/reopened native check has 20/20 networks and only Q1 DRC.
    if remote: assert n in ('Gerber_BottomLayer.GBL','Gerber_InnerLayer2.G2')
    local_deltas.append({'file':n,'changed_area_mm2':change.area,'outside_removed_circuit_0_5mm_neighborhood_mm2':outside.area,'outside_and_beyond_0_00002mm_output_boundary_rounding_mm2':residual.area,'nonlocal_native_GND_repour_fragments':remote})
for n in ('Drill_PTH_Through.DRL','Drill_PTH_Through_Via.DRL'):
    gone=[json.loads(v) for v in (signature(past_drills[n])-signature(drills[n])).elements()]
    assert len(gone)==2
    for h in gone:
        # Drill file coordinates are emitted at 0.001mm precision.
        assert any(max(abs(x-y) for x,y in zip(h['a'],v['a']))<.00051 and abs(h['diameter']-v['diameter'])<.00002 for v in removed_vias)
for n in ('Gerber_TopSilkscreenLayer.GTO','Gerber_BottomSilkscreenLayer.GBO','Gerber_TopPasteMaskLayer.GTP','Gerber_TopSolderMaskLayer.GTS','Gerber_BoardOutlineLayer.GKO'):
    assert signature(layers[n])==signature(past_layers[n])
paste_removed=[json.loads(v) for v in (signature(past_layers['Gerber_BottomPasteMaskLayer.GBP'])-signature(layers['Gerber_BottomPasteMaskLayer.GBP'])).elements()]
assert len(paste_removed)==8
expected_pads=[p for p in old_pads if p['kind']=='pad' and p['ref'] in {'U4','R10'}]
assert len(expected_pads)==8
for s in paste_removed:
    hit=[p for p in expected_pads if Polygon(p['poly']).covers(geom(s).centroid)]
    assert len(hit)==1;expected_pads.remove(hit[0])
assert not expected_pads
paste_check=[]
for p in pads:
    if p['kind']!='pad' or p['ref'] not in excluded:continue
    side,suf=('Top','TP') if p['layer']=='1' else ('Bottom','BP')
    area=Polygon(p['poly']).intersection(gs[f'Gerber_{side}PasteMaskLayer.G{suf}']).area
    assert area<1e-9
    paste_check.append({'ref':p['ref'],'pin':p['pin'],'paste_overlap_mm2':area})
assert len(paste_check)==13
silk=[]
for side,ss,ms in [('Top','TO','TS'),('Bottom','BO','BS')]:
    sg=gs[f'Gerber_{side}SilkscreenLayer.G{ss}'];mg=gs[f'Gerber_{side}SolderMaskLayer.G{ms}']
    direct=sg.intersection(mg).area;buffer=sg.intersection(mg.buffer(.15)).area
    assert direct<1e-9 and buffer<1e-9
    silk.append({'side':side,'overlap_mm2':direct,'within_0_15mm_area_mm2':buffer})
qp={p['pin']:p for p in pads if p['ref']=='Q1' and p['kind']=='pad'}
q1={'copper_gap_2_3_mm':distance(qp['2']['poly'],qp['3']['poly']),'rule_mm':d['DRCRULE']['电源']['clearance']*.254,'native_DRC_remaining':True,'factory_acceptance':False}
holes=drills['Drill_PTH_Through.DRL']+drills['Drill_NPTH_Through.DRL']
assert len(holes)==87
dump('Gerber增量与工艺核验_仅审核.json',{'date':'2026-10-05','sha256':{p.name:sha(p) for p in (P,G,B)},'layers':comparisons,'local_geometry_deltas':local_deltas,'eight_removed_paste_apertures_match_U4_R10_pads':True,'two_removed_drills_match_U4_C1_vias':True,'hole_slot_total':len(holes),'DNP_handwire_paste':paste_check,'silkscreen':silk,'Q1':q1,'native_export_settings':{'layers':4,'estimated_size_mm':[18,18],'dialog_thickness_mm':.8,'dialog_finish':'沉金','not_manufacturing_acceptance':True},'limits':['Finite native Gerber parser and bounded circular approximations; no fabrication tolerance simulation.','Removed U4/R10 pads, traces, two vias and their mask/paste/silk are intentional; ground copper rebuilt natively.','Factory stencil, via filling/capping, machine origin and actual stackup remain unapproved.'],'production_released':False})
print(json.dumps({'saved_refs':len(parts),'models':models,'SMT':len(accurate),'unique_MPN':len({r['完整料号'] for r in accurate}),'holes':len(holes),'Q1':q1,'silk':silk,'CAM_delta':comparisons},ensure_ascii=False,indent=2))
