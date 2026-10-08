"""Read-only Q1 saved-source/output audit; writes review artifacts only.

Explicit current inputs, no historical generator execution and no CAD writes.
"""
from pathlib import Path
from collections import Counter
import ast, csv, hashlib, json, math, sys, zipfile

R = Path(__file__).resolve().parents[1]
S = R / 'easyeda_std/Q1直接修复_20261006'
O = R / 'manufacturing/仅审核禁止生产/Q1直接修复_20261006'
sys.path[:0] = [str(R / 'scripts'), '/tmp/round-pcb-audit-libs']
from check_pcb_a5 import parse, xy
from audit_current_cam import layer
from audit_clone_connector_s_20260929 import drill, hole_gap, final_copper_gap
from shapely.geometry import Polygon, Point, LineString, GeometryCollection, box
from shapely.ops import unary_union
from shapely.validation import make_valid

# Only the two pure geometry functions; never execute the historical audit body.
t = ast.parse((R / 'archive/历史资料与工具_20261006/manufacturing/仅审核禁止生产/整板复审_20261004/independent_manufacturing_geometry.py').read_text())
exec(compile(ast.Module(body=[n for n in t.body if isinstance(n, ast.FunctionDef) and n.name in {'geom', 'merge'}], type_ignores=[]), '<pure geometry helpers>', 'exec'))

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def rows(p):
    raw = p.read_bytes()
    text = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig')
    return list(csv.DictReader(text.splitlines(), delimiter='\t' if '\t' in text.splitlines()[0] else ','))

def write_csv(p, data):
    with p.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader(); w.writerows(data)

pcb = S / 'PCB_Q1直接修复_孔距收尾_保存重开_20261006.json'
pre = S / 'PCB_Q1修改前_原生回读_20261006.json'
saved = S / 'PCB_Q1直接修复_孔距收尾_原生保存后_20261006.json'
gerb = O / 'Gerber_Q1直接修复_孔距收尾_仅审核_20261006.zip'
baseline = R / 'archive/历史资料与工具_20261006/manufacturing/仅审核禁止生产/C9替料_20261005/Gerber_C9替料_仅审核_20261005.zip'
d, parts, pads, holes = parse(pcb)
b, oldparts, oldpads, _ = parse(pre)
s = json.loads(saved.read_text())
assert Counter(s['shape']) == Counter(d['shape'])
assert all(s[k] == d[k] for k in s if k != 'shape')
assert d['DRCRULE'] == b['DRCRULE'] and d['routerRule'] == b['routerRule']
assert len(parts) == 41
assert sorted((p['ref'], p['pin'], p['net']) for p in pads) == sorted((p['ref'], p['pin'], p['net']) for p in oldpads)
changed = sorted(r for r in parts if parts[r] != oldparts[r])
assert changed == ['D4', 'Q1', 'R9']
qshape = next(v for v in d['shape'] if v.startswith('LIB~') and v.split('~')[6] == parts['Q1']['id'])
qhead = qshape.split('#@$')[0].split('~')
assert qhead[8] == '5681cb3b3db54d94938593cf878665cb'
qmodel = json.loads(next(v[1] for v in parts['Q1']['items'] if v[0] == 'SVGNODE'))
assert qmodel['attrs']['c_rotation'] == '0,0,90'
pours = [x.split('~') for x in d['shape'] if x.startswith('COPPERAREA~')]
assert len(pours) == 3 and all(json.loads(x[10]) for x in pours)

native_bom = rows(O / 'BOM_Q1直接修复_原生41位置_仅审核_20261006.csv')
native_cpl = rows(O / 'CPL_Q1直接修复_原生41位置_仅审核_20261006.csv')
assert len(native_bom) == len(native_cpl) == 41
assert {v['Designator'] for v in native_bom} == set(parts)
assert {v['Designator'] for v in native_cpl} == set(parts)
q = next(v for v in native_bom if v['Designator'] == 'Q1')
assert q['Manufacturer Part'] == 'DMP2165UW-7' and q['Supplier Part'] == 'C388477'
oldbom = rows(R / 'archive/历史资料与工具_20261006/manufacturing/仅审核禁止生产/C9替料_20261005/BOM_36件准确料号_C9替料_仅审核_20261005.csv')
oldcpl = rows(R / 'archive/历史资料与工具_20261006/manufacturing/仅审核禁止生产/C9替料_20261005/CPL_36件SMT_中心校正_C9替料_仅审核_20261005.csv')
bom = [dict(v) for v in oldbom]
for v in bom:
    if v['位号'] == 'Q1':
        v.update({'制造商': 'Diodes Incorporated', '完整料号': 'DMP2165UW-7', '封装': q['Footprint'], '原生贴装角度': '0', '历史立创编号_下单前复核': 'C388477', '说明': 'A5专用原厂推荐盘；自定义1=D/2=G/3=S，原厂物理3=D/1=G/2=S；以装配映射图为准；最大高1.10mm；库存和机器角度待厂'})
