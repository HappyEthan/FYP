"""Naming, browsing, and offline viewing of successful brush experiments."""
import csv
from datetime import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PyQt5 import QtCore, QtWidgets as W
from PyQt5.QtGui import QDesktopServices
import pyqtgraph as pg

from brushbot.experiments.archive import validate_name
from brushbot.experiments.reproduce import load_control, open_bundle, read_json


class ExperimentNameDialog(W.QDialog):
    def __init__(self, store, folder, *, completion=False, parent=None):
        super().__init__(parent)
        self.store, self.folder, self.completion = store, Path(folder), completion
        self.record = read_json(self.folder, 'experiment.json')
        self.setWindowTitle('试写成功 · 实验命名' if completion else '重命名实验')
        self.setMinimumWidth(470)
        layout = W.QFormLayout(self)
        if completion:
            layout.addRow(W.QLabel('试写成功，数据已保存。直接回车沿用当前名称。'))
        self.name = W.QLineEdit(self.record['base_name'])
        layout.addRow('实验名称', self.name)
        self.preview = W.QLabel()
        self.preview.setWordWrap(True)
        layout.addRow('保存名称', self.preview)
        self.error = W.QLabel()
        self.error.setStyleSheet('color:#b42318')
        self.error.setWordWrap(True)
        layout.addRow(self.error)
        box = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        box.button(W.QDialogButtonBox.Ok).setText('完成' if completion else '重命名')
        box.button(W.QDialogButtonBox.Cancel).setText('保留当前名称')
        box.accepted.connect(self.save)
        box.rejected.connect(self.reject)
        layout.addRow(box)
        self.name.textChanged.connect(self.update_preview)
        self.update_preview()
        self.name.selectAll()

    def update_preview(self):
        try:
            base = validate_name(self.name.text())
            self.preview.setText(self.folder.name if base == self.record['base_name'] else self.store.preview_name(base))
            self.error.clear()
        except ValueError as exc:
            self.preview.setText('—')
            self.error.setText(str(exc))

    def save(self):
        try:
            self.folder = self.store.rename(self.folder, self.name.text(), remember=self.completion)
            self.accept()
        except (OSError, ValueError, KeyError) as exc:
            self.error.setText(str(exc))


def name_completed_experiment(store, folder):
    """Closing or interrupting naming always leaves the default successful archive."""
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        while True:
            try:
                record = read_json(folder, 'experiment.json')
                answer = input(f'试写成功，实验名称 [{record["base_name"]}]（回车沿用）: ').strip()
                return store.rename(folder, answer or record['base_name'], remember=True)
            except (EOFError, KeyboardInterrupt):
                return Path(folder)
            except ValueError as exc:
                print(str(exc))
    if os.environ.get('WAYLAND_DISPLAY') and not os.environ.get('QT_QPA_PLATFORM'):
        os.environ['QT_QPA_PLATFORM'] = 'wayland'
    app = W.QApplication.instance() or W.QApplication([])
    dialog = ExperimentNameDialog(store, folder, completion=True)
    dialog.exec_()
    print('实验记录：' + str(dialog.folder))
    return dialog.folder


