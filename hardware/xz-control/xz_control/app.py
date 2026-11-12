#!/usr/bin/env python3
"""XZ desktop console. Starts disconnected; never uploads firmware or moves on launch."""
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPointF, QRectF, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QShortcut, QKeySequence, QPalette
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox, QSpinBox,
    QFrame, QPlainTextEdit, QMessageBox, QSizePolicy, QScrollArea, QDockWidget, QFileDialog, QTabWidget)
from .sensor import SensorPanel
from .experiment import Experiment
from .protocol import (Simulator, PROTOCOL, PROTOCOL_INT_MAX, PROTOCOL_INT_MIN, DEFAULT_ACCEL, ERRORS,
                      move_command, parse_status, motion_profile)


class Link(QObject):
    packet = Signal(dict)
    connection = Signal(str)
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.ser = None; self.sim = None; self.ready = False; self.active = False
        self.jog_supported = False
        self.buffer = bytearray(); self.last_rx = 0.; self.started = 0.
        self.last_hello = 0.; self.last_ping = 0.; self.last_tick = time.monotonic()
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(25)

    def connect_to(self, port=None):
        self.close()
        now = time.monotonic(); self.started = self.last_rx = self.last_tick = now
        self.last_hello = self.last_ping = 0.; self.buffer.clear()
        try:
            if port is None:
                self.sim = Simulator(); self.active = self.ready = True
                self.jog_supported = True
                self.connection.emit('demo'); self.packet.emit(self.sim.s.copy())
                self.message.emit('已进入模拟模式，不连接任何电机；使用理想加速—恒速—减速模型，不代表实物性能。')
            else:
                # Explicit DTR/RTS values; opening a port may still reset some boards.
                self.ser = serial.Serial(port=None, baudrate=115200, timeout=0, write_timeout=0.1, exclusive=True)
                self.ser.dtr = False; self.ser.rts = False; self.ser.port = port; self.ser.open()
                self.active = True; self.connection.emit('handshake')
                self.message.emit('等待 XZ1 双轴固件握手；请关闭 Arduino 串口监视器。')
        except (OSError, serial.SerialException) as e:
            self.fail('串口连接失败：' + str(e))

    def raw(self, line):
        payload = (line + '\n').encode('ascii')
        if self.ser.write(payload) != len(payload):
            raise serial.SerialTimeoutException('串口写入不完整')

    def send(self, line):
        if not self.ready:
            self.message.emit('尚未连接兼容的双轴固件。'); return False
        try:
            self.message.emit('→ ' + line)
            if self.sim:
                for p in self.sim.command(line): self.packet.emit(p)
            else:
                self.raw(line)
            return True
        except (OSError, serial.SerialException, ValueError) as e:
            self.fail('通信中断：' + str(e)); return False

    def close(self):
        if self.ser:
            try:
                if self.ready: self.raw('STOP')
            except (OSError, serial.SerialException): pass
            finally: self.ser.close()
        self.ser = None; self.sim = None; self.active = self.ready = False
        self.jog_supported = False
        self.buffer.clear(); self.connection.emit('offline')

    def fail(self, message):
        self.close(); self.message.emit(message)
        self.message.emit('控制已锁定；固件心跳超时后停止脉冲。重新连接不会自动恢复运动。')

    def tick(self):
        now = time.monotonic(); dt = min(now - self.last_tick, .1); self.last_tick = now
        if not self.active: return
        if self.sim:
            for p in self.sim.tick(dt): self.packet.emit(p)
            return
        try:
            if not self.ready and now - self.last_hello > 1:
                self.raw('HELLO'); self.last_hello = now
            if self.ready and now - self.last_ping > .3:
                self.raw('PING'); self.last_ping = now
            self.buffer.extend(self.ser.read(min(self.ser.in_waiting, 4096)))
            if len(self.buffer) > 8192: raise ValueError('收到过长串口数据')
            for _ in range(32):
                if b'\n' not in self.buffer: break
                raw, _, rest = self.buffer.partition(b'\n'); self.buffer = bytearray(rest)
                line = raw.decode('utf-8', errors='replace').strip()
                if not line: continue
                try: p = json.loads(line)
                except json.JSONDecodeError:
                    self.message.emit('设备：' + line[:200]); continue
                if not isinstance(p, dict): continue
                if p.get('type') == 'hello' and p.get('protocol') == PROTOCOL and not self.ready:
                    if p.get('move_accel') is not True:
                        self.fail('固件不支持可调加速度，请上传配套 XZ_Controller 1.4.0 或更新版本。')
                        return
                    if p.get('numeric_ranges') is not True:
                        self.fail('请上传 XZ_Controller 1.4.0：旧版仍有位移或坐标限制。'); return
                    self.ready = True; self.last_rx = now
                    self.jog_supported = p.get('jog') is True and p.get('jog_continuous') is True
                    self.raw('PING'); self.raw('DISARM')
                    self.connection.emit('hardware')
                    self.message.emit('XZ1 握手成功。位置来自控制器脉冲计数，不是编码器反馈。')
                if self.ready:
                    if p.get('type') == 'status':
                        parse_status(p); self.last_rx = now
                    self.packet.emit(p)
            if not self.ready and now - self.started > 8:
                self.fail('握手失败：请先上传配套 XZ_Controller 双轴固件，单轴测试程序不兼容。')
            elif self.ready and now - self.last_rx > 1.5:
                self.fail('超过 1.5 秒未收到有效状态，位置已标记为失效。')
        except (OSError, serial.SerialException, ValueError) as e:
            self.fail('通信错误：' + str(e))


