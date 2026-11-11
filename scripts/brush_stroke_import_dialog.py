"""Select source strokes and preview their placement before a reversible import."""
import copy

import numpy as np
from PyQt5 import QtCore, QtWidgets as W
import pyqtgraph as pg

from scripts.brush_stroke_import import configuration_differences, paper_points, stroke_models


class StrokeImportDialog(W.QDialog):
    def __init__(self, target, source, parent=None):
        super().__init__(parent)
        self.target = target
        self.source = source
        self.candidate = None
        self.setWindowTitle('导入笔画到当前画板')
        self.resize(880, 740)
        layout = W.QVBoxLayout(self)
        note = W.QLabel('勾选要导入的笔画，按来源顺序追加到末尾；之后可用上移、下移调整执行顺序。\n来源：'+str(source.folder))
        note.setWordWrap(True); layout.addWidget(note)
        self.stroke_list = W.QListWidget()
        self.stroke_list.setMaximumHeight(130)
        for index, item in enumerate(stroke_models(source)):
            row = W.QListWidgetItem(f'{index+1}. {item.stroke_name} · {len(item.nodes)} 个节点')
            row.setData(QtCore.Qt.UserRole, item.stroke_id)
            row.setFlags(row.flags() | QtCore.Qt.ItemIsUserCheckable)
            row.setCheckState(QtCore.Qt.Checked)
            self.stroke_list.addItem(row)
        layout.addWidget(self.stroke_list)
        form = W.QFormLayout(); layout.addLayout(form)
        self.side = W.QComboBox()
        for name, value in [('右侧', 'right'), ('左侧', 'left'), ('原位', 'original')]:
            self.side.addItem(name, value)
        form.addRow('放置位置', self.side)
        for attr, label, minimum, maximum, value in [('gap', '间距 mm', 0., 1000., 10.),
                ('offset_x', 'X 偏移 mm', -2000., 2000., 0.), ('offset_y', 'Y 偏移 mm', -2000., 2000., 0.)]:
            spin = W.QDoubleSpinBox(); spin.setRange(minimum, maximum); spin.setDecimals(2); spin.setValue(value)
            setattr(self, attr, spin); form.addRow(label, spin)
        self.plot = pg.PlotWidget(background='#faf9f4')
        self.plot.setLabel('bottom', '纸面 X', units='mm'); self.plot.setLabel('left', '纸面 Y', units='mm')
        self.plot.setAspectLocked(True); self.plot.showGrid(x=True, y=True, alpha=.15)
        self.plot.setMinimumHeight(190); layout.addWidget(self.plot, 1)
        layout.addWidget(W.QLabel('蓝色：当前画板；橙色：导入后的笔画。仅平移摆放，保持物理大小与笔杆姿态。'))
        differences = configuration_differences(target, source)
        self.configuration_note = W.QPlainTextEdit()
        self.configuration_note.setReadOnly(True); self.configuration_note.setMaximumHeight(105)
        self.configuration_note.setPlainText('采用当前工作区的前馈表、现场设置、PI及通用进笔/转场配置；保留来源笔画的磁目标、速度和笔杆角度。\n'
            '来源完整配置随导入记录保存；不修改来源文件。\n'+
            ('以下全局配置存在差异，将采用当前工作区值：\n'+'\n'.join(differences) if differences else '来源与当前工作区的全局配置一致。'))
        layout.addWidget(self.configuration_note)
        self.error = W.QLabel(); self.error.setWordWrap(True); layout.addWidget(self.error)
        self.buttons = W.QDialogButtonBox(W.QDialogButtonBox.Ok | W.QDialogButtonBox.Cancel)
        self.buttons.button(W.QDialogButtonBox.Ok).setText('导入选中笔画')
        self.buttons.button(W.QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.accept); self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.stroke_list.itemChanged.connect(self.preview)
        self.side.currentIndexChanged.connect(self.preview)
        for spin in (self.gap, self.offset_x, self.offset_y):spin.valueChanged.connect(self.preview)
        self.preview()

    def preview(self, *args):
        try:
            ids = [self.stroke_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.stroke_list.count())
                   if self.stroke_list.item(i).checkState() == QtCore.Qt.Checked]
            candidate = copy.deepcopy(self.target)
            imported = candidate.import_strokes(self.source, stroke_ids=ids, side=self.side.currentData(),
                gap_mm=self.gap.value(), offset_mm=(self.offset_x.value(), self.offset_y.value()))
            self.plot.clear()
            for item in stroke_models(candidate):
                points = paper_points(item)
                self.plot.plot(points[:, 0], points[:, 1], pen=pg.mkPen('#e39b24' if item.stroke_id in imported else '#1473c9', width=2))
            self.candidate = candidate
            self.error.setText(f'将追加 {len(imported)} 笔；导入后请重新预检。')
            self.error.setStyleSheet('')
            self.buttons.button(W.QDialogButtonBox.Ok).setEnabled(True)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.candidate = None
            self.error.setText('未导入：'+str(exc)); self.error.setStyleSheet('color:#b42318')
            self.buttons.button(W.QDialogButtonBox.Ok).setEnabled(False)

    def accept(self):
        for spin in (self.gap, self.offset_x, self.offset_y):spin.interpretText()
        self.preview()
        if self.candidate is not None:super().accept()
