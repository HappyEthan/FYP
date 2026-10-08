#!/usr/bin/env python3
"""Read two explicit native PCB snapshots; write review evidence only.

Does not import historical generators, change PCB files, run native DRC,
or produce machine placement instructions. All coordinates use source axes.
"""
import argparse
import collections
import hashlib
import json
import re
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(document):
    result = {}
    for shape in document['shape']:
        if not shape.startswith('LIB~'):
            continue
        header, *children = shape.split('#@$')
        header = header.split('~')
        refs = [s.split('~')[10] for s in children if s.startswith('TEXT~P~')]
        if len(refs) != 1 or refs[0] in result:
            raise ValueError('Missing or duplicate reference designator')
        fields = header[3].split('`')
        result[refs[0]] = (header, dict(zip(fields[::2], fields[1::2])), children)
    return result


def normalise_path(shape):
    fields = shape.split('~')
    index = {'TEXT': 11, 'SOLIDREGION': 3}.get(fields[0])
    if index is not None:
        fields[index] = ' '.join(fields[index].split())
    return '~'.join(fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() in {args.baseline.resolve(), args.snapshot.resolve()}:
        raise ValueError('Output must not overwrite an input')
    baseline = json.loads(args.baseline.read_text())
    snapshot = json.loads(args.snapshot.read_text())
    old, new = parse(baseline), parse(snapshot)
    report = {
        'status': '仅审核；本地快照预审；当前云端身份/保存状态待用户新导出确认；禁止生产',
        'baseline': {'path': str(args.baseline.resolve()), 'sha256': digest(args.baseline)},
        'snapshot': {'path': str(args.snapshot.resolve()), 'sha256': digest(args.snapshot),
                     'bytes': args.snapshot.stat().st_size},
        'native_DRC_this_run': '未运行；不能由源码比较替代',
        'live_schematic_consistency': '待当前五页原理图导出及ERC',
        'added_refs': sorted(new.keys() - old.keys()),
        'removed_refs': sorted(old.keys() - new.keys()),
        'nonshape_changed_keys': [k for k in baseline.keys() | snapshot.keys()
                                  if k != 'shape' and baseline.get(k) != snapshot.get(k)],
        'board_nonLIB_exact_multiset_equal': collections.Counter(
            s for s in baseline['shape'] if not s.startswith('LIB~')) == collections.Counter(
            s for s in snapshot['shape'] if not s.startswith('LIB~')),
        'component_changes': [], 'parts': [],
        'coordinate_convention': 'x/y相对源码head原点，内部单位乘0.254mm；保留源码Y轴及原生角度；底层未镜像。不是机器坐标/CPL。',
        'model_limit': 'SVGNODE平面包络及绑定参数；z为节点偏移原值，不是器件高度。未读取三维网格或验算碰撞。',
    }
    for ref in sorted(new):
        h, attributes, children = new[ref]
        pads = [s.split('~') for s in children if s.startswith('PAD~')]
        models = [json.loads(s.split('~', 1)[1])['attrs']
                  for s in children if s.startswith('SVGNODE~')]
        kind = ('纯飞线焊盘' if ref in {'J2', 'J4', 'SW1'} else
                'DNP' if attributes.get('装配状态') == '不装配' else '拟贴装')
        report['parts'].append({
            'ref': ref, 'kind': kind, 'source_attributes': attributes,
            'source_lib_id': h[6], 'side': {'1': '顶层', '2': '底层'}.get(h[7], h[7]),
            'source_xy_mm': [round((float(h[i]) - float(snapshot['head'][axis])) * .254, 7)
                             for i, axis in [(1, 'x'), (2, 'y')]],
            'native_rotation_deg': float(h[4] or 0),
            'pads': [{'number': p[8], 'net': p[7], 'layer': p[6],
                      'raw_native_pad': '~'.join(p)} for p in pads],
            'model_attributes': models,
            'model_nominal_planar_mm': [[round(float(m['c_width']) * .254, 6),
                                         round(float(m['c_height']) * .254, 6)] for m in models],
            'placement_verified': False,
            'procurement_status': ('非SMT采购项' if kind != '拟贴装' else
                                   '原生仅标称值，完整采购料号未写入' if ref[0] in 'RC' else
                                   '板上插座与外接天线混写，完整后缀待拆分' if ref == 'ANT1' else
                                   '原生有型号；本轮未核供应/客供/极性与机器角度'),
        })
        if ref not in old:
            continue
        oh, oa, oc = old[ref]
        raw_before = collections.Counter(s for s in oc if not s.startswith('SVGNODE~'))
        raw_after = collections.Counter(s for s in children if not s.startswith('SVGNODE~'))
        before = collections.Counter(normalise_path(s) for s in raw_before.elements())
        after = collections.Counter(normalise_path(s) for s in raw_after.elements())
        residual_before, residual_after = list((before-after).elements()), list((after-before).elements())
        delta = {
            'ref': ref,
            'non_attribute_header_changed_fields': [i for i in range(max(len(h), len(oh)))
                                                   if i != 3 and h[i:i+1] != oh[i:i+1]],
            'attribute_changes': {k: [oa.get(k), attributes.get(k)] for k in oa.keys() | attributes.keys()
                                  if oa.get(k) != attributes.get(k)},
            'copper_pads_exact_equal': collections.Counter(s for s in oc if s.startswith('PAD~')) ==
                                      collections.Counter(s for s in children if s.startswith('PAD~')),
            'model_count_before': sum(s.startswith('SVGNODE~') for s in oc),
            'model_count_after': len(models),
            'model_attributes_before': [json.loads(s.split('~', 1)[1])['attrs']
                                        for s in oc if s.startswith('SVGNODE~')],
            'model_attributes_after': models,
            'nonmodel_raw_changed_count': sum((raw_before-raw_after).values()),
            'nonmodel_residual_before': residual_before,
            'nonmodel_residual_after': residual_after,
            'nonmodel_residual_after_path_whitespace_only': [],
        }
        # Retain all residual text differences, including exact before/after strings.
        for prior in residual_before:
            pf = prior.split('~')
            match = next((s for s in residual_after if s.split('~')[:11] == pf[:11]), None)
            detail = {'before': prior, 'after': match}
            if match and pf[0] == 'TEXT':
                af = match.split('~')
                pattern = r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?'
                pt, at = re.findall(pattern, pf[11]), re.findall(pattern, af[11])
                same_ops = len(pt) == len(at) and all(
                    x == y for x, y in zip(pt, at) if x.isalpha() or y.isalpha())
                detail['same_path_commands'] = same_ops
                if same_ops:
                    detail['max_coordinate_delta_mm'] = max(
                        [abs(float(x)-float(y))*.254 for x,y in zip(pt,at)
                         if not x.isalpha()] or [0])
            delta['nonmodel_residual_after_path_whitespace_only'].append(detail)
        if residual_after and not residual_before:
            delta['nonmodel_residual_after_path_whitespace_only'].append({'unmatched_added': residual_after})
        report['component_changes'].append(delta)
    report['counts'] = dict(collections.Counter(p['kind'] for p in report['parts']))
    report['counts']['components'] = len(new)
    report['counts']['models'] = sum(len(p['model_attributes']) for p in report['parts'])
    report['counts']['pad_named_nets'] = len({pad['net'] for p in report['parts'] for pad in p['pads'] if pad['net']})
    q = next(p for p in report['parts'] if p['ref'] == 'Q1')
    qp = {p['number']: p['raw_native_pad'].split('~') for p in q['pads']}
    a, b = qp['2'], qp['3']
    report['Q1_local_only'] = {
        'pad_pair': ['2 USB_5V', '3 VSYS'],
        'axis_aligned_edge_gap_mm': (abs(float(a[3])-float(b[3]))-(float(a[5])+float(b[5]))/2)*.254,
        'power_rule_clearance_mm': snapshot['DRCRULE']['电源']['clearance']*.254,
        'conclusion': '几何间距仍小于现有电源间距规则；沉金不消除规则差异。待原生DRC及国内阻焊/钢网工艺确认，未忽略或修改规则。',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'output': str(args.output.resolve()), 'counts': report['counts'],
                      'Q1': report['Q1_local_only']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
