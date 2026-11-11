"""Comparable out-of-fold metrics; no arbitrary composite score."""
import numpy as np
from sklearn.metrics import classification_report,confusion_matrix,f1_score
from . import LABELS


def evaluate(y,pred,groups,class_count=7):
    y=np.asarray(y,dtype=int);pred=np.asarray(pred,dtype=int);groups=np.asarray(groups)
    if len(y)==0 or y.shape!=pred.shape or np.any(pred<0):
        raise ValueError('留出预测未完整，不能评分')
    labels=LABELS[:class_count]
    matrix=confusion_matrix(y,pred,labels=np.arange(class_count))
    support=matrix.sum(axis=1)
    recall=np.divide(matrix.diagonal(),support,out=np.zeros(class_count),where=support>0)
    per_run={str(g):{'correct':int(np.sum(pred[groups==g]==y[groups==g])),
                     'total':int(np.sum(groups==g))} for g in np.unique(groups)}
    return dict(total=len(y),correct=int(np.sum(pred==y)),errors=int(np.sum(pred!=y)),
        accuracy=float(np.mean(pred==y)),macro_f1=float(f1_score(y,pred,labels=range(class_count),average='macro',zero_division=0)),
        worst_recall=float(recall.min()),worst_classes=[LABELS[i] for i in np.flatnonzero(recall==recall.min())],
        worst_run_correct=min(v['correct'] for v in per_run.values()),per_run=per_run,
        comparable=bool(np.all(support>0)),confusion_matrix=matrix.tolist(),
        per_class=classification_report(y,pred,labels=range(class_count),target_names=labels,output_dict=True,zero_division=0))


def rank_models(metrics):
    eligible={k:v for k,v in metrics.items() if v.get('comparable',False)}
    key=lambda v:(v['errors'],-v['worst_recall'],-v['worst_run_correct'])
    return {name:1+sum(key(other)<key(value) for other in eligible.values()) for name,value in eligible.items()}
