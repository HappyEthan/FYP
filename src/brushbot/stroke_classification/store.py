"""Atomic task registry, full model bundles and reversible deletion. Inputs are never removed."""
from datetime import datetime
import json
import hashlib
from pathlib import Path,PurePosixPath
import re
import shutil
import uuid
import zipfile
import tempfile
from zoneinfo import ZoneInfo

import joblib
import numpy as np


def jsonable(value):
    if isinstance(value,np.ndarray): return value.tolist()
    if isinstance(value,np.generic): return value.item()
    if isinstance(value,Path): return str(value)
    raise TypeError(type(value).__name__)


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False,default=jsonable),encoding='utf-8')
        tmp.replace(path)
    finally: tmp.unlink(missing_ok=True)


class ModelStore:
    def __init__(self,root):
        self.root=Path(root).resolve()
        for name in ('tasks','trash'): (self.root/name).mkdir(parents=True,exist_ok=True)

    def task_path(self,task_id,*,deleted=False):
        if not re.fullmatch(r'[a-zA-Z0-9_-]+',str(task_id)): raise ValueError('无效训练记录ID')
        return self.root/('trash' if deleted else 'tasks')/task_id

    def metadata(self,task_id,*,deleted=False):
        return json.loads((self.task_path(task_id,deleted=deleted)/'task.json').read_text())

    def save(self,task):
        write_json(self.task_path(task['id'])/'task.json',task)

    def create_task(self,name,metadata):
        now=datetime.now(ZoneInfo('Asia/Shanghai'))
        task=dict(id=now.strftime('%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:8],name=name,
                  created_at=now.isoformat(),favorite=False,status='running',models=[],branches={},**metadata)
        self.save(task)
        return task

    def list_tasks(self,*,deleted=False):
        result=[]
        for path in (self.root/('trash' if deleted else 'tasks')).glob('*/task.json'):
            try:
                task=json.loads(path.read_text())
                if task['status'] in ('completed','partial') and (deleted or any(not m.get('deleted') for m in task['models'])):
                    result.append(task)
            except (OSError,ValueError,KeyError): continue
        return sorted(result,key=lambda t:(t.get('favorite',False),t['created_at']),reverse=True)

    def add_model(self,task,metadata,bundle):
        model=dict(id=uuid.uuid4().hex[:12],deleted=False,**metadata)
        folder=self.task_path(task['id'])/'models'/model['id'];folder.mkdir(parents=True)
        tmp=folder/'bundle.tmp'
        joblib.dump(bundle,tmp);tmp.replace(folder/'bundle.joblib')
        model['bundle_sha256']=hashlib.sha256((folder/'bundle.joblib').read_bytes()).hexdigest()
        task['models'].append(model);self.save(task)
        return model

    def complete(self,task):
        task['status']='completed' if all(v.get('status')=='completed' for v in task.get('branches',{}).values()) else 'partial'
        self.save(task)

    def model_path(self,task_id,model_id):
        task=self.metadata(task_id)
        if not any(m['id']==model_id and not m.get('deleted') for m in task['models']):
            raise ValueError('模型不存在或已删除')
        return self.task_path(task_id)/'models'/model_id

    def load_bundle(self,task_id,model_id):
        # Only this local registry is loaded; no arbitrary external pickle upload entry point.
        path=self.model_path(task_id,model_id)/'bundle.joblib'
        record=next(m for m in self.metadata(task_id)['models'] if m['id']==model_id)
        expected=record.get('bundle_sha256')
        if not expected or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('模型文件校验失败，请恢复完整模型包')
        return joblib.load(path)

    def rename(self,task_id,name,model_id=None):
        if not str(name).strip(): raise ValueError('名称不能为空')
        task=self.metadata(task_id)
        target=task if model_id is None else next(m for m in task['models'] if m['id']==model_id)
        target['name']=str(name).strip()[:120];self.save(task)

    def favorite(self,task_id,enabled):
        task=self.metadata(task_id);task['favorite']=bool(enabled);self.save(task)

    def delete(self,task_id,model_id=None):
        folder=self.task_path(task_id);task=self.metadata(task_id)
        if model_id is not None:
            model=next(m for m in task['models'] if m['id']==model_id and not m.get('deleted'))
            source=self.model_path(task_id,model_id)
            target=folder/'deleted_models'/model_id;target.parent.mkdir(exist_ok=True)
            source.rename(target);model['deleted']=True;self.save(task)
        if model_id is None or all(m.get('deleted') for m in task['models']):
            folder.rename(self.task_path(task_id,deleted=True))

    def restore(self,task_id,model_id=None):
        deleted=self.task_path(task_id,deleted=True)
        if deleted.exists(): deleted.rename(self.task_path(task_id))
        task=self.metadata(task_id);folder=self.task_path(task_id)
        for model in task['models']:
            if model.get('deleted') and (model_id is None or model['id']==model_id):
                if model.get('unavailable_in_package'):continue
                (folder/'deleted_models'/model['id']).rename(folder/'models'/model['id'])
                model['deleted']=False
        self.save(task)

    def export(self,task_id,target,model_id=None):
        folder=self.task_path(task_id);target=Path(target).resolve()
        if target.is_relative_to(folder): raise ValueError('导出文件请选择训练记录目录以外的位置')
        if model_id: self.model_path(task_id,model_id)
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob('*'):
                rel=p.relative_to(folder)
                if not p.is_file() or 'deleted_models' in rel.parts: continue
                if model_id and rel.parts[0]=='models' and rel.parts[1]!=model_id: continue
                z.write(p,rel)
        return target

    def import_package(self,path):
        from . import VERSION
        with zipfile.ZipFile(path) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)):raise ValueError('成果包含重复文件')
            if sum(i.file_size for i in archive.infolist())>2*1024**3:raise ValueError('成果包超过支持的大小')
            for name in names:
                p=PurePosixPath(name)
                if p.is_absolute() or '..' in p.parts or '\\' in name:raise ValueError('成果包路径非法')
            if 'task.json' not in names:raise ValueError('缺少训练记录')
            task=json.loads(archive.read('task.json'))
            if task.get('version')!=VERSION or task.get('status') not in ('completed','partial'):
                raise ValueError('不兼容或未完成的模型成果包')
            destination=self.task_path(task['id'])
            for model in task.get('models',[]):
                if not re.fullmatch(r'[a-zA-Z0-9_-]+',model['id']):raise ValueError('模型ID非法')
                if model.get('deleted'):
                    model['unavailable_in_package']=True;continue
                member=f"models/{model['id']}/bundle.joblib"
                if member not in names:
                    model['deleted']=True;model['unavailable_in_package']=True;continue
                if hashlib.sha256(archive.read(member)).hexdigest()!=model.get('bundle_sha256'):
                    raise ValueError('模型成果包校验失败')
            if not any(not m.get('deleted') for m in task.get('models',[])):raise ValueError('成果包没有可用模型')
            if destination.exists():
                existing=self.metadata(task['id'])
                if {m['id']:m.get('bundle_sha256') for m in existing['models']}!={m['id']:m.get('bundle_sha256') for m in task['models']}:
                    raise ValueError('相同训练ID存在不同内容，未覆盖现有模型')
                return existing
            with tempfile.TemporaryDirectory(prefix='import-',dir=self.root) as temporary:
                staging=Path(temporary)/'task';staging.mkdir()
                for name in names:
                    if name.endswith('/'):continue
                    target=staging/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
                write_json(staging/'task.json',task);staging.rename(destination)
        return task
