"""核对用户授权覆盖的现有克隆，保存记录不代表生产验收。"""
import hashlib
import json
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
eda = root / 'easyeda_std'
downloads = Path('/Users/liuchunyu/Downloads')
before = downloads / 'PCBUSBcloudBeforeN20260929.json'
reopen = downloads / 'PCBUSBcloudReopenN20260929.json'
native = eda / 'PCB_克隆板USB局部重布_原生回读_20260929.json'
baseline = eda / 'PCB_克隆板批量补线_原生回读_20260928.json'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(native) == 'f998ec51c0e39f8677129d6a72361ed6ccfdadbf1a4a4367d3309032408a1c45'
a, b = [json.loads(p.read_text()) for p in (before, baseline)]
assert Counter(a['shape']) == Counter(b['shape'])
assert a['DRCRULE'] == b['DRCRULE']
assert reopen.read_bytes() == native.read_bytes()
report = {
    '目标工程': '圆形传感板_SCH_A5',
    '目标PCB': 'PCB_圆形传感板_SCH_A5 copy',
    '文档ID': 'cca094630ebf453c98ae64b900f0d7f0',
    '用户已授权覆盖现有克隆': True,
    '新增云端文档': False, '原版PCB修改': False,
    '覆盖前备份': str(before), '覆盖前SHA256': sha(before),
    '覆盖前图元与规则符合历史基线': True,
    '关闭重开回读': str(reopen), '重开SHA256': sha(reopen),
    '与N原生回读逐字节一致': True,
    '已保存并关闭重开验证': True,
    '原生DRC_界面实测': {
        '临时N标签': 1, '云端关闭重开后': 21,
        '重开后重新铺铜复查': 21, '未连接': 0,
        'Q1焊盘间距': 1, '圆形板框提示': 20,
        '板框分项': {'导线': 6, '焊盘': 11, '过孔': 3},
        '提示板框对象': ['circle_gge5580', 'circle_gge5583'],
        '说明': '相同源码在临时标签与云端重开后结果不同；不可视为仅1项、不可直接认定误报，不降低规则或忽略提示',
    },
    '本次几何或规则修改': False,
    'USB性能已验收': False, '制造已验收': False, '允许生产': False,
    '下一步': '先定位可复现的圆形板框DRC差异，再继续USB参考地、阻抗、电源去耦及制造审核',
}
(eda / '克隆板USB云端保存核验_20260929.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
main = eda / '克隆板USB局部重布检查_20260928.json'
d = json.loads(main.read_text())
d['当前云端保存状态'] = report
main.write_text(json.dumps(d, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False, indent=2))