class ExperimentDataDialog(W.QDialog):
    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.resize(1100, 760)
        with open_bundle(folder) as data_folder:
            self.setWindowTitle('实验数据 · ' + read_json(data_folder, 'experiment.json')['name'])
            self.build_data(data_folder)

    def build_data(self, folder):
        layout = W.QVBoxLayout(self)
        layout.addWidget(W.QLabel('当次实验记录；蓝色为执行计划，橙色为实测数据。编辑路径不会改变这些历史曲线。'))
        tabs = W.QTabWidget()
        layout.addWidget(tabs)
        with np.load(folder / 'timeline.npz', allow_pickle=False) as data:
            poses = data['pose_m_rad'].copy()
            times = data['t_s'].copy()
        xy = pg.PlotWidget(background='#faf9f4')
        xy.setAspectLocked(True)
        xy.addLegend()
        xy.setLabel('bottom', 'X', units='mm')
        xy.setLabel('left', 'Y', units='mm')
        xy.plot(poses[:, 0] * 1000, poses[:, 1] * 1000, pen=pg.mkPen('#1473c9', width=2), name='完整执行计划')
        if (folder / 'actual_tcp.csv').is_file():
            with (folder / 'actual_tcp.csv').open(newline='', encoding='utf-8') as stream:
                actual = [row for row in csv.DictReader(stream) if row['valid'].lower() == 'true']
            if actual:
                xy.plot([float(r['x_m']) * 1000 for r in actual], [float(r['y_m']) * 1000 for r in actual],
                        pen=pg.mkPen('#e39b24', width=2), name='实测 TCP')
        tabs.addTab(xy, '路径')
        control = load_control(folder)
        magnetic = pg.PlotWidget(background='#faf9f4')
        magnetic.addLegend()
        magnetic.setLabel('bottom', '计划时间', units='s')
        magnetic.setLabel('left', '磁响应', units='μT')
        for key, title, color in [('a_ref_uT', '磁目标', '#1473c9'), ('a_control_uT', '实测反馈响应', '#e39b24')]:
            magnetic.plot([r['t_s'] for r in control], [np.nan if r.get(key) is None else r[key] for r in control],
                          pen=pg.mkPen(color, width=2), name=title, connect='finite')
        tabs.addTab(magnetic, '磁目标与响应')
        orientation = pg.PlotWidget(background='#faf9f4')
        orientation.addLegend()
        orientation.setLabel('bottom', '计划时间', units='s')
        orientation.setLabel('left', '执行姿态', units='°')
        for i, (label, color) in enumerate(zip(('Rx', 'Ry', 'Rz'), ('#1473c9', '#239563', '#9465b1'))):
            orientation.plot(times, np.rad2deg(poses[:, i + 3]), pen=pg.mkPen(color, width=2), name=label)
        tabs.addTab(orientation, '执行姿态')
        for plot in (xy, magnetic, orientation):
            plot.showGrid(x=True, y=True, alpha=.2)


class ExperimentRecordsDialog(W.QDialog):
    def __init__(self, store, restore, parent=None):
        super().__init__(parent)
        self.store, self.restore = store, restore
        self.setWindowTitle('实验记录')
        self.resize(820, 530)
        layout = W.QVBoxLayout(self)
        self.table = W.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['实验名称', '完成时间'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.Stretch)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(W.QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _: self.restore_selected())
        layout.addWidget(self.table)
        actions = W.QHBoxLayout()
        for text, callback in [('恢复到编辑器', self.restore_selected), ('查看数据', self.view_selected),
                                ('重命名', self.rename_selected), ('打开文件夹', self.open_selected), ('刷新', self.refresh)]:
            button = W.QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.error = W.QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.refresh()

    def refresh(self):
        self.rows = self.store.records()
        self.table.setRowCount(len(self.rows))
        for i, record in enumerate(self.rows):
            finished = datetime.fromisoformat(record['finished_at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
            self.table.setItem(i, 0, W.QTableWidgetItem(record['name']))
            self.table.setItem(i, 1, W.QTableWidgetItem(finished))
        if self.rows:
            self.table.selectRow(0)
        self.error.setText('仅显示成功完成的实验。' if self.rows else '暂无成功的实验记录。')

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row]['path'] if row >= 0 else None

    def restore_selected(self):
        folder = self.selected()
        if folder:
            try:
                self.restore(folder)
                self.accept()
            except (OSError, ValueError, KeyError) as exc:
                self.error.setText(str(exc))

    def view_selected(self):
        folder = self.selected()
        if folder:
            try:
                ExperimentDataDialog(folder, self).exec_()
            except (OSError, ValueError, KeyError) as exc:
                self.error.setText(str(exc))

    def rename_selected(self):
        folder = self.selected()
        if folder:
            ExperimentNameDialog(self.store, folder, parent=self).exec_()
            self.refresh()

    def open_selected(self):
        folder = self.selected()
        if folder:
            QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))
