"""Dark scientific plots with explicit coordinate meanings and model provenance."""
import numpy as np
import itertools
from matplotlib import font_manager
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg,NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt5 import QtWidgets as W,QtCore,QtGui
from . import LABELS
from .theme import BACKGROUND,PANEL,TEXT,MUTED,COLORS
from .training import stack_strokes

FONT=next((f.name for f in font_manager.fontManager.ttflist if f.name in ('Noto Sans CJK SC','Noto Sans CJK JP','Droid Sans Fallback','WenQuanYi Zen Hei','Microsoft YaHei')),'DejaVu Sans')


class Plot(W.QWidget):
    pointSelected=QtCore.pyqtSignal(int)
    classToggled=QtCore.pyqtSignal(int)

    def __init__(self,parent=None,toolbar=False):
        super().__init__(parent)
        self.figure=Figure(figsize=(5,3),facecolor=PANEL,layout='constrained')
        self.canvas=FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumSize(200,210)
        layout=W.QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.canvas)
        if toolbar:
            self.toolbar=NavigationToolbar2QT(self.canvas,self)
            for action in self.toolbar.actions():
                if action.icon().isNull():continue
                pixmap=action.icon().pixmap(24,24);painter=QtGui.QPainter(pixmap)
                painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(),QtGui.QColor('#b9cce8'));painter.end()
                action.setIcon(QtGui.QIcon(pixmap))
            layout.addWidget(self.toolbar)
        self.canvas.mpl_connect('pick_event',self.pick)
        self.empty('导入数据后显示曲线')

    def pick(self,event):
        artist=event.artist
        if hasattr(artist,'class_index'):
            self.classToggled.emit(artist.class_index);return
        if hasattr(artist,'sample_indices') and len(event.ind):
            self.pointSelected.emit(int(artist.sample_indices[event.ind[0]]))

    def axes(self,projection=None):
        self.figure.clear();ax=self.figure.add_subplot(111,projection=projection)
        ax.set_facecolor(PANEL);ax.tick_params(colors=MUTED,labelsize=10)
        for spine in ax.spines.values(): spine.set_color('#334258')
        ax.xaxis.label.set_color(MUTED);ax.yaxis.label.set_color(MUTED)
        ax.grid(color='#2a374c',linewidth=.5,alpha=.7)
        for label in ax.get_xticklabels()+ax.get_yticklabels(): label.set_fontfamily(FONT)
        return ax

    def finish(self,ax,title=''):
        ax.set_title(title,color=TEXT,fontfamily=FONT,fontsize=12,pad=13)
        for label in (ax.xaxis.label,ax.yaxis.label): label.set_fontfamily(FONT)
        self.canvas.draw_idle()

    def empty(self,message):
        ax=self.axes();ax.set_axis_off()
        ax.text(.5,.5,message,transform=ax.transAxes,ha='center',va='center',color=MUTED,fontfamily=FONT,fontsize=12,wrap=True)
        self.canvas.draw_idle()

    def curve(self,stroke,mode='amplitude'):
        ax=self.axes();tau=np.linspace(0,1,len(stroke.amplitude))
        if mode=='direction':
            d=stroke.representations['D3'];n=len(tau)
            ax.plot(tau,d[:n],color=COLORS[0],label='sin(相对方向)')
            ax.plot(tau,d[n:],color=COLORS[1],label='cos(相对方向)')
            ax.set_ylabel('相对方向分量（无量纲）')
        elif mode=='difference':
            ax.plot(tau,stroke.representations['A4'],color=COLORS[2],linewidth=1.8,label='相邻差分 A4')
            ax.set_ylabel('相邻归一化采样点幅值差 / µT')
        elif mode=='processed':
            ax.plot(tau,stroke.representations['A1'],color=COLORS[0],linewidth=1.8,label='基准扣除后幅值')
            ax.set_ylabel('Δ|Bxy| / µT')
        else:
            ax.plot(stroke.native_tau,stroke.native_ema,color=COLORS[0],linewidth=1.6,label='实测磁幅值 EMA')
            ax.set_ylabel('|ΔBxy| EMA / µT')
        ax.set_xlabel('归一化时间 τ');ax.set_xlim(0,1)
        ax.legend(facecolor=PANEL,labelcolor=TEXT,edgecolor='none',prop={'family':FONT,'size':10})
        label=LABELS[stroke.label] if stroke.label is not None else '未知类别'
        self.finish(ax,f'第{stroke.index}笔 · {label}')

    def matrix(self,metric):
        ax=self.axes();ax.grid(False);matrix=np.array(metric['confusion_matrix'])
        n=len(matrix);labels=LABELS[:n]
        ax.imshow(matrix,cmap='Blues',vmin=0,vmax=max(1,matrix.max()),aspect='equal')
        ax.set_xticks(range(n),labels,rotation=25,ha='right',fontfamily=FONT)
        ax.set_yticks(range(n),labels,fontfamily=FONT)
        for i in range(n):
            for j in range(n):
                ax.text(j,i,str(matrix[i,j]),ha='center',va='center',color='#071222' if matrix[i,j]<matrix.max()*.5 else '#ffffff',fontsize=11)
        ax.set_xlabel('模型预测类别');ax.set_ylabel('真实任务类别')
        self.finish(ax,'混淆矩阵 · 整次实验留出预测')

    def scores(self,values,predicted):
        ax=self.axes();pos=np.arange(len(values));labels=LABELS[:len(values)]
        colors=[COLORS[0] if i==predicted else '#4b6080' for i in pos]
        ax.barh(pos,values,color=colors);ax.set_yticks(pos,labels,fontfamily=FONT);ax.invert_yaxis()
        ax.axvline(0,color=MUTED,linewidth=.7);ax.set_xlabel('判别分数（不是概率）')
        span=max(max(values)-min(values),1)
        for i,v in enumerate(values):ax.text(v+span*.02,i,f'{v:.3f}',color=TEXT,va='center',fontsize=10)
        ax.set_xlim(min(0,min(values))-span*.1,max(values)+span*.3)
        self.finish(ax,'逐类判别分数')

    def quality(self,metric):
        ax=self.axes();labels=LABELS[:len(metric['confusion_matrix'])];values=[metric['per_class'][l]['recall'] for l in labels]
        ax.bar(range(len(labels)),values,color=COLORS[0],width=.55)
        ax.set_xticks(range(len(labels)),labels,fontfamily=FONT,rotation=20);ax.set_ylim(0,1.15)
        ax.set_ylabel('召回率');ax.set_xlabel('笔画类别')
        for i,v in enumerate(values):ax.text(i,v+.025,f'{v:.0%}',ha='center',color=TEXT,fontsize=10)
        self.finish(ax,'各类笔画识别率 · 留出预测')

    def space(self,bundle,three=False,new=None,branch=0,*,plane=(0,1),visible=None,
              highlighted_run=None,errors=None,selected=None,supports_visible=False,size=38,opacity=.8,view=None):
        from matplotlib.colors import to_rgba
        ax=self.axes('3d' if three else None)
        model=bundle['model'];points=bundle['training_projection'];pca=bundle['pca'];supports=model.support_
        prefix=''
        if model.candidate.family=='F3':
            points=model.branch_projections[branch];pca=model.branch_pcas[branch];supports=model.svcs[branch].support_
            prefix=('幅值分支' if branch==0 else '方向分支')+' · '
        dims=(0,1,2) if three else plane
        if max(dims)>=points.shape[1]:
            self.empty('该模型保存的主成分数量不足以显示所选坐标');return
        strokes=bundle['training_strokes'];ys=np.array([s.label for s in strokes])
        visible=np.ones(len(points),dtype=bool) if visible is None else np.asarray(visible,dtype=bool)
        errors=np.zeros(len(points),dtype=bool) if errors is None else np.asarray(errors,dtype=bool)
        def coordinates(indices):return [points[indices,d] for d in dims]
        for i,label in enumerate(bundle['labels']):
            idx=np.flatnonzero((ys==i)&visible)
            colors=[to_rgba(COLORS[i],opacity if not highlighted_run or strokes[j].run_id==highlighted_run else .1) for j in idx]
            artist=ax.scatter(*coordinates(idx),s=size,c=colors or COLORS[i],label=label,picker=6)
            artist.sample_indices=idx
        support_indices=np.asarray(supports,dtype=int)
        if supports_visible:
            support_indices=support_indices[visible[support_indices]]
            artist=ax.scatter(*coordinates(support_indices),s=size*2.2,facecolors='none',edgecolors=TEXT,linewidths=.8,label='支持向量',picker=6)
            artist.sample_indices=support_indices
        wrong=np.flatnonzero(errors&visible)
        if len(wrong):
            artist=ax.scatter(*coordinates(wrong),s=size*1.8,marker='x',color='#ff91ad',linewidths=1.5,label='留出错分',picker=6)
            artist.sample_indices=wrong
        if selected is not None and visible[selected]:
            artist=ax.scatter(*coordinates(np.array([selected])),s=size*3.5,facecolors='none',edgecolors='#ffe0a1',linewidths=2,picker=6)
            artist.sample_indices=np.array([selected])
        if new is not None:
            ax.scatter(*[new[d] for d in dims],s=size*4,marker='*',color='#ffe0a1',edgecolors='#0d121c',label='新样本',depthshade=False) if three else ax.scatter(*[new[d] for d in dims],s=size*4,marker='*',color='#ffe0a1',edgecolors='#0d121c',label='新样本',zorder=8)
        variance=pca.explained_variance_ratio_
        setters=[ax.set_xlabel,ax.set_ylabel]+([lambda text:ax.set_zlabel(text,color=MUTED,fontfamily=FONT)] if three else [])
        for d,setter in zip(dims,setters):setter(f'PC{d+1} · {variance[d]:.1%}')
        # Limits use all saved points, so filtering never stretches a category to fill the plot.
        limits=[ax.set_xlim,ax.set_ylim]+([ax.set_zlim] if three else [])
        for d,setter in zip(dims,limits):
            values=points[:,d] if new is None else np.r_[points[:,d],new[d]]
            low,high=float(values.min()),float(values.max());pad=max((high-low)*.08,.1);setter(low-pad,high+pad)
        if three:
            for axis in (ax.xaxis,ax.yaxis,ax.zaxis):
                axis.set_pane_color((.08,.11,.17,1));axis.label.set_fontfamily(FONT)
            if view is not None:ax.view_init(elev=view[0],azim=view[1])
        legend=ax.legend(facecolor=PANEL,labelcolor=TEXT,edgecolor='none',ncol=4,loc='upper center',
                  bbox_to_anchor=(.5,-.13),prop={'family':FONT,'size':9})
        for text in legend.get_texts():
            if text.get_text() in bundle['labels']:
                text.set_picker(True);text.class_index=bundle['labels'].index(text.get_text())
        self.finish(ax,prefix+f'PCA投影 · 当前累计解释方差 {sum(variance[d] for d in dims):.1%}')

    def pair(self,bundle,first,second,branch=0):
        model=bundle['model'];svc=model.svcs[branch] if model.candidate.family=='F3' else model.svcs[0]
        representations=stack_strokes(bundle['training_strokes']);X=model.project_input(representations)
        if model.candidate.family=='F3':
            blocks=model.blocks(representations)
            X=model.scalers[branch].transform(blocks[branch])
        first,second=sorted((first,second))
        if first==second: self.empty('请选择两个不同类别');return
        pair_index=list(itertools.combinations(range(len(bundle['labels'])),2)).index((first,second))
        shape=svc.decision_function_shape
        try:
            svc.decision_function_shape='ovo';values=svc.decision_function(X)[:,pair_index]
        finally: svc.decision_function_shape=shape
        ax=self.axes();ys=np.array([s.label for s in bundle['training_strokes']])
        for label in (first,second):
            idx=np.flatnonzero(ys==label)
            ax.scatter(values[idx],np.arange(len(idx)),color=COLORS[label],label=LABELS[label],s=40)
        ax.axvline(0,color=TEXT,linewidth=1);ax.set_xlabel('真实两类SVC判别值（0为边界）');ax.set_ylabel('该类样本序号')
        ax.legend(facecolor=PANEL,labelcolor=TEXT,edgecolor='none',prop={'family':FONT,'size':10})
        prefix=('幅值分支 · ' if branch==0 else '方向分支 · ') if model.candidate.family=='F3' else ''
        self.finish(ax,'最终模型 · '+prefix+'两类判别观察')
