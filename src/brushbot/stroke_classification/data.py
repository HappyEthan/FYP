"""Read-only experiment import with verified archive integrity and fixed task labels."""
import csv
from dataclasses import dataclass,field
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import numpy as np

from .features import FeatureConfig,prepare_sensor,extract
from . import LABELS
from brushbot.experiments.reproduce import archive_path, verify


@dataclass
class Stroke:
    sample_id: str
    run_id: str
    label: int | None
    index: int
    amplitude: np.ndarray
    baseline: float
    native_tau: np.ndarray
    native_ema: np.ndarray
    native_u: np.ndarray
    native_v: np.ndarray
    feature_config: dict
    representations: dict
    direction_info: dict
    seq_start: int
    seq_end: int
    label_source: str = 'user-declared-yong-heng-shu-v1'
    source_metadata: dict = field(default_factory=dict)


@dataclass
class Experiment:
    path: str
    name: str
    run_id: str
    sensor_hash: str
    source_hash: str
    strokes: list
    feature_config: dict


def load_experiment(path, config=FeatureConfig(), *, expected_count=7):
    config.validate()
    path=archive_path(path).resolve()
    if path.is_file():
        verify(path)
        with zipfile.ZipFile(path) as z:
            content={name:z.read(name) for name in ('manifest.json','sensor.csv','control.jsonl')}
            for name in ('experiment.json','preflight.json'):
                if name in z.namelist():content[name]=z.read(name)
    else:
        if (path/'bundle_manifest.json').exists(): verify(path)
        content={name:(path/name).read_bytes() for name in ('manifest.json','sensor.csv','control.jsonl')}
        for name in ('experiment.json','preflight.json'):
            if (path/name).exists():content[name]=(path/name).read_bytes()
    manifest=json.loads(content['manifest.json'])
    if manifest.get('status')!='completed' or manifest.get('reason'):
        raise ValueError('实验未成功完成')
    run=str(manifest.get('run_id') or '')
    if not run: raise ValueError('缺少实验run_id')
    for name in ('manifest.json','experiment.json'):
        declaration=json.loads(content[name]) if name in content else {}
        if declaration.get('expected_stroke_count',expected_count)!=expected_count:raise ValueError('实验笔数协议不兼容')
        if 'stroke_labels' in declaration and declaration['stroke_labels']!=list(LABELS[:expected_count]):
            raise ValueError('实验声明的笔画顺序与当前协议不兼容')
        protocol=declaration.get('classification_protocol')
        if protocol is not None and protocol!='yong-heng-shu-v1':raise ValueError('实验分类协议不兼容')
    if 'preflight.json' in content:
        order=json.loads(content['preflight.json']).get('execution_order')
        if order is not None and len(order)!=expected_count:raise ValueError('执行顺序与要求笔数不一致')
    control=[json.loads(x) for x in content['control.jsonl'].splitlines() if x.strip()]
    ticks={}
    for row in control:
        match=re.fullmatch(r'measure_(\d+)',str(row.get('phase','')))
        if match:
            if row.get('sample_seq') is None: raise ValueError('书写事件缺少sample_seq')
            ticks.setdefault(int(match.group(1)),[]).append(int(row['sample_seq']))
    if sorted(ticks)!=list(range(expected_count)):
        raise ValueError(f'要求完整{expected_count}笔实验，实际检测到{len(ticks)}笔；不自动补标签')
    sensor=prepare_sensor(list(csv.DictReader(io.StringIO(content['sensor.csv'].decode('utf-8-sig')))),config)
    strokes=[];prior=-1
    for label,seq in sorted(ticks.items()):
        if np.any(np.diff(seq)<0) or seq[0]<=prior: raise ValueError('笔画事件顺序冲突')
        prior=seq[-1]
        strokes.append(Stroke(sample_id=f'{run}:stroke{label+1}',run_id=run,label=label,index=label+1,
                              source_metadata=dict(path=str(path),protocol='yong-heng-shu-v1',label_source='user-declared-fixed-task-order'),
                              **extract(sensor,seq[0],seq[-1],config)))
    source_hash=hashlib.sha256(b''.join(content[k] for k in sorted(content))).hexdigest()
    return Experiment(str(path),path.stem,run,hashlib.sha256(content['sensor.csv']).hexdigest(),source_hash,strokes,config.to_dict())


def unique_experiments(experiments):
    result=[];runs={};sensors=set()
    for ex in experiments:
        if ex.run_id in runs and runs[ex.run_id]!=ex.source_hash:
            raise ValueError('相同run_id对应不同数据或笔画边界')
        if ex.run_id not in runs and ex.sensor_hash not in sensors: result.append(ex)
        runs[ex.run_id]=ex.source_hash;sensors.add(ex.sensor_hash)
    return result


def load_single_csv(path,config=FeatureConfig(),*,seq_start=None,seq_end=None,true_label=None):
    path=Path(path).resolve();raw=path.read_bytes()
    # Boundaries are explicit, with full continuous prehistory; never infer active start from a class.
    meta_path=path.with_suffix('.json')
    meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
    seq_start=seq_start if seq_start is not None else meta.get('seq_start')
    seq_end=seq_end if seq_end is not None else meta.get('seq_end')
    if seq_start is None or seq_end is None:
        raise ValueError('单笔CSV需同名JSON中的seq_start/seq_end，且保留至少100点写前采样')
    digest=hashlib.sha256(raw).hexdigest()
    sensor=prepare_sensor(list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))),config)
    return Stroke(sample_id=digest,run_id=digest,label=true_label,index=1,
                  label_source='user-provided' if true_label is not None else 'unknown',
                  source_metadata=dict(path=str(path),csv_sha256=digest,seq_start=int(seq_start),seq_end=int(seq_end),
                                       sidecar_sha256=hashlib.sha256(meta_path.read_bytes()).hexdigest() if meta_path.exists() else None),
                  **extract(sensor,seq_start,seq_end,config))
