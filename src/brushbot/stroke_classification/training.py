"""Fixed whole-run outer validation, nested train-side selection and final model packaging."""
from dataclasses import asdict,dataclass,replace
from collections import OrderedDict
import copy
from datetime import datetime
import csv
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sys

import numpy as np
import sklearn
from sklearn.metrics import f1_score
from threadpoolctl import threadpool_limits

from . import LABELS,FAMILIES,VERSION
from .data import unique_experiments
from .features import FeatureConfig,direction_features
from .metrics import evaluate,rank_models
from .models import Candidate,MagneticModel
from .store import ModelStore,write_json


@dataclass(frozen=True)
class TrainConfig:
    families: tuple = ('F0','F1','F2','F3','F4')
    cs: tuple = (.1,1.,10.,100.)
    kernels: tuple = ('linear','rbf')
    gammas: tuple = ('scale',.001,.01,.1)
    amplitudes: tuple = ('A0','A1','A2','A4')
    directions: tuple = ('D1','D2','D3')
    weights: tuple = (.25,.5,1.,2.)
    direction_weights: tuple | None = None
    difference_weights: tuple | None = None
    late_weights: tuple = (.25,.5,.75)
    feature_config: FeatureConfig = FeatureConfig()
    robustness: bool = True

    def validate(self):
        self.feature_config.validate()
        if not self.families or set(self.families)-set(FAMILIES): raise ValueError('至少选择一个有效模型')
        if not self.cs or any(not np.isfinite(float(c)) or float(c)<=0 for c in self.cs): raise ValueError('C必须为有限正数')
        if not self.kernels or set(self.kernels)-{'linear','rbf'}: raise ValueError('核仅支持linear、rbf')
        if not self.gammas or any(g!='scale' and (not isinstance(g,(int,float)) or not np.isfinite(g) or g<=0) for g in self.gammas): raise ValueError('gamma必须为scale或有限正数')
        if not self.amplitudes or set(self.amplitudes)-{'A0','A1','A2','A4'}: raise ValueError('幅值表示无效')
        if not self.directions or set(self.directions)-{'D1','D2','D3'}: raise ValueError('方向表示无效')
        for values in (self.weights,self.direction_weights,self.difference_weights):
            if values is not None and (not values or any(not np.isfinite(w) or w<=0 for w in values)): raise ValueError('特征权重必须为有限正数')
        if not self.late_weights or any(not 0<w<1 for w in self.late_weights): raise ValueError('分数融合权重必须在0到1之间')
        return self


class Cancelled(Exception): pass


def candidates(family,config,directions):
    amplitudes=config.amplitudes if family=='F0' else ('A1',)
    ds=directions if family in ('F1','F2','F3') else ('D3',)
    weights=(config.late_weights if family=='F3' else
             (config.direction_weights if config.direction_weights is not None else config.weights) if family=='F2' else
             (config.difference_weights if config.difference_weights is not None else config.weights) if family=='F4' else (1.,))
    for a,d,kernel,c,w in itertools.product(amplitudes,ds,config.kernels,config.cs,weights):
        for gamma in (config.gammas if kernel=='rbf' else ('scale',)):
            yield Candidate(family,a,d,kernel,float(c),gamma,float(w))


def stack_strokes(strokes):
    return {name:np.array([s.representations[name] for s in strokes]) for name in strokes[0].representations}


def source_fingerprint(experiments):
    source=[(e.run_id,e.source_hash) for e in experiments]
    return hashlib.sha256(json.dumps(sorted(source)).encode()).hexdigest()


