"""Reproducible writing variation on execution copies, never sensor readings.

The profile owns the fixed style. A separate seed owns one repetition. Hardware
execution only validates and applies the saved arrays; it never draws randomness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import uuid

import numpy as np

from brushbot.feedforward import lookup_depth_m

PROFILE_KEY = 'writing_variation'
LEVELS = {'none': 0., 'small': .5, 'medium': 1.}
ARRAYS = ('fixed_xy_mm', 'repeat_xy_mm', 'fixed_g_uT', 'repeat_g_uT')


def new_seed():
    return secrets.randbelow(2**31)


def preset_profiles():
    return [dict(version=1, id=key, revision=1, name=name, seed=seed,
                 bias_pct=bias, xy_limit_mm=.15, repeat_level='small')
            for key, name, seed, bias in [('light', '偏轻', 1101, -20.),
                                         ('medium', '中等', 1102, 0.),
                                         ('heavy', '偏重', 1103, 20.)]]


def default_config():
    return dict(enabled=False, xy_enabled=True, magnetic_enabled=True,
                profile=preset_profiles()[1])


def _integer(value, name, lower=0, upper=2**31-1):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{name}必须为 {lower}～{upper} 的整数')


def validate_profile(profile):
    keys = {'version', 'id', 'revision', 'name', 'seed', 'bias_pct',
            'xy_limit_mm', 'repeat_level'}
    if not isinstance(profile, dict) or set(profile) != keys:
        raise ValueError('书写配置字段不完整或版本不支持')
    _integer(profile['version'], '配置版本', 1, 1)
    _integer(profile['revision'], '配置修订号', 1)
    _integer(profile['seed'], '配置种子')
    for key in ('id', 'name'):
        if (not isinstance(profile[key], str) or not profile[key].strip()
                or len(profile[key]) > 120 or any(ord(c) < 32 for c in profile[key])):
            raise ValueError('配置名称与编号须为非空短文本')
    for key, lo, hi in [('bias_pct', -20., 20.), ('xy_limit_mm', 0., .15)]:
        value = profile[key]
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or not np.isfinite(value) or not lo <= value <= hi):
            raise ValueError(f'配置 {key} 须在 {lo}～{hi} 之间')
    if profile['repeat_level'] not in LEVELS:
        raise ValueError('每次变化程度须为无、小或中')
    return copy.deepcopy(profile)


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {
            'enabled', 'xy_enabled', 'magnetic_enabled', 'profile'}:
        raise ValueError('随机扰动设置字段不完整')
    for key in ('enabled', 'xy_enabled', 'magnetic_enabled'):
        if type(config[key]) is not bool:
            raise ValueError('随机扰动开关必须为布尔值')
    return dict(config, profile=validate_profile(config['profile']))


class ProfileStore:
    """Store latest profile versions; experiment snapshots retain older versions."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return preset_profiles()
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if set(data) != {'version', 'profiles'} or type(data['version']) is not int or data['version'] != 1:
                raise ValueError('配置库格式不支持')
            if not isinstance(data['profiles'], list) or not data['profiles']:
                raise ValueError('配置库不能为空')
            profiles = [validate_profile(p) for p in data['profiles']]
            if len({p['id'] for p in profiles}) != len(profiles):
                raise ValueError('配置编号重复')
            return profiles
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError('无法读取书写配置库：'+str(exc)) from exc

    def save(self, profile):
        profile = validate_profile(profile)
        profiles = self.load()
        index = next((i for i, p in enumerate(profiles) if p['id'] == profile['id']), None)
        if index is not None:
            current = profiles[index]
            if current == profile:
                return profile
            if current['revision'] != profile['revision']:
                raise ValueError('配置版本已变化，请重新载入或另存配置')
            profile['revision'] += 1
            profiles[index] = profile
        else:
            profiles.append(profile)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(dict(version=1, profiles=profiles), stream,
                          ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return copy.deepcopy(profile)


def _digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                      separators=(',', ':')).encode()).hexdigest()


