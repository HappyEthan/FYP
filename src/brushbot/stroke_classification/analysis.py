"""Task-bound diagnostics. Temporary fits never enter the model registry."""
from collections import OrderedDict
from dataclasses import asdict,dataclass,replace
from datetime import datetime
from pathlib import Path
import csv
import itertools
import json
import time
import uuid
from zoneinfo import ZoneInfo

import numpy as np
from threadpoolctl import threadpool_limits

from . import LABELS
from .data import load_experiment,unique_experiments
from .features import FeatureConfig
from .metrics import evaluate
from .models import Candidate,MagneticModel
from .store import ModelStore,write_json
from .training import Cancelled,TrainConfig,candidates,source_fingerprint,stack_strokes


def positive_values(text):
    values=tuple(dict.fromkeys(float(v.strip()) for v in text.replace('，',',').split(',')))
    if not values or any(not np.isfinite(v) or v<=0 for v in values):
        raise ValueError('候选必须为逗号分隔的有限正数')
    return values


def nearby_values(center):
    center=float(center)
    if not np.isfinite(center) or center<=0:raise ValueError('中心值必须为有限正数')
    return tuple(center*v for v in (.25,.5,1.,2.,4.))


def default_sizes(count,family='F4'):
    minimum=3 if family=='F3' else 2
    sizes=[n for n in (4,6,8,10,12) if minimum<=n<count-1]
    if count-1>=minimum:sizes.append(count-1)
    return tuple(sizes)


@dataclass(frozen=True)
class AnalysisConfig:
    kind: str = 'learning'
    sizes: tuple = ()
    seeds: tuple = (20261110,20261111,20261112)
    cs: tuple = (.001,.01,.1,1.,10.,100.)
    weights: tuple = (.25,.5,1.,2.)

    def validate(self,count,family):
        if count<3:raise ValueError('分析至少需要3次完整实验')
        if self.kind not in ('learning','C','weight','joint'):raise ValueError('未知分析类型')
        if self.kind in ('weight','joint') and family!='F4':raise ValueError('差分权重分析仅适用于F4')
        if self.kind=='learning':
            minimum=3 if family=='F3' else 2
            if not self.sizes or any(isinstance(n,bool) or not isinstance(n,(int,np.integer)) or n<minimum or n>=count for n in self.sizes):
                raise ValueError(f'训练次数须为{minimum}到{count-1}的整数')
            if len(set(self.sizes))!=len(self.sizes):raise ValueError('训练次数不能重复')
            if not self.seeds or any(not isinstance(s,int) or s<0 for s in self.seeds):raise ValueError('随机种子须为非负整数')
        for values in (self.cs,self.weights):
            if not values or any(not np.isfinite(v) or v<=0 for v in values):raise ValueError('C和权重候选必须为有限正数')
        if family=='F3' and count<4:raise ValueError('F3分析至少需要4次完整实验')
        return self


def _available(experiments,config):
    return tuple(d for d in config.directions if all(
        np.mean(np.isfinite(s.representations[d]))>=config.feature_config.direction_coverage and
        (d=='D2' or s.direction_info['anchor_ok']) for e in experiments for s in e.strokes))


def estimate_fits(count,train_config,candidate,config):
    """Conservative uncached number of MagneticModel fits, not elapsed time."""
    config.validate(count,candidate.family)
    if config.kind=='learning':
        pool=len(list(candidates(candidate.family,train_config,train_config.directions)))
        return len(config.seeds)*count*sum((pool*n if pool>1 else 0)+1 for n in config.sizes)
    combinations=len(config.cs) if config.kind=='C' else len(config.weights) if config.kind=='weight' else len(config.cs)*len(config.weights)
    return count*combinations