cpl = [dict(v) for v in oldcpl]
nr = {v['Designator']: v for v in native_cpl}
for v in cpl:
    if v['Designator'] in changed:
        v.update(nr[v['Designator']])
assert len(bom) == len(cpl) == 36 and {v['位号'] for v in bom} == {v['Designator'] for v in cpl}
assert next(v['Mid Y'] for v in cpl if v['Designator'] == 'ANT1') == '80.67mm'
cpl_checks = []
for v in cpl:
    ref = v['Designator']; p = parts[ref]
    delta = [float(v['Mid X'].removesuffix('mm')) - p['center'][0], -float(v['Mid Y'].removesuffix('mm')) - p['center'][1]]
    assert ref == 'J1' or max(map(abs, delta)) < .006, (ref, delta)
    assert float(v['Rotation']) == (float(p['rotation'] or 0) + (180 if v['Layer'] == 'B' else 0)) % 360
    cpl_checks.append({'ref': ref, 'CPL_minus_LIB_mm': delta, 'rotation': v['Rotation'], 'side': v['Layer']})
write_csv(O / 'BOM_36件准确料号_Q1修复_仅审核_20261006.csv', bom)
write_csv(O / 'CPL_36件SMT_中心校正_Q1修复_仅审核_20261006.csv', cpl)

report = {'date': '2026-10-06', 'status': 'REVIEW ONLY', 'inputs': {str(p.relative_to(R)): digest(p) for p in (pcb, pre, saved, gerb, baseline)}, 'saved_reopened_shape_and_nonshape_equal': True, 'changed_refs': changed, 'other_38_parts_unchanged': True, 'pad_pin_net_signature_unchanged': True, 'rules_unchanged': True, 'native_UI': {'PCB': 'PCB_圆形传感板_SCH_A5 copy', 'doc_id': 'cca094630ebf453c98ae64b900f0d7f0', 'saved_no_star_and_closed_reopened': True, 'pours_rebuilt': 3, 'components': 41, 'nets': '20/20', 'unconnected': 0, 'DRC_errors': 0, 'ignored_or_relaxed_rules': False}, 'BOM_CPL': {'native_rows': 41, 'SMT_rows': 36, 'top': 6, 'bottom': 30, 'unique_MPNs': len({v['完整料号'] for v in bom}), 'ANT1_corrected_Y_mm': 80.67, 'J1_machine_pick_and_all_tape_angles': 'factory pending', 'checks': cpl_checks}, 'Q1': {'MPN': 'DMP2165UW-7', 'LCSC': 'C388477', 'footprint_uuid': qhead[8], 'model_rotation': qmodel['attrs']['c_rotation'], 'custom_to_manufacturer_pin': {'1': 'D, manufacturer physical 3, BAT_P', '2': 'G, manufacturer physical 1, USB_5V', '3': 'S, manufacturer physical 2, VSYS'}, 'max_height_mm': 1.10, 'USB_plus_candidate_board_plus_Q1_global_height_band_mm': 5.21, 'mechanical_limit': 'Global band, not same XY cross-section; excludes solder/neighbor maximum tolerances and real pen fit.'}, 'production_released': False}
layers = {}; oldlayers = {}; drills = {}; olddrills = {}; comparisons = []
with zipfile.ZipFile(gerb) as z, zipfile.ZipFile(baseline) as oz:
    assert set(z.namelist()) == set(oz.namelist())
    for n in z.namelist():
        if n.startswith('Gerber_'):
            a = layer(z.read(n).decode()); o = layer(oz.read(n).decode())
            layers[n] = a; oldlayers[n] = o
            sa = Counter(json.dumps(v, sort_keys=True) for v in a); so = Counter(json.dumps(v, sort_keys=True) for v in o)
            comparisons.append({'layer': n, 'same_primitives': sa == so, 'removed': sum((so-sa).values()), 'added': sum((sa-so).values())})
        elif n.endswith('.DRL'):
            drills[n] = drill(z.read(n).decode()); olddrills[n] = drill(oz.read(n).decode())
gs = {n: merge(v) for n, v in layers.items()}
og = {n: merge(v) for n, v in oldlayers.items()}
report['CAM_layers'] = comparisons
local_scope = box(22.9, -76.2, 27.6, -71.5)
report['CAM_geometry_delta'] = []
for n in gs:
    delta = gs[n].symmetric_difference(og[n])
    report['CAM_geometry_delta'].append({'layer': n, 'symmetric_difference_mm2': delta.area, 'difference_bounds_mm': None if delta.is_empty else list(delta.bounds), 'outside_Q1_D4_R9_scope_mm2': delta.difference(local_scope).area if n.endswith(('.GTL','.GBL','.G1','.G2')) else None})