def baseline_digest(compiled, nominal, table, setup, entry):
    h = hashlib.sha256()
    for key in ('t_s', 's', 'pose_m_rad', 'g_ref_uT'):
        array = np.asarray(compiled[key], dtype='<f8')
        h.update(str(array.shape).encode())
        h.update(array.tobytes())
    h.update(np.asarray(nominal, dtype='<f8').tobytes())
    h.update(_digest_json([compiled['phase'].tolist(), table, setup, entry]).encode())
    return h.hexdigest()


def _rng(seed, tag):
    value = hashlib.sha256(f'{seed}:{tag}'.encode()).digest()
    return np.random.Generator(np.random.PCG64(int.from_bytes(value[:16], 'little')))


def _ease(u):
    return u**3*(10+u*(-15+6*u))


def _noise(q, interval, rng, dimensions):
    result = np.zeros((len(q), dimensions))
    if len(q) < 5 or q[-1]-q[0] <= 1e-12:
        return result
    anchors = np.linspace(q[0], q[-1], max(3, int(np.ceil((q[-1]-q[0])/interval))+1))
    values = rng.normal(size=(len(anchors), dimensions))
    values[[0, -1]] = 0.
    k = np.clip(np.searchsorted(anchors, q, side='right')-1, 0, len(anchors)-2)
    u = np.clip((q-anchors[k])/(anchors[k+1]-anchors[k]), 0., 1.)
    result = values[k]+_ease(u)[:, None]*(values[k+1]-values[k])
    result[[0, 1, -2, -1]] = 0.
    return result


def _envelope(t):
    if len(t) < 5:
        return np.zeros(len(t))
    ramp = min(.25, (t[-2]-t[1])*.1)
    u = np.minimum(np.clip((t-t[1])/ramp, 0., 1.),
                   np.clip((t[-2]-t)/ramp, 0., 1.))
    return _ease(u)


def _xy_noise(q, interval, rng, std, envelope):
    xy = _noise(q, interval, rng, 2)*envelope[:, None]
    spread = np.std(xy, axis=0)
    xy *= np.divide(std, spread, out=np.zeros(2), where=spread > 1e-12)
    return xy


def _smooth_weight(base):
    # Smooth only the weight used to construct the addition, never the source.
    radius = 10  # 0.2 s on the 20 ms execution grid
    u = np.arange(-radius, radius+1)/(radius+1)
    kernel = (1-u*u)**3
    kernel /= kernel.sum()
    values = np.convolve(np.pad(base, radius, mode='edge'), kernel, mode='valid')
    positive = values > 1e-12
    if positive.any():
        values *= min(1., float(np.min(base[positive]/values[positive])))
    return values


def shape_metrics(reference, actual):
    spread = float(np.std(reference))
    if spread < 1e-8:
        return dict(correlation=None, normalized_rmse=None,
                    peak_shift_fraction=None, trough_shift_fraction=None)
    other = float(np.std(actual))
    result = dict(correlation=float(np.corrcoef(reference, actual)[0, 1]) if other > 1e-8 else 0.,
                  normalized_rmse=float(np.sqrt(np.mean(((reference-reference.mean())/spread
                    -(actual-actual.mean())/max(other, 1e-8))**2))))
    dynamic = float(np.ptp(reference))
    for label, sign in [('peak', 1), ('trough', -1)]:
        signal = reference*sign
        near = np.flatnonzero(signal >= signal.max()-.01*dynamic)
        shift = None
        if (near[-1]-near[0])/max(1, len(reference)-1) <= .02:
            shift = float(np.min(abs(near-int(np.argmax(actual*sign))))/max(1, len(reference)-1))
        result[label+'_shift_fraction'] = shift
    return result