def train(experiments,config,root,progress=None,cancel=None,name=None):
    config.validate();experiments=unique_experiments(experiments)
    if len(experiments)<3: raise ValueError('嵌套留一验证至少需要3次完整实验；分数融合至少4次')
    for e in experiments:
        if len(e.strokes)!=7 or [s.label for s in e.strokes]!=list(range(7)):
            raise ValueError('新训练要求按约定顺序采集的完整七笔实验')
        if e.feature_config!=config.feature_config.to_dict(): raise ValueError('预处理设置改变，请重新导入实验')
    strokes=[s for e in experiments for s in e.strokes]
    y=np.array([s.label for s in strokes],dtype=int)
    groups=np.array([s.run_id for s in strokes]);X=stack_strokes(strokes)
    store=ModelStore(root)
    task=store.create_task(name or datetime.now().strftime('训练 %m-%d %H:%M'),dict(
        version=VERSION,config=asdict(config),source_fingerprint=source_fingerprint(experiments),
        sources=[dict(path=e.path,run_id=e.run_id,sensor_hash=e.sensor_hash,source_hash=e.source_hash,name=e.name) for e in experiments],
        run_count=len(experiments),sample_count=len(strokes),labels=list(LABELS)))
    folder=store.task_path(task['id'])
    write_json(folder/'resolved_config.json',asdict(config))
    write_json(folder/'sample_audit.json',[dict(sample_id=s.sample_id,run_id=s.run_id,label=s.label,
        seq_start=s.seq_start,seq_end=s.seq_end,baseline=s.baseline,direction=s.direction_info) for s in strokes])
    available=[]
    for d in config.directions:
        if all(np.mean(np.isfinite(s.representations[d]))>=config.feature_config.direction_coverage
               and (d=='D2' or s.direction_info['anchor_ok']) for s in strokes): available.append(d)
    event_no=0

    def check():
        if cancel and cancel(): raise Cancelled('训练已取消')

    def emit(message,**details):
        nonlocal event_no
        event_no+=1;event=dict(message=message,**details)
        if progress: progress(event)
        if event_no%10==0 or 'stage' in details:
            with (folder/'events.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(event,ensure_ascii=False)+'\n')

    index=np.arange(len(y))
    # Cache predictions rather than fitted candidate models. This bounds memory while
    # sharing identical training subsets reached by different outer folds.
    score_cache={};fusion_cache=OrderedDict()

    def fit(candidate,train_idx,projection=False):
        check()
        representations={k:v[train_idx] for k,v in X.items()}
        if candidate.family=='F3':
            base=replace(candidate,weight=.5);key=(base,tuple(train_idx))
            if key not in fusion_cache:
                fusion_cache[key]=MagneticModel(base).fit(representations,y[train_idx],groups[train_idx],check,False)
                if len(fusion_cache)>96:fusion_cache.popitem(last=False)
            fusion_cache.move_to_end(key)
            model=copy.copy(fusion_cache[key]);model.candidate=candidate
            if projection:model.fit_projection(representations)
            return model
        return MagneticModel(candidate).fit(representations,y[train_idx],groups[train_idx],check,projection)

    def choose(pool,train_idx):
        if len(pool)==1: return pool[0]
        best=None;best_score=-1
        for ci,c in enumerate(pool):
            check();key=(c,tuple(train_idx))
            if key in score_cache: value=score_cache[key]
            else:
                inner=np.full(len(train_idx),-1,dtype=int)
                for g in np.unique(groups[train_idx]):
                    inner_te=groups[train_idx]==g
                    model=fit(c,train_idx[~inner_te])
                    inner[inner_te]=model.predict({k:v[train_idx[inner_te]] for k,v in X.items()})
                value=float(f1_score(y[train_idx],inner,labels=range(7),average='macro',zero_division=0))
                score_cache[key]=value
            # Deterministic tie-break: candidate order is fixed and linear precedes RBF.
            if value>best_score+1e-12: best,best_score=c,value
            if ci%10==0: emit('训练侧参数比较',candidate=ci+1,candidates=len(pool))
        return best

    try:
        with threadpool_limits(limits=1):
            for family in config.families:
                check()
                if family in ('F1','F2','F3') and not available:
                    task['branches'][family]=dict(status='unavailable',reason='方向有效覆盖或参考锚点不足；不删样本换取高分')
                    emit(FAMILIES[family]+'：方向条件不足',stage='branch');continue
                if family=='F3' and len(experiments)<4:
                    task['branches'][family]=dict(status='unavailable',reason='分数融合的嵌套交叉拟合至少需要4次完整实验')
                    emit('分数融合：实验组数不足',stage='branch');continue
                pool=list(candidates(family,config,available));folds=[]
                pred=np.full(len(y),-1,dtype=int);scores=np.zeros((len(y),7));robust=[]
                for fi,g in enumerate(np.unique(groups)):
                    check();te=index[groups==g];tr=index[groups!=g]
                    emit(FAMILIES[family]+' · 整次实验留出',stage='validation',family=family,
                         fold=fi+1,folds=len(experiments),candidates=len(pool))
                    candidate=choose(pool,tr);model=fit(candidate,tr,projection=True)
                    test={k:v[te] for k,v in X.items()}
                    scores[te]=model.decision_function(test);pred[te]=model.predict(test)
                    fold=dict(train_runs=sorted(set(groups[tr])),test_runs=[g],train_indices=tr.tolist(),test_indices=te.tolist(),
                              selected=asdict(candidate))
                    folds.append(fold)
                    # Stored to explain original OOF errors using the actual fold model.
                    fold_path=folder/'fold_models'/family/f'{fi:03d}.joblib';fold_path.parent.mkdir(parents=True,exist_ok=True)
                    import joblib
                    joblib.dump(model,fold_path)
                    if config.robustness:
                        offsets=[]
                        for offset in (-300.,-200.,-100.,100.,200.,300.):
                            perturbed=dict(test);perturbed['A0']=test['A0']+offset
                            pp=model.predict(perturbed)
                            offsets.append(dict(offset=offset,changed=int(np.sum(pp!=pred[te])),correct=int(np.sum(pp==y[te]))))
                        # Recompute directions from rotated EMA components and the same
                        # scalar amplitude. The active circular anchor is re-established.
                        rotations=[]
                        for angle in (np.pi/2,np.pi,3*np.pi/2):
                            rotated=dict(test)
                            directions=[]
                            for sample in te:
                                s=strokes[sample];u=s.native_u;v=s.native_v
                                directions.append(direction_features(s.native_tau,u*np.cos(angle)-v*np.sin(angle),
                                    u*np.sin(angle)+v*np.cos(angle),s.native_ema,config.feature_config)[0])
                            for d in ('D1','D2','D3'):rotated[d]=np.array([r[d] for r in directions])
                            rotations.append(dict(degrees=float(np.rad2deg(angle)),changed=int(np.sum(model.predict(rotated)!=pred[te]))))
                        robust.append(dict(run=g,offsets=offsets,relative_rotation=rotations))
                emit(FAMILIES[family]+' · 全部开发数据最终拟合',stage='final_fit',family=family)
                candidate=choose(pool,index);final=fit(candidate,index,projection=True)
                bundle=dict(version=VERSION,labels=list(LABELS),model=final,pca=final.pca,
                    feature_config=config.feature_config.to_dict(),reference_mode='first_10_percent_fallback',
                    training_runs=sorted(set(groups)),sensor_hashes=[e.sensor_hash for e in experiments],
                    training_strokes=strokes,training_projection=final.training_projection,
                    candidate=asdict(candidate),versions=dict(python=platform.python_version(),numpy=np.__version__,sklearn=sklearn.__version__),
                    source_fingerprint=task['source_fingerprint'])
                metric=evaluate(y,pred,groups)
                rows=[dict(sample_id=s.sample_id,run_id=s.run_id,stroke=s.index,true=int(y[i]),predicted=int(pred[i]),
                           scores=scores[i].tolist()) for i,s in enumerate(strokes)]
                metadata=dict(name=FAMILIES[family],family=family,metrics=metric,folds=folds,candidate=asdict(candidate),
                              predictions=rows,robustness=robust,tests=[])
                item=store.add_model(task,metadata,bundle)
                with (store.model_path(task['id'],item['id'])/'predictions.csv').open('w',encoding='utf-8-sig',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
                task['branches'][family]=dict(status='completed',model_id=item['id']);store.save(task)
            ranks=rank_models({m['id']:m['metrics'] for m in task['models']})
            for m in task['models']: m['rank']=ranks.get(m['id'])
            task['conditions']={'A3':'未提供独立共同参考响应／增益证据，条件不足',
                'direction_variants':{'available':available,'unavailable':sorted(set(config.directions)-set(available))},
                'reference':'每笔前10%原生EMA中位数扣除；不是接触前空载参考',
                'robustness':'数学偏移／相对旋转对照' if config.robustness else '用户关闭',
                'auxiliary_LinearSVC':'未执行辅助实现对照；不影响F0—F4主模型定义',
                'position_majority_controls':'顺序不用作特征；完整七类每类一次，多数类正确率1/7，顺序映射为非磁识别对照',
                'scope':'本次选中模型和候选范围；不声称所有研究扩展分支全部完成'}
            store.complete(task)
            write_json(folder/'report.json',task)
            lines=['# 磁响应笔画训练结果','',f"实验：{len(experiments)}次；笔画：{len(strokes)}笔",'',
                   '整次实验留一验证；新实验测试另存。','', '|模型|总错分|最差类别召回率|最差实验正确数|推荐顺序|','|---|---:|---:|---:|---:|']
            for m in task['models']:
                v=m['metrics'];lines.append(f"|{m['name']}|{v['errors']}/{v['total']}|{v['worst_recall']:.1%}|{v['worst_run_correct']}/7|{m.get('rank','—')}|")
            lines.extend(['','## 分支状态','',json.dumps(task['branches'],ensure_ascii=False,indent=2),'','## 条件项','',json.dumps(task['conditions'],ensure_ascii=False,indent=2)])
            (folder/'report.md').write_text('\n'.join(lines),encoding='utf-8')
            emit('训练完成' if task['models'] else '没有可保存的模型，请查看条件说明',stage='done',task_id=task['id'])
        return task
    except BaseException as exc:
        task['status']='cancelled' if isinstance(exc,Cancelled) else 'failed'
        task['error']=str(exc);store.save(task)
        raise
