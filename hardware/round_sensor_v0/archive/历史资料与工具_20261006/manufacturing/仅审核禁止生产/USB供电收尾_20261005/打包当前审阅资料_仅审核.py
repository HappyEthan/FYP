"""组装本轮内部审阅包；仅写ZIP/清单，不生成或更改CAD/制造几何。"""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
previous = ROOT / 'manufacturing/仅审核禁止生产/圆形传感板_C9替料_仅审核_20261005.zip'
assert hashlib.sha256(previous.read_bytes()).hexdigest() == '41b73f297fc5e72d225c92484230d815d161424d9da7941f0a06c26a48b5abd8'
files = {}
with zipfile.ZipFile(previous) as z:
    for name in z.namelist():
        if name.startswith('README_') or name.endswith('SHA256_审阅包文件清单.json'):
            continue
        files[name] = z.read(name)

for name in ['CAD_HANDOFF.md', 'AGENTS.md', 'DESIGN_BASELINE_XIAO_PICO.md',
             'README_USB供电审阅包_仅审核.md', 'scripts/check_pcb_a5.py',
             'references/esp32-s3_TRM_USB审核_20261005.pdf', 'references/esp32-s3_chip_current.pdf']:
    files[name] = (ROOT / name).read_bytes()
for p in OUT.iterdir():
    if p.is_file() and p.suffix in ['.md', '.py', '.json'] and p.name not in ['SHA256_审阅包文件清单.json', '审阅包校验结果_仅审核.json']:
        files[str(p.relative_to(ROOT))] = p.read_bytes()

record = json.loads((OUT / '当前USB供电与无充电预算_仅审核.json').read_text())
for item in record['inputs'].values():
    assert hashlib.sha256(files[item['path']]).hexdigest() == item['sha256']
    assert (ROOT / item['path']).read_bytes() == files[item['path']]
assert len([n for n in files if n.endswith('.zip')]) == 1
assert not any('U4' in n for n in files if n.endswith('.csv'))

manifest = {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in sorted(files.items())}
mp = OUT / 'SHA256_审阅包文件清单.json'
mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
files[str(mp.relative_to(ROOT))] = mp.read_bytes()
destination = ROOT / 'manufacturing/仅审核禁止生产/圆形传感板_USB供电审阅_仅审核_20261005.zip'
with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
    for name, data in sorted(files.items()):
        z.writestr(name, data)
with zipfile.ZipFile(destination) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == len(files) == len(set(z.namelist()))
    for name, item in manifest.items():
        assert hashlib.sha256(z.read(name)).hexdigest() == item['sha256']
    assert len([n for n in z.namelist() if n.endswith('.zip')]) == 1

result = {
    'package': str(destination), 'date': '2026-10-05',
    'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
    'bytes': destination.stat().st_size, 'files': len(files),
    'testzip': None, 'all_manifest_hashes_verified': True,
    'only_one_current_Gerber': True, 'current_PCB_SCH_Gerber_unchanged': True,
    'USB_firmware_and_bench_gates_passed': False,
    'production_released': False,
}
(OUT / '审阅包校验结果_仅审核.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