def _masks(compiled):
    names = sorted({str(p) for p in compiled['phase'] if str(p).startswith('measure_')})
    if not names:
        raise ValueError('随机扰动没有可用的完整书写阶段')
    return [(name, compiled['phase'] == name) for name in names]


def _seal(snapshot):
    snapshot['realization_sha256'] = _digest_json({k: v for k, v in snapshot.items()
                                                  if k != 'realization_sha256'})


def _motion_error(exc):
    from brushbot.experiments.z_identification import TrajectoryLimitError
    return isinstance(exc, TrajectoryLimitError) or any(text in str(exc) for text in (
        'workspace limit', 'depth limit', '书写速度', '纸面高度'))


def _scale_rows(snapshot, keys, factor):
    for row in snapshot['strokes']:
        for key in keys:
            row[key] = (np.asarray(row[key])*factor).tolist()


def _component_snapshot(snapshot, component):
    """Check each variable against the standard, independently of its sibling."""
    result = copy.deepcopy(snapshot)
    if component == 'xy':
        result['config']['magnetic_enabled'] = False
        _scale_rows(result, ['fixed_g_uT', 'repeat_g_uT'], 0.)
    else:
        result['config']['xy_enabled'] = False
        _scale_rows(result, ['fixed_xy_mm', 'repeat_xy_mm'], 0.)
    _seal(result)
    return result


