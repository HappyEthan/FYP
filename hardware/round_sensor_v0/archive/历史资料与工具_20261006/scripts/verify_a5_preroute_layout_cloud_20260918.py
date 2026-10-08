"""核验布线前关键区布局已保存、重开并由云端回读。"""
import collections
import hashlib
import json
import math

import build_a5_preroute_layout_candidate_20260918 as candidate
from audit_a5_ufl_keepout import audit as audit_ufl
from repack_a5_local_20260918 import audit


ROOT = candidate.ROOT
CANDIDATE = candidate.OUT
CLOUD = ROOT / 'easyeda_std/PCB_布线前关键区布局_云端重开回读_20260918.json'
REPORT = ROOT / 'easyeda_std/布线前关键区布局_云端核验记录_20260918.json'


def component_signature(parts):
    return {
        ref: (part['id'], part['layer'], part['rotation'])
        for ref, part in parts.items()
    }


def copper_groups(copper):
    groups = collections.defaultdict(list)
    for item in copper:
        key = (item['ref'], item['pin'], item['net'], item['layer'], item['kind'])
        groups[key].append(item['poly'])
    for polys in groups.values():
        polys.sort(key=lambda poly: tuple(sum(p[i] for p in poly) / len(poly) for i in (0, 1)))
    return groups


def verify():
    candidate.main()
    local_doc = json.loads(CANDIDATE.read_text())
    cloud_doc = json.loads(CLOUD.read_text())
    assert local_doc.keys() == cloud_doc.keys()
    assert local_doc['canvas'] == cloud_doc['canvas']
    assert local_doc['DRCRULE'] == cloud_doc['DRCRULE']
    assert collections.Counter(s.split('~')[0] for s in cloud_doc['shape']) == {
        'LIB': 43, 'CIRCLE': 1,
    }

    local_audit, local_parts, local_copper, local_holes, *_ = audit(CANDIDATE)
    cloud_audit, cloud_parts, cloud_copper, cloud_holes, *_ = audit(CLOUD)
    assert set(local_parts) == set(cloud_parts)
    assert component_signature(local_parts) == component_signature(cloud_parts)

    center_delta = max(
        math.dist(local_parts[ref]['center'], cloud_parts[ref]['center'])
        for ref in local_parts
    )
    assert center_delta < 0.00003
    for ref, target in candidate.TARGETS.items():
        # 生成器目标使用界面绝对Y；解析器以画布原点为基准，向上为负Y。
        parsed_target = (target[0], -target[1])
        assert math.dist(cloud_parts[ref]['center'], parsed_target) < 0.00003

    local_groups = copper_groups(local_copper)
    cloud_groups = copper_groups(cloud_copper)
    assert local_groups.keys() == cloud_groups.keys()
    copper_delta = 0.0
    for key in local_groups:
        assert len(local_groups[key]) == len(cloud_groups[key])
        for before, after in zip(local_groups[key], cloud_groups[key]):
            assert len(before) == len(after)
            copper_delta = max(copper_delta, *(math.dist(a, b) for a, b in zip(before, after)))
    # 原生保存会把部分LIB头坐标归一化到4位小数；允许小于0.0002 mm的序列化差。
    assert copper_delta < 0.0002

    assert len(local_holes) == len(cloud_holes)
    hole_delta = 0.0
    for before, after in zip(local_holes, cloud_holes):
        assert before['ref'] == after['ref'] and len(before['poly']) == len(after['poly'])
        hole_delta = max(hole_delta, *(math.dist(a, b) for a, b in zip(before['poly'], after['poly'])))
    assert hole_delta < 0.00003

    q1_mask = [item[18] for item in cloud_parts['Q1']['items'] if item[0] == 'PAD']
    assert q1_mask == ['0', '0', '0']
    assert cloud_parts['ANT1']['rotation'] == '180'

    _, _, ufl_regions = audit_ufl(CLOUD)
    assert not ufl_regions['中心禁走线区']['现有焊盘过孔相交']
    assert not ufl_regions['本体全层净空候选']['现有焊盘过孔相交']
    assert not cloud_audit['铜间隙小于0.1524mm']
    assert not cloud_audit['铜到板边小于0.2mm']
    assert not cloud_audit['定位孔到其他铜小于0.2mm']
    assert cloud_audit == local_audit

    return {
        '日期': '2026-09-18',
        '云端工程': '圆形传感板_SCH_A5',
        '云端PCB': 'PCB_圆形传感板_SCH_A5',
        '候选文件': CANDIDATE.name,
        '候选SHA256': hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
        '云端重开回读文件': CLOUD.name,
        '云端重开回读SHA256': hashlib.sha256(CLOUD.read_bytes()).hexdigest(),
        'UI实际观察': {
            '写回的是现有PCB': True,
            '未新增云端PCB': True,
            '保存成功且星号消失': True,
            '关闭后从工程树重开': True,
            '重开后原生DRC总数': 123,
            '重开后未完成连接': 122,
            '重开后Q1内部间距': 1,
            '另一张未保存工作版未触碰': True,
        },
        '元件数': 43,
        '网络数': 21,
        '元件层和旋转保持': True,
        '关键元件目标坐标保持': True,
        '元件中心最大回读变化_mm': center_delta,
        '铜轮廓最大回读变化_mm': copper_delta,
        '定位孔轮廓最大回读变化_mm': hole_delta,
        'Q1铜与钢网未改': True,
        'Q1三焊盘1比1阻焊开窗': True,
        'ANT1方向': '180度，信号焊盘朝匹配网络',
        'U.FL中心禁走线区冲突': [],
        'U.FL全层净空候选冲突': [],
        '本地铜和板边几何初筛': cloud_audit,
        'DRC规则保持': True,
        '制造放行': False,
        '限制': '仍未正式布线；Q1原厂0.14mm铜间距仍需板厂工艺确认；未验证50欧射频、连续参考地、Gerber、钢网、热、装配和整机机械。',
    }


if __name__ == '__main__':
    result = verify()
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
