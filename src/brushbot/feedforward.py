"""Independent measured response-to-depth configuration; no robot I/O."""
import numpy as np
from brushbot.target_strokeplan import FEATURE

CONTEXT_KEYS = ('vertical_rpy_rad', 'filter', 'installation_id', 'sensor_mount_id',
                'tcp_name', 'ucs_name', 'tool_coord_si', 'user_coord_si', 'contact_z_mm')


def validate_table(table):
    try:
        a, d = (np.asarray(table[k], float) for k in ('amplitude_uT','depth_mm'))
        if (a.ndim != 1 or len(a) < 2 or d.shape != a.shape
                or not np.isfinite(np.r_[a,d]).all() or np.any(a < 0) or np.any(d < 0)
                or np.any(np.diff(a) <= 0) or np.any(np.diff(d) <= 0)):
            raise ValueError('table must be finite, nonnegative and strictly increasing')
        if (table['version'] != 1 or table['feature'] != FEATURE
                or type(table['approved']) is not bool
                or type(table['transient_approved']) is not bool
                or not table['calibration_id'] or not table['source_runs']
                or table['directions'] != ['+x']
                or not np.isfinite(table['speed_mm_s']) or table['speed_mm_s'] != 10.):
            raise ValueError('unsupported or invalid table context')
        ctx = table['context']
        if any(k not in ctx for k in CONTEXT_KEYS):
            raise ValueError('incomplete calibration context')
        for key, size in [('vertical_rpy_rad',3),('tool_coord_si',6),('user_coord_si',6)]:
            v=np.asarray(ctx[key],float)
            if v.shape != (size,) or not np.isfinite(v).all():
                raise ValueError(f'invalid {key}')
        if not np.isfinite(ctx['contact_z_mm']) or not isinstance(ctx['filter'],dict):
            raise ValueError('invalid calibration contact/filter')
    except (KeyError, TypeError) as exc:
        raise ValueError('incomplete feedforward configuration') from exc


def lookup_depth_m(table, g_target):
    validate_table(table)
    g=np.asarray(g_target,float)
    a=np.asarray(table['amplitude_uT'],float)
    if not g.size or not np.isfinite(g).all() or np.any(g < a[0]) or np.any(g > a[-1]):
        raise ValueError('target outside measured range; extrapolation disabled')
    return np.interp(g,a,table['depth_mm'])/1000.


def validate_context(plan, table, settings):
    validate_table(table)
    if plan.meta['feature'] != table['feature'] or plan.meta['filter_definition'] != table['context']['filter']:
        raise ValueError('target feature/filter differs from calibration')
    for key in CONTEXT_KEYS:
        if key not in settings:
            raise ValueError(f'missing execution setting: {key}')
        expected, actual = table['context'][key], settings[key]
        if key == 'vertical_rpy_rad':
            actual=np.asarray(actual,float)
            match=(actual.shape==(3,) and np.isfinite(actual).all()
                   and np.max(abs((actual-np.asarray(expected)+np.pi)%(2*np.pi)-np.pi)) <= np.deg2rad(.1))
        elif key in ('tool_coord_si','user_coord_si'):
            actual=np.asarray(actual,float)
            match=actual.shape==(6,) and np.allclose(actual,expected,atol=1e-9,rtol=0)
        else:
            match=actual == expected
        if not match:
            raise ValueError(f'execution context differs from calibration: {key}')


def require_execution_approval(table, settings):
    validate_table(table)
    if table['approved'] is not True or table['transient_approved'] is not True or settings.get('verified') is not True:
        raise ValueError('execution requires approved calibration, transient approval and verified site settings')
