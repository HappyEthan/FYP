"""布线前关键区局部候选；只读已核验云端回读，不写在线工程。"""
import collections
import hashlib
import json
from pathlib import Path

from repack_a5_local_20260918 import ROOT, audit, shift_with_holes
from build_a5_rf_clearance_layout import ref
from build_a5_usb_front_candidate import rotate_shift_180
from audit_a5_ufl_keepout import audit as audit_ufl

SOURCE = ROOT / 'easyeda_std/PCB_局部重排_槽孔修正后云端回读_20260918.json'
SHA = '45405df1734ccd60cbab39ace39a9e58210ab57bbf10022d86609de2814b63cc'
OUT = ROOT / 'easyeda_std/PCB_布线前关键区局部候选_20260918.json'
REPORT = ROOT / 'easyeda_std/布线前关键区局部候选检查_20260918.json'

# 坐标使用嘉立创界面毫米值。保持主控、USB、传感器和板框不动。
TARGETS = {
    # U.FL 向板边移动并转180度，让信号焊盘朝向匹配网络。
    'ANT1': (29.30, 80.70), 'R30': (28.60, 84.40),
    'C30': (27.20, 84.00), 'C31': (29.45, 83.50),
    # 稳压器及外围退出 U.FL 全层净空候选。
    'U5': (29.40, 78.15), 'C9': (30.70, 76.70),
    'C10': (27.20, 78.50), 'R11': (29.00, 75.60),
    # 上移主控储能和去耦，给 RF_SOC 绕过主控上缘预留通道。
    'C20': (22.48, 86.79), 'C21': (25.27, 86.65),
}


def main():
    raw = SOURCE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA, '当前云端回读已变化，停止套用候选'
    doc = json.loads(raw)
    assert collections.Counter(s.split('~')[0] for s in doc['shape']) == {'LIB': 43, 'CIRCLE': 1}
    before, parts, copper, *_ = audit(SOURCE)
    changed = []
    for i, shape in enumerate(doc['shape']):
        if not shape.startswith('LIB~'):
            continue
        name = ref(shape)
        if name in TARGETS:
            x, y = TARGETS[name]
            origin = parts[name]['center']
            delta = (x-origin[0], -y-origin[1])
            doc['shape'][i] = (rotate_shift_180(shape, delta) if name == 'ANT1'
                               else shift_with_holes(shape, delta))
            changed.append(name)
        elif name == 'Q1':
            chunks = shape.split('#@$')
            for j, chunk in enumerate(chunks):
                fields = chunk.split('~')
                if fields[0] == 'PAD':
                    assert fields[18] == '0.2'
                    fields[18] = '0'  # 1:1 阻焊开窗；铜和钢网不变。
                    chunks[j] = '~'.join(fields)
            doc['shape'][i] = '#@$'.join(chunks)
            changed.append(name)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n')
    after, new_parts, new_copper, *_ = audit(OUT)
    signature = lambda ps: sorted((p['ref'], p['pin'], p['net'], p['kind'], p['layer']) for p in ps)
    assert signature(copper) == signature(new_copper)
    assert len(new_parts) == 43
    ufl, _, regions = audit_ufl(OUT)
    assert not regions['中心禁走线区']['现有焊盘过孔相交']
    assert not regions['本体全层净空候选']['现有焊盘过孔相交']
    assert not after['铜间隙小于0.1524mm']
    assert not after['铜到板边小于0.2mm']
    assert not after['定位孔到其他铜小于0.2mm']
    report = {
        '来源': SOURCE.name, '来源SHA256': SHA,
        '仅调整': sorted(changed),
        '调整前': before, '调整后': after,
        'U.FL中心禁走线区冲突': regions['中心禁走线区']['现有焊盘过孔相交'],
        'U.FL全层净空候选冲突': regions['本体全层净空候选']['现有焊盘过孔相交'],
        'Q1': '铜焊盘保持原厂推荐尺寸；仅将三焊盘阻焊扩展从0.0508mm改为0，形成1:1开窗候选',
        '网络脚号与层保持': True, '原生在线工程已修改': False,
        '生产放行': False,
        '未覆盖': '器件本体/装配、RF阻抗与真实参考平面、钢网、热、正式布线及原生DRC',
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