class PathView(QWidget):
    def __init__(self):
        super().__init__(); self.s = None; self.order = 'XZ'
        self.start = None; self.setMinimumSize(300, 180)

    def set_state(self, s):
        if s['busy'] and (not self.s or not self.s['busy']):
            self.start = (self.s['x'], self.s['z']) if self.s else (s['x'], s['z'])
        self.s = s.copy(); self.update()

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        area = QRectF(65, 28, self.width()-105, self.height()-72)
        s = self.s
        start = (self.start or (s['x'], s['z'])) if s else (0, 0)
        # Display only X >= 0 and Z >= 0; do not change motion coordinates.
        def extent(values):
            span = max(10, max(abs(v) for v in values) * 1.2)
            step = 10 ** math.floor(math.log10(span))
            return math.ceil(span / step) * step
        xmax = extent([max(0, v) for v in (s['x'], s['tx'], start[0])]) if s else 10
        zmax = extent([max(0, v) for v in (s['z'], s['tz'], start[1])]) if s else 10
        def pt(x, z):
            return QPointF(area.left() + x / xmax * area.width(),
                           area.top() + z / zmax * area.height())
        p.setPen(QPen(QColor('#e8edf5'), 1))
        for i in range(5):
            x = area.left() + area.width()*i/4; y = area.top()+area.height()*i/4
            p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        origin = pt(0, 0)
        p.setPen(QPen(QColor('#93a3ba'), 1.4))
        p.drawLine(origin, pt(xmax, 0))
        p.drawLine(origin, pt(0, zmax))
        tip = pt(0, zmax)
        p.drawLine(tip, tip + QPointF(-4, -6))
        p.drawLine(tip, tip + QPointF(4, -6))
        tip = pt(xmax, 0)
        p.drawLine(tip, tip + QPointF(-6, -4))
        p.drawLine(tip, tip + QPointF(-6, 4))
        p.setPen(QColor('#526782'))
        p.drawText(QRectF(origin.x()-25, area.bottom()+6, 50, 20), Qt.AlignCenter, 'Z + ↓')
        p.drawText(QRectF(area.right()+3, origin.y()-10, 35, 20), Qt.AlignCenter, 'X +')
        font = p.font(); font.setPointSize(9); p.setFont(font)
        p.setPen(QColor('#718096'))
        for fraction in (.25, .5, .75, 1):
            z = fraction*zmax; x = fraction*xmax
            p.drawText(QRectF(0, pt(0, z).y()-9, area.left()-8, 18), Qt.AlignRight | Qt.AlignVCenter, f'{z:g}')
            p.drawText(QRectF(pt(x, 0).x()-32, area.top()-24, 64, 18), Qt.AlignCenter, f'{x:g}')
        p.drawText(origin + QPointF(-14, -8), '0')
        p.drawEllipse(origin, 3, 3)
        if not s:
            p.drawText(QRectF(area.left(), area.top()+25, area.width(), 20), Qt.AlignCenter, '等待连接 · 坐标单位：脉冲')
            return
        p.save(); p.setClipRect(area.adjusted(-1, -1, 1, 1))
        if s['busy']:
            points = [start]
            if self.order == 'XZ': points.append((s['tx'], start[1]))
            elif self.order == 'ZX': points.append((start[0], s['tz']))
            points.append((s['tx'], s['tz']))
            p.setPen(QPen(QColor('#a6b9f4'), 2, Qt.DashLine))
            for a, b in zip(points, points[1:]): p.drawLine(pt(*a), pt(*b))
        target_visible = s['tx'] >= 0 and s['tz'] >= 0
        current_visible = s['x'] >= 0 and s['z'] >= 0
        if target_visible:
            p.setPen(QPen(QColor('#8293ad'), 2)); p.drawEllipse(pt(s['tx'], s['tz']), 7, 7)
        if current_visible:
            current = pt(s['x'], s['z'])
            p.setPen(Qt.NoPen); p.setBrush(QColor('#4263eb')); p.drawEllipse(current, 6, 6)
            p.setPen(QColor('#334155'))
            text = f"({s['x']}, {s['z']})"
            text_x = min(current.x()+12, area.right()-p.fontMetrics().horizontalAdvance(text)-4)
            p.drawText(QPointF(text_x, max(area.top()+16, current.y()-10)), text)
        p.restore()
        if not current_visible or not target_visible:
            outside = '当前位置' if not current_visible else '目标位置'
            p.setPen(QColor('#a16b25'))
            p.drawText(QRectF(area.left()+35, area.bottom()+6, area.width()-35, 20),
                       Qt.AlignRight | Qt.AlignVCenter, outside + '在显示范围外')


