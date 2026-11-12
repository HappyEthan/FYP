"""Sequential scan orchestration; sample timestamps are host receive times."""
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QObject, QTimer, Signal
from .protocol import move_command

MOTOR_FIELDS = ('x','z','tx','tz','vx','vz','armed','busy','phase','refx','refz','fault')
MOTOR_COLUMNS = ('motor_x_pulses','motor_z_pulses','motor_target_x_pulses','motor_target_z_pulses',
                 'motor_vx_pps','motor_vz_pps','motor_armed','motor_busy','motor_phase',
                 'motor_refx','motor_refz','motor_fault','motor_remaining_x_pulses','motor_remaining_z_pulses')
TIMING_COLUMNS = ('device_time_us','device_clock_segment','device_clock_reset','relative_transport_lag_s',
                  'serial_pending_bytes','read_batch_id','host_poll_gap_s')

def motor_values(s):
    return [s[k] for k in MOTOR_FIELDS] + [s['tx']-s['x'], s['tz']-s['z']]


class Experiment(QObject):
    changed = Signal(str)

    def __init__(self, send, motor_state, sensor_alive, parent=None):
        super().__init__(parent)
        self.send=send; self.motor_state=motor_state; self.sensor_alive=sensor_alive
        self.active=False; self.recording=False; self.stage='idle'; self.file=None
        self.folder=None; self.meta={}; self.count=0; self.last_status_at=None
        self.controller_file=None; self.event_file=None
        self.controller_count=0; self.event_count=0
        self.timer=QTimer(self); self.timer.setInterval(50); self.timer.timeout.connect(self.tick)
        self.timer.start()

    def start(self, folder, endpoint, speeds, accels, context):
        if self.active: raise ValueError('实验正在进行')
        s=self.motor_state()
        if not s or not s['armed'] or s['busy'] or s['fault']!='NONE' or not s['refx'] or not s['refz']:
            raise ValueError('请先连接电机、设置两轴零点并使能，确保当前无运动或故障')
        if s['x']!=0 or s['z']!=0: raise ValueError('实验必须从人工零点 X=0、Z=0 开始；请先回零或重新确认并设零')
        if not self.sensor_alive(): raise ValueError('请先连接传感器并确认持续收到有效磁场数据')
        x,z=endpoint
        if x==0: raise ValueError('X 终点不能为 0，否则没有扫描行程')
        positions=[(0,0),(0,z),(x,z),(x,0),(0,0)]
        self.commands=[]
        for before,after in zip(positions,positions[1:]):
            self.commands.append(move_command('ABS','SIM',*after,*speeds,dict(x=before[0],z=before[1]),*accels))
        # Create outputs before moving. Each run owns a new directory and never overwrites a run.
        root=Path(folder); root.mkdir(parents=True,exist_ok=True)
        self.folder=root/datetime.now().strftime('%Y%m%d_%H%M%S_%f'); self.folder.mkdir()
        self.count=0; self.last_flush=time.monotonic(); self.record_start=None
        self.run_start=time.monotonic(); self.controller_count=0; self.event_count=0
        self.meta=dict(schema_version=4,status='preparing',created_utc=datetime.now(timezone.utc).isoformat(),
                       endpoint_pulses=dict(x=x,z=z),speed_pps=dict(zip(('x','z'),speeds)),
                       acceleration_pps2=dict(zip(('x','z'),accels)),context=context,
                       timestamps='host monotonic receive time; motor position is latest reported software pulse count',
                       units='uT per sensor firmware convention',samples=0,scan_complete=False,returned_to_zero=False,
                       files=dict(samples='magnetic_xyz.csv',controller='controller.csv',events='events.jsonl'),
                       motor_phase_codes={'0':'idle','1':'X first','2':'Z first','3':'final/simultaneous'},
                       motor_speed_meaning='controller scheduled pulse rate, not measured motor speed',
                       magnetic_columns='magnetic_xyz = original serial values; corrected_magnetic_xyz = original minus baseline_xyz; calibration_id 0 means uncalibrated. signal_kind describes original input.',
                       sensor_timing='CSV first column preserved as device_time_us per t_us contract; confirm firmware units. Relative lag is excess over minimum observed host-device offset, NOT absolute latency; clock drift and buffering affect it. Labelled output has no device time.')
        try:
            self.file=(self.folder/'magnetic_xyz.csv').open('x',newline='',encoding='utf-8')
            self.writer=csv.writer(self.file)
            self.writer.writerow(['host_elapsed_s','host_monotonic_s','received_utc','experiment_elapsed_s','experiment_stage',
                                  'magnetic_x_uT','magnetic_y_uT','magnetic_z_uT','signal_kind',
                                  *MOTOR_COLUMNS,'motor_status_age_s',*TIMING_COLUMNS,
                                  'corrected_magnetic_x_uT','corrected_magnetic_y_uT','corrected_magnetic_z_uT',
                                  'baseline_x_uT','baseline_y_uT','baseline_z_uT','calibration_id'])
            self.controller_file=(self.folder/'controller.csv').open('x',newline='',encoding='utf-8')
            self.controller_writer=csv.writer(self.controller_file)
            self.controller_writer.writerow(['experiment_elapsed_s','host_monotonic_s','received_utc','experiment_stage',*MOTOR_COLUMNS])
            self.event_file=(self.folder/'events.jsonl').open('x',encoding='utf-8')
            self.stage='preparing'; self.record_event('start',dict(initial_motor_state=dict(s)))
            self.flush_files(); self.save_meta()
        except Exception:
            for name in ('file','controller_file','event_file'):
                f=getattr(self,name); setattr(self,name,None)
                if f: f.close()
            raise
        self.active=True; self.recording=False; self.endpoint=endpoint
        self.issue(0,'position_z','① Z 移动到实验高度')

    def save_meta(self):
        self.meta['samples']=self.count
        self.meta['controller_samples']=self.controller_count; self.meta['events']=self.event_count
        tmp=self.folder/'metadata.json.tmp'
        tmp.write_text(json.dumps(self.meta,ensure_ascii=False,indent=2),encoding='utf-8')
        tmp.replace(self.folder/'metadata.json')

    def issue(self, index, stage, text):
        self.stage=stage; self.acked=False; self.done=False; self.verified=False
        self.expected=[(0,self.endpoint[1]),self.endpoint,(self.endpoint[0],0),(0,0)][index]
        self.meta['status']=stage; self.changed.emit(text)
        try: self.record_event('command_requested',dict(command=self.commands[index]))
        except (OSError,ValueError) as e: self.abort('指令记录失败：'+str(e)); return
        self.send(self.commands[index])

    def record_event(self, event, payload):
        now=time.monotonic()
        self.event_file.write(json.dumps(dict(event=event,experiment_stage=self.stage,
            experiment_elapsed_s=now-self.run_start,host_monotonic_s=now,
            utc=datetime.now(timezone.utc).isoformat(),payload=payload),ensure_ascii=False)+'\n')
        self.event_count+=1

    def flush_files(self):
        for f in (self.file,self.controller_file,self.event_file):
            if f: f.flush()
        self.last_flush=time.monotonic()

    def close_controller_files(self):
        errors=[]
        for name in ('controller_file','event_file'):
            f=getattr(self,name); setattr(self,name,None)
            if f:
                try:
                    try: f.flush(); os.fsync(f.fileno())
                    finally: f.close()
                except (OSError,ValueError) as e: errors.append(str(e))
        if errors: raise OSError('; '.join(errors))

    def packet(self,p):
        if p.get('type')=='status': self.last_status_at=time.monotonic()
        if not self.active: return
        kind=p.get('type')
        try:
            if kind=='status':
                now=self.last_status_at
                self.controller_writer.writerow([f'{now-self.run_start:.6f}',f'{now:.6f}',
                    datetime.now(timezone.utc).isoformat(),self.stage,*motor_values(p)])
                self.controller_count+=1
            else: self.record_event('controller_packet',p)
        except (OSError,ValueError) as e: self.abort('控制器记录失败：'+str(e)); return
        if kind=='error': self.abort('控制器拒绝命令：'+str(p.get('code'))); return
        if kind=='ack' and p.get('cmd')=='MOVE': self.acked=True
        if kind=='done' and self.acked:
            self.done=True
            if self.stage=='scan_x': self.recording=False
        if kind=='status':
            if p['fault']!='NONE' or not p['armed'] or not p['refx'] or not p['refz']:
                self.abort('电机停止、故障或零点失效'); return
            if self.done and not p['busy']:
                if (p['x'],p['z'])!=self.expected:
                    self.abort('控制器完成位置与实验目标不一致'); return
                self.verified=True

    def sample(self, now, values, kind, timing=None):
        if not self.active or not self.recording: return
        s=self.motor_state()
        try:
            baseline=(timing or {}).get('baseline_uT',(0.,0.,0.))
            corrected=[v-b for v,b in zip(values[:3],baseline)]
            self.writer.writerow([f'{now-self.record_start:.6f}',f'{now:.6f}',datetime.now(timezone.utc).isoformat(),
                                  f'{now-self.run_start:.6f}',self.stage,*values[:3],kind,*motor_values(s),
                                  '' if self.last_status_at is None else f'{max(0,now-self.last_status_at):.6f}',
                                  *[(timing or {}).get(k,'') for k in TIMING_COLUMNS],
                                  *corrected,*baseline,(timing or {}).get('calibration_id',0)])
            self.count+=1
            if now-self.last_flush>=.25:
                self.flush_files()
        except (OSError,ValueError,TypeError) as e: self.abort('记录失败：'+str(e))

    def close_csv(self):
        if self.file:
            f=self.file; self.file=None
            try: f.flush(); os.fsync(f.fileno())
            finally: f.close()

    def tick(self):
        if not self.active: return
        if not self.sensor_alive(): self.abort('传感器断开或有效数据超时'); return
        try:
            if time.monotonic()-self.last_flush>=.25: self.flush_files()
        except (OSError,ValueError) as e: self.abort('文件刷新失败：'+str(e)); return
        if self.stage=='record_ready':
            if self.count: self.issue(1,'scan_x','③ 正在记录磁场 X/Y/Z，并沿 X 扫描')
            elif time.monotonic()-self.record_start>2: self.abort('记录开始后没有收到传感器样本')
            return
        if not self.verified: return
        self.verified=False
        try:
            if self.stage=='position_z':
                self.stage='record_ready'; self.record_start=time.monotonic(); self.recording=True
                self.meta['record_start_utc']=datetime.now(timezone.utc).isoformat()
                self.record_event('recording_started',{})
                self.changed.emit('② 开始记录，等待首个有效样本后启动 X')
            elif self.stage=='scan_x':
                self.recording=False; self.close_csv()
                if not self.count: self.abort('扫描结束但没有有效样本'); return
                self.meta['scan_complete']=True; self.meta['status']='scan_saved'; self.save_meta()
                self.record_event('scan_saved',dict(samples=self.count))
                self.issue(2,'return_z','④ 数据已保存，Z 返回零点')
            elif self.stage=='return_z': self.issue(3,'return_x','⑤ X 返回零点')
            elif self.stage=='return_x':
                self.record_event('complete',dict(returned_to_zero=True)); self.close_controller_files()
                self.meta.update(status='complete',returned_to_zero=True); self.save_meta()
                self.active=False; self.stage='complete'; self.changed.emit('实验完成并回零 · '+str(self.folder))
        except (OSError,ValueError) as e: self.abort('保存或执行失败：'+str(e))

    def abort(self, reason):
        if not self.active: return
        self.active=False; self.recording=False; self.stage='aborted'
        # Cancel all further transitions before sending STOP (callbacks may be synchronous).
        errors=[]
        try:
            if self.event_file:
                self.record_event('aborted',dict(reason=reason))
                self.record_event('command_requested',dict(command='STOP'))
        except (OSError,ValueError) as e: errors.append(str(e))
        self.send('STOP')
        try: self.close_csv()
        except (OSError,ValueError) as e: errors.append(str(e))
        try: self.close_controller_files()
        except (OSError,ValueError) as e: errors.append(str(e))
        self.meta.update(status='aborted',reason=reason)
        try: self.save_meta()
        except OSError as e: errors.append(str(e))
        suffix='；保存错误：'+'; '.join(errors) if errors else '；已保留采集文件：'+str(self.folder)
        self.changed.emit('实验已中止：'+reason+suffix)
