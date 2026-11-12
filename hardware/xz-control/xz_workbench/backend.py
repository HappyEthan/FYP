"""Background device ownership, heartbeat, sensing and recording orchestration."""
import copy
import json
import math
import queue
import threading
import time
from collections import deque
from pathlib import Path

import serial
from xz_control.protocol import Simulator, parse_status
from .engine import Engine
from .model import AxisConfig, plan_steps
from .recording import Frame, SensorDecoder, BaselineCollector, Recorder


def open_port(port,baud):
    conn=serial.Serial(port=None,baudrate=baud,timeout=0,write_timeout=.1,exclusive=True)
    conn.dtr=False; conn.rts=False; conn.port=port
    try: conn.open()
    except Exception:
        conn.close(); raise
    return conn


def same_device(a,b):
    if not a or not b or a=='DEMO' or b=='DEMO': return False
    return Path(a).resolve()==Path(b).resolve()


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(name='xz-device-worker',daemon=True)
        self.commands=queue.Queue(maxsize=256); self.events=queue.Queue(maxsize=200)
        self.exit_event=threading.Event(); self.stop_event=threading.Event(); self.release_event=threading.Event()
        self.lock=threading.Lock(); self.latest={}; self.gui_lease=0.; self.generation=0
        self.engine=Engine(self._send,time.monotonic,self._engine_event)
        self.motor=None; self.motor_port=None; self.sensor=None; self.sensor_port=None
        self.sim=None; self.sensor_demo=False; self.decoder=SensorDecoder(); self.motor_buffer=bytearray()
        self.packets=deque(); self.hello=None; self.opened_at=0.; self.last_hello=0.; self.last_ping=0.
        self.handshake_complete=False
        self.collector=None; self.baseline=None; self.baseline_info=None
        self.last_sensor=0.; self.last_frame=None; self.history=deque(maxlen=2000); self.last_plot=0.
        self.demo_stamp=0; self.demo_frame_at=0.; self.previous_cycle=time.monotonic()
        self.recorder=None; self.record_owned=False; self.pending_recipe=None; self.record_wait=None
        self.finalizers=[]; self.saved_path=None; self.notice=''; self.last_publish=0.

    def emit(self,kind,**payload):
        event=dict(type=kind,**payload)
        try: self.events.put_nowait(event)
        except queue.Full:
            try: self.events.get_nowait()
            except queue.Empty: pass
            try: self.events.put_nowait(event)
            except queue.Full: pass

    def snapshot(self):
        with self.lock: return copy.deepcopy(self.latest)

    def submit(self,name,**payload):
        if name in ('stop','release'):
            with self.lock: self.generation+=1
            (self.stop_event if name=='stop' else self.release_event).set()
            return
        with self.lock: generation=self.generation
        try: self.commands.put_nowait((generation,name,copy.deepcopy(payload)))
        except queue.Full:
            self.stop_event.set(); self.emit('error',message='操作队列已满，已请求停止')

    def lease(self):
        with self.lock: self.gui_lease=time.monotonic()

    def _send(self,line):
        if self.sim:
            self.packets.extend(self.sim.command(line)); return
        if not self.motor: raise OSError('电机串口未连接')
        data=(line+'\n').encode('ascii')
        if self.motor.write(data)!=len(data): raise OSError('电机串口写入不完整')

    def _engine_event(self,event):
        self.emit(event['type'],**{k:v for k,v in event.items() if k!='type'})
        if event['type']=='stopped':
            self.pending_recipe=None
            self._end_record('aborted',event.get('reason'))
        elif event['type']=='complete' and self.record_owned:
            self._end_record('completed')

    def _close_motor(self):
        try:
            if self.engine.ready: self.engine.stop('断开电机')
            elif self.motor: self._send('STOP')
        finally:
            if self.motor: self.motor.close()
            self.motor=None; self.sim=None; self.motor_port=None; self.hello=None
            self.handshake_complete=False
            self.engine.ready=False; self.engine.status=None; self.engine.pending=None
            self.packets.clear(); self.motor_buffer.clear()

    def _connect_motor(self,port):
        if self.recorder or self.engine.owner: raise ValueError('请先停止运动和采集')
        if same_device(port,self.sensor_port): raise ValueError('该设备已用于磁传感器')
        self._close_motor()
        self.motor_port=port; self.opened_at=time.monotonic(); self.last_hello=0.
        if port=='DEMO':
            self.sim=Simulator(); self.engine.connect(self.sim.s.copy())
            self.handshake_complete=True
            self.emit('log',message='模拟电机：不连接硬件，运动仅为理想模型')
        else:
            try: self.motor=open_port(port,115200)
            except Exception: self.motor_port=None; raise
            self.emit('log',message='等待 XZ1 固件握手')

    def _connect_sensor(self,port,baud):
        if self.recorder or self.collector: raise ValueError('请先结束采集或基线校准')
        if same_device(port,self.motor_port): raise ValueError('该设备已用于电机')
        if self.sensor: self.sensor.close()
        self.sensor=None; self.sensor_port=None; self.sensor_demo=False
        self.baseline=None; self.baseline_info=None; self.last_sensor=0.; self.last_frame=None
        self.decoder=SensorDecoder(); self.history.clear()
        if port:
            if port=='DEMO': self.sensor_demo=True
            else: self.sensor=open_port(port,baud)
            self.sensor_port=port

    def _start_record(self,root,recipe=None):
        self.engine.require_idle()
        if self.recorder or self.collector: raise ValueError('正在采集或校准')
        if self.baseline is None: raise ValueError('请先完成静止空载基线校准')
        if time.monotonic()-self.last_sensor>2: raise ValueError('传感器没有持续输出有效数据')
        if recipe:
            self.engine.require_idle(armed=True)
            if recipe.config_changed(self.engine.config): raise ValueError('流程配置已改变，请检查并重新保存')
            plan_steps(recipe,self.engine.status,self.engine.config)
        self._discard_sensor_backlog()
        context=dict(motor_port=self.motor_port,sensor_port=self.sensor_port,config=self.engine.config.to_dict(),
                     demo=bool(self.sim or self.sensor_demo),baseline=self.baseline_info,
                     recipe=({'name':recipe.name,'steps':[vars(s) for s in recipe.steps]} if recipe else None))
        self.recorder=Recorder(root,self.baseline,context); self.engine.recording=True
        self.record_owned=recipe is not None; self.pending_recipe=recipe
        self.record_wait=time.monotonic()+2.
        if recipe is not None:
            self.engine.owner='preparing'; self.engine.stage='record_ready'
        self.emit('log',message='记录已创建，等待新的传感器样本：'+str(self.recorder.path))

    def _end_record(self,outcome='completed',reason=None):
        recorder=self.recorder
        self.recorder=None; self.engine.recording=False; self.record_owned=False
        self.pending_recipe=None; self.record_wait=None
        if not recorder: return
        # Final flushing never blocks motor heartbeat or user stop processing.
        def finalize():
            try:
                path=recorder.close(outcome,reason); self.saved_path=str(path)
                self.emit('saved',path=str(path),outcome=outcome)
            except Exception as exc: self.emit('error',message=str(exc))
        thread=threading.Thread(target=finalize,name='xz-record-finalize',daemon=True)
        self.finalizers=[t for t in self.finalizers if t.is_alive()]+[thread]
        thread.start()

    def _handle(self,name,payload):
        if name=='connect_motor': self._connect_motor(payload['port'])
        elif name=='disconnect_motor': self._close_motor()
        elif name=='connect_sensor': self._connect_sensor(payload.get('port'),payload.get('baud',115200))
        elif name=='configure': self.engine.configure(AxisConfig(**payload['config']))
        elif name=='zero': self.engine.zero(payload['axis'])
        elif name=='arm': self.engine.arm()
        elif name=='clear': self.engine.clear()
        elif name=='jog':
            if self.collector: raise ValueError('基线采集中不能移动')
            self.engine.jog(payload['axis'],payload['direction'])
        elif name in ('move','run'):
            if self.collector: raise ValueError('基线采集中不能移动')
            if name=='move': self.engine.move(payload['step'])
            else: self.engine.run(payload['recipe'])
        elif name=='baseline':
            self.engine.require_idle()
            if self.recorder or self.collector: raise ValueError('正在录制或校准')
            if time.monotonic()-self.last_sensor>2: raise ValueError('请先连接传感器并确认数据')
            self._discard_sensor_backlog()
            self.collector=BaselineCollector(time.monotonic(),payload.get('seconds',2))
            self.emit('log',message='正在采集空载基线，请保持静止')
        elif name=='record_start': self._start_record(payload['root'])
        elif name=='run_record': self._start_record(payload['root'],payload['recipe'])
        elif name=='record_stop':
            if self.record_owned: raise ValueError('函数录制请等待完成，或点击中止')
            self._end_record()
        else: raise ValueError('未知工作台操作')

    def _discard_sensor_backlog(self):
        if self.sensor: self.sensor.reset_input_buffer()
        self.decoder.buffer.clear(); self.decoder.discarding=False

    def _receive_motor(self,now,dt):
        if self.sim:
            self.packets.extend(self.sim.tick(min(dt,.1)))
        elif self.motor:
            if not self.engine.ready:
                if now-self.opened_at>8: raise OSError('XZ1 握手超时，请核对固件和串口')
                if now-self.last_hello>=1: self._send('HELLO'); self.last_hello=now
            if now-self.last_ping>=.25: self._send('PING'); self.last_ping=now
            self.motor_buffer.extend(self.motor.read(min(self.motor.in_waiting,65536)))
            if len(self.motor_buffer)>65536: raise OSError('电机串口数据过长')
            while b'\n' in self.motor_buffer:
                raw,_,rest=self.motor_buffer.partition(b'\n'); self.motor_buffer=bytearray(rest)
                try: packet=json.loads(raw)
                except (ValueError,UnicodeDecodeError): continue
                if not isinstance(packet,dict): continue
                if packet.get('type')=='hello':
                    if packet.get('protocol')!='XZ1' or not all(packet.get(k) is True for k in ('move_accel','jog_continuous','numeric_ranges')):
                        raise OSError('固件不兼容，请使用配套 XZ_Controller 1.4.0')
                    self.hello=packet
                elif packet.get('type')=='status' and not self.engine.ready and self.hello:
                    self.engine.connect(parse_status(packet)); self.handshake_complete=True
                    self.engine.issue('DISARM')
                elif self.engine.ready: self.packets.append(packet)
        for _ in range(min(200,len(self.packets))): self.engine.packet(self.packets.popleft())

    def _receive_sensor(self,now):
        frames=[]
        if self.sensor_demo:
            if now-self.demo_frame_at>=.02:
                self.demo_frame_at=now
                x=(self.engine.status or {}).get('x',0)/250
                for _ in range(5):
                    self.demo_stamp+=4000
                    b=math.sin(self.demo_stamp/1e5+x)*2
                    frames.append(Frame(self.demo_stamp,self.demo_stamp,0,time.monotonic_ns(),100+b,20+b*.2,30-b*.4))
        elif self.sensor:
            try:
                frames=self.decoder.feed(self.sensor.read(min(self.sensor.in_waiting,65536)))
            except (OSError,serial.SerialException) as exc:
                if self.recorder: raise
                try: self.sensor.close()
                except OSError: pass
                self.sensor=None; self.sensor_port=None; self.last_sensor=0.
                self.collector=None; self.baseline=None; self.baseline_info=None
                self.notice=str(exc); self.emit('error',message=str(exc)); return
        for frame in frames:
            self.last_frame=frame; self.last_sensor=now
            if self.collector: self.collector.add(frame)
            if self.recorder:
                self.recorder.append(frame,self.engine.stage,self.engine.status)
                self.record_wait=None
            if now-self.last_plot>=.02:
                self.history.append((now,*frame.values)); self.last_plot=now
        if self.collector and self.collector.ready(now):
            collector=self.collector; self.collector=None
            try:
                info=collector.finish(now)
                self.baseline_info=info; self.baseline=info['baseline']
                self.emit('log',message='基线校准完成：'+str(tuple(round(v,3) for v in self.baseline)))
            except ValueError as exc:
                self.notice=str(exc); self.emit('error',message=str(exc))
        if self.recorder:
            if self.recorder.error: raise OSError('CSV 写入失败：'+self.recorder.error)
            if now-self.last_sensor>2 or (self.record_wait and now>self.record_wait):
                raise OSError('传感器超过 2 秒没有有效数据')
            if self.pending_recipe and self.record_wait is None:
                recipe=self.pending_recipe; self.pending_recipe=None
                self.engine.owner=None
                self.engine.run(recipe)

    def _publish(self):
        snap=self.engine.snapshot()
        snap.update(motor_port=self.motor_port,sensor_port=self.sensor_port,
                    sensor_alive=time.monotonic()-self.last_sensor<2,
                    baseline=self.baseline,calibrating=self.collector is not None,
                    sensor_values=self.last_frame.values if self.last_frame else None,
                    history=list(self.history),record_owned=self.record_owned,
                    samples=self.recorder.count if self.recorder else 0,
                    bad_lines=self.decoder.bad_lines,saved_path=self.saved_path,notice=self.notice,
                    demo=bool(self.sim or self.sensor_demo))
        with self.lock: self.latest=snap

    def run(self):
        try:
            while not self.exit_event.is_set():
                now=time.monotonic(); dt=now-self.previous_cycle; self.previous_cycle=now
                try:
                    if self.stop_event.is_set():
                        self.stop_event.clear(); self.collector=None
                        self.engine.stop('用户停止全部')
                        while True:
                            try: self.commands.get_nowait()
                            except queue.Empty: break
                    if self.release_event.is_set(): self.release_event.clear(); self.engine.release()
                    for _ in range(16):
                        try: generation,name,payload=self.commands.get_nowait()
                        except queue.Empty: break
                        if generation!=self.generation: continue
                        try: self._handle(name,payload); self.notice=''
                        except ValueError as exc:
                            self.notice=str(exc); self.emit('error',message=str(exc))
                            if name=='run_record' and self.recorder: self.engine.stop(str(exc))
                    self._receive_motor(now,dt)
                    self._receive_sensor(now)
                    with self.lock: gui_lease=self.gui_lease
                    if gui_lease>self.engine.lease_at: self.engine.lease_at=gui_lease
                    self.engine.tick()
                    if self.motor and self.handshake_complete and not self.engine.ready: self._close_motor()
                except Exception as exc:
                    self.notice=str(exc); self.emit('error',message=str(exc))
                    self.collector=None
                    try: self._close_motor()
                    except Exception: self.engine.ready=False; self.engine.status=None
                    self._end_record('aborted',str(exc))
                    if self.sensor:
                        try: self.sensor.close()
                        except Exception: pass
                    self.sensor=None; self.sensor_port=None; self.sensor_demo=False
                if now-self.last_publish>=.04:
                    self._publish(); self.last_publish=now
                self.exit_event.wait(.005)
        finally:
            try: self._close_motor()
            except Exception as exc: self.emit('error',message=str(exc))
            self._end_record('aborted','工作台关闭')
            if self.sensor:
                try: self.sensor.close()
                except Exception: pass
            self._publish()

    def shutdown(self):
        self.exit_event.set()
        if self.is_alive(): self.join(timeout=3)
        for finalizer in self.finalizers: finalizer.join(timeout=6)
