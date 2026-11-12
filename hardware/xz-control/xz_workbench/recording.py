"""Raw sensor framing and a bounded, incremental Windows-compatible CSV writer."""
import csv
import json
import math
import os
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from windows_acquire import quality_mask, mean, population_std

CSV_HEADER='seq,sensor_t_us,device_time_unwrapped_us,device_clock_segment,sensor_t_s,host_rx_ns,host_elapsed_s,stage,motor_x_pulses,motor_z_pulses,motor_target_x_pulses,motor_target_z_pulses,motor_busy,motor_phase,motor_fault,Bx_uT,By_uT,Bz_uT,dBx_uT,dBy_uT,dBz_uT,sample_valid,invalid_reason'.split(',')


@dataclass(frozen=True)
class Frame:
    sensor_us: int
    unwrapped_us: int
    segment: int
    host_ns: int
    bx: float
    by: float
    bz: float

    @property
    def values(self): return (self.bx,self.by,self.bz)


class SensorDecoder:
    def __init__(self):
        self.buffer=bytearray(); self.bad_lines=0; self.last=None; self.offset=0; self.segment=0
        self.discarding=False

    def feed(self,data,host_ns=None):
        host_ns=time.monotonic_ns() if host_ns is None else host_ns
        result=[]
        for byte in data:
            if byte!=10:
                if not self.discarding:
                    self.buffer.append(byte)
                    if len(self.buffer)>1024:
                        self.buffer.clear(); self.discarding=True; self.bad_lines+=1
                continue
            line=self.buffer.decode('utf-8',errors='replace').strip(); self.buffer.clear()
            if self.discarding: self.discarding=False; continue
            if not line or line.startswith('#') or line.upper()=='READY' or line.startswith('t_us,'): continue
            try:
                parts=line.split(',')
                if len(parts)!=4: raise ValueError()
                stamp=int(float(parts[0])); values=tuple(float(v) for v in parts[1:])
                if stamp<0 or not all(math.isfinite(v) for v in values): raise ValueError()
            except (ValueError,OverflowError): self.bad_lines+=1; continue
            if self.last is not None and stamp<self.last:
                if self.last-stamp>2**31: self.offset+=2**32
                else: self.segment+=1; self.offset=0
            self.last=stamp
            result.append(Frame(stamp,stamp+self.offset,self.segment,host_ns,*values))
        return result


class BaselineCollector:
    def __init__(self,start,duration=2):
        self.start=start; self.duration=duration; self.frames=[]

    def add(self,frame):
        if len(self.frames)>=200000: raise ValueError('基线样本积压，请降低采样率')
        self.frames.append(frame)

    def ready(self,now): return now-self.start>=self.duration

    def finish(self,now):
        if not self.ready(now): raise ValueError('基线采集尚未完成')
        values=[f.values for f in self.frames]
        valid,_=quality_mask(values)
        good=[v for v,ok in zip(values,valid) if ok]
        if len(good)<20: raise ValueError('基线有效样本不足 20 个')
        if self.frames and self.frames[0].segment!=self.frames[-1].segment: raise ValueError('基线期间设备时钟复位，请重试')
        return dict(baseline=tuple(mean(v[i] for v in good) for i in range(3)),
                    sigma=tuple(population_std(v[i] for v in good) for i in range(3)),
                    samples=len(values),invalid_samples=len(values)-len(good))


class Recorder:
    def __init__(self,root,baseline,context,clock_ns=time.monotonic_ns):
        self.baseline=tuple(baseline); self.context=dict(context)
        self.start_ns=clock_ns(); self.items=queue.Queue(maxsize=10000)
        self.error=None; self.count=0; self.invalid=0; self.closed=False
        self.outcome='interrupted'; self.reason='程序未正常结束'
        self.path=Path(root)/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.path.mkdir(parents=True,exist_ok=False)
        self.file=(self.path/'sensor.csv').open('x',newline='',encoding='utf-8-sig')
        self.writer=csv.writer(self.file); self.writer.writerow(CSV_HEADER); self.file.flush()
        self.created=datetime.now(timezone.utc).isoformat()
        self._metadata()
        self.thread=threading.Thread(target=self._write_loop,name='xz-csv-writer',daemon=True)
        self.thread.start()

    def _metadata(self):
        meta=dict(schema_version=1,created_at=self.created,outcome=self.outcome,error=self.reason,
                  sample_count=self.count,invalid_sample_count=self.invalid,
                  baseline_B0_uT=dict(zip(('Bx_uT','By_uT','Bz_uT'),self.baseline)),
                  context=self.context,files={'sensor':'sensor.csv'},
                  sample_quality={'rule':'finite and not isolated >=1000uT spike returning within 250uT','raw_values_preserved':True},
                  timestamps='host monotonic receive time; motor position is latest software pulse count, not hardware synchronized')
        tmp=self.path/'metadata.json.tmp'
        tmp.write_text(json.dumps(meta,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        tmp.replace(self.path/'metadata.json')

    def append(self,frame,stage,status):
        if self.closed: raise OSError('记录已经关闭')
        if self.error: raise OSError('CSV 写入失败：'+self.error)
        try: self.items.put_nowait((frame,stage,dict(status or {})))
        except queue.Full: raise OSError('CSV 写入队列已满，采集已中止') from None

    def _row(self,item,valid,reason,first_us):
        frame,stage,status=item
        self.count+=1; self.invalid+=int(not valid)
        d=tuple(v-b for v,b in zip(frame.values,self.baseline))
        self.writer.writerow([self.count,frame.sensor_us,frame.unwrapped_us,frame.segment,
            f'{(frame.unwrapped_us-first_us)/1e6:.6f}',frame.host_ns,f'{(frame.host_ns-self.start_ns)/1e9:.6f}',stage,
            *[status.get(k,'') for k in ('x','z','tx','tz','busy','phase','fault')],
            *[f'{v:.6f}' for v in frame.values],*[f'{v:.6f}' for v in d],int(valid),reason])

    def _write_loop(self):
        previous=None; pending=None; first_us=None; last_flush=time.monotonic()
        try:
            while True:
                try: item=self.items.get(timeout=.1)
                except queue.Empty:
                    self.file.flush(); continue
                if item is None: break
                if first_us is None: first_us=item[0].unwrapped_us
                if pending:
                    if previous:
                        valid,reasons=quality_mask([previous.values,pending[0].values,item[0].values])
                        self._row(pending,valid[1],reasons[1],first_us)
                    else: self._row(pending,True,'',first_us)
                    previous=pending[0]
                pending=item
                if time.monotonic()-last_flush>=.25:
                    self.file.flush(); last_flush=time.monotonic()
            if pending: self._row(pending,True,'',first_us)
            self.file.flush(); os.fsync(self.file.fileno())
        except Exception as exc: self.error=str(exc)
        finally:
            try: self.file.close()
            except OSError as exc: self.error=str(exc)

    def close(self,outcome='completed',reason=None):
        if self.closed: return self.path
        self.closed=True
        if self.thread.is_alive():
            try: self.items.put(None,timeout=1)
            except queue.Full: self.error='写入服务阻塞，队列未清空'
            self.thread.join(timeout=5)
            if self.thread.is_alive(): self.error='CSV 写盘超时，部分数据仍可能未写入'
        self.outcome='aborted' if self.error else outcome
        self.reason=self.error or reason
        self._metadata()
        if self.error: raise OSError(f'{self.error}；已保留目录：{self.path}')
        return self.path
