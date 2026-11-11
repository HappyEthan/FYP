"""Freeze variation provenance and verify exported execution before hardware use."""
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from .stroke_variation import ALGORITHM

INPUT_FILES=('strokeplan.npz','feedforward.json','settings.json','entry_profile.json','pi_profile.json',
             'editor_state.json','recipe.json','workspace_recipe.json','preflight.json','speed_adaptation.json','segment_target_audit.json')


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def write_variation_bundle(folder,frozen,arrays):
    folder=Path(folder);metadata=copy.deepcopy(frozen)
    if any(np.asarray(a).dtype.kind=='O' for a in arrays.values()):raise ValueError('随机审计数组不允许对象类型')
    np.savez(folder/'variation_arrays.npz',**arrays)
    metadata['arrays_sha256']=_hash(folder/'variation_arrays.npz')
    metadata['input_sha256']={n:_hash(folder/n) for n in INPUT_FILES if (folder/n).exists()}
    metadata['metadata_sha256']=_digest(metadata)
    (folder/'variation.json').write_text(json.dumps(metadata,ensure_ascii=False,allow_nan=False,indent=2)+'\n')


def validate_variation_bundle(folder,compiled):
    folder=Path(folder)
    try:
        entry=json.loads((folder/'entry_profile.json').read_text()) if (folder/'entry_profile.json').exists() else {}
        profiles=entry.get('stroke_profiles',[entry])
        has_field=any(p.get('magnetic_variation') is not None for p in profiles)
        state=json.loads((folder/'editor_state.json').read_text()) if (folder/'editor_state.json').exists() else {}
        random_state=state.get('random_variation') or {}
        has_variation=has_field or random_state.get('options',{}).get('enabled',False)
        meta_file=folder/'variation.json';array_file=folder/'variation_arrays.npz'
        if not has_variation and not meta_file.exists() and not array_file.exists():return None
        # XY-only variations have no magnetic field; the metadata still freezes their inputs.
        if not meta_file.exists() or not array_file.exists():raise ValueError('缺少随机变化冻结文件，请重新导出')
        metadata=json.loads(meta_file.read_text())
        if metadata.get('version')!=1 or metadata.get('algorithm')!=ALGORITHM:raise ValueError('不支持的随机变化版本，请重新导出')
        expected=metadata.pop('metadata_sha256',None)
        if _digest(metadata)!=expected:raise ValueError('随机变化元数据已改变，请重新导出')
        metadata['metadata_sha256']=expected
        if _hash(array_file)!=metadata['arrays_sha256']:raise ValueError('随机变化数组已改变，请重新导出')
        if not {'strokeplan.npz','feedforward.json','settings.json','entry_profile.json','pi_profile.json','editor_state.json'}<=metadata['input_sha256'].keys():
            raise ValueError('随机变化执行输入快照不完整')
        for name,checksum in metadata['input_sha256'].items():
            if name not in INPUT_FILES or _hash(folder/name)!=checksum:raise ValueError('随机变化执行输入不匹配：'+name)
        if _digest(metadata['source_snapshot'])!=metadata['source_digest'] or metadata['batch']['source_digest']!=metadata['source_digest']:
            raise ValueError('随机变化标准来源不匹配')
        actual_spec=copy.deepcopy(compiled['spec_snapshot'])
        actual_spec.pop('run_label',None)
        if _digest(actual_spec)!=_digest(metadata['execution_spec']) or _digest(compiled['setup_snapshot'])!=_digest(metadata['execution_setup']):
            raise ValueError('实际控制模式、反馈参数或现场设置与冻结配置不一致，请重新导出')
        order=metadata['execution_order']
        if len(profiles)!=len(order):raise ValueError('随机变化笔画顺序不匹配')
        for key,profile in zip(order,profiles):
            field=profile.get('magnetic_variation')
            if metadata['options']['magnetic_enabled']:
                if field is None or field['fields']!=metadata['batch']['stroke_fields'][key] or field['magnetic_scale']!=metadata['scales'][key]['magnetic']:
                    raise ValueError('冻结磁场与执行磁场不一致')
            elif field is not None:raise ValueError('磁变化已关闭，但执行配置仍携带磁场')
        with np.load(array_file,allow_pickle=False) as arrays:
            for name in ('t_s','s','phase','pose_m_rad','g_ref_uT','depth_ff_m'):
                saved=arrays['execution_'+name];actual=np.asarray(compiled[name])
                equal=np.array_equal(saved,actual,equal_nan=True) if saved.dtype.kind in 'fci' else np.array_equal(saved,actual)
                if not equal:raise ValueError('当前编译与冻结执行结果不同：'+name+'；请重新生成并导出')
        return metadata
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('随机变化冻结文件缺失或损坏，请重新导出') from exc
