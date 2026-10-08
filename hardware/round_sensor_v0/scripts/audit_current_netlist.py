#!/usr/bin/env python3
"""Compare explicit native schematic netlist, saved schematic geometry and PCB pads.

Read-only design audit; writes a report, never runs a historical generator.
PCB copper continuity remains the separate native DRC/unconnected check.
"""
import argparse
from datetime import date
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re


def schematic_geometry(doc):
    pins, refs, labels, nc, edges, junctions = {}, {}, defaultdict(set), set(), [], set()
    for page_index, page in enumerate(doc['schematics']):
        def node(x, y):
            return page_index, float(x), float(y)
        for shape in page['dataStr']['shape']:
            f = shape.split('~')
            if f[0] == 'LIB':
                h, *body = shape.split('#@$')
                ref, = [s.split('~')[12] for s in body if s.startswith('T~P~')]
                assert ref not in refs, ('duplicate ref', ref)
                refs[ref] = page['title']
                for s in body:
                    if not s.startswith('P~'):
                        continue
                    sections = s.split('^^')
                    cfg = sections[0].split('~')
                    num = sections[4].split('~')[4]
                    p = node(*sections[1].split('~'))
                    assert cfg[3] == num and node(cfg[4], cfg[5]) == p
                    key = ref + '.' + num
                    assert key not in pins
                    pins[key] = p
            elif f[0] == 'W':
                coords = list(map(float, f[1].split()))
                points = [node(x, y) for x, y in zip(coords[::2], coords[1::2])]
                edges.extend(zip(points, points[1:]))
            elif f[0] == 'N':
                labels[node(f[1], f[2])].add(f[5])
            elif f[0] == 'O':
                nc.add(node(f[1], f[2]))
            elif f[0] == 'J':
                junctions.add(node(f[1], f[2]))
    nodes = set(pins.values()) | set(labels) | nc | junctions | {p for ab in edges for p in ab}
    parent = {p: p for p in nodes}
    def find(p):
        if parent[p] != p:
            parent[p] = find(parent[p])
        return parent[p]
    for a, b in edges:
        assert a[1] == b[1] or a[2] == b[2], 'Nonorthogonal wire needs explicit handling'
        for p in nodes:
            if p[0] != a[0]:
                continue
            cross = (p[1]-a[1])*(b[2]-a[2])-(p[2]-a[2])*(b[1]-a[1])
            if abs(cross) < 1e-9 and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]) and min(a[2], b[2]) <= p[2] <= max(a[2], b[2]):
                parent[find(p)] = find(a)
    groups, names = defaultdict(list), defaultdict(set)
    for key, p in pins.items():
        groups[find(p)].append(key)
    for p, name in labels.items():
        names[find(p)].update(name)
    return pins, refs, nc, groups, names, find


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('schematic', 'pcb', 'netlist', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--date', default=date.today().isoformat())
    ap.add_argument('--native-schematic-ui', default='Not recorded for this invocation')
    args = ap.parse_args()
    assert args.output.resolve() not in {getattr(args, n).resolve() for n in ('schematic', 'pcb', 'netlist')}
    sch = json.loads(args.schematic.read_text())
    pcb = json.loads(args.pcb.read_text())
    native = args.netlist.read_text(encoding='utf-8-sig')
    components = {}
    for block in re.findall(r'^\[\s*\n(.*?)^\]', native, flags=re.M | re.S):
        lines = block.splitlines()
        assert lines[0] not in components
        components[lines[0]] = {'footprint': lines[1], 'value': lines[2]}
    nets, native_pins = {}, {}
    for block in re.findall(r'^\(\s*\n(.*?)^\)', native, flags=re.M | re.S):
        lines = [s.strip() for s in block.splitlines() if s.strip()]
        net = lines[0]
        assert net not in nets
        nets[net] = []
        for pin in lines[1:]:
            ref, num = pin.split('-', 1)
            key = ref + '.' + num
            assert key not in native_pins
            native_pins[key] = net
            nets[net].append(key)
    pins, refs, nc, groups, names, find = schematic_geometry(sch)
    assert set(components) == set(refs), 'Native export does not cover all schematic refs'
    assert set(native_pins) <= set(pins), 'Unknown exported pin'
    sch_nets, faults = {}, []
    for key, p in pins.items():
        root = find(p)
        if p in nc:
            sch_nets[key] = ''
            if len(groups[root]) != 1 or names[root] or key in native_pins:
                faults.append({'pin': key, 'error': 'NC connected/exported'})
        else:
            ns = names[root]
            if len(ns) > 1:
                faults.append({'pin': key, 'error': 'conflicting labels', 'labels': sorted(ns)})
            if ns:
                net = next(iter(ns))
                if native_pins.get(key) != net:
                    faults.append({'pin': key, 'error': 'label/export mismatch'})
            else:
                # Unlabelled local wiring: validate its entire pin group against native export.
                values = {native_pins.get(k) for k in groups[root]}
                if len(groups[root]) < 2 or len(values) != 1 or None in values:
                    faults.append({'pin': key, 'error': 'floating/local group mismatch', 'group': groups[root]})
                net = native_pins.get(key, '')
                if set(groups[root]) != set(nets.get(net, [])):
                    faults.append({'pin': key, 'error': 'native local group differs from geometry'})
            sch_nets[key] = native_pins.get(key, '')
    pcb_pins, physical, pcb_refs, duplicates = {}, [], set(), defaultdict(list)
    for shape in pcb['shape']:
        if not shape.startswith('LIB~'):
            continue
        _, *body = shape.split('#@$')
        ref, = [s.split('~')[10] for s in body if s.startswith('TEXT~P~')]
        assert ref not in pcb_refs
        pcb_refs.add(ref)
        for s in body:
            if not s.startswith('PAD~'):
                continue
            f = s.split('~')
            key, net = ref + '.' + f[8], f[7]
            if key in pcb_pins and pcb_pins[key] != net:
                faults.append({'pin': key, 'error': 'duplicate pad number has different net'})
            pcb_pins[key] = net
            duplicates[key].append(f[12])
            physical.append({'pin': key, 'net': net, 'pad_id': f[12]})
    mismatch = [{'pin': k, 'schematic': sch_nets.get(k), 'pcb': pcb_pins.get(k)}
                for k in sorted(set(sch_nets) | set(pcb_pins)) if sch_nets.get(k) != pcb_pins.get(k)]
    report = {
        'date': args.date, 'status': 'PASS' if not faults and not mismatch and set(refs) == pcb_refs else 'FAIL',
        'scope': 'Native Protel schematic export vs saved schematic geometry/NC and PCB pad net assignments. Not copper continuity or full electrical-type ERC.',
        'inputs': {n: {'path': str(getattr(args, n).resolve()), 'sha256': hashlib.sha256(getattr(args, n).read_bytes()).hexdigest()} for n in ('schematic', 'pcb', 'netlist')},
        'counts': {'schematic_refs': len(refs), 'pcb_refs': len(pcb_refs), 'schematic_pins': len(pins), 'pcb_unique_pins': len(pcb_pins), 'physical_pads': len(physical), 'native_nets': len(nets), 'connected_pins': len(native_pins), 'explicit_NC_pins': sum(v == '' for v in sch_nets.values())},
        'ref_difference': sorted(set(refs) ^ pcb_refs), 'geometry_faults': faults, 'pin_net_mismatches': mismatch,
        'duplicate_physical_pads': {k: v for k, v in duplicates.items() if len(v) > 1},
        'native_networks': nets, 'pin_comparison': [{'pin': k, 'schematic': sch_nets.get(k), 'pcb': pcb_pins.get(k)} for k in sorted(set(sch_nets) | set(pcb_pins))],
        'native_schematic_UI': {'refreshed_design_manager': args.native_schematic_ui, 'scope_reference': 'https://docs.lceda.cn/cn/Schematic/Design-Manager/', 'ERC': 'No standalone electrical-type ERC command found in Standard 6.5.51 Design/Tools menus. Record native network check plus explicit design review; do not claim full ERC passed.'},
        'production_released': False,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'counts', 'ref_difference', 'geometry_faults', 'pin_net_mismatches', 'duplicate_physical_pads')}, ensure_ascii=False, indent=2))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
