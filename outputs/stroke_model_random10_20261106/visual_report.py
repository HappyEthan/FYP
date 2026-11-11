"""Static scientific figures and an offline HTML viewer for held-out predictions."""
import base64
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
from analysis_utils import LABELS,TAU

COLORS=['#2764bf','#ce6a16','#318568','#a64b72','#7960b5']
MODEL_NAMES={'linear':'固定线性 SVC','rbf':'固定 RBF-SVC','nested_selected':'训练侧选核流程'}


def save(fig,path):
    fig.savefig(path.with_suffix('.png'),dpi=160)
    fig.savefig(path.with_suffix('.svg'))
    plt.close(fig)


def render_all(out,X,y,g,samples,native,predictions,scores,folds,overall,meta):
    font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=font).get_name(),
        'axes.unicode_minus':False,'font.size':11,'svg.fonttype':'none',
        'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})
    figures=out/'figures';figures.mkdir(exist_ok=True)
    p=predictions['nested_selected'];primary=overall['nested_selected']
    cm=np.array(primary['confusion_matrix'])
    fig,axes=plt.subplots(2,2,figsize=(15,10),layout='constrained')
    ax=axes[0,0];im=ax.imshow(cm,cmap='Blues',vmin=0,vmax=10)
    ax.set_xticks(range(5),LABELS);ax.set_yticks(range(5),LABELS)
    ax.set_xlabel('预测类别');ax.set_ylabel('任务真实类别');ax.set_title('整次实验留出的混淆矩阵')
    for i in range(5):
        for j in range(5):ax.text(j,i,str(cm[i,j]),ha='center',va='center',color='white' if cm[i,j]>5 else '#152237',fontsize=14)
    recalls=np.diag(cm)/cm.sum(axis=1)
    ax=axes[0,1];bars=ax.bar(LABELS,recalls,color=COLORS)
    ax.set_ylim(0,1.15);ax.set_yticks([0,.25,.5,.75,1],['0%','25%','50%','75%','100%'])
    ax.set_title('各类召回率 · 每类10笔');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    for b,r in zip(bars,recalls):ax.text(b.get_x()+b.get_width()/2,r+.025,f'{r:.0%}',ha='center')
    ax=axes[1,0]
    for k,col in [('linear','#738399'),('rbf','#ca7421'),('nested_selected','#2764bf')]:
        vals=[np.mean(predictions[k][g==run]==y[g==run]) for run in range(1,11)]
        ax.plot(range(1,11),vals,'o-',label=MODEL_NAMES[k],color=col,alpha=.9)
    ax.set_xticks(range(1,11));ax.set_ylim(-.05,1.15);ax.set_yticks(np.linspace(0,1,6))
    ax.set_xlabel('留出的整次实验编号');ax.set_ylabel('识别正确比例');ax.set_title('每次实验的五笔识别结果');ax.legend(fontsize=9);ax.grid(alpha=.2)
    ax=axes[1,1];keys=['linear','rbf','nested_selected'];pos=np.arange(3)
    ax.bar(pos-.18,[overall[k]['accuracy'] for k in keys],width=.36,label='Accuracy',color='#2764bf')
    ax.bar(pos+.18,[overall[k]['macro_f1'] for k in keys],width=.36,label='Macro-F1',color='#39866f')
    ax.set_xticks(pos,['线性 SVC','RBF-SVC','训练侧选核']);ax.set_ylim(0,1.25);ax.set_yticks(np.linspace(0,1,6));ax.legend(fontsize=9);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    ax.set_title('相同外层留出划分下的模型比较')
    for i,k in enumerate(keys):ax.text(i,max(overall[k]['accuracy'],overall[k]['macro_f1'])+.025,f'{overall[k]["correct"]}/50',ha='center')
    fig.suptitle(f'十次随机实验 · 五类磁响应模型\n嵌套分组验证：{primary["correct"]}/50 正确，Accuracy {primary["accuracy"]:.1%}，Macro-F1 {primary["macro_f1"]:.3f}',fontsize=19)
    save(fig,figures/'训练成果总览')

    final_key=meta['kernel'];fixed=overall[final_key];fixed_cm=np.array(fixed['confusion_matrix'])
    fig,axes=plt.subplots(1,2,figsize=(13,5.5),layout='constrained')
    ax=axes[0];ax.imshow(fixed_cm,cmap='Blues',vmin=0,vmax=10)
    ax.set_xticks(range(5),LABELS);ax.set_yticks(range(5),LABELS)
    ax.set_xlabel('预测类别');ax.set_ylabel('任务真实类别');ax.set_title('固定核的整运行留出混淆矩阵')
    for i in range(5):
        for j in range(5):ax.text(j,i,str(fixed_cm[i,j]),ha='center',va='center',fontsize=13,color='white' if fixed_cm[i,j]>5 else '#152237')
    recalls=np.diag(fixed_cm)/fixed_cm.sum(axis=1);ax=axes[1]
    bars=ax.bar(LABELS,recalls,color=COLORS);ax.set_ylim(0,1.15)
    ax.set_yticks([0,.25,.5,.75,1],['0%','25%','50%','75%','100%']);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    ax.set_title('各类召回率 · 每类10笔')
    for b,r in zip(bars,recalls):ax.text(b.get_x()+b.get_width()/2,r+.025,f'{r:.0%}',ha='center')
    fig.suptitle(f'最终选定核：{final_key} SVC｜开发集分组验证 {fixed["correct"]}/50，Accuracy {fixed["accuracy"]:.1%}\n此图为固定核的开发表现；最终全50笔模型仍待新实验验收',fontsize=16)
    save(fig,figures/'最终选定核的留出表现')

    fig,axes=plt.subplots(5,2,figsize=(15,15),layout='constrained')
    for cls in range(5):
        for i in np.flatnonzero(y==cls):
            axes[cls,0].plot(native[i]['tau'],native[i]['ema'],color=plt.cm.viridis((int(g[i])-1)/9),lw=1,alpha=.75)
            axes[cls,1].plot(TAU,X[i],color=plt.cm.viridis((int(g[i])-1)/9),lw=1,alpha=.75)
        axes[cls,0].set_ylabel(f'{LABELS[cls]}\nEMA / µT');axes[cls,1].set_ylabel('Δr / µT')
        for ax in axes[cls]:ax.grid(alpha=.2);ax.set_xlim(0,1)
    axes[0,0].set_title('实测幅值 · 连续记录先取模再EMA')
    axes[0,1].set_title('模型实际输入 · 前10%基线扣除，128点')
    for ax in axes[-1]:ax.set_xlabel('归一化时间 τ')
    fig.suptitle('每类十条曲线 · 颜色由实验001到010渐变',fontsize=19)
    save(fig,figures/'五类全部曲线与模型输入')

    errors=np.flatnonzero(p!=y);error_dir=figures/'误分类';error_dir.mkdir(exist_ok=True)
    error_rows=[]
    for i in errors:
        tr=np.flatnonzero(g!=g[i]);true=int(y[i]);pred=int(p[i]);fig,ax=plt.subplots(figsize=(11,5.6),layout='constrained')
        for cls,col,style in [(true,'#318568','-'),(pred,'#bd4e4a','--')]:
            values=X[tr[y[tr]==cls]];mean=values.mean(axis=0);std=values.std(axis=0)
            ax.plot(TAU,mean,color=col,linestyle=style,lw=2,label=f'训练侧 {LABELS[cls]} 均值')
            ax.fill_between(TAU,mean-std,mean+std,color=col,alpha=.10)
        ax.plot(TAU,X[i],color='#192d49',lw=2,label='留出测试笔画')
        ax.set(title=f'实验{g[i]:03d}：任务标签 {LABELS[true]} → 预测 {LABELS[pred]}',
            xlabel='归一化时间 τ',ylabel='基线扣除后的磁响应 Δr / µT')
        ax.legend(fontsize=10);ax.grid(alpha=.2)
        rel=f'figures/误分类/run{int(g[i]):02d}_stroke{true+1:02d}'
        save(fig,out/rel)
        error_rows.append(dict(sample_id=samples[i]['sample_id'],run_number=int(g[i]),
            true_label=LABELS[true],predicted_label=LABELS[pred],figure=rel+'.png'))
    (out/'misclassifications.json').write_text(json.dumps(error_rows,ensure_ascii=False,indent=2)+'\n')

    idx=int(errors[0]) if len(errors) else 0
    fig,axes=plt.subplots(1,2,figsize=(13,4.8),layout='constrained')
    axes[0].plot(TAU,X[idx],color='#2764bf',lw=2)
    axes[0].set(xlabel='归一化时间 τ',ylabel='模型输入 Δr / µT',title='一条完整笔画的磁响应输入');axes[0].grid(alpha=.2)
    values=scores['nested_selected'][idx];cols=['#2764bf' if j==p[idx] else '#bec9d7' for j in range(5)]
    axes[1].barh(LABELS,values,color=cols);axes[1].invert_yaxis()
    axes[1].set(xlabel='OVR 判别分数（不是概率）',title=f'预测：{LABELS[p[idx]]}｜任务标签：{LABELS[y[idx]]}')
    fig.suptitle(f'单笔识别留出示例 · 实验{g[idx]:03d} · 该次运行未参与本轮模型拟合',fontsize=16)
    save(fig,figures/'单笔识别留出示例')

    lines=['# 十次随机实验五类笔画模型：训练报告','',
        f'主验证流程：外层10次整运行留出，内层只在9次训练运行中选核。50笔中识别正确 **{primary["correct"]}笔**，Accuracy **{primary["accuracy"]:.1%}**，Macro-F1 **{primary["macro_f1"]:.3f}**，Balanced Accuracy **{primary["balanced_accuracy"]:.1%}**。','',
        f'最终保存模型：**{meta["kernel"]} SVC**，StandardScaler＋SVC，使用全部50个合格样本训练。最终核根据两个固定核的开发CV按预登记规则选择；最终模型还没有全新独立测试实验。','',
        '![最终选定核的开发表现](figures/最终选定核的留出表现.png)','',
        '![完整选核流程验证](figures/训练成果总览.png)','','## 数据与处理','',
        '使用随机测试1（xy，磁）_001～_010的真实sensor.csv，共10次运行、50笔，每类10笔。未加入10月31日标准数据，没有生成合成训练样本。采集身份用于任务标签，不代表额外做过墨迹人工裁定。所有50个窗口有效，无窗口内采样缺口。','',
        '输入：sqrt(dBx²+dBy²) → 连续记录标量EMA(alpha=0.3) → measure完整书写段 → 按实际时间前10%区间中位数扣基线 → 归一化时间128点。此基线是方案允许的回退参考，不是空载零力。原始幅值和基线均保留。','',
        '每折缩放器只拟合训练侧。模型没有读取笔序、实验编号、时间长度、坐标或磁目标；phase只用于切段。每笔独立预测，不强制每次五笔各占一类。','',
        '## 固定核与选核流程的留出表现','','| 模型／流程 | 正确数 | Accuracy | Macro-F1 | Balanced Accuracy |','|---|---:|---:|---:|---:|']
    for k,m in overall.items():lines.append(f'| {MODEL_NAMES[k]} | {m["correct"]}/50 | {m["accuracy"]:.1%} | {m["macro_f1"]:.3f} | {m["balanced_accuracy"]:.1%} |')
    lines+=['','两个固定核的CV用于最终选核开发；主成绩使用内层选核后的外层预测，避免读取外层测试标签选择核。固定参数C=1，RBF gamma=scale；RBF的内层Macro-F1比线性高超过0.02才选RBF，否则选线性。','',
        '## 每类结果','','| 类别 | precision | recall | F1 | 支持数 |','|---|---:|---:|---:|---:|']
    for name in LABELS:
        r=primary['per_class'][name];lines.append(f'| {name} | {r["precision"]:.3f} | {r["recall"]:.3f} | {r["f1-score"]:.3f} | {int(r["support"])} |')
    lines+=['','## 每次实验','','| 留出实验 | 内层选核 | 该次正确数 |','|---|---|---:|']
    for fold in folds:lines.append(f'| {fold["held_out_run"]:03d} | {fold["selected_kernel"]} | {fold["outer_metrics"]["nested_selected"]["correct"]}/5 |')
    lines+=['','## 误分类','','全部误分类均列出，图中仅用外层训练侧类别曲线计算均值及±1个标准差阴影；阴影不是置信区间。','']
    if not error_rows:lines.append('本次主流程没有误分类；这不等于今后所有新数据都会正确。')
    for r in error_rows:lines.append(f'- 实验{r["run_number"]:03d}，{r["true_label"]} → {r["predicted_label"]}：[曲线对照]({r["figure"]})')
    lines+=['','## 识别接口','',
        'model.joblib是标准sklearn Pipeline，输入形状(n,128)，各列必须是同一处理定义下的Δr，不是原始dBx/dBy，也不是图片。模型输出0～4，映射见model_metadata.json。','',
        '附带predict_stroke.py可从单笔原始CSV、或完整.brushrun中指定一笔完成处理并识别。原始CSV需有seq、sensor_t_us、dBx_uT、dBy_uT及至少100个连续有效写前采样；valid和baseline_id可用现有采集字段。写前数据只用于连续滤波，不进入分类向量。单笔接口不需要真实标签或笔顺特征。若只剩已经裁切且无EMA状态的原始曲线，不能静默按每笔重置EMA冒充同一输入。','',
        '```bash',
        f'python predict_stroke.py --sensor-csv example_single_stroke.csv --seq-start {samples[0]["seq_start"]} --seq-end {samples[0]["seq_end"]}',
        'python predict_stroke.py --archive /绝对路径/新实验.brushrun --stroke 3',
        '```','',
        '第二种调用的stroke仅用于选择边界，不参与分类。example_single_stroke.csv来自本次训练样本，只验证模型加载和输入接口，不能用其预测成绩证明泛化。HTML中的单笔示例使用外层留出模型，和最终全量模型的接口演示分开。','',
        '## 可视化与文件','',
        '- [交互报告](训练成果可视化.html)：选择50个样本查看留出曲线、预测及各类判别分数。',
        '- [全部实测曲线和模型输入](figures/五类全部曲线与模型输入.png)。',
        '- [单笔留出示例](figures/单笔识别留出示例.png)。',
        '- predictions.csv：两个固定核及主流程的全部150行逐笔留出预测。',
        '- sample_audit.csv / data_manifest.json：样本边界、参考基线、原始来源与随机设置。',
        '- cv_folds.json / fold_models/：完整外层与内层划分、缩放器统计和每折模型，便于重放留出预测。',
        '- features_128.npz / .csv / curves_native.csv：模型输入和原生实测曲线。',
        '- model.joblib / model_metadata.json / requirements.txt：最终离线模型、预处理定义、标签、环境版本。','',
        '## 解释边界','',
        '十次运行来自同一套机器人采集协议，随机参数中途发生过变化，不能当成十位独立书写者。50笔属于10个运行组。CV是这批数据上的建模流程估计，不是跨批次或自由手写准确率。训练侧按类重复采集有固定笔顺／目标协议混杂，排除笔序特征并不能完全消除这些物理混杂。','',
        '多数类基线Accuracy为20%；仅按笔序直接映射可得100%，后者不是磁响应分类成绩。','',
        '五类模型对任何合格输入都会输出一个已知类别，尚无横／竖／未知类别拒识；不包含实时起止检测、图片识别、概率校准或控制界面改动。各类OVR判别分数不能解释为概率。建议下一批完整实验在模型冻结后做独立验收。','']
    (out/'训练报告.md').write_text('\n'.join(lines))
    build_html(out,X,y,g,p,scores['nested_selected'],folds,primary,error_rows)


