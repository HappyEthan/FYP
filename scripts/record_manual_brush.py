"""Organize and open manual brush recording; never connect a robot."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ['recording_id', 'created_at', 'action', 'sensor_csv', 'sensor_json',
           'sample_count', 'duration_s', 'valid', 'photo', 'video', 'note']


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def prepare_session(root, *, brush_id='brush2', label='dunbi', action='dot'):
    for name, value in [('brush_id', brush_id), ('label', label)]:
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value):
            raise ValueError(name+' must use letters, digits, hyphens or underscores')
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    parent = Path(root)/brush_id/'manual'
    folder = parent/now.strftime('%Y-%m-%d')/(now.strftime('%H-%M-%S_%f')+'__'+label)
    folder.mkdir(parents=True, exist_ok=False)
    for name in ['raw', 'media', 'analysis']:
        (folder/name).mkdir()
    write_json(folder/'session.json', dict(
        schema_version=1, session_id=folder.name, created_at=now.isoformat(),
        timezone='Asia/Shanghai', acquisition_mode='handheld_manual',
        brush_id=brush_id, label=label, default_action=action,
        sensor_tip_offset_mm=dict(value=5., source='operator_report', measured=False),
        paper=None, ink_or_water=None, wetting_method=None, brush_orientation=None,
        tcp_recorded=False, xy_recorded=False, video_synchronization='not_established',
        signal_storage='unfiltered delta B plus baseline; no display smoothing',
        raw_format='monitor CSV + same-stem JSON', note=''))
    (folder/'README.md').write_text(
        '# 手采批次\n\n'
        '- `raw/`：按开始/停止录制生成的 CSV 和同名 JSON；保留原样。CSV 是未经显示平滑的三轴 ΔB，JSON 保存基线和采样质量。原始 B 可由 ΔB + B0 重建，但这里没有保存完整原始串口报文。\n'
        '- `media/`：照片和视频。建议与对应磁记录同名前缀，例如 `<recording_id>_ink.jpeg`、`<recording_id>_top.mp4`。\n'
        '- `analysis/`：裁剪、滤波、拟合、图表等派生结果，不覆盖 raw。\n'
        '- `records.csv`：每条录制一行，可填写动作类型、照片、视频及备注。照片和视频路径相对本批目录。自动更新时保留已填写的 action/photo/video/note。\n'
        '- `session.json`：补填纸张、墨/水、蘸水方式和姿态。未知条件保持 null，不以计划值代替实测。\n\n'
        '每条记录单独按一次开始/停止，按实际动作填写 `dot`（顿笔）、`dot_retract`（顿笔短收）、`heng`（横）或自定义标签。\n'
        '开始前悬空静止取基线；一条动作结束再停止，保留少量前后空载数据。视频默认未同步，不能直接当作机器人 XY 或同步 TCP 示教。\n\n'
        '重新打开本批：\n\n'
        '```bash\ncd /home/serein/FYP\n'
        f'QT_QPA_PLATFORM=wayland PYTHONPATH=src .venv/bin/python scripts/record_manual_brush.py --session "{folder.resolve()}"\n```\n',
        encoding='utf-8')
    if not (parent/'README.md').exists():
        (parent/'README.md').write_text(
            '# brush2 手采实验\n\n'
            '按 `日期/时间__批次名/` 保存手持毛笔的录制，与日期目录下的机器人执行实验分开。\n'
            '新建批次：`PYTHONPATH=src .venv/bin/python scripts/record_manual_brush.py --label dunbi`。\n'
            '每批保留 raw、media、analysis、session.json、records.csv 和操作说明。未录制的空批次不算实测数据。\n',
            encoding='utf-8')
    refresh_index(folder)
    return folder


def refresh_index(folder):
    folder = Path(folder)
    session = json.loads((folder/'session.json').read_text(encoding='utf-8'))
    if session.get('schema_version') != 1 or session.get('acquisition_mode') != 'handheld_manual':
        raise ValueError('not a supported manual session')
    path = folder/'records.csv'
    existing = {}
    if path.exists():
        with path.open(newline='', encoding='utf-8') as stream:
            existing = {row['recording_id']: row for row in csv.DictReader(stream)}
    rows = []
    for metadata in sorted((folder/'raw').glob('*.json')):
        sensor_csv = metadata.with_suffix('.csv')
        if not sensor_csv.is_file():
            continue
        meta = json.loads(metadata.read_text(encoding='utf-8'))
        row = dict(recording_id=metadata.stem, created_at=meta.get('created_at', ''),
                   action=session.get('default_action', 'unlabelled'),
                   sensor_csv=str(sensor_csv.relative_to(folder)),
                   sensor_json=str(metadata.relative_to(folder)),
                   sample_count=meta.get('sample_count', ''), duration_s=meta.get('measured_duration_s', ''),
                   valid=meta.get('valid', ''), photo='', video='', note=meta.get('note', ''))
        old = existing.pop(metadata.stem, {})
        row.update({key: old[key] for key in ['action', 'photo', 'video', 'note'] if key in old})
        rows.append(row)
    # Keep previously indexed rows if a source file is temporarily unavailable.
    rows.extend(existing.values())
    temporary = path.with_suffix('.csv.tmp')
    with temporary.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)
    return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, help='resume an existing session')
    parser.add_argument('--root', type=Path, default=ROOT/'runs')
    parser.add_argument('--brush-id', default='brush2')
    parser.add_argument('--label', default='dunbi')
    parser.add_argument('--action', default='dot')
    parser.add_argument('--port', default='/dev/ttyACM0')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--index-only', action='store_true')
    args = parser.parse_args(argv)
    folder = args.session.resolve() if args.session else prepare_session(
        args.root, brush_id=args.brush_id, label=args.label, action=args.action).resolve()
    refresh_index(folder)
    print('手采批次:', folder, flush=True)
    if args.prepare_only or args.index_only:
        return 0
    # GUI imports are deferred so preparation and indexing stay hardware-free.
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        os.environ.setdefault('QT_QPA_PLATFORM', 'wayland')
    from PyQt5 import QtWidgets
    from brushbot.monitor.window import MonitorWindow

    class ManualWindow(MonitorWindow):
        def _stop_record(self, valid=True, note=''):
            super()._stop_record(valid=valid, note=note)
            try:
                refresh_index(folder)
            except Exception as exc:
                self.statusBar().showMessage('录制文件保留；更新手采索引失败: '+str(exc), 10000)

    app = QtWidgets.QApplication([])
    window = ManualWindow(out_dir=str(folder/'raw'), config_dir=str(ROOT/'configs'),
                          control_socket='/tmp/brushbot-manual-monitor.sock')
    window.setWindowTitle('手采磁触觉 · '+folder.name)
    window._set_src_mode('串口')
    window.ed_port.setText(args.port)
    window.show()
    try:
        return app.exec_()
    finally:
        refresh_index(folder)


if __name__ == '__main__':
    sys.exit(main())