def run_analysis(experiments,train_config,candidate,config,progress=None,cancel=None):
    started=time.monotonic();train_config.validate()
    experiments=unique_experiments(experiments);config.validate(len(experiments),candidate.family)
    for e in experiments:
        if len(e.strokes)!=7 or [s.label for s in e.strokes]!=list(range(7)):
            raise ValueError('分析需要完整七笔实验；历史五类模型仅支持查看投影')
        if e.feature_config!=train_config.feature_config.to_dict():raise ValueError('来源预处理配置不一致')
    available=_available(experiments,train_config)
    if candidate.family in ('F1','F2','F3') and (not available or
            (config.kind!='learning' and candidate.direction not in available)):
        raise ValueError('方向有效覆盖或参考锚点不足')
    strokes=[s for e in experiments for s in e.strokes]
    X=stack_strokes(strokes);y=np.array([s.label for s in strokes]);groups=np.array([s.run_id for s in strokes])
    runs=np.unique(groups);index=np.arange(len(y));cache=OrderedDict();choices={};fits=0
    pool=list(candidates(candidate.family,train_config,available))
    rows=[];folds=[]

    def check():
        if cancel and cancel():raise Cancelled('分析已取消')

    def fit_predict(c,tr):
        nonlocal fits
        check();key=(c,tuple(tr))
        if key not in cache:
            model=MagneticModel(c).fit({k:v[tr] for k,v in X.items()},y[tr],groups[tr],check,False)
            cache[key]=model.predict(X).astype(np.int8);fits+=1
            if len(cache)>32768:cache.popitem(last=False)
        cache.move_to_end(key)
        return cache[key]

    def macro(a,b):
        matrix=np.bincount(a*7+b,minlength=49).reshape(7,7)
        denom=matrix.sum(0)+matrix.sum(1)
        return float(np.mean(np.divide(2*matrix.diagonal(),denom,out=np.zeros(7),where=denom>0)))

    def choose(tr):
        check();key=tuple(tr)
        if key in choices:return choices[key]
        if len(pool)==1:return pool[0]
        best=pool[0];best_score=-1.
        for ci,c in enumerate(pool):
            pred=np.full(len(y),-1,dtype=int)
            for run in np.unique(groups[tr]):
                te=tr[groups[tr]==run];inside=tr[groups[tr]!=run]
                pred[te]=fit_predict(c,inside)[te]
            score=macro(y[tr],pred[tr])
            if score>best_score+1e-12:best,best_score=c,score
            if progress and ci%20==0:progress(dict(message=f'训练侧选参 {ci+1}/{len(pool)} · 已拟合{fits}次'))
        choices[key]=best
        return best

    if config.kind=='learning':
        jobs=[(seed,n,None) for seed in config.seeds for n in sorted(config.sizes)]
    else:
        values=(replace(candidate,C=c) for c in config.cs) if config.kind=='C' else (
            (replace(candidate,weight=w) for w in config.weights) if config.kind=='weight' else
            (replace(candidate,C=c,weight=w) for c,w in itertools.product(config.cs,config.weights)))
        jobs=[(None,len(runs)-1,c) for c in values]
    total=len(jobs)*len(runs);done=0
    with threadpool_limits(limits=1):
        for seed,size,fixed in jobs:
            pred=np.full(len(y),-1,dtype=int);training_true=[];training_pred=[]
            for ri,run in enumerate(runs):
                check()
                if seed is None:train_runs=runs[runs!=run]
                else:
                    order=np.random.default_rng(np.random.SeedSequence([seed,ri])).permutation(runs[runs!=run])
                    train_runs=order[:size]
                tr=index[np.isin(groups,train_runs)];te=index[groups==run]
                selected=choose(tr) if config.kind=='learning' else fixed
                p=fit_predict(selected,tr);pred[te]=p[te]
                training_true.extend(y[tr].tolist());training_pred.extend(p[tr].tolist())
                inner_splits=[dict(test_run=str(g),train_runs=sorted(set(groups[tr][groups[tr]!=g]))) for g in np.unique(groups[tr])] if config.kind=='learning' and len(pool)>1 else []
                folds.append(dict(seed=seed,size=size,candidate=asdict(selected),train_runs=sorted(train_runs.tolist()),test_runs=[str(run)],
                    train_indices=tr.tolist(),test_indices=te.tolist(),inner_splits=inner_splits,
                    test_true=y[te].tolist(),test_predicted=pred[te].tolist()))
                done+=1
                if progress:progress(dict(message=f'外层评价 {done}/{total} · 已拟合{fits}次',done=done,total=total,fits=fits))
            a=np.array(training_true);b=np.array(training_pred)
            rows.append(dict(size=size,seed=seed,candidate=asdict(fixed) if fixed else None,
                training_accuracy=float(np.mean(a==b)),training_macro_f1=macro(a,b),metrics=evaluate(y,pred,groups),
                predictions=[dict(sample_id=s.sample_id,run_id=s.run_id,stroke=s.index,true=int(y[i]),predicted=int(pred[i])) for i,s in enumerate(strokes)]))
    check()
    return dict(kind=config.kind,analysis_config=asdict(config),train_config=asdict(train_config),fixed_candidate=asdict(candidate),
        source_fingerprint=source_fingerprint(experiments),run_count=len(runs),sample_count=len(y),rows=rows,folds=folds,
        fits=fits,elapsed_seconds=time.monotonic()-started,
        notes=['整次实验留一；学习曲线在训练侧内部选参；参数曲线是开发调参诊断。',
               '训练成绩是回代成绩。重复阴影为min–max，不是置信区间；最大规模重复训练集合相同。',
               '按run留一不等同未见随机配置验证；同配置重复实验可能分处两侧。',
               '筛选方法及参数后，需另采未参与选择的新实验验收。'])


