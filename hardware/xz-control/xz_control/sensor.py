"""Independent read-only magnetic sensor serial monitor. No device commands."""
import math
import re
import time
from datetime import datetime, timezone
from collections import deque
import serial
from serial.tools import list_ports
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, Signal, QLineF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QSizePolicy


class SensorParser:
    def __init__(self):
        self.kind = '磁场（CSV 未声明 B/ΔB）'
        self.device_time_us = None

    def parse(self, line):
        self.device_time_us = None
        line = line.strip()
        if line.startswith('#') and 't_us,Bx_uT,By_uT,Bz_uT' in line:
            self.kind = 'B'
            return None
        if not line or line.startswith('#'): return None
        fields = [v.strip() for v in line.split(',')]
        if fields in (['t_us', 'Bx', 'By', 'Bz'], ['t_us', 'Bx_uT', 'By_uT', 'Bz_uT'], ['t_us', 'dBx', 'dBy', 'dBz']):
            self.kind = 'ΔB' if fields[1].startswith('d') else 'B'
            return None
        labels = dict(re.findall(r'\b(d?B[xyz])\s*:\s*([^,\s]+)', line, re.I))
        labels = {k.lower(): v for k, v in labels.items()}
        try:
            if all(k in labels for k in ('dbx','dby','dbz')):
                values = [float(labels[k]) for k in ('dbx','dby','dbz')]; kind = 'ΔB'
            elif all(k in labels for k in ('bx','by','bz')):
                values = [float(labels[k]) for k in ('bx','by','bz')]; kind = 'B'
            elif len(fields) == 4:
                stamp = int(fields[0])
                if stamp < 0: return None
                values = [float(v) for v in fields[1:]]; kind = self.kind
            else: return None
            if not all(math.isfinite(v) and abs(v) <= 1e12 for v in values): return None
        except (ValueError, OverflowError): return None
        self.kind = kind
        if not labels: self.device_time_us = stamp
        return tuple(values)

class TimingTracker:
    """Relative transport lag, not absolute latency; clocks are not synchronized."""
    def __init__(self):
        self.last_device = None; self.min_offset = None; self.segment = 0
        self.intervals = deque(maxlen=500)

    def update(self, device_us, host_time):
        reset = device_us is not None and self.last_device is not None and device_us < self.last_device
        if reset:
            self.min_offset = None; self.intervals.clear(); self.segment += 1
        lag = None
        if device_us is not None:
            if self.last_device is not None and device_us > self.last_device:
                self.intervals.append((device_us-self.last_device)/1e6)
            offset = host_time-device_us/1e6
            self.min_offset = offset if self.min_offset is None else min(self.min_offset,offset)
            lag = max(0., offset-self.min_offset)
            self.last_device = device_us
        return dict(device_time_us=device_us,device_clock_segment=self.segment,
                    device_clock_reset=int(reset),relative_transport_lag_s=lag)

    def rate(self):
        return len(self.intervals)/sum(self.intervals) if self.intervals else None


class DisplayEnvelope:
    """Display-only 50 ms min/max bins; acquisition and CSV never use this reduction."""
    def __init__(self):
        self.bins = deque(maxlen=202)

    def clear(self): self.bins.clear()

    def append(self, sample):
        t=sample[0]; values=sample[1:3]; slot=math.floor(t/.05)
        if self.bins and slot < self.bins[-1]['slot']: self.clear()
        if not self.bins or self.bins[-1]['slot']!=slot:
            self.bins.append(dict(slot=slot,t=t,end=t,first=list(values),last=list(values),
                                  low=list(values),high=list(values)))
        else:
            b=self.bins[-1]; b['end']=t; b['last']=list(values)
            for a in range(2): b['low'][a]=min(b['low'][a],values[a]); b['high'][a]=max(b['high'][a],values[a])
        while self.bins and self.bins[0]['end'] < t-10: self.bins.popleft()

    def snapshot(self):
        return [dict(b,first=b['first'][:],last=b['last'][:],low=b['low'][:],high=b['high'][:]) for b in self.bins]


