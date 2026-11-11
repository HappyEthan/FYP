"""Reproducible analysis controls embedded in the existing result page."""
from dataclasses import asdict
from pathlib import Path
import json
import shutil
import uuid
import numpy as np
from PyQt5 import QtWidgets as W,QtCore as C

from . import LABELS
from .analysis import AnalysisConfig,default_sizes,estimate_fits,nearby_values,positive_values
from .features import FeatureConfig
from .jobs import AnalysisProcess
from .models import Candidate
from .plots import Plot,FONT
from .store import write_json
from .theme import COLORS,MUTED,PANEL,TEXT
from .training import TrainConfig

KINDS={'learning':'学习曲线','C':'C验证','weight':'差分权重验证','joint':'C × 差分权重'}


class AnalysisPanel(W.QWidget):
    candidateChosen=C.pyqtSignal(object)
    busyChanged=C.pyqtSignal(bool)

    def __init__(self,kind='learning',parent=None):
        super().__init__(parent)
        self.kind=kind;self.source=None;self.result=None;self.folder=None;self.busy=False;self.active_source=None
        self.job=AnalysisProcess(self);self.job.progressed.connect(self.on_progress);self.job.finished.connect(self.on_finished)
        layout=W.QVBoxLayout(self);layout.setContentsMargins(8,8,8,8)
        self.origin=W.QLabel('选择一个已训练模型后生成分析。');self.origin.setWordWrap(True);layout.addWidget(self.origin)
        self.settings=W.QWidget();form=W.QGridLayout(self.settings);form.setContentsMargins(0,0,0,0)
        self.mode=W.QComboBox()
        for key in ('C','weight','joint'):self.mode.addItem(KINDS[key],key)
        self.mode.setVisible(kind!='learning')
        self.cs=W.QLineEdit('0.001, 0.01, 0.1, 1, 10, 100')
        self.weights=W.QLineEdit('0.25, 0.5, 1, 2')
        self.sizes=W.QLineEdit();self.seeds=W.QLineEdit('20261110, 20261111, 20261112')
        self.center=W.QDoubleSpinBox();self.center.setDecimals(9);self.center.setRange(.000000001,1e9);self.center.setValue(.1)
        self.near=W.QPushButton('生成附近2倍候选');self.near.clicked.connect(self.generate_nearby)
        self.coarse=W.QPushButton('数量级候选');self.coarse.clicked.connect(lambda:self.cs.setText('0.001, 0.01, 0.1, 1, 10, 100'))
        if kind=='learning':
            form.addWidget(W.QLabel('训练实验次数'),0,0);form.addWidget(self.sizes,0,1,1,4)
            form.addWidget(W.QLabel('重复随机种子'),1,0);form.addWidget(self.seeds,1,1,1,4)
        else:
            form.addWidget(self.mode,0,0);form.addWidget(W.QLabel('C候选'),0,1);form.addWidget(self.cs,0,2,1,3)
            form.addWidget(W.QLabel('F4差分权重'),1,0);form.addWidget(self.weights,1,1,1,4)
            form.addWidget(W.QLabel('C中心值'),2,0);form.addWidget(self.center,2,1);form.addWidget(self.near,2,2);form.addWidget(self.coarse,2,3)
        layout.addWidget(self.settings)
        row=W.QHBoxLayout();self.generate=W.QPushButton('生成分析');self.generate.setObjectName('primary');self.generate.clicked.connect(self.start);self.generate.setEnabled(False)
        self.cancel_button=W.QPushButton('取消');self.cancel_button.setEnabled(False);self.cancel_button.clicked.connect(self.cancel)
        self.export_button=W.QPushButton('导出分析');self.export_button.clicked.connect(self.export_result)
        self.metric=W.QComboBox();self.metric.addItem('正确率','accuracy');self.metric.addItem('Macro-F1','macro_f1');self.metric.setCurrentIndex(1);self.metric.currentIndexChanged.connect(self.draw)
        for item in (self.generate,self.cancel_button,self.export_button,self.metric):row.addWidget(item)
        row.addStretch();layout.addLayout(row)
        self.estimate_label=W.QLabel('');self.estimate_label.setWordWrap(True);layout.addWidget(self.estimate_label)
        self.charts=W.QTabWidget();self.plot=Plot(toolbar=True);self.matrix=Plot();self.classes=Plot()
        self.charts.addTab(self.plot,'分析图');self.charts.addTab(self.matrix,'所选结果混淆矩阵');self.charts.addTab(self.classes,'所选结果类别召回')
        layout.addWidget(self.charts,3)
        self.rows=W.QTableWidget();self.rows.setEditTriggers(W.QAbstractItemView.NoEditTriggers);self.rows.setSelectionBehavior(W.QAbstractItemView.SelectRows);self.rows.setSelectionMode(W.QAbstractItemView.SingleSelection)
        self.rows.setMaximumHeight(145);self.rows.itemSelectionChanged.connect(self.select_row);layout.addWidget(self.rows,1)
        row=W.QHBoxLayout();self.records=W.QComboBox();self.records.setMinimumWidth(180);row.addWidget(self.records,1)
        load=W.QPushButton('查看分析记录');load.clicked.connect(self.load_record);row.addWidget(load)
        self.apply=W.QPushButton('将所选候选写入下次训练设置');self.apply.clicked.connect(self.apply_candidate);self.apply.setVisible(kind!='learning');self.apply.setEnabled(False);row.addWidget(self.apply);layout.addLayout(row)
        self.status=W.QLabel('尚未生成分析。');self.status.setWordWrap(True);layout.addWidget(self.status)
        warning=W.QLabel('开发调参诊断；最高点不是独立测试成绩。重复阴影为min–max，非置信区间。按实验留一不等同未见随机配置验证。');warning.setWordWrap(True);warning.setObjectName('muted');layout.addWidget(warning)
        for edit in (self.cs,self.weights,self.sizes,self.seeds):edit.textChanged.connect(self.refresh_estimate)
        self.mode.currentIndexChanged.connect(self.refresh_estimate)

    def set_source(self,store,task,model,bundle):
        key=(str(store.root),task['id'],model['id'])
        if self.source and self.source[0]==key:return
        self.source=(key,store,task,model,bundle)
        self.result=None;self.folder=None;self.apply.setEnabled(False);self.rows.setRowCount(0)
        self.plot.empty('点击生成分析，或查看已保存的分析记录')
        self.matrix.empty('选择一行分析结果');self.classes.empty('选择一行分析结果')
        c=asdict(Candidate(**bundle['candidate']));self.center.setValue(c['C'])
        self.sizes.setText(', '.join(map(str,default_sizes(task['run_count'],model['family']))))
        self.origin.setText(f"{task['name']} / {model['name']} · {task['run_count']}次实验\n固定项（参数验证）：核={c['kernel']}，gamma={c['gamma']}，C={c['C']}，权重={c['weight']}，表示={c['amplitude']}/{c['direction']}，EMA={bundle['feature_config']['alpha']}。学习曲线沿用原任务候选范围并在训练侧选参。")
        supported=len(bundle['labels'])==7 and 'config' in task and 'source_fingerprint' in task
        self.generate.setEnabled(supported and not self.busy)
        self.refresh_records();self.refresh_estimate()
        if not supported:self.status.setText('历史五类模型仅支持查看投影，不能进行七笔分析。')

    def config(self):
        kind='learning' if self.kind=='learning' else self.mode.currentData()
        sizes=tuple(int(v.strip()) for v in self.sizes.text().replace('，',',').split(',') if v.strip()) if kind=='learning' else ()
        seeds=tuple(int(v.strip()) for v in self.seeds.text().replace('，',',').split(',') if v.strip())
        return AnalysisConfig(kind=kind,sizes=sizes,seeds=seeds,cs=positive_values(self.cs.text()),weights=positive_values(self.weights.text()))

    def training_config(self):
        values=dict(self.source[2]['config']);values['feature_config']=FeatureConfig(**values['feature_config'])
        return TrainConfig(**values)

    def estimate(self):
        if not self.source:raise ValueError('请先选择模型')
        return estimate_fits(self.source[2]['run_count'],self.training_config(),Candidate(**self.source[3]['candidate']),self.config())

    def refresh_estimate(self,*args):
        if not self.source:return
        try:
            count=self.estimate()
            extra='；F3单次拟合还包含分支校准' if self.source[3]['family']=='F3' else ''
            self.estimate_label.setText(f'预计最多 {count:,} 次模型拟合（不计缓存复用{extra}）。参数更改只影响下次运行。')
        except (ValueError,TypeError,KeyError) as exc:self.estimate_label.setText(str(exc))

    def generate_nearby(self):
        self.cs.setText(', '.join(format(v,'.9g') for v in nearby_values(self.center.value())))
        self.status.setText('已生成C候选供预览，可继续修改；尚未运行分析。')

    def start(self):
        if self.busy or not self.source:return
        try:
            if hasattr(self,'start_allowed') and not self.start_allowed():raise ValueError('请等待其他训练或分析任务结束')
            cfg=self.config();self.estimate()
            key,store,task,model,bundle=self.source
            if len(bundle['labels'])!=7:raise ValueError('分析需要七类模型')
            identifier=uuid.uuid4().hex
            request=dict(root=str(store.root),task_id=task['id'],model_id=model['id'],analysis_id=identifier,
                source_fingerprint=task['source_fingerprint'],analysis=asdict(cfg))
            self.request=store.root/'analysis_requests'/f'{identifier}.json';write_json(self.request,request)
            self.active_folder=store.task_path(task['id'])/'analyses'/identifier;self.active_source=key
            self.result=None;self.folder=None;self.apply.setEnabled(False);self.rows.setRowCount(0)
            self.set_busy(True);self.status.setText('正在核验来源并生成分析…');self.job.start(self.request)
        except Exception as exc:self.status.setText(str(exc))

    def set_busy(self,busy):
        self.busy=busy;self.settings.setEnabled(not busy);self.cancel_button.setEnabled(busy)
        self.generate.setEnabled(not busy and bool(self.source) and len(self.source[4]['labels'])==7)
        self.busyChanged.emit(busy)

    def cancel(self):
        if self.busy:self.cancel_button.setEnabled(False);self.status.setText('正在取消分析…');self.job.cancel()

    def on_progress(self,event):
        self.status.setText(event.get('message','正在分析…'))

    def on_finished(self,ok,message):
        self.set_busy(False)
        if not ok:
            # A forced kill cannot update the worker's status record itself.
            record=self.active_folder/'record.json'
            if record.exists():
                data=json.loads(record.read_text())
                if data['status'] in ('running','completed') and self.job.cancelled:
                    data['status']='cancelled';write_json(record,data)
            self.status.setText(message or '分析失败，请检查来源及配置');self.refresh_records();return
        if self.source and self.source[0]==self.active_source:
            self.load_path(self.active_folder);self.refresh_records()
        else:self.status.setText('分析已保存至原训练任务；当前模型已改变，请从原任务回看。')

    def refresh_records(self):
        self.records.clear()
        if not self.source:return
        _,store,task,model,_=self.source
        for path in sorted((store.task_path(task['id'])/'analyses').glob('*/record.json'),reverse=True):
            try:
                record=json.loads(path.read_text());kind=record['request']['analysis']['kind']
                if record['model_id']!=model['id'] or (kind=='learning')!=(self.kind=='learning'):continue
                if record['status']=='completed':self.records.addItem(record['created_at'][5:19].replace('T',' ')+' · '+KINDS[kind],str(path.parent))
            except (OSError,ValueError,KeyError):continue

    def load_record(self):
        if self.busy:return
        if self.records.currentData():
            try:self.load_path(Path(self.records.currentData()))
            except Exception as exc:self.status.setText('无法读取分析：'+str(exc))

    def load_path(self,path):
        result=json.loads((Path(path)/'results.json').read_text())
        record=json.loads((Path(path)/'record.json').read_text())
        if result.get('status')!='completed' or record['status']!='completed':raise ValueError('该分析未完成')
        if not self.source or result['task_id']!=self.source[2]['id'] or result['model_id']!=self.source[3]['id'] or result['source_fingerprint']!=self.source[2]['source_fingerprint']:raise ValueError('分析与当前模型来源不符')
        self.result=result;self.folder=Path(path)
        headers=['训练次数 / 种子','C','差分/融合权重','训练Macro-F1','留出Macro-F1','正确率','最差类召回','错分数']+list(LABELS)
        self.rows.setColumnCount(len(headers));self.rows.setHorizontalHeaderLabels(headers);self.rows.setRowCount(len(result['rows']))
        for i,row in enumerate(result['rows']):
            c=row['candidate'] or {};m=row['metrics']
            vals=[f"{row['size']} / {row['seed'] if row['seed'] is not None else '固定参数'}",c.get('C','内层选择'),c.get('weight','内层选择'),
                f"{row['training_macro_f1']:.2%}",f"{m['macro_f1']:.2%}",f"{m['accuracy']:.2%}",f"{m['worst_recall']:.2%}",m['errors']]+[f"{m['per_class'][l]['recall']:.2%}" for l in LABELS]
            for j,value in enumerate(vals):self.rows.setItem(i,j,W.QTableWidgetItem(str(value)))
        self.rows.resizeColumnsToContents();self.rows.selectRow(0);self.draw()
        self.status.setText(f"已完成 · {result['fits']:,}次实际拟合 · {result['elapsed_seconds']:.1f}秒 · 临时模型未加入历史列表")

    def select_row(self):
        if not self.result:return
        row=self.rows.currentRow()
        if row<0 or row>=len(self.result['rows']):return
        record=self.result['rows'][row];self.matrix.matrix(record['metrics']);self.classes.quality(record['metrics'])
        self.apply.setEnabled(record['candidate'] is not None and not self.busy)
        if record['candidate']:self.center.setValue(record['candidate']['C'])

    def apply_candidate(self):
        if self.busy or not self.result:return
        row=self.rows.currentRow()
        if row<0:return
        candidate=self.result['rows'][row]['candidate']
        if candidate:self.candidateChosen.emit(dict(candidate=candidate,train_config=self.result['train_config'],source_fingerprint=self.result['source_fingerprint']))

    def draw(self,*args):
        if not self.result:return
        ax=self.plot.axes();result=self.result;metric=self.metric.currentData();rows=result['rows']
        if result['kind']=='joint':
            cs=sorted(set(r['candidate']['C'] for r in rows));ws=sorted(set(r['candidate']['weight'] for r in rows));z=np.full((len(ws),len(cs)),np.nan)
            for r in rows:z[ws.index(r['candidate']['weight']),cs.index(r['candidate']['C'])]=r['metrics'][metric]
            ax.grid(False);im=ax.imshow(z,vmin=0,vmax=1,cmap='Blues',aspect='auto')
            ax.set_xticks(range(len(cs)),[f'{v:g}' for v in cs]);ax.set_yticks(range(len(ws)),[f'{v:g}' for v in ws]);ax.set_xlabel('C');ax.set_ylabel('F4差分权重')
            for yi,xi in np.ndindex(z.shape):ax.text(xi,yi,f'{z[yi,xi]:.2%}',ha='center',va='center',color='white' if z[yi,xi]>.55 else '#102030')
            colorbar=self.plot.figure.colorbar(im,ax=ax,shrink=.8);colorbar.ax.tick_params(colors=MUTED)
        else:
            key='size' if result['kind']=='learning' else 'C' if result['kind']=='C' else 'weight'
            get=lambda r:r['size'] if key=='size' else r['candidate'][key]
            xs=sorted(set(get(r) for r in rows));train=[];test=[];lo=[];hi=[]
            for x in xs:
                subset=[r for r in rows if get(r)==x];values=[r['metrics'][metric] for r in subset]
                train.append(np.mean([r['training_'+metric] for r in subset]));test.append(np.mean(values));lo.append(min(values));hi.append(max(values))
            ax.plot(xs,train,'o--',color=COLORS[1],label='训练回代');ax.plot(xs,test,'o-',color=COLORS[0],label='整次实验留出')
            if result['kind']=='learning':ax.fill_between(xs,lo,hi,color=COLORS[0],alpha=.18,label='重复min–max')
            if key=='C':ax.set_xscale('log')
            ax.set_xlabel('训练实验次数' if key=='size' else 'C（对数坐标）' if key=='C' else 'F4差分权重')
            ax.set_ylabel('正确率' if metric=='accuracy' else 'Macro-F1');ax.set_ylim(0,1.04)
            ax.legend(facecolor=PANEL,labelcolor=TEXT,edgecolor='none',prop={'family':FONT,'size':9})
        self.plot.finish(ax,KINDS[result['kind']]+' · 开发数据诊断')

    def export_result(self):
        if not self.result:return
        folder=W.QFileDialog.getExistingDirectory(self,'选择分析导出目录')
        if not folder:return
        try:
            target=Path(folder)/('analysis-'+self.folder.name);target.mkdir(exist_ok=True)
            for name in ('results.json','record.json','summary.csv'):shutil.copy2(self.folder/name,target/name)
            write_json(target/'config.json',self.result['request'])
            for name,plot in [('analysis',self.plot),('confusion',self.matrix),('class_recall',self.classes)]:
                for suffix in ('png','pdf'):plot.figure.savefig(target/f'{name}.{suffix}',dpi=180,facecolor=plot.figure.get_facecolor())
            self.status.setText('分析已导出：'+str(target))
        except Exception as exc:self.status.setText('导出失败：'+str(exc))
