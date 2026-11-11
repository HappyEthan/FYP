"""Qt import threads and isolated training process protocol."""
import json
import os
import signal
from pathlib import Path
import sys
import traceback
from PyQt5 import QtCore

from .features import FeatureConfig
from .training import TrainConfig,train
from .data import load_experiment


class ImportThread(QtCore.QThread):
    imported=QtCore.pyqtSignal(object,object)

    def __init__(self,paths,config,parent=None,expected_count=7):
        super().__init__(parent);self.paths=paths;self.config=config;self.expected_count=expected_count

    def run(self):
        records=[];errors=[]
        for path in self.paths:
            if self.isInterruptionRequested(): break
            try:
                counts=self.expected_count if isinstance(self.expected_count,tuple) else (self.expected_count,)
                last=None
                for count in counts:
                    try:
                        records.append(load_experiment(path,self.config,expected_count=count));last=None;break
                    except Exception as exc:last=exc
                if last:raise last
            except Exception as exc: errors.append(dict(path=str(path),message=str(exc)))
        self.imported.emit(records,errors)


class TrainingProcess(QtCore.QObject):
    progressed=QtCore.pyqtSignal(object)
    finished=QtCore.pyqtSignal(bool,str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process=QtCore.QProcess(self);self.buffer=b'';self.errors=b'';self.cancelled=False;self.generation=0
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.done)
        self.process.errorOccurred.connect(self.process_error)

    def start(self,request):
        self.generation+=1;self.cancelled=False;self.buffer=b'';self.errors=b''
        program,arguments=self.command(request)
        self.process.setProgram(program);self.process.setArguments(arguments);self.process.start()

    def command(self,request):
        script=Path(__file__).resolve().parents[3]/'scripts/train_stroke_classifier.py'
        return sys.executable,['-u',str(script),'--worker',str(request)]

    def read_stdout(self):
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try: self.progressed.emit(json.loads(line))
            except ValueError: pass

    def read_stderr(self): self.errors+=bytes(self.process.readAllStandardError())

    def process_error(self,error):
        if error==QtCore.QProcess.FailedToStart:
            self.finished.emit(False,'无法启动训练进程：'+self.process.errorString())

    def cancel(self):
        self.cancelled=True
        self.process.terminate()
        generation=self.generation
        QtCore.QTimer.singleShot(1200,lambda:self.kill_if_running() if self.generation==generation else None)

    def kill_if_running(self):
        if self.process.state()!=QtCore.QProcess.NotRunning:self.process.kill()

    def done(self,code,status):
        self.read_stdout();self.read_stderr()
        message='训练已取消；未完成任务不进入成功模型历史' if self.cancelled else self.errors.decode('utf-8',errors='replace')[-3000:]
        self.finished.emit(code==0 and not self.cancelled,message)


class AnalysisProcess(TrainingProcess):
    def command(self,request):
        script=Path(__file__).resolve().parents[3]/'scripts/train_stroke_classifier.py'
        return sys.executable,['-u',str(script),'--analysis-worker',str(request)]

    def done(self,code,status):
        self.read_stdout();self.read_stderr()
        message='分析已取消' if self.cancelled else self.errors.decode('utf-8',errors='replace')[-3000:]
        self.finished.emit(code==0 and not self.cancelled,message)


def analysis_worker(path):
    from .analysis import execute_request
    cancelled=False
    def request_cancel(signum,frame):
        nonlocal cancelled
        cancelled=True
    signal.signal(signal.SIGTERM,request_cancel)
    try:
        folder=execute_request(path,progress=lambda e:print(json.dumps(e,ensure_ascii=False),flush=True),cancel=lambda:cancelled)
        print(json.dumps(dict(stage='result',folder=str(folder),message='分析结果已保存'),ensure_ascii=False),flush=True)
        return 0
    except Exception:
        traceback.print_exc();return 1


def worker(path):
    request=json.loads(Path(path).read_text())
    values=request['config'];values['feature_config']=FeatureConfig(**values['feature_config'])
    config=TrainConfig(**values)
    cancelled=False
    def request_cancel(signum,frame):
        nonlocal cancelled
        cancelled=True
    signal.signal(signal.SIGTERM,request_cancel)
    try:
        data=[load_experiment(p,config.feature_config) for p in request['paths']]
        # Verify input snapshot before starting any fitted model.
        actual=[(e.run_id,e.source_hash) for e in data]
        expected=[tuple(s) for s in request['sources']]
        if actual!=expected: raise ValueError('实验文件在提交后发生变化，请重新导入')
        task=train(data,config,request['root'],progress=lambda e:print(json.dumps(e,ensure_ascii=False),flush=True),
                   cancel=lambda:cancelled,name=request['name'])
        print(json.dumps(dict(stage='result',task_id=task['id'],message='结果已保存'),ensure_ascii=False),flush=True)
        return 0
    except Exception:
        traceback.print_exc();return 1
