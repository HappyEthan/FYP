"""Read editable strokes and merge copies into a workspace without hardware access."""
import copy
import json
from pathlib import Path
import uuid

import numpy as np


CONFIG_FILES = ('feedforward.json', 'settings.json', 'entry_profile.json', 'pi_profile.json')
LOCAL_ENTRY_KEYS = {'writing_tilt_deg', 'entry_reverse_mm', 'segment_magnetic_targets',
                    'writing_height', 'magnetic_variation'}


def stroke_models(model):
    from scripts.brush_path_editor_model import PathModel
    states = {s['stroke_id']: s for s in model.other_strokes}
    states[model.stroke_id] = model.state(False)
    return [PathModel.from_state(states[key]) for key in model.stroke_order]


def load_stroke_source(path):
    """Prefer the selected bundle's frozen files over historical absolute paths."""
    from scripts.brush_path_editor_model import PathModel, CONTEXT
    path = Path(path).resolve()
    if not path.exists():
        raise FileNotFoundError(f'笔画来源不存在：{path}')
    folder = path if path.is_dir() else path.parent
    state_path = path if path.is_file() and path.name != 'recipe.json' else folder/'editor_state.json'
    model = PathModel.restore(state_path) if state_path.is_file() else PathModel(folder)
    models = stroke_models(model)
    for index, item in enumerate(models):
        settings = {}
        overrides = {'feedforward.json': item.feedforward_override,
                     'settings.json': item.settings_override,
                     'entry_profile.json': item.entry_profile_override}
        for name in CONFIG_FILES:
            local = folder/name
            per_stroke = folder/'stroke_settings'/item.stroke_id/name
            if per_stroke.is_file():
                local = per_stroke
            snapshot = item.settings_snapshot or {}
            if local.is_file():
                settings[name] = json.loads(local.read_text())
            elif name in snapshot:
                settings[name] = copy.deepcopy(snapshot[name])
            else:
                historical = Path(overrides[name]) if overrides.get(name) else item.folder/name
                # Match the legacy editor's default for recipes without bundled settings.
                if not historical.is_file() and not overrides.get(name):
                    historical = CONTEXT/name
                settings[name] = json.loads(historical.read_text())
        entry = settings['entry_profile.json']
        profiles = entry.pop('stroke_profiles', None)
        if profiles is not None:
            if len(profiles) != len(models):
                raise ValueError('来源进笔配置与笔画数量不匹配')
            for key in LOCAL_ENTRY_KEYS:
                entry.pop(key, None)
            entry.update(copy.deepcopy(profiles[index]))
            entry.pop('node_angles', None)
        item.folder = folder
        item.settings_snapshot = settings
        item.feedforward_override = item.settings_override = item.entry_profile_override = None
    active = next(item for item in models if item.stroke_id == model.stroke_id)
    active.other_strokes = [item.state(False) for item in models if item.stroke_id != active.stroke_id]
    active.stroke_order = model.stroke_order.copy()
    active.pending_point = copy.deepcopy(model.pending_point)
    active.pending_stroke_position = model.pending_stroke_position
    return active


def placement_transform(model):
    placement = model.base['placement']
    angle = np.deg2rad(float(placement['rotation_deg']))
    scale = float(placement['scale'])
    origin = np.asarray(placement['origin_mm'], float)
    if not np.isfinite([angle, scale, *origin]).all() or scale <= 0 or origin.shape != (2,):
        raise ValueError('来源位置、旋转和缩放必须是有效数值')
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    return origin, rotation, scale


def paper_points(model, points=None):
    origin, rotation, scale = placement_transform(model)
    return (model.points() if points is None else points) @ rotation.T * scale + origin


def configuration_differences(target, source):
    """List shared configuration fields the current workspace will supply."""
    current = stroke_models(target)[0].settings()
    rows = []
    for item in stroke_models(source):
        for name, values in item.settings().items():
            for key in sorted(set(values) | set(current[name])):
                if name == 'entry_profile.json' and key in LOCAL_ENTRY_KEYS | {'stroke_profiles'}:
                    continue
                if values.get(key) != current[name].get(key):
                    rows.append(f'{item.stroke_name}：{name} / {key}')
    return rows


def import_strokes(target, source, *, stroke_ids=None, side='right', gap_mm=10., offset_mm=(0., 0.)):
    from scripts.brush_path_editor_model import PathModel
    if target.pending_point is not None:
        raise ValueError('请先添加第二个点完成新笔画，或取消独立起点')
    if not isinstance(source, PathModel):
        source = load_stroke_source(source)
    if source.pending_point is not None:
        raise ValueError('来源笔画缺少第二个点，请先完成或取消独立起点')
    selected = source.stroke_order if stroke_ids is None else list(stroke_ids)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(source.stroke_order):
        raise ValueError('请至少选择一笔有效且不重复的来源笔画')
    offset = np.asarray(offset_mm, float)
    if side not in ('right', 'left', 'original') or not np.isfinite(gap_mm) or gap_mm < 0:
        raise ValueError('导入位置须为左侧、右侧或原位，间距须为非负有限数值')
    if offset.shape != (2,) or not np.isfinite(offset).all():
        raise ValueError('导入偏移须为有限的 X/Y 数值')
    imported = [item for item in stroke_models(source) if item.stroke_id in selected]
    current = stroke_models(target)
    existing_points = np.vstack([paper_points(item) for item in current])
    incoming_points = np.vstack([paper_points(item) for item in imported])
    delta = offset.copy()
    if side != 'original':
        delta[0] += (existing_points[:, 0].max() + gap_mm - incoming_points[:, 0].min()
                     if side == 'right' else existing_points[:, 0].min() - gap_mm - incoming_points[:, 0].max())
        delta[1] += (existing_points[:, 1].min() + existing_points[:, 1].max()
                     - incoming_points[:, 1].min() - incoming_points[:, 1].max()) / 2
    origin, rotation, scale = placement_transform(target)
    shared = current[0].settings()
    additions = []
    for item in imported:
        source_settings = item.settings()
        original_id = item.stroke_id
        item.import_source = dict(path=str(source.folder), stroke_id=original_id,
                                  settings=copy.deepcopy(source_settings), offset_mm=delta.tolist())
        item.original = (paper_points(item, item.original) + delta - origin) @ rotation / scale
        item.nodes = (paper_points(item, item.nodes) + delta - origin) @ rotation / scale
        item.base['path']['points_mm'] = item.original.tolist()
        item.base['placement'] = copy.deepcopy(target.base['placement'])
        item.stroke_id = 'stroke-' + uuid.uuid4().hex
        item.stroke_order = [item.stroke_id]
        item.settings_snapshot = copy.deepcopy(shared)
        entry = item.settings_snapshot['entry_profile.json']
        for key in LOCAL_ENTRY_KEYS | {'stroke_profiles'}:
            entry.pop(key, None)
        entry.update({key: copy.deepcopy(value) for key, value in source_settings['entry_profile.json'].items()
                      if key in LOCAL_ENTRY_KEYS and key != 'magnetic_variation'})
        item.feedforward_override = item.settings_override = item.entry_profile_override = None
        item.validate()
        from scripts.generate_strokeplan_from_json import build_plan
        build_plan(item.recipe())  # Reject invalid recipes before mutating the target.
        additions.append(item.state(False))
    ids = [state['stroke_id'] for state in additions]
    # All reads, validation and coordinate conversion finish before a single mutation.
    target.other_strokes = target.other_strokes + additions
    target.stroke_order = target.stroke_order + ids
    return ids