def build_html(out,X,y,g,p,scores,folds,primary,errors):
    data=[dict(run=int(g[i]),truth=LABELS[y[i]],pred=LABELS[p[i]],correct=bool(p[i]==y[i]),
        kernel=folds[int(g[i])-1]['selected_kernel'],values=X[i].tolist(),scores=scores[i].tolist()) for i in range(len(y))]
    payload=json.dumps(dict(samples=data,labels=LABELS),ensure_ascii=False).replace('<','\\u003c')
    def embed(path):return 'data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode()
    image=embed(out/'figures/训练成果总览.png')
    fixed_image=embed(out/'figures/最终选定核的留出表现.png')
    curves=embed(out/'figures/五类全部曲线与模型输入.png')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>五类笔画模型训练成果</title>
<style>*{box-sizing:border-box}body{font:16px/1.6 system-ui,"Noto Sans CJK SC",sans-serif;background:#f0f3f8;color:#182a43;margin:0}main{max-width:1200px;margin:32px auto;padding:0 20px}h1{font-size:30px}h2{font-size:22px}.card{background:white;padding:24px;border-radius:14px;margin:20px 0;box-shadow:0 3px 16px #13233d0a}.muted{color:#5c6b80}img{width:100%;height:auto}select{font:inherit;padding:8px;border:1px solid #aab8cd;border-radius:6px;max-width:100%}.grid{display:grid;grid-template-columns:1.5fr 1fr;gap:22px}svg{width:100%;height:auto}.score{display:grid;grid-template-columns:70px 1fr 60px;align-items:center;gap:8px;margin:18px 0}.bar{height:22px;background:#e4eaf2;border-radius:5px;overflow:hidden}.fill{height:100%;background:#aab8cc}.good{color:#19734d}.bad{color:#b44336}@media(max-width:750px){.grid{grid-template-columns:1fr}}</style>
<main><h1>十次随机实验 · 五类笔画模型</h1><p class="muted">50条完整笔画，10个运行分组。模型只使用128点基线扣除后的实测磁幅值。</p>
<div class="card"><h2>最终选定核的开发表现</h2><p>最终核由两个固定核的分组CV按预登记规则确定；这里是该核的开发表现，不是最终全量模型的新实验成绩。</p><img src="FIXEDFIG" alt="最终选定核的分组验证结果"></div>
<div class="card"><h2>留出验证总览</h2><p>外层每次留出整次实验；核选择和标准化均只看训练侧。主流程：<b>SUMMARY</b>。</p><img src="IMAGE" alt="混淆矩阵、识别率和逐次实验表现"></div>
<div class="card"><h2>单笔识别 · 留出结果查看</h2><p class="muted">选择一条曲线，查看该次实验未参与拟合时的预测。这50例不是新的独立验收数据。</p><select id="sample"></select><p id="result"></p><div class="grid"><div><svg id="curve" viewBox="0 0 700 330" role="img" aria-label="所选笔画的128点磁响应曲线"></svg><p class="muted">横轴：归一化时间τ；纵轴：Δr / µT。每条曲线独立调整显示范围。</p></div><div><div id="scores"></div><p class="muted">OVR判别分数，不是概率。横条长度仅为显示缩放。</p></div></div></div>
<div class="card"><h2>五类实测曲线与实际模型输入</h2><img src="CURVES" alt="每类十条原生曲线与基线扣除后的模型输入"></div>
<div class="card"><h2>模型文件与适用范围</h2><p>model.joblib与model_metadata.json保存在本报告同目录。完整方法和误分类清单见训练报告.md；逐笔结果见predictions.csv。</p><p>最终模型使用全部50笔训练，需要后续全新实验验收；适用于已切好边界的五类笔画磁响应，不包含图片识别、自动切段或未知类别拒识。没有修改控制脚本。</p></div></main>
<script>const DATA=PAYLOAD;
const sel=document.getElementById('sample');DATA.samples.forEach((s,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`实验${String(s.run).padStart(3,'0')} · ${s.truth} · ${s.correct?'正确':'误分类'}`;sel.appendChild(o)});
function draw(){const s=DATA.samples[Number(sel.value)];const r=document.getElementById('result');r.className=s.correct?'good':'bad';r.textContent=`任务标签：${s.truth}　预测：${s.pred}　${s.correct?'识别正确':'识别不一致'}　训练侧选核：${s.kernel}`;
const lo=Math.min(...s.values),hi=Math.max(...s.values),pad=Math.max(5,(hi-lo)*.12),mn=lo-pad,mx=hi+pad;const px=i=>58+i/127*620,py=v=>285-(v-mn)/(mx-mn)*245;let svg='';for(let j=0;j<=4;j++){let v=mn+(mx-mn)*j/4,y=py(v);svg+=`<line x1="58" x2="678" y1="${y}" y2="${y}" stroke="#e1e6ef"/><text x="50" y="${y+4}" text-anchor="end" fill="#64748b" font-size="13">${v.toFixed(0)}</text>`}for(let j=0;j<=5;j++){let x=58+j/5*620;svg+=`<text x="${x}" y="310" text-anchor="middle" font-size="13" fill="#64748b">${(j/5).toFixed(1)}</text>`}let d=s.values.map((v,i)=>(i?'L':'M')+px(i).toFixed(2)+','+py(v).toFixed(2)).join(' ');svg+=`<path d="${d}" fill="none" stroke="#2764bf" stroke-width="2.5"/><text x="60" y="20" font-size="14" fill="#354760">Δr / µT</text>`;document.getElementById('curve').innerHTML=svg;
const box=document.getElementById('scores');box.replaceChildren();const scale=Math.max(1,...s.scores.map(Math.abs));DATA.labels.forEach((n,j)=>{let row=document.createElement('div');row.className='score';let label=document.createElement('span');label.textContent=n;let bar=document.createElement('div');bar.className='bar';let fill=document.createElement('div');fill.className='fill';fill.style.width=(Math.max(0,s.scores[j])/scale*100)+'%';if(n===s.pred)fill.style.background='#2764bf';bar.appendChild(fill);let value=document.createElement('span');value.textContent=s.scores[j].toFixed(3);row.append(label,bar,value);box.appendChild(row)})}sel.addEventListener('change',draw);draw();</script></html>'''
    page=page.replace('SUMMARY',f'{primary["correct"]}/50 正确，Accuracy {primary["accuracy"]:.1%}，Macro-F1 {primary["macro_f1"]:.3f}')
    page=page.replace('IMAGE',image).replace('FIXEDFIG',fixed_image).replace('CURVES',curves).replace('PAYLOAD',payload)
    (out/'训练成果可视化.html').write_text(page)
