"""Read-only final inference verification from a recorded live session."""
import csv
import hashlib
import io
import json
from pathlib import Path

import joblib
import numpy as np

from brushbot.stroke_classification.features import FeatureConfig, prepare_sensor
from .history import LoadedModel
from .inference import PredictionJob, evaluate_job


def replay_final(session_dir):
    path = Path(session_dir).resolve()
    meta = json.loads((path/'session.json').read_text())
    if meta.get('format') != 'brushbot-live-strokes':
        raise ValueError('不是实时识别会话目录')
    with (path/'sensor.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    with (path/'predictions.jsonl').open() as handle:
        finals = [json.loads(line) for line in handle if line.strip()]
    finals = [r for r in finals if r['kind']=='final']
    models, records, results = {}, {}, []
    for saved in finals:
        digest = saved['model_sha256']
        if digest not in models:
            if digest not in meta['models'] or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('会话模型标识无效')
            info = meta['models'][digest]
            blob = (path/'models'/digest/'bundle.joblib').read_bytes()
            if hashlib.sha256(blob).hexdigest()!=digest:
                raise ValueError('会话模型快照校验失败')
            bundle = joblib.load(io.BytesIO(blob))
            config = FeatureConfig(**bundle['feature_config']).validate()
            models[digest] = LoadedModel(info['task_id'],info['model_id'],info['name'],digest,
                                        blob,bundle,dict(family=info['family']),config,tuple(bundle['labels']))
            records[digest] = prepare_sensor(rows,config)
        job = PredictionJob(meta['session_id'],saved['stroke_id'],'final',models[digest],records[digest],
                            int(saved['first']),int(saved['last']))
        actual = evaluate_job(job)
        matches = actual['status']==saved['status'] and actual['predicted']==saved['predicted']
        if matches and saved.get('scores') is not None:
            matches = bool(np.allclose(actual['scores'],saved['scores'],rtol=1e-9,atol=1e-9))
        results.append(dict(stroke_id=job.stroke_id, saved_label=saved.get('label'),
                            replay_label=actual.get('label'), matches=matches,
                            status=actual['status'], error=actual.get('error')))
    return results
