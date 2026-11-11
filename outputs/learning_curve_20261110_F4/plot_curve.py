import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

OUT=Path(__file__).resolve().parent
r=json.loads((OUT/'results.json').read_text());s=r['summary'];x=np.array([v['training_runs'] for v in s])
plt.rcParams.update({'font.family':'Noto Sans CJK JP','font.size':11,'axes.unicode_minus':False,'figure.facecolor':'#101827','axes.facecolor':'#152238','axes.edgecolor':'#506078','axes.labelcolor':'#dce6f2','text.color':'#e9eef6','xtick.color':'#aebdd0','ytick.color':'#aebdd0','grid.color':'#35445b','savefig.facecolor':'#101827','pdf.fonttype':42})
fig,axs=plt.subplots(1,2,figsize=(13.8,6.5),gridspec_kw={'width_ratios':[1.25,1]})
fig.subplots_adjust(top=.76,bottom=.23,left=.075,right=.97,wspace=.24)
fig.text(.075,.925,'F4 学习曲线｜第二轮 · 16次毛笔实验',fontsize=20,weight='bold')
fig.text(.075,.865,'幅值＋差分 · 整次实验留出 · 每个规模在训练侧重新选参 · 3组固定随机种子',color='#aebdd0',fontsize=11)
ax=axs[0]
mean=np.array([v['accuracy_mean'] for v in s]);lo=np.array([v['accuracy_min'] for v in s]);hi=np.array([v['accuracy_max'] for v in s]);train=np.array([v['training_accuracy_mean'] for v in s])
ax.fill_between(x,lo,hi,color='#49c4f2',alpha=.17)
ax.plot(x,train,'o--',color='#f5b968',lw=1.8,label='训练正确率（已见数据）',markersize=5)
ax.plot(x,mean,'o-',color='#49c4f2',lw=2.4,label='留出验证正确率',markersize=6)
for a,b in zip(x,mean):ax.annotate(f'{b:.1%}',(a,b),xytext=(0,-19),textcoords='offset points',ha='center',color='#72d5f6',fontsize=10)
ax.set_title('数据增加后，识别正确率怎样变化？',loc='left',pad=16,fontsize=12)
ax.set_ylabel('正确率');ax.set_ylim(max(0,np.floor((lo.min()-.07)*10)/10),1.025);ax.set_yticks(np.arange(.8,1.001,.05))
ax.legend(loc='lower right',facecolor='#152238',edgecolor='#35445b',labelcolor='#e9eef6',fontsize=10)
ax=axs[1]
for key,color,label in [('macro_f1','#bfa0ff','Macro-F1'),('worst_recall','#70dbb2','最差类别召回率')]:
    values=np.array([v[key+'_mean'] for v in s]);lower=np.array([v[key+'_min'] for v in s]);upper=np.array([v[key+'_max'] for v in s])
    ax.fill_between(x,lower,upper,color=color,alpha=.12)
    ax.plot(x,values,'o-',color=color,lw=2,label=label,markersize=5)
    ax.annotate(f'{values[-1]:.2%}',(x[-1],values[-1]),xytext=(-7,9 if key=='macro_f1' else -18),textcoords='offset points',ha='right',color=color,fontsize=10)
ax.set_title('各类别是否都在改善？',loc='left',pad=16,fontsize=12)
ax.set_ylim(max(0,np.floor((min(v['worst_recall_min'] for v in s)-.08)*10)/10),1.025)
ax.set_ylabel('指标值');ax.legend(loc='lower right',facecolor='#152238',edgecolor='#35445b',labelcolor='#e9eef6',fontsize=10)
for ax in axs:
    ax.set_xticks(x);ax.set_xlabel('每个外层模型的训练实验次数（每次7笔）',labelpad=10);ax.yaxis.set_major_formatter(PercentFormatter(1));ax.grid(axis='y',alpha=.55);ax.spines[['top','right']].set_visible(False)
fig.text(.075,.115,'每个点：汇总全部16个外层留出实验，共112笔；阴影：3组训练子集结果的最小～最大值，非置信区间。',fontsize=10,color='#aebdd0')
fig.text(.075,.065,'15次训练端点与原保存的112笔留出预测逐笔一致。011/012配置相同；本图评价按实验留出，未单独评价全新配置。',fontsize=10,color='#aebdd0')
fig.text(.075,.025,'15次训练时，各重复使用同一完整训练集，波动带归零是设计结果，不代表泛化不确定性为零。',fontsize=9,color='#aebdd0')
fig.savefig(OUT/'learning_curve.png',dpi=190);fig.savefig(OUT/'learning_curve.pdf');plt.close(fig)
# Class-specific companion: averages across complete OOF repeats.
labels=r['config'].get('labels') or ['右点','横折钩','横撇','撇','捺','横','竖']
values=np.array([[np.mean([rep['metrics']['per_class'][label]['recall'] for rep in r['repeats'] if rep['training_runs']==n]) for n in x] for label in labels])
fig,ax=plt.subplots(figsize=(10.3,6.3));fig.subplots_adjust(left=.13,right=.88,top=.82,bottom=.17)
im=ax.imshow(values,cmap='YlGnBu',vmin=.5,vmax=1,aspect='auto')
ax.set_xticks(range(len(x)),x);ax.set_yticks(range(7),labels);ax.set_xlabel('训练实验次数');ax.set_title('各类笔画的留出召回率｜F4',loc='left',pad=20,fontsize=16)
for i in range(7):
    for j in range(len(x)):ax.text(j,i,f'{values[i,j]:.1%}',ha='center',va='center',color='white' if values[i,j]>.8 else '#13243c',fontsize=11)
cb=fig.colorbar(im,ax=ax,fraction=.04,pad=.04);cb.ax.yaxis.set_major_formatter(PercentFormatter(1));cb.set_label('召回率')
fig.text(.13,.055,'每格为3组完整留出结果的平均值；每类每组有16笔测试预测。重复使用同一批实验。',fontsize=10,color='#aebdd0')
fig.savefig(OUT/'class_recall.png',dpi=190);plt.close(fig)
print('Rendered learning_curve.png, learning_curve.pdf, class_recall.png')
