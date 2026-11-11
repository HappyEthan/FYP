"""Read the training workbench's registry and freeze a verified model artifact."""
from dataclasses import dataclass
import hashlib
import io

import joblib
import numpy as np

from brushbot.stroke_classification import VERSION
from brushbot.stroke_classification.features import FeatureConfig


@dataclass(frozen=True)
class LoadedModel:
    task_id: str
    model_id: str
    name: str
    sha256: str
    blob: bytes
    bundle: dict
    metadata: dict
    config: FeatureConfig
    labels: tuple

    @property
    def token(self):
        return f'{self.task_id}/{self.model_id}/{self.sha256}'

    def summary(self):
        return dict(task_id=self.task_id, model_id=self.model_id, name=self.name,
                    sha256=self.sha256, token=self.token, labels=list(self.labels),
                    family=self.metadata.get('family',''),
                    feature_config=self.config.to_dict(), metrics=self.metadata.get('metrics', {}))


def load_model(store, task_id, model_id):
    task = store.metadata(task_id)
    if task.get('status') not in ('completed','partial'):
        raise ValueError('该训练记录尚未完成')
    item = next((m for m in task['models'] if m['id'] == model_id and not m.get('deleted')), None)
    if item is None:
        raise ValueError('模型不存在或已删除')
    path = store.model_path(task_id, model_id)/'bundle.joblib'
    # Verify the exact bytes later deserialized and archived, with no second file read.
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != item.get('bundle_sha256'):
        raise ValueError('模型文件校验失败，请恢复完整模型包')
    bundle = joblib.load(io.BytesIO(blob))
    if not isinstance(bundle, dict) or bundle.get('version') != VERSION:
        raise ValueError('模型处理链版本不兼容')
    config = FeatureConfig(**bundle['feature_config']).validate()
    labels = tuple(bundle['labels'])
    model = bundle['model']
    if not labels or len(set(labels)) != len(labels) or not all(isinstance(x,str) for x in labels):
        raise ValueError('模型类别定义无效')
    if not np.array_equal(model.classes_, np.arange(len(labels))):
        raise ValueError('模型类别映射不兼容')
    if model.candidate.family not in ('F0','F1','F2','F3','F4'):
        raise ValueError('模型类型不受支持')
    return LoadedModel(task_id, model_id, f"{task['name']} · {item.get('name', item['family'])}",
                       digest, blob, bundle, dict(item), config, labels)
