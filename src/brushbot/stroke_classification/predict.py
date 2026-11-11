"""Inference never fits estimators, scales, reference rules or projections."""
import numpy as np
from . import VERSION
from .training import stack_strokes


def predict_strokes(bundle,strokes):
    if bundle.get('version')!=VERSION: raise ValueError('模型处理链版本不兼容')
    model=bundle['model'];c=model.candidate;config=bundle['feature_config']
    if not strokes: raise ValueError('没有待识别笔画')
    if any(s.feature_config!=config for s in strokes):raise ValueError('笔画预处理配置与模型不一致，请按模型配置重新导入')
    outside=[s.label is not None and not 0<=s.label<len(bundle['labels']) for s in strokes]
    if any(outside):
        supported=[s for s,out in zip(strokes,outside) if not out]
        inner=iter(predict_strokes(bundle,supported) if supported else [])
        result=[]
        for s,out in zip(strokes,outside):
            if not out:result.append(next(inner));continue
            result.append(dict(sample_id=s.sample_id,run_id=s.run_id,stroke=s.index,true_label=s.label,
                label_source=s.label_source,input_source=s.source_metadata,unsupported=True,predicted=None,
                correct=None,scores=None,branch_scores=[],projection=None,branch_projections=[],training_overlap=False))
        return result
    if c.family in ('F1','F2','F3'):
        for s in strokes:
            if np.mean(np.isfinite(s.representations[c.direction]))<config['direction_coverage']:
                raise ValueError('方向有效覆盖不足，当前模型不采用未登记的幅值回退')
            if c.direction!='D2' and not s.direction_info['anchor_ok']: raise ValueError('方向参考锚点不足')
    X=stack_strokes(strokes);pred=model.predict(X);scores=model.decision_function(X)
    projection=model.project(X);branches=model.branch_scores(X)
    projections=[model.project(X,b) for b in range(2)] if c.family=='F3' else [projection]
    result=[]
    for i,s in enumerate(strokes):
        result.append(dict(sample_id=s.sample_id,run_id=s.run_id,stroke=s.index,true_label=s.label,
            label_source=s.label_source,input_source=s.source_metadata,unsupported=False,
            predicted=int(pred[i]),correct=None if s.label is None else bool(pred[i]==s.label),
            scores=scores[i].tolist(),branch_scores=[b[i].tolist() for b in branches],
            projection=projection[i].tolist(),branch_projections=[p[i].tolist() for p in projections],training_overlap=s.run_id in bundle['training_runs']))
    return result