class MagneticPlot(QWidget):
    COLORS = ('#345eea', '#16a085', '#d96a35')

    def __init__(self):
        super().__init__(); self.samples = DisplayEnvelope()
        self.setMinimumSize(310, 300)
        self.frozen = False; self.frozen_samples = []; self.window_seconds=10

    def clear(self):
        self.samples.clear(); self.frozen_samples = []; self.update()

    def pause(self, frozen):
        self.frozen = frozen
        self.frozen_samples = self.samples.snapshot() if frozen else []
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor('white'))
        data = self.frozen_samples if self.frozen else self.samples.snapshot()
        end = data[-1]['end'] if data else time.monotonic()
        start = end - self.window_seconds
        data = [r for r in data if r['end'] >= start]
        height = (self.height()-24)/2
        for axis in range(2):
            area = QRectF(65, axis*height+25, self.width()-80, height-48)
            lo = min(r['low'][axis] for r in data) if data else -1.
            hi = max(r['high'][axis] for r in data) if data else 1.
            pad = max((hi-lo)*.12, .01)
            lo -= pad; hi += pad
            p.setPen(QColor(self.COLORS[axis]))
            p.drawText(QPointF(8, area.top()-7), f'{"XYZ"[axis]}  (µT)')
            p.setPen(QColor('#e3e8f1'))
            for i in range(5):
                y=area.top()+area.height()*i/4
                p.drawLine(QPointF(area.left(),y), QPointF(area.right(),y))
            p.setPen(QColor('#718096'))
            p.drawText(QRectF(0,area.top()-8,60,18), Qt.AlignRight, f'{hi:.4g}')
            p.drawText(QRectF(0,area.bottom()-8,60,18), Qt.AlignRight, f'{lo:.4g}')
            lines=[]; previous=None; previous_time=None
            def xy(t,v):
                return QPointF(area.left()+(t-start)/self.window_seconds*area.width(),
                               area.bottom()-(v-lo)/(hi-lo)*area.height())
            for r in data:
                mid=(r['t']+r['end'])/2
                lines.append(QLineF(xy(mid,r['low'][axis]),xy(mid,r['high'][axis])))
                if previous is not None and r['t']-previous_time<=.5:
                    lines.append(QLineF(previous,xy(r['t'],r['first'][axis])))
                lines.append(QLineF(xy(r['t'],r['first'][axis]),xy(r['end'],r['last'][axis])))
                previous=xy(r['end'],r['last'][axis]); previous_time=r['end']
            p.save(); p.setClipRect(area); p.setPen(QPen(QColor(self.COLORS[axis]),1))
            if lines: p.drawLines(lines)
            p.restore()
            if not data:
                p.drawText(area, Qt.AlignCenter, '等待传感器数据')
        p.setPen(QColor('#718096'))
        p.drawText(QRectF(65,self.height()-22,self.width()-80,20), Qt.AlignCenter,
                   f'−{self.window_seconds} s    接收时间 · 极值包络    0 s')


