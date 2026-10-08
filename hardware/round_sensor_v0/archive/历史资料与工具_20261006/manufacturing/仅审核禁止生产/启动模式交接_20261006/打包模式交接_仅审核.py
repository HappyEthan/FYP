"""仅更新审阅包中的需求/交接；CAD、Gerber、BOM/CPL必须保持当前哈希。"""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
previous = ROOT / 'manufacturing/仅审核禁止生产/圆形传感板_USB供电审阅_仅审核_20261005.zip'
expected_previous = '07c77b1bf9563621c38acc8a1f4ebf3e6eeddfdc668d64ef97e373089a04bf43'
assert hashlib.sha256(previous.read_bytes()).hexdigest() == expected_previous
files = {}
with zipfile.ZipFile(previous) as z:
    for name in z.namelist():
        if name.endswith('SHA256_审阅包文件清单.json'):
            continue
        files[name] = z.read(name)

updated = ['AGENTS.md', 'DESIGN_BASELINE_XIAO_PICO.md', 'CAD_HANDOFF.md',
           'README_USB供电审阅包_仅审核.md',
           'manufacturing/仅审核禁止生产/USB供电收尾_20261005/给博后的待确认清单_仅审核.md']
for name in updated:
    files[name] = (ROOT / name).read_bytes()
script = Path(__file__).resolve()
files[str(script.relative_to(ROOT))] = script.read_bytes()
record = json.loads((ROOT / 'manufacturing/仅审核禁止生产/USB供电收尾_20261005/当前USB供电与无充电预算_仅审核.json').read_text())
for value in record['inputs'].values():
    assert hashlib.sha256((ROOT / value['path']).read_bytes()).hexdigest() == value['sha256']
    assert hashlib.sha256(files[value['path']]).hexdigest() == value['sha256']
with zipfile.ZipFile(previous) as z:
    for name in files:
        if name in z.namelist() and name not in updated:
            assert files[name] == z.read(name), name
assert len([n for n in files if n.endswith('.zip')]) == 1

manifest = {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in sorted(files.items())}
manifest_path = OUT / 'SHA256_审阅包文件清单.json'
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
files[str(manifest_path.relative_to(ROOT))] = manifest_path.read_bytes()
destination = ROOT / 'manufacturing/仅审核禁止生产/圆形传感板_启动模式交接_仅审核_20261006.zip'
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
    for name, data in sorted(files.items()):
        z.writestr(name, data)
with zipfile.ZipFile(destination) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == len(files) == len(set(z.namelist()))
    for name, value in manifest.items():
        assert hashlib.sha256(z.read(name)).hexdigest() == value['sha256']
    gerbers = [n for n in z.namelist() if n.endswith('.zip')]
    assert len(gerbers) == 1

result = {
    'date': '2026-10-06', 'scope': '更新需求、推荐固件交互规格与博后确认清单；未编码或操作在线EDA',
    'package': str(destination), 'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
    'bytes': destination.stat().st_size, 'files': len(files),
    'all_manifest_hashes_verified': True, 'testzip': None,
    'one_current_Gerber': gerbers[0],
    'PCB_SCH_Gerber_BOM_CPL_unchanged': True, 'firmware_implemented': False,
    'native_DRC_rerun': False, 'production_released': False,
    'prior_package_preserved_sha256': expected_previous,
}
(OUT / '审阅包校验结果_仅审核.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