def summary_rows(result):
    output=[]
    for row in result['rows']:
        metric=row['metrics'];candidate=row['candidate'] or {}
        output.append(dict(size=row['size'],seed=row['seed'],C=candidate.get('C'),weight=candidate.get('weight'),
            training_accuracy=row['training_accuracy'],training_macro_f1=row['training_macro_f1'],
            **{k:metric[k] for k in ('accuracy','macro_f1','worst_recall','errors','total')},
            **{'recall_'+label:metric['per_class'][label]['recall'] for label in LABELS}))
    return output


def save_csv(path,result):
    rows=summary_rows(result)
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def execute_request(path,progress=None,cancel=None):
    request=json.loads(Path(path).read_text());store=ModelStore(request['root'])
    task=store.metadata(request['task_id']);model=next(m for m in task['models'] if m['id']==request['model_id'])
    bundle=store.load_bundle(task['id'],model['id'])
    if len(bundle['labels'])!=7:raise ValueError('历史五类模型仅支持查看投影，不支持七笔分析')
    if request['source_fingerprint']!=task.get('source_fingerprint') or bundle['source_fingerprint']!=task['source_fingerprint']:
        raise ValueError('任务与模型来源指纹不一致')
    values=dict(task['config']);values['feature_config']=FeatureConfig(**values['feature_config']);train_config=TrainConfig(**values).validate()
    config=AnalysisConfig(**request['analysis']);config.validate(task['run_count'],model['family'])
    # Verify all source identities, including duplicate/copy sources, before fitting anything.
    data=[load_experiment(s['path'],train_config.feature_config) for s in task['sources']]
    if [(e.run_id,e.source_hash) for e in data]!=[(s['run_id'],s['source_hash']) for s in task['sources']]:
        raise ValueError('来源实验已改变，请勿沿用旧模型进行分析')
    if source_fingerprint(unique_experiments(data))!=task['source_fingerprint']:raise ValueError('来源数据指纹不符')
    identifier=request.get('analysis_id') or datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8]
    import re
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',identifier):raise ValueError('无效分析ID')
    folder=store.task_path(task['id'])/'analyses'/identifier;folder.mkdir(parents=True,exist_ok=False)
    record=dict(status='running',task_id=task['id'],model_id=model['id'],task_name=task['name'],model_name=model['name'],
                created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),request=request)
    write_json(folder/'record.json',record)
    try:
        result=run_analysis(data,train_config,Candidate(**model['candidate']),config,progress,cancel)
        result.update(record,status='completed');write_json(folder/'results.json',result);save_csv(folder/'summary.csv',result)
        record['status']='completed';write_json(folder/'record.json',record)
        return folder
    except BaseException as exc:
        record.update(status='cancelled' if isinstance(exc,Cancelled) else 'failed',error=str(exc))
        write_json(folder/'record.json',record);raise
