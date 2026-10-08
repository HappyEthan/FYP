"""一次性整理已核对的 PCB 下载文件；默认只预览，绝不永久删除。"""
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = Path('/Users/liuchunyu/Downloads')
TRASH = Path('/Users/liuchunyu/.Trash/fyp_pcb_downloads_20260929')
ARCHIVE = ROOT / 'archive/下载历史_20260929.zip'
CURRENT = ROOT / 'archive/R核验与Q恢复_20260929'
GERBER = ROOT / 'manufacturing/仅审核禁止生产'
MANIFEST = ROOT / '清理清单_20260929.json'
KEEP = {
    'PCBMLXBeforeR20260929.json',
    'PCBMLXNativeR20260929.json',
    'PCBMLXNativeR20260929.usb.json',
    'PCBMLXNativeR20260929.power.json',
}
EXTRA = {
    'charger_now.png', 'SGM40567_pin_check-03.png',
    'SGM40567_land_check-14.png', 'USB_I_route_review.png',
    'MLX_ground_debug.png',
    'SCH_round_sensor_SCH_A2_bound60_2026-09-15.json',
}
RGERBER = 'Gerber_圆形传感板_R_仅审核禁止生产_20260929.zip'
CLOUD = 'PCBMLXCloudReopenR20260929.json'
CANONICAL = ROOT / 'easyeda_std/PCB_克隆板USB局部重布_原生回读_20260929.json'

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def selected(p):
    return p.is_file() and not p.is_symlink() and (
        p.name.startswith(('PCBUSB', 'PCBMLX', 'PCBpower', 'PCB_克隆板',
                           'PCB_PCB_圆形传感板', 'PCB_临时补线',
                           'PCB_round_sensor_', 'PCBLIB_USB4105_',
                           'PCBstagingbackup', 'Gerber_圆形传感板_'))
        or p.name in EXTRA)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    assert not MANIFEST.exists(), '已有清理清单，禁止重复执行'
    files = sorted(p for p in DOWNLOADS.iterdir() if selected(p))
    assert files and all(p.parent == DOWNLOADS for p in files)
    expected = {
        CANONICAL: 'c3c0d4e5630df0b756df07d380213af8edc1a5eab8da054e44c54a5e4e337954',
        DOWNLOADS / CLOUD: 'c3c0d4e5630df0b756df07d380213af8edc1a5eab8da054e44c54a5e4e337954',
        DOWNLOADS / 'PCBMLXBeforeR20260929.json': '26cdf1c80dbe3e5bc43660953d9f6fdb41da61ddeb4cee2725395cdcbd236eb8',
        DOWNLOADS / 'PCBMLXNativeR20260929.json': 'aa0227ce2340d43c39341f66b20747049edb6b9e990939ee8f0d5c8269fe8d25',
        DOWNLOADS / RGERBER: '3660b1f776e00ce33d671d8ed88066fd348e57455e6e41f433869474edd8d3f1',
    }
    for p, sha in expected.items():
        assert digest(p) == sha, f'来源已改变：{p}'
    records = []
    for p in files:
        if p.name in KEEP:
            target, action = CURRENT / p.name, '保留核验或恢复输入'
        elif p.name == RGERBER:
            target, action = GERBER / p.name, '当前制造审核包，禁止生产'
        else:
            target, action = TRASH / p.name, '移入废纸篓；历史压缩包另有留档'
        assert not target.exists(), f'禁止覆盖：{target}'
        records.append(dict(source=str(p), destination=str(target), action=action,
                            sha256=digest(p), bytes=p.stat().st_size))
    print(json.dumps({'文件数': len(records), '字节数': sum(x['bytes'] for x in records),
                      '保留散文件': len(KEEP) + 1, '废纸篓': len(records)-len(KEEP)-1,
                      '文件': [Path(x['source']).name for x in records]}, ensure_ascii=False, indent=2))
    if not args.apply:
        return
    assert not ARCHIVE.exists() and not TRASH.exists()
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    # 先归档并逐文件回读核验，再移动散文件；中途失败仍保留可恢复副本。
    with zipfile.ZipFile(ARCHIVE, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for row in records:
            if Path(row['destination']).parent == TRASH:
                z.write(row['source'], Path(row['source']).name)
    with zipfile.ZipFile(ARCHIVE) as z:
        assert z.testzip() is None
        for row in records:
            if Path(row['destination']).parent == TRASH:
                assert hashlib.sha256(z.read(Path(row['source']).name)).hexdigest() == row['sha256']
    result = {'日期': '2026-09-29', '范围': '仅已识别的圆形传感板下载散文件',
              '永久删除': False, '云端变更': False, '历史压缩包': str(ARCHIVE),
              '历史压缩包SHA256': digest(ARCHIVE), '当前PCB': str(CANONICAL),
              '当前PCBSHA256': digest(CANONICAL), '文件': records, '状态': '移动前清单'}
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    for row in records:
        p, target = Path(row['source']), Path(row['destination'])
        assert digest(p) == row['sha256']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(target))
        assert digest(target) == row['sha256'] and not p.exists()
    assert digest(CANONICAL) == expected[CANONICAL]
    result['状态'] = '全部移动完成，目标哈希核验通过'
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print('完成：当前设计内容未变；逐文件哈希、历史压缩包与恢复文件核验通过。')

if __name__ == '__main__':
    main()