def generate(compiled, nominal, table, setup, entry, config, repeat_seed):
    config = validate_config(config)
    _integer(repeat_seed, '本次种子')
    if not config['enabled']:
        raise ValueError('关闭随机扰动时应直接使用标准流程')
    profile = config['profile']
    level = LEVELS[profile['repeat_level']]
    limit = profile['xy_limit_mm']
    run_gain = _rng(repeat_seed, 'run_gain').uniform(-.01, .01)*level
    snapshot = dict(version=1, config=config, repeat_seed=repeat_seed,
                    baseline_sha256=baseline_digest(compiled, nominal, table, setup, entry), strokes=[])
    desired_repeat = []
    for name, mask in _masks(compiled):
        t = compiled['t_s'][mask]
        if len(t) < 2 or not np.allclose(np.diff(t), .02, atol=1e-9, rtol=0):
            raise ValueError('随机扰动要求 20 ms 书写网格')
        t = t-t[0]
        q = compiled['s'][mask]
        base = compiled['g_ref_uT'][mask]
        geometry = hashlib.sha256(np.asarray(compiled['pose_m_rad'][mask, :2], dtype='<f8').tobytes()).hexdigest()
        envelope = _envelope(t)
        fixed_xy = _xy_noise(q, .15, _rng(profile['seed'], geometry+':fixed_xy'),
                             .04*limit/.15, envelope)
        maximum = float(np.linalg.norm(fixed_xy, axis=1).max())
        if maximum > limit:
            fixed_xy *= limit/maximum
        repeat_xy = _xy_noise(t, .5, _rng(repeat_seed, name+':repeat_xy'),
                              .02*limit/.15*level, envelope)
        weight = _smooth_weight(base)
        fixed_g = profile['bias_pct']/100*weight*envelope
        stroke_gain = _rng(repeat_seed, name+':stroke_gain').uniform(-.01, .01)*level
        local = _noise(t, .8, _rng(repeat_seed, name+':local_g'), 1)[:, 0]
        local /= max(1., float(abs(local).max()))
        repeat_g = ((run_gain+stroke_gain)*weight
                    +local*np.minimum(.01*base, 2.)*level)*envelope
        if not config['xy_enabled']:
            fixed_xy[:] = 0.
            repeat_xy[:] = 0.
        if not config['magnetic_enabled']:
            fixed_g[:] = 0.
            repeat_g[:] = 0.
        snapshot['strokes'].append(dict(phase=name, fixed_xy_mm=fixed_xy.tolist(),
            repeat_xy_mm=np.zeros_like(repeat_xy).tolist(), fixed_g_uT=fixed_g.tolist(),
            repeat_g_uT=np.zeros_like(repeat_g).tolist(), fixed_xy_scale=1.,
            repeat_xy_scale=1., repeat_magnetic_scale=1.))
        desired_repeat.append((repeat_xy, repeat_g))

    # Establish that the requested fixed magnetic tendency itself is compatible.
    try:
        apply(compiled, nominal, table, setup, entry, _component_snapshot(snapshot, 'magnetic'))
    except ValueError as exc:
        raise ValueError('固定轻重配置与当前笔画不兼容，请调整整体轻重：'+str(exc)) from exc
    for attempt in range(14):
        try:
            apply(compiled, nominal, table, setup, entry, _component_snapshot(snapshot, 'xy'))
            break
        except ValueError as exc:
            if not _motion_error(exc) or attempt == 13:
                raise ValueError('固定路径偏差未通过预检：'+str(exc)) from exc
            _scale_rows(snapshot, ['fixed_xy_mm'], .5)
            for row in snapshot['strokes']:
                row['fixed_xy_scale'] *= .5

    # Each repetition component has its own reduction. A radial XY limit must
    # never reduce a magnetic draw (or change a single-factor comparison).
    for row, (xy, delta) in zip(snapshot['strokes'], desired_repeat):
        row['repeat_xy_mm'], row['repeat_g_uT'] = xy.tolist(), delta.tolist()
    for component, key, scale_key in [('xy', 'repeat_xy_mm', 'repeat_xy_scale'),
                                       ('magnetic', 'repeat_g_uT', 'repeat_magnetic_scale')]:
        for attempt in range(15):
            try:
                apply(compiled, nominal, table, setup, entry, _component_snapshot(snapshot, component))
                break
            except ValueError:
                if attempt == 14:
                    raise
                factor = 0. if attempt == 13 else .5
                _scale_rows(snapshot, [key], factor)
                for row in snapshot['strokes']:
                    row[scale_key] *= factor
    _seal(snapshot)
    try:
        apply(compiled, nominal, table, setup, entry, snapshot)
    except ValueError as exc:
        # Coupled XYZ motion can be infeasible even if each factor is valid.
        # Reject it explicitly instead of silently changing the other factor.
        raise ValueError('路径与磁目标组合未通过预检，请减小偏差或每次变化程度：'+str(exc)) from exc
    for row, (_, mask) in zip(snapshot['strokes'], _masks(compiled)):
        xy = np.asarray(row['fixed_xy_mm'])+np.asarray(row['repeat_xy_mm'])
        delta = np.asarray(row['fixed_g_uT'])+np.asarray(row['repeat_g_uT'])
        base = compiled['g_ref_uT'][mask]
        row['report'] = dict(xy_max_mm=float(np.linalg.norm(xy, axis=1).max()),
                            magnetic_max_uT=float(abs(delta).max()),
                            fixed_xy_scale=row['fixed_xy_scale'], repeat_xy_scale=row['repeat_xy_scale'],
                            repeat_magnetic_scale=row['repeat_magnetic_scale'],
                            **shape_metrics(base, base+delta))
    _seal(snapshot)
    return snapshot


