"""Train-only masked scaling, SVC branches and OOF-standardized late fusion."""
from dataclasses import dataclass
import numpy as np
from sklearn.decomposition import PCA
from sklearn.svm import SVC


class MaskedScaler:
    def fit(self,X):
        finite=np.isfinite(X);count=finite.sum(axis=0)
        self.active_=count>0
        self.mean_=np.divide(np.where(finite,X,0).sum(axis=0),count,out=np.zeros(X.shape[1]),where=count>0)
        variance=np.divide(np.where(finite,(X-self.mean_)**2,0).sum(axis=0),count,out=np.ones(X.shape[1]),where=count>0)
        self.scale_=np.sqrt(variance);self.scale_[self.scale_<1e-12]=1.
        return self

    def transform(self,X):
        result=np.where(np.isfinite(X),(X-self.mean_)/self.scale_,0.)
        result[:,~self.active_]=0.
        return result


@dataclass(frozen=True)
class Candidate:
    family: str
    amplitude: str = 'A1'
    direction: str = 'D3'
    kernel: str = 'linear'
    C: float = 1.
    gamma: str | float = 'scale'
    weight: float = 1.


class MagneticModel:
    def __init__(self,candidate):
        self.candidate=candidate

    def blocks(self,representations):
        c=self.candidate
        if c.family=='F0': return [representations[c.amplitude]]
        if c.family=='F1': return [representations[c.direction]]
        if c.family in ('F2','F3'): return [representations['A1'],representations[c.direction]]
        return [representations['A1'],representations['A4']]

    def fit(self,representations,y,groups,check=lambda:None,projection=True):
        c=self.candidate;blocks=self.blocks(representations)
        self.scalers=[MaskedScaler().fit(b) for b in blocks]
        transformed=[s.transform(b) for s,b in zip(self.scalers,blocks)]
        if c.family=='F3':
            if len(np.unique(groups))<2: raise ValueError('分数融合的训练侧交叉拟合组不足')
            all_scores=[]
            for k,b in enumerate(blocks):
                oof=np.empty((len(y),len(np.unique(y))))
                for group in np.unique(groups):
                    check();tr=groups!=group;te=~tr
                    if len(np.unique(y[tr]))!=len(np.unique(y)): raise ValueError('分数校准子折缺类')
                    scaler=MaskedScaler().fit(b[tr]);model=self.svc().fit(scaler.transform(b[tr]),y[tr])
                    oof[te]=model.decision_function(scaler.transform(b[te]))
                all_scores.append(oof)
            self.score_mean=[s.mean(axis=0) for s in all_scores]
            self.score_scale=[np.maximum(s.std(axis=0),1e-8) for s in all_scores]
            self.svcs=[self.svc().fit(b,y) for b in transformed]
        else:
            self.svcs=[self.svc().fit(self.combine(transformed),y)]
        self.classes_=self.svcs[0].classes_
        if projection:self.fit_projection(representations)
        self.support_=self.svcs[0].support_
        return self

    def fit_projection(self,representations):
        if self.candidate.family=='F3':
            transformed=[s.transform(b) for s,b in zip(self.scalers,self.blocks(representations))]
            self.branch_pcas=[PCA(n_components=min(3,*b.shape),svd_solver='full').fit(b) for b in transformed]
            self.branch_projections=[p.transform(b) for p,b in zip(self.branch_pcas,transformed)]
            self.pca=self.branch_pcas[0];self.training_projection=self.branch_projections[0]
        else:
            features=self.project_input(representations)
            self.pca=PCA(n_components=min(3,*features.shape),svd_solver='full').fit(features)
            self.training_projection=self.pca.transform(features)
        return self

    def svc(self):
        c=self.candidate
        return SVC(kernel=c.kernel,C=c.C,gamma=c.gamma,probability=False,
                   decision_function_shape='ovr',break_ties=True,cache_size=128)

    def combine(self,blocks):
        return blocks[0] if len(blocks)==1 else np.c_[blocks[0],self.candidate.weight*blocks[1]]

    def project_input(self,representations):
        blocks=[s.transform(b) for s,b in zip(self.scalers,self.blocks(representations))]
        return np.concatenate(blocks,axis=1) if self.candidate.family=='F3' else self.combine(blocks)

    def project(self,representations,branch=0):
        if self.candidate.family=='F3':
            features=self.scalers[branch].transform(self.blocks(representations)[branch])
            return self.branch_pcas[branch].transform(features)
        return self.pca.transform(self.project_input(representations))

    def branch_scores(self,representations):
        blocks=[s.transform(b) for s,b in zip(self.scalers,self.blocks(representations))]
        if self.candidate.family!='F3': return [self.svcs[0].decision_function(self.combine(blocks))]
        return [m.decision_function(b) for m,b in zip(self.svcs,blocks)]

    def decision_function(self,representations):
        scores=self.branch_scores(representations)
        if self.candidate.family!='F3': return scores[0]
        w=self.candidate.weight
        return w*(scores[0]-self.score_mean[0])/self.score_scale[0]+(1-w)*(scores[1]-self.score_mean[1])/self.score_scale[1]

    def predict(self,representations):
        return self.classes_[np.argmax(self.decision_function(representations),axis=1)]
