#!/usr/bin/env python3
"""Read explicit Gerber exports and source; reuse bounded read-only format parsers.

No generation/import/update of any PCB. Nominal geometry review, not factory DFM.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

from check_pcb_a5 import parse, inside, distance, point_seg, xy, ORIGIN
from audit_clone_connector_s_20260929 import gerber, drill, point_copper_gap, final_copper_gap, hole_gap


def layer(text):
    """Preserve exact arc parameters for all-positive silk/document/outline layers."""
    # Native exporter also emits a bare modal G01 on its own line and G03X...
    # on one line. Split modal words for this parser only; original files stay intact.
    text = re.sub(r'^G01\s*\n', 'G01*\n', text, flags=re.M)
    text = re.sub(r'^(G0[23])(?=X)', r'\1*\n', text, flags=re.M)
    if not any(x in text for x in ('G02*', 'G03*')):
        return gerber(text)
    assert '%LPC*%' not in text, 'Arc/polarity combination unsupported'
    apertures = dict(re.findall(r'%ADD(\d+)C,([\d.]+)\*%', text))
    out, arcs, current, active, mode = [], [], None, None, None
    for s in text.splitlines():
        if s in ('G01*', 'G02*', 'G03*'):
            mode = s
            out.append('G01*')
            continue
        if m := re.fullmatch(r'D(\d+)\*', s):
            active = m[1]
        if m := re.fullmatch(r'X(-?\d+)Y(-?\d+)I(-?\d+)J(-?\d+)D01\*', s):
            assert current is not None and active in apertures and mode in ('G02*', 'G03*')
            x, y, i, j = [int(v)/1e5 for v in m.groups()]
            q = (x, -y)
            arcs.append({'arc': True, 'a': current, 'b': q, 'center': (current[0]+i, current[1]-j), 'clockwise_source_y_down': mode == 'G03*', 'radius': float(apertures[active])/2, 'clear': False})
            current = q
            out.append(f'X{m[1]}Y{m[2]}D02*')
            continue
        if m := re.fullmatch(r'X(-?\d+)Y(-?\d+)D0[123]\*', s):
            current = (int(m[1])/1e5, -int(m[2])/1e5)
        out.append(s)
    return gerber('\n'.join(out)) + arcs


def encode(s):
    return json.dumps(s, sort_keys=True)


def polarity_runs(shapes):
    runs = []
    for s in shapes:
        if not runs or runs[-1][0] != s['clear']:
            runs.append((s['clear'], Counter()))
        runs[-1][1][encode(s)] += 1
    return runs


def shape_poly(s):
    assert not s['clear'] and 'arc' not in s
    if 'rings' in s:
        assert len(s['rings']) == 1
        return s['rings'][0]
    assert s['a'] == s['b']
    x, y = s['a']
    return [(x+s['radius']*math.cos(t*math.pi/64), y+s['radius']*math.sin(t*math.pi/64)) for t in range(128)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for n in ('pcb', 'gerber', 'baseline', 'output'):
        ap.add_argument('--' + n, type=Path, required=True)
    ap.add_argument('--handwire-paste-fix', action='store_true',
                    help='Require exactly the five J2/SW1 paste apertures removed; no other layer changes')
    a = ap.parse_args()
    assert a.output.resolve() not in {getattr(a, n).resolve() for n in ('pcb', 'gerber', 'baseline')}
    d, parts, pads, _ = parse(a.pcb)
    assert (float(d['head']['x']), float(d['head']['y'])) == ORIGIN
    comparisons, layers, files = {}, {}, {}
    with zipfile.ZipFile(a.gerber) as z, zipfile.ZipFile(a.baseline) as old:
        assert set(z.namelist()) == set(old.namelist())
        for name in z.namelist():
            raw, previous = z.read(name), old.read(name)
            files[name] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            if name.startswith('Gerber_'):
                now, before = layer(raw.decode()), layer(previous.decode())
                layers[name] = now
                x, y = Counter(map(encode, before)), Counter(map(encode, now))
                comparisons[name] = {'before_primitives': len(before), 'after_primitives': len(now), 'removed': sum((x-y).values()), 'added': sum((y-x).values()), 'same_polarity_runs': polarity_runs(before) == polarity_runs(now), 'removed_primitives': [json.loads(s) for s in (x-y).elements()], 'added_primitives': [json.loads(s) for s in (y-x).elements()]}
            elif name.endswith('.DRL'):
                now, before = drill(raw.decode()), drill(previous.decode())
                layers[name] = now
                comparisons[name] = {'count': len(now), 'exact_geometry_equal': now == before}
    # Required geometry preserves T. The opt-in local fix accepts only the five
    # specifically matched pad apertures, not arbitrary changes to paste layers.
    paste_fix_evidence = []
    if a.handwire_paste_fix:
        target_pads = [p for p in pads if p['kind']=='pad' and p['ref'] in {'J2','SW1'}]
        assert len(target_pads)==5
        for ref in ('J2','SW1'):
            assert all(v[17]=='-11.811024' for v in parts[ref]['items'] if v[0]=='PAD')
        for name, v in comparisons.items():
            if 'PasteMask' not in name:
                assert v.get('same_polarity_runs',v.get('exact_geometry_equal',True)), name
                continue
            assert v['added']==0, name
            side='1' if '_Top' in name else '2'
            expected=[p for p in target_pads if p['layer']==side]
            assert len(expected)==v['removed'], name
            unmatched=list(expected)
            for s in v['removed_primitives']:
                poly=shape_poly(s)
                def boundary_error(p):
                    other=p['poly']
                    return max(min(point_seg(t,u,w) for u,w in zip(q,q[1:]+q[:1]))
                               for vertices,q in ((poly,other),(other,poly)) for t in vertices)
                hits=[p for p in unmatched if boundary_error(p)<.0005]
                assert len(hits)==1, (name,s)
                p=hits[0];unmatched.remove(p)
                paste_fix_evidence.append({'layer':name,'ref':p['ref'],'pin':p['pin'],
                                           'removed_aperture_boundary_error_mm':boundary_error(p)})
            assert not unmatched
        assert len(paste_fix_evidence)==5
    else:
        assert all(v.get('same_polarity_runs', v.get('exact_geometry_equal', True)) for k, v in comparisons.items() if not any(s in k for s in ('Silkscreen', 'Document')))
    paste = {side: [shape_poly(s) for s in layers[f'Gerber_{side}PasteMaskLayer.G'+('TP' if side == 'Top' else 'BP')]] for side in ('Top', 'Bottom')}
    flying = []
    for p in pads:
        if p['kind'] != 'pad' or p['ref'] not in {'J2', 'J4', 'SW1'}:
            continue
        relevant = paste['Top' if p['layer'] == '1' else 'Bottom']
        gaps = [distance(p['poly'], q) for q in relevant]
        flying.append({'ref': p['ref'], 'pin': p['pin'], 'paste_overlap': min(gaps) < 1e-7, 'nearest_paste_gap_mm': min(gaps)})
    assert len(flying) == 9
    qp = {p['pin']: p for p in pads if p['ref'] == 'Q1'}
    mask = layers['Gerber_BottomSolderMaskLayer.GBS']
    qm = {}
    for pin, pad in qp.items():
        center = tuple(sum(p[k] for p in pad['poly'])/len(pad['poly']) for k in (0, 1))
        shapes = [s for s in mask if not s['clear'] and point_copper_gap(center, s) <= 0]
        assert len(shapes) == 1
        qm[pin] = shape_poly(shapes[0])
    q1 = {'copper_gap_2_3_mm': distance(qp['2']['poly'], qp['3']['poly']), 'nominal_mask_web_2_3_mm': distance(qm['2'], qm['3']), 'rule_mm': d['DRCRULE']['电源']['clearance']*.254, 'conclusion': 'Retain original pads and DRC warning; nominal mask web is not a factory yield guarantee.'}
    plated = layers['Drill_PTH_Through.DRL']
    npth = layers['Drill_NPTH_Through.DRL']
    holes = plated + npth
    copper_names = ['Gerber_TopLayer.GTL', 'Gerber_BottomLayer.GBL', 'Gerber_InnerLayer1.G1', 'Gerber_InnerLayer2.G2']
    npth_gaps = [{'hole': h, 'gaps_mm': {n: final_copper_gap(h['a'], layers[n])-h['diameter']/2 for n in copper_names}} for h in npth]
    ep = next(p['poly'] for p in pads if p['ref'] == 'U1' and p['pin'] == '57')
    ep_holes = [h for h in layers['Drill_PTH_Through_Via.DRL'] if inside(h['a'], ep)]
    ep_paste = [q for q in paste['Top'] if distance(q, ep) < 1e-7]
    area = lambda p: abs(sum(x*v-u*y for (x,y),(u,v) in zip(p,p[1:]+p[:1])))/2
    report = {'date': '2026-10-04', 'status': 'FAIL: hand-solder pad paste present' if any(p['paste_overlap'] for p in flying) else 'Nominal CAM comparison and targeted manufacturing checks completed; review only',
        'inputs': {n: {'path': str(getattr(a,n).resolve()), 'sha256': hashlib.sha256(getattr(a,n).read_bytes()).hexdigest()} for n in ('pcb','gerber','baseline')},
        'native_export_settings': {'layers': 4, 'size_estimate_mm': [18,18], 'thickness_dialog_mm': .8, 'finish_dialog': '沉金', 'note': 'Dialog choices are not stackup or manufacturing acceptance; Gerber does not encode finished thickness.'},
        'files': files, 'comparisons': comparisons, 'intentional_paste_fix': paste_fix_evidence,
        'flying_wire_paste_exclusions': flying, 'Q1': q1,
        'holes': {'total': len(holes), 'plated': len(plated), 'NPTH': len(npth), 'minimum_hole_edge_gap_mm': min(hole_gap(x,y) for i,x in enumerate(holes) for y in holes[:i]), 'NPTH_copper_gaps': npth_gaps},
        'PICO_EP': {'via_count': len(ep_holes), 'paste_opening_count': len(ep_paste), 'paste_area_mm2': sum(map(area,ep_paste)), 'pad_area_mm2': area(ep), 'factory_decision': 'Via filling/capping, paste quantity and one-reflow/double-sided process remain postdoc/factory confirmation.'},
        'limits': ['Finite native format parser; arc parameters retained exactly for all-positive layers.', 'Polygon/circle distance calculations use bounded polygon approximations; manufacturing tolerances and process yield are not simulated.', 'Electrical continuity is covered separately by native DRC and schematic/PCB net assignment comparison.'], 'production_released': False}
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('status','Q1','holes','PICO_EP','flying_wire_paste_exclusions')},ensure_ascii=False,indent=2))
    print('layer differences:', {k: (v.get('removed'),v.get('added')) for k,v in comparisons.items() if v.get('added') or v.get('removed')})


if __name__ == '__main__':
    main()