def apply(compiled, nominal, table, setup, entry, snapshot):
    """Validate and apply frozen arrays. No seed or RNG is consulted here."""
    from brushbot.experiments.z_identification import _check_trajectory
    if not isinstance(snapshot, dict) or type(snapshot.get('version')) is not int or snapshot['version'] != 1:
        raise ValueError('随机结果快照版本不支持')
    config = validate_config(snapshot.get('config'))
    _integer(snapshot.get('repeat_seed'), '本次种子')
    if not config['enabled']:
        raise ValueError('关闭随机扰动时不能应用执行快照')
    if snapshot.get('baseline_sha256') != baseline_digest(compiled, nominal, table, setup, entry):
        raise ValueError('随机快照与标准输入不匹配，请重新预检')
    masks = _masks(compiled)
    rows = snapshot.get('strokes')
    if not isinstance(rows, list) or len(rows) != len(masks):
        raise ValueError('随机快照笔画数量不匹配')
    profile = config['profile']
    level, limit = LEVELS[profile['repeat_level']], profile['xy_limit_mm']
    poses, targets = compiled['pose_m_rad'].copy(), compiled['g_ref_uT'].copy()
    for row, (name, mask) in zip(rows, masks):
        if row.get('phase') != name:
            raise ValueError('随机快照笔画顺序不匹配')
        try:
            fx, rx, fg, rg = [np.asarray(row[key], dtype=float) for key in ARRAYS]
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError('随机快照数组格式不合法') from exc
        count = int(mask.sum())
        if (fx.shape != (count, 2) or rx.shape != fx.shape or fg.shape != (count,)
                or rg.shape != fg.shape or not all(np.isfinite(v).all() for v in (fx, rx, fg, rg))):
            raise ValueError('随机快照数组数量或数值不合法')
        edges = list(range(count)) if count < 5 else [0, 1, count-2, count-1]
        if any(np.any(values[edges] != 0) for values in (fx, rx, fg, rg)):
            raise ValueError('附加量首尾位置与速度必须为零')
        if (np.linalg.norm(fx+rx, axis=1).max() > limit+1e-9
                or np.linalg.norm(fx, axis=1).max() > limit+1e-9
                or np.any(np.std(fx, axis=0) > .04*limit/.15+1e-9)
                or np.any(np.std(rx, axis=0) > .02*limit/.15*level+1e-9)):
            raise ValueError('路径偏差超过配置上限')
        if not config['xy_enabled'] and (fx.any() or rx.any()):
            raise ValueError('路径扰动关闭时不能有 XY 附加量')
        if not level and (rx.any() or rg.any()):
            raise ValueError('每次变化为无时不能有本次附加量')
        base = targets[mask]
        if (np.any(abs(fg) > abs(profile['bias_pct'])/100*base+1e-9)
                or np.any(fg*profile['bias_pct'] < -1e-9)
                or np.any(abs(rg) > (.02*base+np.minimum(.01*base, 2.))*level+1e-9)):
            raise ValueError('磁目标附加量超过配置变化范围')
        if not config['magnetic_enabled'] and (fg.any() or rg.any()):
            raise ValueError('磁扰动关闭时不能有磁附加量')
        delta = fg+rg
        varied = base+delta
        metrics = shape_metrics(base, varied)
        if metrics['correlation'] is not None and metrics['correlation'] < .98:
            raise ValueError('磁目标形状相关系数低于 0.98')
        if any(metrics[key] is not None and metrics[key] > .02 for key in (
                'peak_shift_fraction', 'trough_shift_fraction')):
            raise ValueError('磁目标主要峰谷位置变化超过 2%')
        if delta.any():
            try:
                lookup_depth_m(table, varied)
                poses[mask, 2] -= lookup_depth_m(table, nominal[mask]+delta)-lookup_depth_m(table, nominal[mask])
            except ValueError as exc:
                raise ValueError('磁目标超出当前允许的前馈范围：'+str(exc)) from exc
        poses[mask, :2] += (fx+rx)/1000
        targets[mask] = varied
        if (np.linalg.norm(np.diff(poses[mask, :2], axis=0), axis=1)/.02*1000).max() > table['speed_mm_s']+1e-6:
            raise ValueError('书写速度超过当前前馈表支持范围')
        if np.any(poses[mask, 2] > setup['contact_z_mm']/1000+1e-9):
            raise ValueError('磁目标叠加已有提笔量后超过纸面高度')
    if snapshot.get('realization_sha256') != _digest_json({k: v for k, v in snapshot.items()
                                                         if k != 'realization_sha256'}):
        raise ValueError('随机快照完整性校验失败')
    return poses, targets, _check_trajectory(poses, setup, entry)