STYLE = '''
QMainWindow, QWidget#root {background:#f3f5f9; color:#18243a;}
QWidget {font-family:"PingFang SC","Helvetica Neue"; font-size:13px; color:#18243a;}
QTabWidget::pane {background:#f3f5f9; border:0; top:0;}
QTabBar {background:#f3f5f9;}
QTabBar::tab {background:#e6ebf3; color:#526782; border:1px solid #d3dce9;
    border-top-left-radius:8px; border-top-right-radius:8px; padding:8px 16px; margin-right:4px;}
QTabBar::tab:selected {background:white; color:#244cc5; border-color:#b6c7f2; font-weight:650;}
QTabBar::tab:hover:!selected {background:#edf2ff; color:#244cc5;}
QTabBar::tab:disabled {background:#edf0f5; color:#9ca9bb;}
QFrame#card {background:white; border:1px solid #e3e8f1; border-radius:14px;}
QLabel#title {font-size:27px; font-weight:700;}
QLabel#section {font-size:16px; font-weight:650;}
QLabel#muted {color:#718096; font-size:12px;}
QLabel#position {font-family:"SF Mono","Menlo";font-size:34px;font-weight:650;color:#244cc5;}
QLabel#badge {background:#e6ebf6; color:#435673;border-radius:12px;padding:7px 13px;font-weight:600;}
QLabel#notice {background:#eaf0ff;color:#3455a4;border-radius:8px;padding:10px;}
QPushButton {background:white;border:1px solid #d3dce9;border-radius:8px;padding:7px 12px;font-weight:550;}
QPushButton:hover {background:#edf2ff;border-color:#8ba7ed;}
QPushButton:pressed {background:#dce6ff;}
QPushButton:disabled {color:#a1adbf;background:#f5f7fa;border-color:#e5eaf2;}
QPushButton#primary {background:#345eea;color:white;border-color:#345eea;}
QPushButton#primary:hover {background:#244dd4;}
QPushButton#primary:disabled {background:#d2dcf7;border-color:#d2dcf7;color:#879bc9;}
QPushButton#stop {background:#fff0ef;color:#c63932;border:1px solid #efb3af;font-size:16px;font-weight:700;}
QPushButton#stop:hover {background:#ffdedb;}
QPushButton#stop:disabled {color:#c9a4a0;border-color:#eddad8;background:#faf3f2;}
QComboBox,QSpinBox {background:#fbfcfe;border:1px solid #d8e0ec;border-radius:7px;padding:6px;min-height:18px;}
QComboBox:disabled,QSpinBox:disabled {color:#9ca9bb;background:#f3f5f9;}
QComboBox::drop-down {background:#edf2f8;border:0;width:25px;border-top-right-radius:7px;border-bottom-right-radius:7px;}
QComboBox QAbstractItemView {background:white; alternate-background-color:#f3f5f9; color:#18243a;
    border:1px solid #d3dce9; selection-background-color:#dce6ff; selection-color:#244cc5; outline:0;}
QComboBox QAbstractItemView::item {min-height:28px; padding:4px 8px;}
QComboBox QAbstractItemView::item:selected {background:#dce6ff; color:#244cc5;}
QScrollBar:vertical {background:#edf0f5;width:12px;border:0;margin:0;}
QScrollBar::handle:vertical {background:#b7c4d6;min-height:24px;border-radius:5px;}
QScrollBar:horizontal {background:#edf0f5;height:12px;border:0;margin:0;}
QScrollBar::handle:horizontal {background:#b7c4d6;min-width:24px;border-radius:5px;}
QScrollBar::add-line,QScrollBar::sub-line {width:0;height:0;border:0;}
QScrollBar::add-page,QScrollBar::sub-page {background:#edf0f5;}
QPlainTextEdit {background:#f8fafc;border:0;font-family:"Menlo";font-size:11px;}
'''

def label(text, name=None):
    w = QLabel(text)
    if name: w.setObjectName(name)
    return w

def card():
    w = QFrame(); w.setObjectName('card'); box = QVBoxLayout(w)
    box.setContentsMargins(16, 12, 16, 12); box.setSpacing(8)
    return w, box