report['CAM_local_scope_source_mm'] = list(local_scope.bounds)
report['silkscreen'] = [{'side': side, 'opening_overlap_mm2': gs[f'Gerber_{side}SilkscreenLayer.G{ss}'].intersection(gs[f'Gerber_{side}SolderMaskLayer.G{ms}']).area, 'within_0_15mm_opening_mm2': gs[f'Gerber_{side}SilkscreenLayer.G{ss}'].intersection(gs[f'Gerber_{side}SolderMaskLayer.G{ms}'].buffer(.15)).area} for side, ss, ms in [('Top','TO','TS'), ('Bottom','BO','BS')]]
report['excluded_paste'] = []
for p in pads:
    if p['kind'] != 'pad' or p['ref'] not in {'C30', 'C31', 'J2', 'J4', 'SW1'}: continue
    n = 'Gerber_TopPasteMaskLayer.GTP' if p['layer'] == '1' else 'Gerber_BottomPasteMaskLayer.GBP'
    area = Polygon(p['poly']).intersection(gs[n]).area
    assert area < 1e-9
    report['excluded_paste'].append({'ref': p['ref'], 'pin': p['pin'], 'overlap_mm2': area})
assert len(report['excluded_paste']) == 13
report['Q1_pads'] = []
for p in pads:
    if p['ref'] != 'Q1': continue
    g = Polygon(p['poly']); c = g.centroid
    pas = [geom(v) for v in layers['Gerber_BottomPasteMaskLayer.GBP'] if not v['clear'] and geom(v).contains(c)]
    mask = [geom(v) for v in layers['Gerber_BottomSolderMaskLayer.GBS'] if not v['clear'] and geom(v).contains(c)]
    assert len(pas) == len(mask) == 1
    report['Q1_pads'].append({'custom_pin': p['pin'], 'net': p['net'], 'center_source_mm': list(c.coords)[0], 'copper_area_mm2': g.area, 'paste_area_mm2': pas[0].area, 'paste_symmetric_difference_mm2': pas[0].symmetric_difference(g).area, 'mask_bounds_source_mm': list(mask[0].bounds), 'mask_exposed_fraction': g.intersection(mask[0]).area/g.area, 'stencil_area_ratio': {str(t): pas[0].area/(pas[0].length*t) for t in (.08,.1,.12)}})
q = {p['pin']: Polygon(p['poly']) for p in pads if p['ref'] == 'Q1'}
report['Q1']['G_S_copper_gap_mm'] = q['2'].distance(q['3'])
report['Q1']['clearance_rule_mm'] = d['DRCRULE']['电源']['clearance']*.254
report['drills'] = {'total': sum(len(v) for k,v in drills.items() if k != 'Drill_PTH_Through_Via.DRL'), 'PTH': len(drills['Drill_PTH_Through.DRL']), 'NPTH': len(drills['Drill_NPTH_Through.DRL']), 'via_subset_of_PTH': len(drills['Drill_PTH_Through_Via.DRL']), 'before_total': sum(len(v) for k,v in olddrills.items() if k != 'Drill_PTH_Through_Via.DRL')}
allholes = drills['Drill_PTH_Through.DRL'] + drills['Drill_NPTH_Through.DRL']
report['drills']['minimum_hole_edge_gap_mm'] = min(hole_gap(a,b) for i,a in enumerate(allholes) for b in allholes[:i])
oldholes = olddrills['Drill_PTH_Through.DRL'] + olddrills['Drill_NPTH_Through.DRL']
old_minimum = min(hole_gap(a,b) for i,a in enumerate(oldholes) for b in oldholes[:i])
assert report['drills']['minimum_hole_edge_gap_mm'] >= old_minimum - 1e-9
assert not any('ggeUSB0928V329' in x for x in d['shape'])
report['drills']['C9_baseline_minimum_hole_edge_gap_mm'] = old_minimum
report['drills']['duplicate_local_GND_via_removed'] = 'ggeUSB0928V329; C7 stub now terminates on existing ggeUSB0928V328'
report['drills']['superseded_initial_Q1_export_gap_mm'] = 0.041908776
report['drills']['initial_Q1_export_not_for_manufacturing'] = True
report['drills']['NPTH_copper_gaps'] = [{'hole': h, 'gaps_mm': {n: final_copper_gap(h['a'], layers[n])-h['diameter']/2 for n in ['Gerber_TopLayer.GTL','Gerber_BottomLayer.GBL','Gerber_InnerLayer1.G1','Gerber_InnerLayer2.G2']}} for h in drills['Drill_NPTH_Through.DRL']]
report['limits'] = ['Finite native format parser and bounded circular geometry; not factory DFM or machine setup.', '137 connected pins / 49 explicit NC verified by separate whole schematic graph report; not complete native electrical-type ERC.', 'No ordering, quotation upload, physical USB/RF/power/pen testing.']
(O / 'Q1保存重开与制造增量核验_仅审核.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({k: report[k] for k in ('changed_refs','rules_unchanged','Q1','silkscreen','Q1_pads','drills','CAM_geometry_delta')}, ensure_ascii=False, indent=2))
