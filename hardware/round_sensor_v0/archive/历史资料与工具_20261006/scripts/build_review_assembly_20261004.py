#!/usr/bin/env python3
"""Build review-only assembly data from explicit source/native CPL and retained MPN mapping.

Never writes PCB/schematic or generates machine rotations from source angles.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from check_pcb_a5 import parse, xy


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for n in ('pcb', 'native-cpl', 'mapping', 'output-dir'):
        ap.add_argument('--'+n, type=Path, required=True)
    a = ap.parse_args()
    d, parts, pads, _ = parse(a.pcb)
    mapped = json.loads(a.mapping.read_text())
    catalogue = {p['ref']: p for p in mapped['parts']}
    with a.native_cpl.open(encoding='utf-16', newline='') as f:
        native = list(csv.DictReader(f, delimiter='\t'))
    assert len(parts) == len(native) == len(catalogue) == 43
    assert set(parts) == set(catalogue) == {r['Designator'] for r in native}
    # The historical MPN mapping is reusable only when pad numbering, geometry,
    # nets, layer and part placement match the current source. Paste is separate.
    for ref, p in parts.items():
        old = catalogue[ref]
        assert max(abs(x-y) for x,y in zip(p['center'], old['source_xy_mm'])) < 1e-6
        assert float(p['rotation'] or 0) == old['native_rotation_deg']
        current_pads = [v for v in p['items'] if v[0] == 'PAD']
        old_pads = [v['raw_native_pad'].split('~') for v in old['pads']]
        assert len(current_pads) == len(old_pads)
        for now, before in zip(current_pads, old_pads):
            assert now[:17] == before[:17] and now[18:] == before[18:]
    excluded = {'C30','C31','J2','J4','SW1'}
    rows = [dict(r) for r in native if r['Designator'] not in excluded]
    assert len(rows) == 38
    assert sum(r['Layer'] == 'T' for r in rows) == 6
    ant = next(r for r in rows if r['Designator'] == 'ANT1')
    assert (ant['Mid X'],ant['Mid Y'],ant['Ref X'],ant['Ref Y']) == ('29.15mm','81.43mm','29.15mm','80.67mm')
    # Hirose catalogue p12: coax axis aligns with the GND pad common horizontal
    # centreline; the signal pad is offset 1.525mm. Source LIB origin is that axis.
    pp = {v[8]: xy(v[2],v[3]) for v in parts['ANT1']['items'] if v[0]=='PAD'}
    axis = ((pp['2'][0]+pp['3'][0])/2, (pp['2'][1]+pp['3'][1])/2)
    assert max(abs(x-y) for x,y in zip(axis,parts['ANT1']['center'])) < .0002
    assert abs(pp['1'][1]-axis[1]+1.525) < .0002
    ant['Mid Y'] = ant['Ref Y']
    out=a.output_dir; out.mkdir(parents=True,exist_ok=True)
    cpl=out/'CPL_38件SMT_中心校正_仅审核_20261004.csv'
    with cpl.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=native[0].keys());w.writeheader();w.writerows(rows)
    # Verify all retained cells, except the explicitly justified one, are native.
    original={r['Designator']:r for r in native}
    delta=[{'ref':r['Designator'],'field':k,'before':original[r['Designator']][k],'after':v}
           for r in rows for k,v in r.items() if original[r['Designator']][k]!=v]
    assert delta == [{'ref':'ANT1','field':'Mid Y','before':'81.43mm','after':'80.67mm'}]
    bom=[]
    for r in rows:
        ref=r['Designator'];p=catalogue[ref];c=p['candidate'];assert c
        bom.append({'位号':ref,'单板数量':1,'制造商':c['manufacturer'],'完整料号':c['candidate_mpn'],
                    '封装':r['Footprint'],'贴装面':r['Layer'],'原生贴装角度':r['Rotation'],
                    '历史立创编号_下单前复核':c['historical_domestic_code'] or '',
                    '说明':'板上插座；外置FPC天线另计' if ref=='ANT1' else
                           '国内采购/接贴核准；不可用同系列代替' if ref in {'SW2','SW3'} else
                           '客供方式由博后确认' if ref in {'U1','U4'} else
                           '核实生命周期/库存；保持原值' if ref in {'C1','C7','C9','C10'} else '按完整料号复核供货'})
    assert len({r['完整料号'] for r in bom})==23
    bpath=out/'BOM_38件准确料号_仅审核_20261004.csv'
    with bpath.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=bom[0].keys());w.writeheader();w.writerows(bom)
    anchors=[]
    for ref in ('U1','U2','U3','U4','U5','U6','Q1','D1','D2','D3','D4','ANT1','J1','SW2','SW3','J2','J4','SW1'):
        p=parts[ref];cr=original[ref]
        for v in p['items']:
            if v[0]!='PAD':continue
            x,y=xy(v[2],v[3])
            anchors.append({'ref':ref,'pin':v[8],'net':v[7] or 'NC','side':cr['Layer'],
                            'X_mm':round(x,6),'Y_mm':round(-y,6),'native_rotation_deg':cr['Rotation']})
    report={'status':'仅审核；输入为最终保存重开源，工厂机器库与接贴确认另行完成','date':'2026-10-04',
            'inputs':{n:{'path':str(getattr(a,n).resolve()),'sha256':sha(getattr(a,n))} for n in ('pcb','native_cpl','mapping')},
            'counts':{'positions':43,'SMT':38,'top':6,'bottom':32,'MPNs':23},
            'excluded':sorted(excluded),'CPL_changes':delta,
            'ANT1_evidence':{'source_axis_mm':[axis[0],-axis[1]],'datasheet':'references/Hirose_U.FL_catalog.pdf p12',
                             'datasheet_sha256':sha(Path(__file__).resolve().parents[1]/'references/Hirose_U.FL_catalog.pdf'),
                             'reason':'Native Mid is displaced toward offset signal pad. Coax body axis equals Ref; retain rotation 180 and all other native cells.',
                             'factory_action':'Use corrected body centre; factory confirms nozzle/pick method and machine library angle against assembly pin map.'},
            'coordinate_convention':'mm; native X/positive-up Y; bottom not mirrored. Assembly drawing bottom is mirrored for viewing only.',
            'pin_anchors':anchors,'outputs':{p.name:sha(p) for p in (cpl,bpath)},
            'inventory_checked':False,'production_released':False}
    (out/'装配数据核验_仅审核.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('counts','CPL_changes','outputs')},ensure_ascii=False))


if __name__=='__main__':main()
