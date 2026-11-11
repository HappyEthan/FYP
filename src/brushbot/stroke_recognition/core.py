"""GUI-free contact segmentation and continuously filtered native sensor samples."""
from collections import deque
from dataclasses import dataclass
import math

import numpy as np

from brushbot.stroke_classification.features import FeatureConfig


@dataclass(frozen=True)
class SegmentConfig:
    down_threshold: float
    up_threshold: float
    down_ms: float = 40.
    up_ms: float = 120.

    def validate(self):
        values = (self.down_threshold, self.up_threshold, self.down_ms, self.up_ms)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('分笔参数必须为有限数值')
        if not 0 <= self.up_threshold < self.down_threshold:
            raise ValueError('落笔阈值必须大于提笔阈值，提笔阈值不能小于零')
        if min(self.down_ms, self.up_ms) < 0:
            raise ValueError('确认时间不能小于零')
        return self


class StrokeSegmenter:
    def __init__(self, config):
        self.config = config.validate()
        self.reset()

    @property
    def busy(self):
        return self.state in ('down_pending', 'writing', 'up_pending')

    def reset(self, wait_for_up=False):
        self.state = 'waiting_up' if wait_for_up else 'idle'
        self.first = self.last_seq = None
        self.candidate_t = self.candidate_seq = self.end_seq = None

    def interrupt(self, reason):
        event = dict(type='interrupted', first=self.first, last=self.last_seq, reason=reason)
        self.reset(wait_for_up=True)
        return event

    def feed(self, seq, t, amplitude):
        if not math.isfinite(t) or not math.isfinite(amplitude):
            return [self.interrupt('无效采样')]
        c = self.config
        events = []
        if self.state == 'waiting_up':
            if amplitude <= c.up_threshold:
                if self.candidate_t is None:
                    self.candidate_t = t
                if t-self.candidate_t+1e-12 >= c.up_ms/1000:
                    self.reset()
                    events.append(dict(type='ready', seq=seq))
            else:
                self.candidate_t = None
        elif self.state == 'idle':
            if amplitude >= c.down_threshold:
                self.state = 'down_pending'
                self.candidate_t, self.candidate_seq = t, seq
                events.append(dict(type='down_candidate', seq=seq, t=t))
                if c.down_ms == 0:
                    self.state, self.first = 'writing', seq
                    events.append(dict(type='down', first=seq, confirmed_seq=seq, t=t))
        elif self.state == 'down_pending':
            if amplitude < c.down_threshold:
                self.reset()
                events.append(dict(type='down_cancelled', seq=seq))
            elif t-self.candidate_t+1e-12 >= c.down_ms/1000:
                self.state, self.first = 'writing', self.candidate_seq
                events.append(dict(type='down', first=self.first, confirmed_seq=seq, t=t))
        elif self.state == 'writing':
            if amplitude <= c.up_threshold:
                self.state, self.candidate_t = 'up_pending', t
                self.end_seq = self.last_seq
                events.append(dict(type='up_candidate', seq=seq, last=self.end_seq, t=t))
                if c.up_ms == 0:
                    events.append(dict(type='up', first=self.first, last=self.end_seq,
                                       confirmed_seq=seq, t=t))
                    self.reset()
        elif self.state == 'up_pending':
            if amplitude > c.up_threshold:
                self.state = 'writing'
                events.append(dict(type='up_cancelled', seq=seq, t=t))
            elif t-self.candidate_t+1e-12 >= c.up_ms/1000:
                events.append(dict(type='up', first=self.first, last=self.end_seq,
                                   confirmed_seq=seq, t=t))
                self.reset()
        self.last_seq = seq
        return events


@dataclass(frozen=True)
class SensorSample:
    row: dict
    seq: int
    time: float
    raw: float
    ema: float
    u: float
    v: float
    valid: bool
    break_before: bool
    reset_seq: int


class SensorBuffer:
    """Retain native values plus exact EMA checkpoints when trimming idle history.

    The arrays returned by snapshot follow features.extract's record contract.
    A reset may precede the retained arrays (negative relative index); its age
    remains known, so warmup validation does not restart on buffer eviction.
    """
    def __init__(self, config=FeatureConfig(), idle_capacity=512):
        self.config = config.validate()
        self.idle_capacity = max(int(idle_capacity), config.warmup+2)
        self.samples = deque()
        self.intervals = deque(maxlen=501)
        self.pinned = None
        self.last = None

    def __len__(self):
        return len(self.samples)

    @property
    def ready(self):
        return bool(self.last and self.last.valid and
                    self.last.seq-self.last.reset_seq >= self.config.warmup)

    def append(self, row):
        row = dict(row)
        seq, clock = int(row['seq']), int(row['sensor_t_us'])
        previous = self.last
        if previous is not None and seq <= previous.seq:
            raise ValueError('接收序号重复或逆序')
        bx, by = float(row['dBx_uT']), float(row['dBy_uT'])
        valid = str(row.get('valid', True)).lower() in ('true', '1') and math.isfinite(bx) and math.isfinite(by)
        broken, t = previous is None, 0.
        if previous is not None:
            old_clock = int(previous.row['sensor_t_us'])
            dt = clock-old_clock
            if old_clock > 2**32-1_000_000 and clock < 1_000_000 and dt < 0:
                dt += 2**32
            nominal = float(np.median(self.intervals)) if self.intervals else max(dt, 1)
            broken = (dt <= 0 or dt > 2*nominal or seq != previous.seq+1 or
                      row.get('baseline_id', '') != previous.row.get('baseline_id', ''))
            if dt > 0:
                self.intervals.append(dt)
            t = previous.time + dt/1e6
        raw = math.hypot(bx, by)
        reset = broken or previous is None or not previous.valid
        if valid:
            if reset:
                scalar, u, v = raw, bx, by
            else:
                a = self.config.alpha
                scalar = a*raw + (1-a)*previous.ema
                u = a*bx + (1-a)*previous.u
                v = a*by + (1-a)*previous.v
            reset_seq = seq if reset else previous.reset_seq
        else:
            scalar = u = v = float('nan')
            reset_seq = seq
        sample = SensorSample(row, seq, t, raw, scalar, u, v, valid, broken, reset_seq)
        self.samples.append(sample)
        self.last = sample
        self._trim()
        return sample

    def pin(self, seq):
        self.pinned = int(seq)

    def release(self):
        self.pinned = None
        self._trim()

    def _trim(self):
        while len(self.samples) > self.idle_capacity:
            if self.pinned is not None and self.samples[0].seq >= self.pinned-self.config.warmup:
                break
            self.samples.popleft()

    def snapshot(self, first, last):
        selected = [s for s in self.samples if first-self.config.warmup <= s.seq <= last]
        if not selected or selected[0].seq > first or selected[-1].seq != last:
            raise ValueError('笔画边界已超出保留的数据')
        seq = np.array([s.seq for s in selected], dtype=np.int64)
        index = {int(s): i for i, s in enumerate(seq)}
        if first not in index:
            raise ValueError('笔画起点不在传感器记录中')
        reset_indices = [selected[0].reset_seq-selected[0].seq]
        reset_indices += [i for i, s in enumerate(selected) if s.valid and s.reset_seq == s.seq]
        result = dict(seq=seq, seq_index=index, resets=np.unique(reset_indices))
        for key, attribute, dtype in [('time','time',float), ('raw','raw',float), ('ema','ema',float),
                                      ('u','u',float), ('v','v',float), ('valid','valid',bool),
                                      ('breaks','break_before',bool)]:
            result[key] = np.array([getattr(s, attribute) for s in selected], dtype=dtype)
        return result
