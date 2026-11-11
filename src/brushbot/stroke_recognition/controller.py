"""Single-owner acquisition state; GUI communicates through commands/snapshots."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import copy
import math
from pathlib import Path
from queue import Empty, Queue
import threading
import time

import numpy as np

from brushbot.monitor.core import Baseline, frame_quality_mask
from brushbot.monitor.sources import SerialSource
from brushbot.stroke_classification.features import FeatureConfig
from brushbot.stroke_classification.store import ModelStore
from .core import SensorBuffer, SegmentConfig, StrokeSegmenter
from .history import load_model
from .inference import InferenceWorker, PredictionJob
from .recording import SessionRecorder


class LiveController:
    def __init__(self, output_root, source_factory=SerialSource, *, autostart=True,
                 clock=time.monotonic, baseline_duration=1., max_stroke_seconds=60.):
        self.output_root = Path(output_root)
        self.source_factory, self.clock = source_factory, clock
        self.baseline_duration = baseline_duration
        self.max_stroke_seconds = max_stroke_seconds
        self.source = self.recorder = None
        self.model = self.pending_model = None
        self._available = True
        self._loader = ThreadPoolExecutor(max_workers=1,thread_name_prefix='stroke-model')
        self._loading = None
        self._load_generation = 0
        self._commands = Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._closing = False
        self._snapshot = {}
        self._worker = InferenceWorker()
        self._recorders = {}
        self._closing_sessions = set()
        self._final_counts = {}
        self._history = deque(maxlen=500)
        self._traces = deque(maxlen=3000)
        self._changes = deque(maxlen=200)
        self._preview_times = deque(maxlen=100)
        self._current = self._stroke_model = None
        self._pending_config = None
        self._config = SegmentConfig(100.,60.)
        self._thresholds_confirmed = False
        self._interval_ms = 100.
        self._seg = StrokeSegmenter(self._config)
        self._buffer = SensorBuffer()
        self._baseline = Baseline()
        self._calibrating = None
        self._baseline_samples = []
        self._epoch = self._seq = self._stroke_counter = 0
        self._last_rx = self._last_flush = self.clock()
        self._next_preview = 0.
        self._stale = False
        self._bad_lines = 0
        self.running = False
        self.error = ''
        self._storage_error = False
        self._last_path = ''
        self._port, self._baud = '', 115200
        self._publish()
        self.thread = None
        if autostart:
            self.thread = threading.Thread(target=self._run,name='stroke-acquisition',daemon=True)
            self.thread.start()

    def command(self, name, **args):
        if not self._closing:
            self._commands.put((name,args))

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    @property
    def closed(self):
        return self._closed.is_set()

    def _record(self, recorder, method, *args, **kwargs):
        if recorder is None or recorder.closed or recorder.failed:
            return False
        try:
            getattr(recorder,method)(*args,**kwargs)
            return True
        except Exception as exc:
            recorder.failed = True
            self.error = f'记录保存失败：{exc}'
            self._storage_error = True
            self.running = False
            self._abort(self.error, persist=False)
            return False

    def _event(self, event_name, **values):
        return self._record(self.recorder,'event',event_name,**values)

    def _new_epoch(self, reason):
        self._epoch += 1
        self._buffer = SensorBuffer(self.model.config if self.model else FeatureConfig())
        self._traces.clear()
        self._seg.reset(wait_for_up=True)
        self._event('processing_epoch',epoch=self._epoch,reason=reason,
                    feature_config=self._buffer.config.to_dict())

    def _ready(self):
        return bool(self.source and self._baseline.ready and self._calibrating is None and
                    self._buffer.ready and self.model and self._available and
                    self._thresholds_confirmed and not self._loading and
                    not self._storage_error and not self._stale)

    def _handle(self, name, args):
        if name == 'connect':
            self._disconnect('重新连接')
            port = str(args['port']).strip()
            if not port:
                raise ValueError('请选择串口')
            baud = int(args.get('baud',115200))
            source = self.source_factory(port,baud)
            try:
                source.start()
                recorder = SessionRecorder(self.output_root,dict(port=port,baud=baud))
            except Exception:
                source.stop()
                raise
            self.source, self.recorder = source, recorder
            self._recorders[recorder.session_id] = recorder
            self._final_counts[recorder.session_id] = 0
            self._last_path, self._port, self._baud = str(recorder.path), port, baud
            self._baseline, self._calibrating = Baseline(), None
            self._seq = self._stroke_counter = self._bad_lines = 0
            self._storage_error, self._stale, self.error = False, False, ''
            self._last_rx = self.clock()
            self._new_epoch('连接传感器')
            self._save_configuration()
            self._event('connected',port=port,baud=baud)
        elif name == 'disconnect':
            self._disconnect('断开连接')
        elif name == 'baseline':
            if not self.source:
                raise ValueError('请先连接传感器')
            self.running = False
            self._abort('重新采集基线')
            self._baseline.ready = False
            self._calibrating = self.clock()
            self._baseline_samples = []
            self.error = ''
            self._event('baseline_started')
        elif name == 'configure':
            config = args['config'].validate()
            interval = float(args.get('interval_ms',100.))
            if not math.isfinite(interval) or not 20 <= interval <= 5000:
                raise ValueError('识别间隔应为20～5000毫秒')
            values = (config,interval,bool(args.get('thresholds_confirmed',False)))
            if self._seg.busy or self._current:
                self._pending_config = values
            else:
                self._apply_config(values)
        elif name == 'start':
            if not self._ready():
                raise ValueError('请先完成模型加载、连接、基线、连续预热和分笔阈值确认')
            self.running = True
            self.error = ''
            self._seg.reset(wait_for_up=True)
            self._next_preview = self.clock()
            self._event('recognition_started')
        elif name == 'stop':
            self.running = False
            self._abort('停止识别')
            self._event('recognition_stopped')
        elif name == 'load_model':
            self._load_generation += 1
            if self._loading:
                self._loading[1].cancel()
            future = self._loader.submit(load_model,ModelStore(args['root']),args['task_id'],args['model_id'])
            self._loading = (self._load_generation,future)
            self.error = ''
        elif name == 'set_model':
            self.pending_model = args['model']
            self._apply_pending()
        elif name == 'availability':
            if self.model and args['token']==self.model.token:
                self._available = bool(args['available'])
                if not self._available:
                    self.error = '当前模型已从历史中移除，请选择其他模型；当前笔仍会完成识别'
                    if not self._current:
                        self.running = False
        else:
            raise ValueError(f'未知操作：{name}')

    def _apply_config(self, values):
        self._config,self._interval_ms,self._thresholds_confirmed = values
        self._seg = StrokeSegmenter(self._config)
        self._seg.reset(wait_for_up=True)
        self._save_configuration()

    def _save_configuration(self):
        self._record(self.recorder,'config',dict(segmentation=asdict(self._config),
                     thresholds_confirmed=self._thresholds_confirmed, interval_ms=self._interval_ms,
                     max_stroke_seconds=self.max_stroke_seconds, max_final_queue=self._worker.max_finals))

    def _apply_pending(self):
        if self._seg.busy or self._current:
            return
        if self._pending_config:
            values,self._pending_config = self._pending_config,None
            self._apply_config(values)
        if self.pending_model:
            model = self.pending_model
            if self.recorder and not self._record(self.recorder,'model',model):
                return
            old_config = self._buffer.config
            self.model,self.pending_model,self._available = model,None,True
            if old_config != model.config:
                self._new_epoch('模型预处理配置变化，重新预热')
            self._event('model_selected',**model.summary())

    def _disconnect(self, reason):
        self.running = False
        self._abort(reason)
        if self.source:
            try:
                self.source.stop()
            except Exception as exc:
                self.error = str(exc)
        self._event('disconnected',reason=reason)
        if self.recorder:
            self._closing_sessions.add(self.recorder.session_id)
        self.source = self.recorder = None
        self._calibrating = None
        self._baseline.ready = False
        self._close_finished_sessions()

    def _abort(self, reason, persist=True):
        self._worker.discard_preview()
        if self._current:
            row = dict(self._current,status='interrupted',error=reason,predicted=None,label=None,scores=None)
            self._history.append(row)
            self._current = self._stroke_model = None
            if persist:
                self._record(self.recorder,'stroke',row)
        self._seg.interrupt(reason)
        self._buffer.release()

    def _process_frame(self, frame):
        now = self.clock()
        self._last_rx = now
        self._stale = False
        b = np.asarray(frame['B_uT'],dtype=float)
        if b.shape != (3,):
            raise ValueError('传感器磁场帧不是三轴数据')
        finite = bool(np.isfinite(b).all())
        if self._calibrating is not None and finite:
            self._baseline_samples.append(b)
        d = b-self._baseline.b0 if self._baseline.ready else np.full(3,np.nan)
        row = dict(seq=self._seq,sensor_t_us=int(frame['sensor_t_us']),
                   host_rx_ns=int(frame.get('host_rx_ns',time.monotonic_ns())),
                   Bx_uT=float(b[0]),By_uT=float(b[1]),Bz_uT=float(b[2]),
                   dBx_uT=float(d[0]),dBy_uT=float(d[1]),dBz_uT=float(d[2]),
                   valid=finite and self._baseline.ready and self._calibrating is None,
                   baseline_id=f'epoch-{self._epoch}')
        self._seq += 1
        if self.recorder:
            self._record(self.recorder,'sensor',row)
        sample = self._buffer.append(row)
        self._traces.append((sample.time,float(d[0]),float(d[1]),sample.raw))
        if (sample.break_before and len(self._buffer)>1) or not sample.valid:
            if self._current or self._seg.busy:
                self._abort('采样无效、时钟缺口或连续性中断')
            elif sample.break_before:
                self._seg.reset(wait_for_up=True)
        if not self.running:
            return
        # A frozen current stroke continues while another model is loading.
        if not self._current and not self._ready():
            return
        if not sample.valid or not self._buffer.ready:
            return
        for event in self._seg.feed(sample.seq,sample.time,sample.raw):
            self._event(event['type'],**{k:v for k,v in event.items() if k!='type'})
            kind = event['type']
            if kind == 'down_candidate':
                self._buffer.pin(event['seq'])
            elif kind == 'down_cancelled':
                self._buffer.release()
            elif kind == 'down':
                if not self._record(self.recorder,'model',self.model):
                    self._seg.reset(wait_for_up=True)
                    continue
                self._stroke_counter += 1
                self._stroke_model = self.model
                record = self._buffer.snapshot(event['first'],sample.seq)
                first_t = float(record['time'][record['seq_index'][event['first']]])
                self._current = dict(session_id=self.recorder.session_id,stroke_id=self._stroke_counter,
                    first=event['first'],last=sample.seq,first_t=first_t,duration=0.,status='writing',
                    model_token=self.model.token,model_sha256=self.model.sha256,model_name=self.model.name,
                    predicted=None,label=None,scores=None,error=None,confirmed_down_seq=sample.seq)
                self._changes.clear()
                self._next_preview = now
            elif kind == 'up':
                self._finish_stroke(event)
                self._apply_pending()
        if self._current:
            self._current.update(last=sample.seq,duration=max(0.,sample.time-self._current['first_t']))
            if self._current['duration'] > self.max_stroke_seconds:
                self.running = False
                self.error = '当前笔超过60秒上限，已中断；请确认阈值并重新开始'
                self._abort(self.error)

    def _finish_stroke(self, event):
        if not self._current:
            return
        row = dict(self._current,last=event['last'],status='finalizing',predicted=None,
                   label=None,scores=None,error=None,confirmed_up_seq=event['confirmed_seq'])
        try:
            record = self._buffer.snapshot(row['first'],row['last'])
            row['duration'] = float(record['time'][-1]-row['first_t'])
            job = PredictionJob(row['session_id'],row['stroke_id'],'final',self._stroke_model,
                                record,row['first'],row['last'])
            if not self._worker.submit(job):
                raise RuntimeError('最终识别队列已满，暂停新识别；本笔原始数据和边界已保留')
            self._final_counts[row['session_id']] += 1
        except Exception as exc:
            row.update(status='unavailable',error=str(exc))
            self.error, self.running = str(exc), False
            self._record(self.recorder,'stroke',row)
        self._history.append(row)
        self._current = self._stroke_model = None
        self._buffer.release()
        if not self._available:
            self.running = False

    def _maybe_preview(self):
        if not self._current or self._seg.state!='writing' or self.clock()<self._next_preview:
            return
        row = self._current
        if row['last'] <= row['first']:
            return
        self._next_preview = self.clock()+self._interval_ms/1000
        record = self._buffer.snapshot(row['first'],row['last'])
        self._worker.submit(PredictionJob(row['session_id'],row['stroke_id'],'preview',
                            self._stroke_model,record,row['first'],row['last']))

    def _drain_results(self):
        while True:
            try:
                result = self._worker.results.get_nowait()
            except Empty:
                break
            recorder = self._recorders.get(result['session_id'])
            self._record(recorder,'prediction',result)
            if result['kind']=='final':
                self._final_counts[result['session_id']] = max(0,self._final_counts.get(result['session_id'],0)-1)
                for row in reversed(self._history):
                    if (row['session_id'],row['stroke_id'],row['model_token'],row['status']) == (
                            result['session_id'],result['stroke_id'],result['model_token'],'finalizing'):
                        row.update(predicted=result['predicted'],label=result['label'],scores=result['scores'],
                                   error=result['error'],elapsed_ms=result['elapsed_ms'],
                                   status='locked' if result['status']=='ok' else 'unavailable')
                        self._record(recorder,'stroke',row)
                        break
            else:
                row = self._current
                if row and (row['session_id'],row['stroke_id'],row['model_token']) == (
                        result['session_id'],result['stroke_id'],result['model_token']):
                    if result['last']>=row.get('prediction_last',-1):
                        row.update(predicted=result['predicted'],label=result['label'],scores=result['scores'],
                                   error=result['error'],elapsed_ms=result['elapsed_ms'],prediction_last=result['last'])
                        self._preview_times.append(self.clock())
                        self._changes.append(dict(duration=row['duration'],label=result['label'],
                                                  error=result['error'],last=result['last']))
        self._close_finished_sessions()

    def _close_finished_sessions(self):
        for sid in list(self._closing_sessions):
            if self._final_counts.get(sid,0):
                continue
            recorder = self._recorders.pop(sid,None)
            if recorder:
                try:
                    recorder.close()
                except Exception as exc:
                    self.error = f'会话汇总保存失败：{exc}'
            self._closing_sessions.remove(sid)

    def step(self):
        while True:
            try:
                name,args = self._commands.get_nowait()
            except Empty:
                break
            try:
                self._handle(name,args)
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
        if self._loading and self._loading[1].done():
            _,future = self._loading
            self._loading = None
            try:
                self.pending_model = future.result()
            except Exception as exc:
                self.error = f'模型加载失败：{exc}'
        self._apply_pending()
        if self.source:
            try:
                bad_lines = int(getattr(self.source,'bad_lines',0))
                if bad_lines > self._bad_lines:
                    self._abort('串口出现无效数据行')
                    self._new_epoch('串口解析异常，重新预热')
                self._bad_lines = bad_lines
                for frame in self.source.read_frames() or []:
                    self._process_frame(frame)
                if self.clock()-self._last_rx > 1. and not self._stale:
                    self._stale = True
                    self.error = '传感器超过1秒未收到数据'
                    self._abort(self.error)
                    self._new_epoch('传感器断流，重新预热')
            except Exception as exc:
                self.error = f'传感器读取失败：{exc}'
                self._disconnect(self.error)
        if self._calibrating is not None and self.clock()-self._calibrating >= self.baseline_duration:
            self._calibrating = None
            try:
                values = np.asarray(self._baseline_samples,dtype=float)
                if len(values)<3:
                    raise ValueError('基线有效采样不足，请保持毛笔悬空后重试')
                values = values[frame_quality_mask(values)]
                self._baseline.take(values)
                self._new_epoch('空载基线完成')
                self._event('baseline_completed',baseline=self._baseline.b0.tolist(),
                            sigma=self._baseline.sigma.tolist())
            except Exception as exc:
                self.error = str(exc)
        self._drain_results()
        self._maybe_preview()
        if self.recorder and self.clock()-self._last_flush >= .5:
            self._record(self.recorder,'flush')
            self._last_flush = self.clock()
        self._publish()

    def _publish(self):
        current = copy.deepcopy(self._current)
        now = self.clock()
        recent = [t for t in self._preview_times if now-t<=1.]
        latest_final = next((copy.deepcopy(h) for h in reversed(self._history) if h['status']=='locked'),None)
        with self._lock:
            self._snapshot = dict(connected=self.source is not None, port=self._port,baud=self._baud,
                baseline_ready=self._baseline.ready,calibrating=self._calibrating is not None,
                baseline=self._baseline.b0.tolist(),warmup_count=(self._buffer.last.seq-self._buffer.last.reset_seq
                    if self._buffer.last else 0),warmup_required=self._buffer.config.warmup,
                ready=self._ready(),running=self.running,state=self._seg.state,
                error=self.error,bad_lines=self._bad_lines,model_loading=self._loading is not None,
                model=self.model.summary() if self.model else None,
                pending_model=self.pending_model.summary() if self.pending_model else None,
                config=asdict(self._config),thresholds_confirmed=self._thresholds_confirmed,
                interval_ms=self._interval_ms,current=current,history=copy.deepcopy(list(self._history)),
                latest_final=latest_final,traces=list(self._traces),changes=list(self._changes),
                actual_hz=len(recent),sample_rate_hz=(1e6/float(np.median(self._buffer.intervals))
                    if self._buffer.intervals else 0.),pending_finals=self._worker.pending_finals,
                session_path=self._last_path,storage_error=self._storage_error,
                pending_configuration=self._pending_config is not None)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.step()
            except Exception as exc:
                self.running = False
                self.error = f'识别控制异常：{exc}'
                self._abort(self.error)
                self._publish()
            self._stop.wait(.01)

    def close(self):
        if self._closing:
            self._closed.wait()
            return
        self._closing = True
        try:
            self._stop.set()
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join()
            self._disconnect('关闭窗口')
            self._loader.shutdown(wait=True,cancel_futures=True)
            self._worker.close()
            self._drain_results()
            for recorder in list(self._recorders.values()):
                try:
                    recorder.close()
                except Exception as exc:
                    self.error = str(exc)
            self._recorders.clear()
            self._publish()
        finally:
            self._closed.set()
