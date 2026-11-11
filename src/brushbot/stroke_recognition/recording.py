"""Append-only acquisition records and immutable model snapshots for replay."""
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo

from brushbot.stroke_classification.store import write_json


SENSOR_FIELDS = ('seq','sensor_t_us','host_rx_ns','Bx_uT','By_uT','Bz_uT',
                 'dBx_uT','dBy_uT','dBz_uT','valid','baseline_id')
STROKE_FIELDS = ('session_id','stroke_id','first','last','duration','status',
                 'predicted','label','model_sha256','model_token','error')


def clean_json(value):
    if isinstance(value, dict):
        return {str(k):clean_json(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, 'item'):
        return clean_json(value.item())
    return value


class SessionRecorder:
    def __init__(self, root, device):
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        self.session_id = now.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
        self.path = Path(root).resolve()/self.session_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.failed = False
        self.closed = False
        self._files = []
        self.meta = dict(version=1, format='brushbot-live-strokes', session_id=self.session_id,
                         created_at=now.isoformat(), status='recording', device=device,
                         models={}, config_history=[])
        try:
            self._sensor = self._open('sensor.csv')
            self._strokes = self._open('strokes.csv')
            self._events = self._open('events.jsonl')
            self._predictions = self._open('predictions.jsonl')
            self._sensor_writer = csv.DictWriter(self._sensor, fieldnames=SENSOR_FIELDS, extrasaction='ignore')
            self._stroke_writer = csv.DictWriter(self._strokes, fieldnames=STROKE_FIELDS, extrasaction='ignore')
            self._sensor_writer.writeheader()
            self._stroke_writer.writeheader()
            self.save_meta()
        except Exception:
            for handle in self._files:
                handle.close()
            raise

    def _open(self, name):
        handle = (self.path/name).open('w', encoding='utf-8', newline='')
        self._files.append(handle)
        return handle

    def save_meta(self):
        write_json(self.path/'session.json', clean_json(self.meta))

    def sensor(self, row):
        self._sensor_writer.writerow(row)

    def event(self, event_name, **values):
        row = dict(event=event_name, host_ns=time.time_ns(), **values)
        self._events.write(json.dumps(clean_json(row),ensure_ascii=False,allow_nan=False)+'\n')

    def prediction(self, result):
        self._predictions.write(json.dumps(clean_json(result),ensure_ascii=False,allow_nan=False)+'\n')

    def stroke(self, row):
        self._stroke_writer.writerow(clean_json(row))
        self.flush()

    def model(self, model):
        if model.sha256 in self.meta['models']:
            return
        folder = self.path/'models'/model.sha256
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder/'bundle.tmp'
        temporary.write_bytes(model.blob)
        temporary.replace(folder/'bundle.joblib')
        info = model.summary()
        write_json(folder/'model.json', clean_json(info))
        self.meta['models'][model.sha256] = info
        self.save_meta()

    def config(self, config):
        self.meta['config_history'].append(clean_json(config))
        self.event('configuration', **config)
        self.save_meta()

    def flush(self):
        for handle in self._files:
            handle.flush()

    def close(self, status='completed'):
        if self.closed:
            return
        try:
            self.meta.update(status='error' if self.failed else status,
                             ended_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
            self.flush()
            self.save_meta()
        finally:
            self.closed = True
            for handle in self._files:
                handle.close()