class SensorPanel(QWidget):
    sample_received = Signal(float, object, str, object)
    calibration_changed = Signal()
    def __init__(self, motor_port, calibration_allowed=lambda: True):
        super().__init__(); self.motor_port = motor_port; self.ser = None
        self.calibration_allowed=calibration_allowed
        self.offset=(0.,0.,0.); self.calibration_id=0; self.calibration_info={}
        self.calibrating=False; self.calibration_start=0.; self.calibration_count=0
        self.calibration_sum=[0.,0.,0.]; self.calibration_last=None
        self.buffer = bytearray(); self.discarding = False; self.parser = SensorParser()
        self.last_sample = None; self.last_values = None; self.received = deque(maxlen=12000)
        self.count = 0; self.bad = 0; self.started = 0
        self.timing=TimingTracker(); self.sample_timing={}; self.raw_line='—'
        self.last_poll=None; self.poll_gap=0.; self.pending_bytes=0; self.batch_id=0
        layout=QVBoxLayout(self); layout.setContentsMargins(8,8,8,8)
        title=QLabel('磁毛传感器 · ESP32-C3'); title.setObjectName('section'); layout.addWidget(title)
        info=QLabel('I²C 0x0C（用户配置） · 独立串口，只接收数据'); info.setWordWrap(True); layout.addWidget(info)
        self.ports=QComboBox(); layout.addWidget(self.ports)
        self.ports.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.ports.setMinimumContentsLength(20)
        row=QHBoxLayout(); self.baud=QComboBox()
        for v in (115200,230400,460800,921600,9600): self.baud.addItem(str(v),v)
        row.addWidget(self.baud)
        self.refresh=QPushButton('刷新'); self.refresh.clicked.connect(self.refresh_ports); row.addWidget(self.refresh)
        self.connect_btn=QPushButton('连接传感器'); self.connect_btn.clicked.connect(self.toggle); row.addWidget(self.connect_btn)
        layout.addLayout(row)
        self.status=QLabel('未连接'); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.values=QLabel('X —    Y — µT'); self.values.setWordWrap(True); layout.addWidget(self.values)
        self.recalibrate_btn=QPushButton('Recalibration · 空载归零')
        self.recalibrate_btn.clicked.connect(self.start_calibration); layout.addWidget(self.recalibrate_btn)
        self.calibration_status=QLabel('未校正 · 空载静止后点击，采集 2 秒基线')
        self.calibration_status.setWordWrap(True); layout.addWidget(self.calibration_status)
        self.recalibrate_btn.setEnabled(False)
        self.plot=MagneticPlot(); layout.addWidget(self.plot,1)
        row=QHBoxLayout(); self.pause_btn=QPushButton('暂停曲线'); self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self.pause); row.addWidget(self.pause_btn)
        clear=QPushButton('清空曲线'); clear.clicked.connect(self.plot.clear); row.addWidget(clear); layout.addLayout(row)
        self.window_select=QComboBox()
        for seconds in (2,5,10): self.window_select.addItem(f'显示最近 {seconds} 秒',seconds)
        self.window_select.setCurrentIndex(2)
        self.window_select.currentIndexChanged.connect(self.change_plot_window)
        layout.addWidget(self.window_select)
        self.raw=QLabel('最近串口行：—'); self.raw.setWordWrap(True); self.raw.setMaximumHeight(60); layout.addWidget(self.raw)
        self.raw.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        note=QLabel('自动识别 Bx/By/Bz、dBx/dBy/dBz 标签或四列 CSV。\n单位按 FYP 固件 µT；不追加平滑、不修改采样频率。')
        note.setObjectName('muted'); note.setWordWrap(True); layout.addWidget(note)
        self.timer=QTimer(self); self.timer.timeout.connect(self.poll); self.timer.start(10)
        self.display_timer=QTimer(self); self.display_timer.timeout.connect(self.render_status); self.display_timer.start(50)
        self.refresh_ports()

    @property
    def port(self): return self.ser.port if self.ser else None

    def calibration_snapshot(self):
        return dict(id=self.calibration_id, baseline_uT=list(self.offset), **self.calibration_info)

    def corrected(self, values):
        return tuple(v-b for v,b in zip(values,self.offset))

    def refresh_calibration_button(self):
        fresh=self.last_sample is not None and time.monotonic()-self.last_sample<2
        self.recalibrate_btn.setEnabled(bool(self.ser and fresh and not self.calibrating and self.calibration_allowed()))

    def reset_calibration(self):
        self.calibrating=False; self.offset=(0.,0.,0.); self.calibration_id=0; self.calibration_info={}
        self.calibration_status.setText('未校正 · 空载静止后点击，采集 2 秒基线')
        self.refresh_calibration_button(); self.calibration_changed.emit()

    def cancel_calibration(self, reason):
        self.calibrating=False
        self.calibration_status.setText(reason+'；保留之前的基线，请重新校准')
        self.refresh_calibration_button(); self.calibration_changed.emit()

    def start_calibration(self):
        self.refresh_calibration_button()
        if not self.recalibrate_btn.isEnabled(): return
        self.calibrating=True; self.calibration_start=time.monotonic()
        self.calibration_count=0; self.calibration_sum=[0.,0.,0.]; self.calibration_last=None
        self.calibration_status.setText('正在采集 2 秒空载基线，请保持静止…')
        self.refresh_calibration_button(); self.calibration_changed.emit()

    def calibration_sample(self, now, values, timing):
        if not self.calibrating: return
        if not self.calibration_allowed():
            self.cancel_calibration('控制器状态发生变化'); return
        if (timing.get('device_clock_reset') or (timing.get('relative_transport_lag_s') or 0)>.25
                or (self.calibration_last is not None and now-self.calibration_last>.5)):
            self.cancel_calibration('数据不连续或存在积压'); return
        self.calibration_last=now
        self.calibration_count+=1
        for i,v in enumerate(values): self.calibration_sum[i]+=v
        if now-self.calibration_start<2: return
        if self.calibration_count<20:
            self.cancel_calibration('有效样本不足'); return
        self.offset=tuple(s/self.calibration_count for s in self.calibration_sum)
        self.calibration_id+=1; self.calibrating=False
        self.calibration_info=dict(completed_utc=datetime.now(timezone.utc).isoformat(),
                                   samples=self.calibration_count, duration_s=now-self.calibration_start,
                                   source_kind=self.parser.kind, method='mean of unloaded input; corrected = input - baseline')
        self.plot.clear(); self.pause_btn.setChecked(False)
        self.calibration_status.setText('已空载归零 · 基线 XYZ / µT：\n'+', '.join(f'{v:.2f}' for v in self.offset))
        self.refresh_calibration_button(); self.calibration_changed.emit()

    def refresh_ports(self):
        old=self.ports.currentData(); self.ports.clear()
        for p in list_ports.comports():
            if 'Bluetooth' not in p.device and 'debug-console' not in p.device:
                self.ports.addItem(f'{p.device} · {p.description}',p.device)
        index=self.ports.findData(old)
        if index>=0: self.ports.setCurrentIndex(index)

    def disconnect(self, message='已断开 · 曲线保留为历史数据'):
        if self.ser:
            try: self.ser.close()
            except (OSError, serial.SerialException): pass
        self.ser=None; self.buffer.clear()
        self.reset_calibration()
        self.connect_btn.setText('连接传感器')
        for w in (self.ports,self.refresh,self.baud): w.setEnabled(True)
        self.values.setText('X —    Y — µT'); self.status.setText(message)

    def toggle(self):
        if self.ser: self.disconnect(); return
        port=self.ports.currentData()
        if not port: self.status.setText('未发现串口，请插入 ESP32-C3 后刷新。'); return
        if port == self.motor_port():
            self.status.setText('这个串口已用于电机，请选择 ESP32-C3 的另一个串口。'); return
        try:
            conn=serial.Serial(port=None,baudrate=self.baud.currentData(),timeout=0,exclusive=True)
            conn.dtr=False; conn.rts=False; conn.port=port
            try: conn.open()
            except Exception: conn.close(); raise
            self.ser=conn
        except (OSError,serial.SerialException) as e:
            self.status.setText('连接失败：'+str(e)); return
        self.buffer.clear(); self.discarding=False; self.parser=SensorParser()
        self.timing=TimingTracker(); self.sample_timing={}; self.raw_line='—'
        self.last_poll=None; self.poll_gap=0.; self.pending_bytes=0; self.batch_id=0
        self.count=self.bad=0; self.received.clear(); self.last_sample=None; self.last_values=None
        self.reset_calibration()
        self.started=time.monotonic(); self.plot.clear(); self.pause_btn.setChecked(False)
        self.connect_btn.setText('断开传感器')
        for w in (self.ports,self.refresh,self.baud): w.setEnabled(False)
        self.status.setText('串口已打开，等待有效磁场数据…')

    def feed(self, data, now):
        self.batch_id+=1
        # Bounded framing; discard an overlong frame through its newline.
        for byte in data:
            if byte == 10:
                if not self.discarding:
                    line=self.buffer.decode('utf-8',errors='replace').strip()
                    if line:
                        self.raw_line=line[:150]
                        values=self.parser.parse(line)
                        if values is not None:
                            self.last_sample=now; self.last_values=values; self.count+=1
                            self.received.append(now)
                            timing=self.timing.update(self.parser.device_time_us,now)
                            self.calibration_sample(now,values,timing)
                            self.plot.samples.append((now,*self.corrected(values)))
                            timing.update(baseline_uT=self.offset,calibration_id=self.calibration_id)
                            timing.update(serial_pending_bytes=self.pending_bytes,read_batch_id=self.batch_id,
                                          host_poll_gap_s=self.poll_gap)
                            self.sample_timing=timing
                            self.sample_received.emit(now, values, self.parser.kind, timing)
                        elif not line.startswith('#') and not line.startswith('t_us,'): self.bad+=1
                self.buffer.clear(); self.discarding=False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer)>1024:
                    self.buffer.clear(); self.discarding=True; self.bad+=1

    def poll(self):
        if not self.ser: return
        try:
            now=time.monotonic(); self.poll_gap=0. if self.last_poll is None else now-self.last_poll; self.last_poll=now
            self.pending_bytes=self.ser.in_waiting
            data=self.ser.read(min(self.pending_bytes,16384))
            self.feed(data,time.monotonic())
        except (OSError,serial.SerialException) as e:
            self.disconnect('传感器连接中断：'+str(e))

    def render_status(self):
        self.refresh_calibration_button()
        if self.calibrating and time.monotonic()-self.calibration_start>3:
            self.cancel_calibration('校准超时')
        if not self.ser: return
        now=time.monotonic()
        self.raw.setText('最近串口行：'+self.raw_line)
        while self.received and self.received[0]<now-2: self.received.popleft()
        age=now-(self.last_sample if self.last_sample is not None else self.started)
        if self.last_sample is None:
            self.status.setText('等待有效磁场数据；若持续无数据，请检查波特率和最近串口行。')
        elif age>2:
            self.status.setText(f'数据已过期 · {age:.1f}s 未收到有效样本 · 曲线为历史数据')
            self.values.setText('X —    Y — µT')
        else:
            rate=len(self.received)/min(2,max(.1,now-self.started))
            device_rate=self.timing.rate() if self.sample_timing.get('device_time_us') is not None else None
            lag=self.sample_timing.get('relative_transport_lag_s')
            timing_text='无设备时间，无法判断积压' if lag is None else f'相对延迟增量 {lag*1000:.0f} ms'
            rate_text='' if device_rate is None else f' · 设备约 {device_rate:.1f} Hz'
            self.status.setText(f'{self.parser.kind} · 接收 {rate:.1f} Hz{rate_text}\n'
                                f'{timing_text} · 读取前缓冲 {self.pending_bytes} B · {self.count} 点 · 未识别 {self.bad} 行')
            prefix='归零后 · ' if self.calibration_id else ''
            self.values.setText(prefix+'    '.join(f'{a} {v:.2f}' for a,v in zip('XY',self.corrected(self.last_values)))+' µT')
        if not self.plot.frozen: self.plot.update()

    def pause(self, checked):
        self.plot.pause(checked); self.pause_btn.setText('恢复曲线' if checked else '暂停曲线')

    def change_plot_window(self):
        self.plot.window_seconds=self.window_select.currentData(); self.plot.update()
