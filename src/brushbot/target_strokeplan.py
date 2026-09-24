"""V3 target-only StrokePlan. Legacy V2 remains in brushbot.strokeplan."""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

FORMAT_VERSION = 3
FEATURE = 'filtered_dBxy_norm_uT'
UNITS = {'position': 'm', 'time': 's', 'magnetic_field': 'uT'}


def _check_metadata(value):
    if isinstance(value, dict):
        for key, child in value.items():
            key = str(key).lower()
            if (key in {'z', 'z_ff', 'z_cmd', 'z_demo', 'reference_table', 'setup',
                        'feedforward', 'depth_mm', 'contact_z_mm', 'wait_z_mm'}
                    or set(key.split('_')) & {'z', 'depth', 'feedforward'}):
                raise ValueError(f'device/Z data is not target metadata: {key}')
            _check_metadata(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _check_metadata(child)


@dataclass
class Stroke:
    s: np.ndarray
    xy: np.ndarray
    t: np.ndarray
    g_target: np.ndarray
    orientation: np.ndarray | None = None

    def validate(self):
        s, xy, t, g = [np.asarray(a, dtype=float) for a in
                        (self.s, self.xy, self.t, self.g_target)]
        if (s.ndim != 1 or len(s) < 2 or xy.shape != (len(s), 2)
                or t.shape != s.shape or g.shape != s.shape):
            raise ValueError('stroke arrays must have matching lengths')
        if not all(np.isfinite(a).all() for a in (s, xy, t, g)):
            raise ValueError('nonfinite stroke values')
        if t[0] != 0 or np.any(np.diff(t) <= 0) or np.any(g < 0):
            raise ValueError('t must increase from zero; targets must be nonnegative')
        arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
        if arc[-1] <= 0 or not np.allclose(s, arc/arc[-1], atol=1e-8, rtol=0):
            raise ValueError('s must equal normalized XY arclength; zero length rejected')
        if self.orientation is not None:
            rpy = np.asarray(self.orientation, float)
            if rpy.shape != (len(s), 3) or not np.isfinite(rpy).all():
                raise ValueError('orientation must be finite M x 3 RPY radians')


@dataclass
class StrokePlan:
    strokes: list[Stroke]
    meta: dict

    def validate(self):
        if not isinstance(self.meta, dict) or not self.strokes:
            raise ValueError('plan needs metadata and at least one stroke')
        _check_metadata(self.meta)
        # Also rejects NaN in nested metadata before serialization.
        json.dumps(self.meta, allow_nan=False)
        if self.meta.get('source') not in {'synthetic', 'demonstration', 'mixed'}:
            raise ValueError('source must be synthetic/demonstration/mixed')
        if self.meta.get('source') != 'synthetic' and not self.meta.get('provenance'):
            raise ValueError('measured or mixed data requires provenance')
        if self.meta.get('coordinate_frame') not in {'paper', 'base'}:
            raise ValueError('explicit paper/base coordinate_frame required')
        if self.meta.get('feature') != FEATURE or not isinstance(self.meta.get('filter_definition'), dict):
            raise ValueError('explicit magnetic feature/filter_definition required')
        if 'units' in self.meta and self.meta['units'] != UNITS:
            raise ValueError('V3 units are m/s/uT')
        for stroke in self.strokes:
            stroke.validate()
            if stroke.orientation is not None and self.meta.get('orientation_convention') != 'base_rpy_rad':
                raise ValueError('orientation_convention must be base_rpy_rad')

    def save(self, path):
        self.validate()
        arrays = dict(format_version=np.array(FORMAT_VERSION),
                      n_strokes=np.array(len(self.strokes)),
                      meta_json=np.array(json.dumps(self.meta | {'units': UNITS}, allow_nan=False)))
        for i, st in enumerate(self.strokes):
            for suffix, value in [('s', st.s), ('xy', st.xy), ('t', st.t), ('g', st.g_target)]:
                arrays[f's{i}_{suffix}'] = np.asarray(value, float)
            if st.orientation is not None:
                arrays[f's{i}_rpy'] = np.asarray(st.orientation, float)
        with Path(path).open('xb') as stream:
            np.savez(stream, **arrays)

    @classmethod
    def load(cls, path):
        try:
            with np.load(path, allow_pickle=False) as data:
                if data['format_version'].shape != () or data['format_version'].item() != FORMAT_VERSION:
                    raise ValueError('expected target-only V3; use explicit legacy reader for V2')
                raw_n = data['n_strokes']
                if raw_n.shape != () or raw_n.dtype.kind not in 'iu' or not 0 < int(raw_n) <= 10000:
                    raise ValueError('invalid stroke count')
                n = int(raw_n)
                required = {'format_version', 'n_strokes', 'meta_json'}
                for i in range(n):
                    required.update(f's{i}_{k}' for k in ('s','xy','t','g'))
                optional = {f's{i}_rpy' for i in range(n)}
                if not required <= set(data.files) or set(data.files) - required - optional:
                    raise ValueError('missing or unsupported V3 fields (Z is forbidden)')
                strokes = [Stroke(data[f's{i}_s'], data[f's{i}_xy'], data[f's{i}_t'],
                                  data[f's{i}_g'], data[f's{i}_rpy'] if f's{i}_rpy' in data else None)
                           for i in range(n)]
                plan = cls(strokes, json.loads(str(data['meta_json'])))
        except (KeyError, TypeError, IndexError) as exc:
            raise ValueError('invalid V3 file') from exc
        plan.validate()
        return plan
