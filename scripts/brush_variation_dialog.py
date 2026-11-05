"""Three writing controls, reusable styles, and a frozen execution preview."""
import copy
from pathlib import Path
import uuid

import numpy as np
from PyQt5 import QtWidgets as W
import pyqtgraph as pg

from brushbot.experiments.writing_variation import ProfileStore, new_seed, validate_config

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT/'outputs/brush_path_editor/writing_profiles.json'


class WritingVariationDialog(W.QDialog):
    def __init__(self, model, parent=None, profiles_path=None):
        super().__init__(parent)
        self.candidate = copy.deepcopy(model)
        self.store = ProfileStore(profiles_path or PROFILES)
        self.profiles = self.store.load()
        current = copy.deepcopy(model.writing_variation['profile'])
        # Keep the library's latest version AND the experiment's exact version.
        # Loading a historic snapshot must not hide a newer saved configuration.
        if current not in self.profiles:
            self.profiles.append(current)
        self.profile = current
        self.preview_data = None
        self.loading = True
        self.setWindowTitle('书写随机扰动')
        self.resize(1050, 760)
        self.setMinimumSize(800, 640)
        self.setStyleSheet('QDoubleSpinBox, QComboBox, QLineEdit { min-height:26px; }'
                          'QPushButton { padding:5px 12px; }')
        layout = W.QVBoxLayout(self)
        note = W.QLabel('同一配置保留固定书写倾向，每次重写再有小变化。原标准路径不改，'
                        '关闭总开关恢复标准执行；采集的磁数据照实保存。')
        note.setWordWrap(True)
        layout.addWidget(note)

        flags = W.QHBoxLayout()
        self.enabled = W.QCheckBox('启用随机扰动')
        self.xy_enabled = W.QCheckBox('路径')
        self.magnetic_enabled = W.QCheckBox('磁目标')
        for field, key in [(self.enabled, 'enabled'), (self.xy_enabled, 'xy_enabled'),
                           (self.magnetic_enabled, 'magnetic_enabled')]:
            field.setChecked(model.writing_variation[key])
            flags.addWidget(field)
        flags.addStretch()
        layout.addLayout(flags)

        profile_row = W.QHBoxLayout()
        profile_row.addWidget(W.QLabel('书写配置'))
        self.profile_selector = W.QComboBox()
        for profile in self.profiles:
            self.profile_selector.addItem(profile['name']+f' · v{profile["revision"]}',
                                          (profile['id'], profile['revision']))
        self.profile_selector.setCurrentIndex(next(i for i, p in enumerate(self.profiles) if p == current))
        profile_row.addWidget(self.profile_selector, 1)
        self.profile_name = W.QLineEdit(current['name'])
        self.profile_name.setMaximumWidth(210)
        profile_row.addWidget(self.profile_name)
        new = W.QPushButton('新建配置')
        new.clicked.connect(lambda: self.new_profile())
        profile_row.addWidget(new)
        layout.addLayout(profile_row)

        form = W.QFormLayout()
        self.bias = W.QDoubleSpinBox()
        self.bias.setRange(-20., 20.)
        self.bias.setDecimals(1)
        self.bias.setSuffix(' %')
        self.bias.setKeyboardTracking(False)
        bias_row = W.QHBoxLayout()
        bias_row.addWidget(self.bias)
        for label, value in [('偏轻 −20%', -20.), ('中等 0%', 0.), ('偏重 +20%', 20.)]:
            button = W.QPushButton(label)
            button.clicked.connect(lambda checked=False, value=value: self.bias.setValue(value))
            bias_row.addWidget(button)
        form.addRow('整体轻重', bias_row)
        self.xy_limit = W.QDoubleSpinBox()
        self.xy_limit.setRange(0., .15)
        self.xy_limit.setDecimals(3)
        self.xy_limit.setSingleStep(.01)
        self.xy_limit.setSuffix(' mm')
        self.xy_limit.setKeyboardTracking(False)
        self.xy_limit.setToolTip('每个执行点与对应标准点的直线距离上限，包含固定与本次偏移。'
                                '不是整笔行程或累计偏差。设为0则路径不变。')
        form.addRow('路径偏差上限', self.xy_limit)
        self.repeat_level = W.QComboBox()
        for label, value in [('无', 'none'), ('小', 'small'), ('中', 'medium')]:
            self.repeat_level.addItem(label, value)
        form.addRow('每次变化程度', self.repeat_level)
        layout.addLayout(form)
        help_text = W.QLabel('整体轻重：固定的偏轻／偏重倾向。  路径偏差：每个点最多偏离标准多少毫米。\n'
                            '每次变化：只调重写时的小差异；选“无”仍保留配置固定倾向。'
                            '首次验证可先将整体轻重设为 ±10%。')
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        actions = W.QHBoxLayout()
        self.preview_button = W.QPushButton('预览并预检')
        self.preview_button.clicked.connect(self.preview)
        actions.addWidget(self.preview_button)
        self.regenerate_button = W.QPushButton('换一次变化')
        self.regenerate_button.clicked.connect(self.regenerate)
        actions.addWidget(self.regenerate_button)
        reuse = W.QPushButton('复用本次结果')
        reuse.clicked.connect(self.reuse_previous)
        actions.addWidget(reuse)
        self.stroke_selector = W.QComboBox()
        self.stroke_selector.currentIndexChanged.connect(self.draw_preview)
        actions.addWidget(self.stroke_selector, 1)
        layout.addLayout(actions)

        plots = W.QHBoxLayout()
        self.xy_plot = pg.PlotWidget(background='w')
        self.xy_plot.setAspectLocked(True)
        self.xy_plot.setLabel('bottom', '相对起点 X', units='mm')
        self.xy_plot.setLabel('left', 'Y', units='mm')
        self.xy_plot.addLegend()
        self.g_plot = pg.PlotWidget(background='w')
        self.g_plot.setLabel('bottom', '笔画时间', units='s')
        self.g_plot.setLabel('left', '磁目标（非实测响应）', units='μT')
        self.g_plot.addLegend()
        plots.addWidget(self.xy_plot)
        plots.addWidget(self.g_plot)
        layout.addLayout(plots, 1)
        self.report = W.QLabel('点击预览并预检。保存前会再次核对；设置仅从下一次运行生效。')
        self.report.setWordWrap(True)
        layout.addWidget(self.report)
        self.buttons = W.QDialogButtonBox(W.QDialogButtonBox.Save | W.QDialogButtonBox.Cancel)
        self.buttons.button(W.QDialogButtonBox.Save).setText('保存配置与设置')
        self.buttons.button(W.QDialogButtonBox.Cancel).setText('取消')
        self.buttons.accepted.connect(self.save_settings)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.load_profile(current)
        self.loading = False
        self.profile_selector.currentIndexChanged.connect(self.select_profile)
        for field in (self.enabled, self.xy_enabled, self.magnetic_enabled):
            field.toggled.connect(self.mark_stale)
        self.bias.valueChanged.connect(self.mark_stale)
        self.xy_limit.valueChanged.connect(self.mark_stale)
        self.repeat_level.currentIndexChanged.connect(self.mark_stale)
        self.profile_name.textChanged.connect(self.mark_stale)

    def load_profile(self, profile):
        self.loading = True
        self.profile = copy.deepcopy(profile)
        self.profile_name.setText(profile['name'])
        self.bias.setValue(profile['bias_pct'])
        self.xy_limit.setValue(profile['xy_limit_mm'])
        self.repeat_level.setCurrentIndex(self.repeat_level.findData(profile['repeat_level']))
        self.loading = False

    def select_profile(self, index):
        if self.loading or index < 0:
            return
        self.load_profile(self.profiles[index])
        self.mark_stale()

    def config(self):
        profile = dict(self.profile, name=self.profile_name.text().strip(),
                       bias_pct=self.bias.value(), xy_limit_mm=self.xy_limit.value(),
                       repeat_level=self.repeat_level.currentData())
        return validate_config(dict(enabled=self.enabled.isChecked(), xy_enabled=self.xy_enabled.isChecked(),
                                    magnetic_enabled=self.magnetic_enabled.isChecked(), profile=profile))

    def mark_stale(self, *args):
        if self.loading:
            return
        self.preview_data = None
        self.xy_plot.clear()
        self.g_plot.clear()
        self.report.setText('参数已更改，请重新预览并预检。')

    def new_profile(self):
        try:
            profile = dict(self.config()['profile'], id=uuid.uuid4().hex, revision=1,
                           seed=new_seed(), name=f'书写配置 {len(self.profiles)+1}')
            self.profiles.append(profile)
            self.profile_selector.addItem(profile['name']+' · v1', (profile['id'], profile['revision']))
            self.profile_selector.setCurrentIndex(len(self.profiles)-1)
            self.load_profile(profile)
            self.mark_stale()
        except ValueError as exc:
            self.report.setText('未新建配置：'+str(exc))

    def preview(self):
        self.preview_data = None
        try:
            self.candidate.set_writing_variation(self.config())
            _, _, compiled, _, _ = self.candidate.compile_workspace()
            self.preview_data = dict(standard=self.candidate.last_standard_compiled,
                                     effective=compiled, snapshot=self.candidate.last_variation)
            index = max(0, self.stroke_selector.currentIndex())
            self.stroke_selector.blockSignals(True)
            self.stroke_selector.clear()
            self.stroke_selector.addItems([row['stroke_name'] for row in self.candidate.last_workspace_strokes])
            self.stroke_selector.setCurrentIndex(min(index, self.stroke_selector.count()-1))
            self.stroke_selector.blockSignals(False)
            self.draw_preview()
            return True
        except Exception as exc:
            self.xy_plot.clear()
            self.g_plot.clear()
            self.report.setText('预检未通过：'+str(exc))
            return False

    def draw_preview(self, *args):
        if self.preview_data is None:
            return
        index = max(0, self.stroke_selector.currentIndex())
        phase = f'measure_{index:02}'
        standard, effective = self.preview_data['standard'], self.preview_data['effective']
        mask = standard['phase'] == phase
        origin = standard['pose_m_rad'][mask, :2][0]
        self.xy_plot.clear()
        self.g_plot.clear()
        t = standard['t_s'][mask]
        t = t-t[0]
        for compiled, color, name in [(standard, '#596b7b', '标准'), (effective, '#d17a16', '执行')]:
            xy = (compiled['pose_m_rad'][mask, :2]-origin)*1000
            self.xy_plot.plot(xy[:, 0], xy[:, 1], pen=pg.mkPen(color, width=2), name=name)
            self.g_plot.plot(t, compiled['g_ref_uT'][mask], pen=pg.mkPen(color, width=2), name=name+'目标')
        snapshot = self.preview_data['snapshot']
        if snapshot is None:
            self.report.setText('总开关关闭：使用标准执行结果。未连接硬件。')
            return
        report = snapshot['strokes'][index]['report']
        correlation = report['correlation']
        shape = '近似常量目标' if correlation is None else f'目标形状相关系数 {correlation:.4f}'
        self.report.setText(f'预检通过：最大路径偏差 {report["xy_max_mm"]:.4f} mm，'
            f'最大磁目标变化 {report["magnetic_max_uT"]:.2f} μT；{shape}。'
            f'固定路径生效比例 {report["fixed_xy_scale"]:.1%}，'
            f'本次路径 {report.get("repeat_xy_scale", report.get("repeat_scale", 1.)):.1%}，'
            f'本次磁变化 {report.get("repeat_magnetic_scale", report.get("repeat_scale", 1.)):.1%}。'
            + ('已锁定本次结果。' if self.candidate.variation_locked else '本次结果已冻结用于下一次试写。')
            + ' 未连接硬件，以上为控制目标。')

    def regenerate(self):
        self.candidate.regenerate_writing_variation()
        return self.preview()

    def reuse_previous(self):
        try:
            snapshot = self.candidate.variation_snapshot
            if snapshot is None or snapshot['config'] != self.config():
                raise ValueError('请先按当前参数预览生成结果，再选择复用')
            self.candidate.variation_locked = True
            return self.preview()
        except ValueError as exc:
            self.report.setText('未复用：'+str(exc))
            return False

    def save_settings(self):
        if not self.preview():
            return False
        try:
            locked = self.candidate.variation_locked
            config = self.config()
            latest = next((p for p in self.store.load() if p['id'] == config['profile']['id']), None)
            historic_unchanged = (latest is not None and config['profile'] == self.profile
                                   and latest['revision'] > config['profile']['revision'])
            if not historic_unchanged:
                config['profile'] = self.store.save(config['profile'])
            self.candidate.set_writing_variation(config)
            # A saved edit gets a new profile revision; rebuild its authoritative
            # snapshot with the same seeds before handing it to the editor.
            self.candidate.compile_workspace()
            self.candidate.variation_locked = locked
            self.accept()
            return True
        except Exception as exc:
            self.report.setText('未保存：'+str(exc))
            return False