class Window(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('XZ 双轴控制台'); self.resize(1060, 790)
        self.link = Link(); self.s = None; self.pending = None; self.pending_at = 0.
        self.connection_mode = 'offline'; self.was_busy = False
        self.jog_button = None
        self.experiment = None
        shell = QWidget(); shell.setObjectName('root'); self.setCentralWidget(shell)
        outer = QVBoxLayout(shell); outer.setContentsMargins(18, 12, 18, 10); outer.setSpacing(8)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        root = QWidget(); root.setObjectName('root'); scroll.setWidget(root); outer.addWidget(scroll, 1)
        main = QVBoxLayout(root); main.setContentsMargins(2, 2, 2, 2); main.setSpacing(10)
        header = QHBoxLayout(); titles = QVBoxLayout()
        titles.addWidget(label('XZ 双轴控制台', 'title'))
        titles.addWidget(label('ESP32-S3  /  HBS57     ·     运动控制与位置监视', 'muted'))
        header.addLayout(titles); header.addStretch()
        self.badge = label('未连接', 'badge'); header.addWidget(self.badge); main.addLayout(header)

        connection_card, cb = card(); row = QHBoxLayout()
        self.mode = QComboBox(); self.mode.addItems(['模拟演示', '真实设备'])
        self.ports = QComboBox(); self.ports.setMinimumWidth(280)
        self.refresh = QPushButton('刷新端口'); self.refresh.clicked.connect(self.refresh_ports)
        self.connect_btn = QPushButton('连接'); self.connect_btn.clicked.connect(self.toggle_connection)
        self.connect_btn.setObjectName('primary')
        row.addWidget(self.mode); row.addWidget(self.ports, 1); row.addWidget(self.refresh); row.addWidget(self.connect_btn)
        cb.addLayout(row); main.addWidget(connection_card)
        self.mode.currentIndexChanged.connect(self.mode_changed)

        positions = QHBoxLayout(); self.position = {}; self.target = {}; self.velocity = {}; self.reference = {}
        for a, subtitle in [('x', 'X · 水平轴'), ('z', 'Z · 升降轴')]:
            c, b = card(); top = QHBoxLayout(); top.addWidget(label(subtitle, 'section')); top.addStretch()
            self.reference[a] = label('尚未设零', 'muted'); top.addWidget(self.reference[a]); b.addLayout(top)
            self.position[a] = label('—', 'position'); b.addWidget(self.position[a])
            line = QHBoxLayout(); self.target[a] = label('目标 — 脉冲', 'muted')
            self.velocity[a] = label('速度 — 脉冲/秒', 'muted')
            line.addWidget(self.target[a]); line.addStretch(); line.addWidget(self.velocity[a]); b.addLayout(line)
            positions.addWidget(c)
        main.addLayout(positions)

        middle = QHBoxLayout(); control, b = card(); b.addWidget(label('运动任务', 'section'))
        b.setSpacing(4); b.setContentsMargins(16, 10, 16, 10)
        types = QHBoxLayout(); self.coord = QComboBox()
        self.coord.addItem('相对位移 · 从当前位置移动', 'REL'); self.coord.addItem('绝对位置 · 相对所设零点', 'ABS')
        types.addWidget(self.coord); b.addLayout(types)
        grid = QGridLayout(); grid.addWidget(label('轴'), 0, 0)
        self.target_header = label('目标位移 / 脉冲'); grid.addWidget(self.target_header, 0, 1)
        grid.addWidget(label('恒速目标\n脉冲/秒'), 0, 2)
        grid.addWidget(label('加速度\n脉冲/秒²'), 0, 3)
        self.inputs = {}; self.accels = {}
        for i, a in enumerate(('x', 'z'), 1):
            grid.addWidget(label(a.upper()), i, 0)
            target = QSpinBox(); target.setRange(PROTOCOL_INT_MIN, PROTOCOL_INT_MAX); target.setValue(10); target.setSingleStep(10)
            speed = QSpinBox(); speed.setRange(1, PROTOCOL_INT_MAX); speed.setValue(10)
            speed.setToolTip('已取消 1000 脉冲/秒的人为上限；实际速度受加速度及脉冲输出能力影响。')
            grid.addWidget(target, i, 1); grid.addWidget(speed, i, 2); self.inputs[a] = (target, speed)
            accel = QSpinBox(); accel.setRange(1, PROTOCOL_INT_MAX); accel.setValue(DEFAULT_ACCEL)
            accel.setSingleStep(100)
            accel.setToolTip('数值越大，加速和减速时间越短。理想加速时间 = 速度 ÷ 加速度；机械可承受值需实测。')
            grid.addWidget(accel, i, 3); self.accels[a] = accel
            for widget in (target, speed, accel): widget.setMinimumWidth(80)
        b.addLayout(grid)
        self.profile_note = label('', 'muted'); self.profile_note.setWordWrap(True)
        b.addWidget(self.profile_note)
        self.order = QComboBox()
        for text, code in [('X → Z · X 完成后再移动 Z', 'XZ'), ('Z → X · Z 完成后再移动 X', 'ZX'), ('同时开始 · 两轴独立到达', 'SIM')]:
            self.order.addItem(text, code)
        b.insertWidget(2, self.order)
        self.order_note = label('第一轴到位后，控制器自动启动第二轴。', 'muted'); self.order_note.setWordWrap(True)
        self.order.setToolTip(self.order_note.text())
        self.execute = QPushButton('执行双轴任务'); self.execute.setObjectName('primary')
        self.execute.clicked.connect(self.start_move)
        self.execute.setToolTip('快速加速 → 恒速运行 → 到目标前减速；已取消人为位移上限。')
        self.task_tabs = QTabWidget(); self.task_tabs.addTab(control, '运动控制')
        middle.addWidget(self.task_tabs, 6)
        visual, vb = card(); vb.addWidget(label('传感器位置示意 · Z 正向下', 'section')); self.view = PathView(); vb.addWidget(self.view, 1)
        vb.addWidget(label('● 当前位置    ○ 目标    虚线：顺序示意（非插补轨迹）', 'muted'))
        middle.addWidget(visual, 5); main.addLayout(middle, 1)

        exp_card, eb = card(); eb.setSpacing(4); eb.setContentsMargins(16, 8, 16, 8); eb.addWidget(label('平面扫描实验', 'section'))
        exp_hint = label('先人工定位并“两轴设零”。终点为相对该零点的绝对坐标；速度/加速度沿用“运动控制”页设置。', 'muted')
        exp_hint.setWordWrap(True); eb.addWidget(exp_hint)
        er = QGridLayout(); self.exp_targets = {}
        for row_index, axis in enumerate(('x', 'z')):
            er.addWidget(label(axis.upper() + ' 实验终点 / 脉冲'), row_index, 0)
            spin = QSpinBox(); spin.setRange(PROTOCOL_INT_MIN, PROTOCOL_INT_MAX); spin.setValue(100 if axis == 'x' else 10)
            er.addWidget(spin, row_index, 1); self.exp_targets[axis] = spin
        eb.addLayout(er)
        self.exp_folder = Path(__file__).resolve().parents[1] / 'data' / 'experiments'
        self.exp_path = label(str(self.exp_folder), 'muted'); self.exp_path.setWordWrap(True); self.exp_path.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred); eb.addWidget(self.exp_path)
        er = QHBoxLayout(); self.exp_choose = QPushButton('选择保存目录'); self.exp_choose.clicked.connect(self.choose_exp_folder)
        self.exp_start = QPushButton('开始实验'); self.exp_start.setObjectName('primary'); self.exp_start.clicked.connect(self.start_experiment)
        self.exp_abort = QPushButton('中止实验'); self.exp_abort.clicked.connect(lambda: self.experiment.abort('用户中止'))
        for btn in (self.exp_choose, self.exp_start, self.exp_abort): er.addWidget(btn)
        eb.insertLayout(1, er)
        self.exp_status = label('Z 到位 → 开始记录 → X 扫描 → 保存 → Z 回零 → X 回零', 'muted')
        self.exp_status.setWordWrap(True); eb.addWidget(self.exp_status); self.task_tabs.addTab(exp_card, '平面扫描实验')

        actions, ab = card(); ar = QHBoxLayout()
        jog_row = QHBoxLayout(); jog_row.addWidget(label('实时点动 · 按住移动', 'section'))
        self.jog_buttons = []
        for text, axis, direction in [('X −', 'x', -1), ('X +', 'x', 1), ('Z 下 (+)', 'z', 1), ('Z 上 (−)', 'z', -1)]:
            button = QPushButton(text); button.setAutoRepeat(False)
            button.pressed.connect(lambda a=axis, d=direction, b=button: self.start_jog(a, d, b))
            button.released.connect(self.end_jog)
            jog_row.addWidget(button); self.jog_buttons.append(button)
        ab.addLayout(jog_row)
        self.jog_note = label('沿用各轴速度/加速度；松开减速停止；持续点动，仅保留整数运算边界。', 'muted')
        self.jog_note.setWordWrap(True); ab.addWidget(self.jog_note)
        self.jog_timer = QTimer(self); self.jog_timer.setInterval(100)
        self.jog_timer.timeout.connect(self.keep_jog)
        self.arm = QPushButton('使能运动'); self.arm.clicked.connect(lambda: self.command('ARM'))
        self.disarm = QPushButton('取消使能'); self.disarm.clicked.connect(lambda: self.command('DISARM'))
        self.stop = QPushButton('■  停止全部  [空格]'); self.stop.setObjectName('stop')
        self.stop.clicked.connect(lambda: self.command('STOP'))
        ar.addWidget(self.arm); ar.addWidget(self.disarm); ar.addWidget(self.execute); ar.addWidget(self.stop, 1)
        self.clear = QPushButton('复位故障'); self.clear.clicked.connect(lambda: self.command('CLEAR')); ar.addWidget(self.clear)
        ab.addLayout(ar); zr = QHBoxLayout(); zr.addWidget(label('当前位置设零', 'muted'))
        self.zeros = []
        for text, axis in [('X 设零', 'X'), ('Z 设零', 'Z'), ('两轴设零', 'ALL')]:
            btn = QPushButton(text); btn.clicked.connect(lambda checked=False, a=axis: self.zero(a))
            zr.addWidget(btn); self.zeros.append(btn)
        self.return_zero = QPushButton('一键回零点')
        self.return_zero.setToolTip('按所选顺序、两轴速度和加速度返回 X=0、Z=0；不会重新设零或寻找原点开关。')
        self.return_zero.clicked.connect(self.go_to_zero); zr.addWidget(self.return_zero)
        zr.addStretch(); zr.addWidget(label('动力上电：外部手动', 'muted'))
        log_toggle = QPushButton('通信记录'); zr.addWidget(log_toggle)
        ab.addLayout(zr); outer.addWidget(actions)
        self.notice = label('选择模拟演示体验界面；连接真实设备前请先上传配套双轴固件。', 'notice')
        self.notice.setWordWrap(True); outer.addWidget(self.notice)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(250); self.log.setMaximumHeight(100)
        outer.addWidget(self.log); self.log.hide()
        log_toggle.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        footer = label('位置为软件脉冲计数，非编码器实测。设零不会移动机械。ENA / ALM / 限位未接入，软件停止不切断动力。', 'muted')
        footer.setWordWrap(True); outer.addWidget(footer)
        self.shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.shortcut.activated.connect(lambda: self.command('STOP'))
        self.link.packet.connect(self.on_packet); self.link.connection.connect(self.on_connection)
        self.link.message.connect(self.log_message)
        self.coord.currentIndexChanged.connect(self.update_labels)
        self.order.currentIndexChanged.connect(self.update_labels)
        for a in ('x', 'z'):
            for widget in (*self.inputs[a], self.accels[a]): widget.valueChanged.connect(self.update_profile)
        self.guard = QTimer(self); self.guard.timeout.connect(self.guard_pending); self.guard.start(200)
        self.refresh_ports(); self.mode_changed(); self.update_controls()
        self.sensor = SensorPanel(lambda: self.link.ser.port if self.link.ser else None,
                                  lambda: not (self.experiment and self.experiment.active)
                                  and not (self.s and self.s['busy']) and not self.pending
                                  and self.jog_button is None)
        self.sensor.calibration_changed.connect(self.update_controls)
        dock = QDockWidget('X/Y 磁场监测', self)
        dock.setFeatures(QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetMovable)
        dock.setWidget(self.sensor); self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.resize(1440, 830)
        self.resizeDocks([dock], [380], Qt.Horizontal)
        # The popup's outer frame uses its palette independently of the list stylesheet.
        for combo in self.findChildren(QComboBox):
            popup = combo.view().window()
            palette = popup.palette()
            palette.setColor(QPalette.Window, QColor('white'))
            palette.setColor(QPalette.Base, QColor('white'))
            palette.setColor(QPalette.Text, QColor('#18243a'))
            popup.setPalette(palette); popup.setAutoFillBackground(True)
        self.experiment = Experiment(self.command, lambda: self.s, self.sensor_alive, self)
        self.experiment.changed.connect(self.experiment_changed)
        self.sensor.sample_received.connect(self.experiment.sample)
        self.update_controls()

    def log_message(self, msg):
        self.log.appendPlainText(datetime.now().strftime('%H:%M:%S') + '  ' + msg)

    def refresh_ports(self):
        old = self.ports.currentData(); self.ports.clear()
        for p in list_ports.comports():
            if 'Bluetooth' not in p.device and 'debug-console' not in p.device:
                self.ports.addItem(f'{p.device}  ·  {p.description}', p.device)
        index = self.ports.findData(old)
        if index >= 0: self.ports.setCurrentIndex(index)
        if self.ports.count() == 0: self.ports.addItem('未发现串口，请插入 USB', None)

    def mode_changed(self):
        enabled = self.mode.currentIndex() == 1 and not self.link.active
        self.ports.setEnabled(enabled); self.refresh.setEnabled(enabled)

    def toggle_connection(self):
        if self.link.active:
            self.link.close(); return
        if self.mode.currentIndex() == 1 and not self.ports.currentData():
            QMessageBox.information(self, '没有串口', '插入 ESP32 USB 后点击刷新端口。'); return
        if self.mode.currentIndex() == 1 and self.ports.currentData() == self.sensor.port:
            QMessageBox.warning(self, '串口已占用', '这个串口已用于传感器，请选择电机 ESP32-S3 的串口。'); return
        self.link.connect_to(None if self.mode.currentIndex() == 0 else self.ports.currentData())

    def on_connection(self, mode):
        if self.experiment and self.experiment.active and mode == 'offline':
            self.experiment.abort('电机连接断开')
        self.jog_button = None; self.jog_timer.stop()
        self.connection_mode = mode; self.pending = None; self.s = None
        if mode == 'hardware':
            self.pending = 'DISARM'; self.pending_at = time.monotonic()
        self.view.s = None; self.view.start = None; self.view.update()
        names = dict(offline='未连接 · 位置失效', demo='模拟模式 · 不控制硬件', handshake='正在握手', hardware='设备已连接')
        self.badge.setText(names[mode]); self.connect_btn.setText('断开连接' if self.link.active else '连接')
        self.mode.setEnabled(not self.link.active); self.mode_changed()
        for a in ('x', 'z'):
            self.position[a].setText('—'); self.reference[a].setText('尚未确认')
            self.target[a].setText('目标 — 脉冲'); self.velocity[a].setText('速度 — 脉冲/秒')
        if mode == 'offline': self.notice.setText('未连接，当前位置不可用。重新连接后需收到控制器状态。')
        self.update_controls()

    def on_packet(self, p):
        kind = p.get('type')
        if kind == 'status':
            try: self.s = parse_status(p)
            except ValueError as e: self.link.fail(str(e)); return
            if not p['armed'] or p['fault'] != 'NONE':
                self.jog_button = None; self.jog_timer.stop()
            for a in ('x', 'z'):
                self.position[a].setText(f"{p[a]:,}  <span style='font-size:13px;color:#718096'>脉冲</span>")
                self.target[a].setText(f"目标 {p['t'+a]:,} 脉冲")
                self.velocity[a].setText(f"速度 {p['v'+a]:.1f} 脉冲/秒")
                self.reference[a].setText('已设软件零点' if p['ref'+a] else '需要设零')
            self.view.set_state(p)
            prefix = '模拟 · ' if self.link.sim else ''
            if p['fault'] != 'NONE': text = ERRORS.get(p['fault'], p['fault']) + '；请检查并复位。'
            elif p['busy']: text = {1:'X 轴移动中，Z 轴等待', 2:'Z 轴移动中，X 轴等待', 3:'运动执行中'}[p['phase']]
            elif not p['refx'] or not p['refz']: text = '确认机械所在位置后，将两轴当前位置设为软件零点。'
            elif p['armed']: text = '已使能，可以执行运动任务。'
            else: text = '已停止 / 未使能，点击“使能运动”后可执行任务。'
            self.notice.setText(self.exp_status.text() if self.experiment and self.experiment.active else prefix + text)
        elif kind == 'ack':
            if self.pending == p.get('cmd'): self.pending = None
            self.log_message('✓ ' + str(p.get('cmd', '')) + ' 已确认')
        elif kind == 'error':
            self.end_jog()
            self.pending = None; self.log_message('错误：' + ERRORS.get(p.get('code'), str(p.get('code'))))
        elif kind == 'done':
            self.jog_button = None; self.jog_timer.stop()
            self.log_message('✓ 双轴任务完成（控制器脉冲计数到位）')
        if self.experiment: self.experiment.packet(p)
        self.update_controls()

    def update_controls(self):
        valid = self.link.ready and self.s is not None
        busy = bool(self.s and self.s['busy']); fault = bool(self.s and self.s['fault'] != 'NONE')
        experimenting = bool(self.experiment and self.experiment.active)
        calibrating = bool(hasattr(self, 'sensor') and self.sensor.calibrating)
        idle = valid and not busy and not self.pending and self.jog_button is None and not experimenting and not calibrating
        refs = bool(self.s and self.s['refx'] and self.s['refz'])
        armed = bool(self.s and self.s['armed'])
        self.arm.setEnabled(idle and refs and not armed and not fault)
        self.disarm.setEnabled(valid and (armed or busy))
        self.stop.setEnabled(self.link.ready)
        self.clear.setEnabled(idle and fault)
        self.execute.setEnabled(idle and armed and refs and not fault)
        self.return_zero.setEnabled(idle and armed and refs and not fault)
        for button in self.jog_buttons:
            button.setEnabled(button is self.jog_button or
                              (idle and armed and refs and not fault and self.link.jog_supported))
        self.jog_note.setText('沿用各轴速度/加速度；松开减速停止；持续点动，仅保留整数运算边界。'
                             if self.link.jog_supported or not valid else '实时点动需要上传 XZ_Controller 1.4.0 固件。')
        for b in self.zeros: b.setEnabled(idle and not fault)
        for pair in self.inputs.values():
            for w in pair: w.setEnabled(not busy and not self.pending and self.jog_button is None and not experimenting)
        for w in self.accels.values(): w.setEnabled(not busy and not self.pending and self.jog_button is None and not experimenting)
        self.coord.setEnabled(not busy and not self.pending and not experimenting); self.order.setEnabled(not busy and not self.pending and not experimenting)
        self.exp_start.setEnabled(idle and armed and refs and not fault and self.connection_mode == 'hardware')
        self.exp_abort.setEnabled(experimenting)
        self.exp_choose.setEnabled(not experimenting)
        for w in self.exp_targets.values(): w.setEnabled(not experimenting)
        self.connect_btn.setEnabled(not experimenting)
        if hasattr(self, 'sensor'):
            self.sensor.connect_btn.setEnabled(not experimenting)
            self.sensor.refresh_calibration_button()
        if not busy and not self.pending: self.update_profile()

    def command(self, line):
        if not self.link.ready: return
        cmd = line.split()[0]
        if cmd in ('STOP', 'DISARM'):
            if self.experiment and self.experiment.active:
                self.experiment.abort('用户停止或取消使能'); return
            self.jog_button = None; self.jog_timer.stop()
        if self.pending and cmd not in ('STOP', 'DISARM', 'JEND'): return
        self.pending = cmd; self.pending_at = time.monotonic(); self.update_controls()
        if not self.link.send(line): self.pending = None; self.update_controls()

    def start_jog(self, axis, direction, button):
        if self.jog_button is not None or not button.isEnabled(): return
        if not self.link.ready or not self.link.jog_supported or self.pending: return
        self.jog_button = button
        self.command(f'JOG {axis.upper()} {direction} {self.inputs[axis][1].value()} {self.accels[axis].value()}')
        if self.jog_button is button: self.jog_timer.start()

    def end_jog(self):
        if self.jog_button is None: return
        self.jog_button = None; self.jog_timer.stop()
        self.command('JEND')

    def keep_jog(self):
        if self.jog_button is None: return
        if not self.isActiveWindow() or not self.jog_button.isDown():
            self.end_jog(); return
        if self.link.sim: self.link.sim.command('JKEEP')
        elif self.link.ready:
            try: self.link.raw('JKEEP')
            except (OSError, serial.SerialException) as e: self.link.fail(str(e))

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.end_jog()
        super().changeEvent(event)

    def start_move(self):
        if not self.execute.isEnabled(): return
        try:
            x, vx = (w.value() for w in self.inputs['x'])
            z, vz = (w.value() for w in self.inputs['z'])
            cmd = move_command(self.coord.currentData(), self.order.currentData(), x, z, vx, vz, self.s,
                               self.accels['x'].value(), self.accels['z'].value())
        except ValueError as e:
            QMessageBox.warning(self, '检查运动参数', str(e)); return
        self.log_message(self.profile_note.text().replace('\n', '；'))
        self.view.order = self.order.currentData(); self.command(cmd)

    def zero(self, axis):
        text = '两轴' if axis == 'ALL' else axis + ' 轴'
        result = QMessageBox.question(self, '设置软件零点', f'将{text}的当前位置记为 0？\n不会移动机械，也不会寻找原点开关。',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if result == QMessageBox.Yes: self.command('ZERO ' + axis)

    def go_to_zero(self):
        if not self.return_zero.isEnabled(): return
        try:
            vx = self.inputs['x'][1].value(); vz = self.inputs['z'][1].value()
            cmd = move_command('ABS', self.order.currentData(), 0, 0, vx, vz, self.s,
                               self.accels['x'].value(), self.accels['z'].value())
        except ValueError as e:
            QMessageBox.warning(self, '无法回零点', str(e)); return
        self.view.order = self.order.currentData()
        self.log_message('返回已设置的软件零点 X=0、Z=0。')
        self.log_message(self.profile_text(return_zero=True).replace('\n', '；'))
        self.command(cmd)

    def update_labels(self):
        self.target_header.setText('目标位移 / 脉冲' if self.coord.currentData() == 'REL' else '目标位置 / 脉冲')
        self.order_note.setText('同时启动，各轴按自己的速度到达；不是同步到达或直线插补。'
                               if self.order.currentData() == 'SIM' else '第一轴到位后，控制器自动启动第二轴。')
        self.order.setToolTip(self.order_note.text())
        self.update_profile()

    def profile_text(self, return_zero=False):
        if (return_zero or self.coord.currentData() == 'ABS') and self.s is None:
            return '理想速度预估：连接并收到当前位置后计算。'
        lines = ['理想速度预估（未计入硬件输出限制）']
        for a in ('x', 'z'):
            target, speed = (w.value() for w in self.inputs[a])
            if return_zero: distance = abs(self.s[a])
            elif self.coord.currentData() == 'REL': distance = abs(target)
            else: distance = abs(target - self.s[a])
            accel = self.accels[a].value(); p = motion_profile(distance, speed, accel)
            if not distance: text = '无需移动'
            elif p['peak'] < speed:
                text = f"行程不足，峰值约 {p['peak']:.1f} 脉冲/秒，无恒速段"
            else:
                text = (f"加速 {p['ramp_time']:.3g}s → 恒速 {p['cruise_distance']:.1f} 脉冲"
                        f" → 减速 {p['ramp_time']:.3g}s")
            lines.append(f'{a.upper()}：{text}')
        return '\n'.join(lines)

    def update_profile(self):
        self.profile_note.setText(self.profile_text())

    def sensor_alive(self):
        return bool(self.sensor.ser and self.sensor.last_sample is not None and
                    time.monotonic() - self.sensor.last_sample < 2)

    def choose_exp_folder(self):
        folder = QFileDialog.getExistingDirectory(self, '选择实验数据保存目录', str(self.exp_folder))
        if folder: self.exp_folder = Path(folder); self.exp_path.setText(folder)

    def experiment_changed(self, message):
        self.exp_status.setText(message); self.notice.setText(message); self.log_message(message); self.update_controls()

    def start_experiment(self):
        if self.sensor.calibrating: return
        if not self.exp_start.isEnabled(): return
        if self.connection_mode != 'hardware':
            QMessageBox.warning(self, '需要真实设备', '实验记录需要连接真实电机和传感器，模拟模式不能生成实验测量记录。'); return
        try:
            self.view.order = 'ZX'
            self.experiment.start(self.exp_folder, tuple(self.exp_targets[a].value() for a in ('x','z')),
                tuple(self.inputs[a][1].value() for a in ('x','z')),
                tuple(self.accels[a].value() for a in ('x','z')),
                dict(motor_port=self.link.ser.port, sensor_port=self.sensor.port,
                     sensor_baud=self.sensor.baud.currentData(), sensor_address='0x0C (user supplied)',
                     sensor_calibration=self.sensor.calibration_snapshot()))
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, '无法开始实验', str(e))
        self.update_controls()

    def guard_pending(self):
        if self.pending and time.monotonic() - self.pending_at > 2.0:
            cmd = self.pending; self.pending = None
            self.link.fail(f'{cmd} 未收到确认，已请求停止并断开；请检查实际运动状态。')

    def closeEvent(self, event):
        if self.experiment: self.experiment.abort('窗口关闭')
        self.sensor.disconnect(); self.link.close(); event.accept()


def main():
    app = QApplication(sys.argv); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    w = Window(); w.show()
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
