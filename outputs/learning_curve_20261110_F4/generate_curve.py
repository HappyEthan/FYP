"""Standalone analysis artifact; leaves source code and model history unchanged."""
import csv,json,time
from dataclasses import asdict
from pathlib import Path
import numpy as np
from sklearn.metrics import f1_score
from threadpoolctl import threadpool_limits
from brushbot.stroke_classification.data import load_experiment,unique_experiments
from brushbot.stroke_classification.features import FeatureConfig
from brushbot.stroke_classification.training import TrainConfig,candidates,stack_strokes,source_fingerprint
from brushbot.stroke_classification.models import MagneticModel
from brushbot.stroke_classification.metrics import evaluate

OUT=Path(__file__).resolve().parent
TASK=Path('outputs/stroke_classifier/tasks/20261110-125350-35e2c423/task.json').resolve()
task=json.loads(TASK.read_text());meta=next(m for m in task['models'] if m['family']=='F4')
config=TrainConfig(**{**task['config'],'feature_config':FeatureConfig(**task['config']['feature_config'])})
experiments=unique_experiments([load_experiment(s['path'],config.feature_config) for s in task['sources']])
assert len(experiments)==16 and source_fingerprint(experiments)==task['source_fingerprint']
strokes=[s for e in experiments for s in e.strokes]
y=np.array([s.label for s in strokes]);groups=np.array([s.run_id for s in strokes]);runs=np.unique(groups)
X=stack_strokes(strokes);pool=list(candidates('F4',config,('D1','D2','D3')))
sizes=[4,6,8,10,12,15];seeds=[20261110,20261111,20261112]
cache={};choices={};fits=0;start=time.monotonic()

def predict(candidate,tr):
    global fits
    key=(candidate,tuple(tr))
    if key not in cache:
        model=MagneticModel(candidate).fit({k:v[tr] for k,v in X.items()},y[tr],groups[tr],projection=False)
        cache[key]=model.predict(X).astype(np.int8)
        fits+=1
    return cache[key]

def macro_f1(a,b):
    matrix=np.bincount(a*7+b,minlength=49).reshape(7,7)
    denom=matrix.sum(0)+matrix.sum(1)
    return float(np.mean(np.divide(2*matrix.diagonal(),denom,out=np.zeros(7),where=denom>0)))

def choose(tr):
    key=tuple(tr)
    if key in choices:return choices[key]
    best=None;score=-1
    for c in pool:
        p=np.full(len(y),-1,dtype=int)
        for run in np.unique(groups[tr]):
            inside=tr[groups[tr]!=run];te=tr[groups[tr]==run]
            p[te]=predict(c,inside)[te]
        value=macro_f1(y[tr],p[tr])
        if value>score+1e-12:best,score=c,value
    choices[key]=best
    return best

folds=[];repeats=[]
with threadpool_limits(limits=1):
    for rep,seed in enumerate(seeds):
        orders={run:np.random.default_rng(np.random.SeedSequence([seed,i])).permutation(runs[runs!=run]) for i,run in enumerate(runs)}
        for n in sizes:
            heldout=np.full(len(y),-1,dtype=int);train_acc=[];train_f1=[]
            for i,run in enumerate(runs):
                training_runs=orders[run][:n]
                tr=np.flatnonzero(np.isin(groups,training_runs));te=np.flatnonzero(groups==run)
                assert len(tr)==7*n and not np.intersect1d(tr,te).size
                c=choose(tr);p=predict(c,tr);heldout[te]=p[te]
                train_acc.append(float(np.mean(y[tr]==p[tr])));train_f1.append(macro_f1(y[tr],p[tr]))
                folds.append(dict(repeat=rep+1,seed=seed,training_runs_count=n,test_run=str(run),training_runs=sorted(training_runs.tolist()),candidate=asdict(c),training_accuracy=train_acc[-1],test_true=y[te].tolist(),test_predicted=p[te].tolist()))
                print(f'repeat={rep+1}/3 size={n} fold={i+1}/16 fits={fits} elapsed={time.monotonic()-start:.0f}s',flush=True)
            metrics=evaluate(y,heldout,groups)
            assert abs(metrics['macro_f1']-macro_f1(y,heldout))<1e-12
            assert abs(metrics['macro_f1']-f1_score(y,heldout,average='macro'))<1e-12
            if n==15:
                prior={(r['run_id'],r['stroke']):r['predicted'] for r in meta['predictions']}
                assert all(prior[(s.run_id,s.index)]==int(heldout[i]) for i,s in enumerate(strokes)), 'Endpoint differs from saved nested OOF predictions'
            repeats.append(dict(repeat=rep+1,seed=seed,training_runs=n,training_accuracy=float(np.mean(train_acc)),training_macro_f1=float(np.mean(train_f1)),metrics=metrics))
            (OUT/'checkpoint.json').write_text(json.dumps(dict(repeats=repeats,folds=folds),ensure_ascii=False,indent=2))
summary=[]
for n in sizes:
    rows=[r for r in repeats if r['training_runs']==n]
    row=dict(training_runs=n,training_strokes=n*7,repeats=len(rows))
    for key in ('accuracy','macro_f1','worst_recall','errors'):
        values=[r['metrics'][key] for r in rows]
        row.update({f'{key}_mean':float(np.mean(values)),f'{key}_min':float(np.min(values)),f'{key}_max':float(np.max(values))})
    row['training_accuracy_mean']=float(np.mean([r['training_accuracy'] for r in rows]))
    summary.append(row)
result=dict(task_id=task['id'],task_name=task['name'],family='F4',model_id=meta['id'],source_fingerprint=task['source_fingerprint'],candidate_count=len(pool),config=task['config'],seeds=seeds,summary=summary,repeats=repeats,folds=folds,fits=fits,elapsed_seconds=time.monotonic()-start,endpoint_exactly_matches_saved_oof=True,notes=['Nested whole-run leave-one-out; parameters selected using training runs only.','Three nested subset orders per outer fold; bands show min/max across repeats, not confidence intervals.','011 and 012 have identical target configurations; run grouping is not unseen-configuration grouping.','Training accuracy is resubstitution, not independent evaluation.','F4 family was selected using these development data; no independent final-model test.'])
(OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
with (OUT/'summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=summary[0]);writer.writeheader();writer.writerows(summary)
print('COMPLETE',json.dumps(summary,ensure_ascii=False),flush=True)
