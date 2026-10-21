"""Conservative normal scans: obscured and unbounded widths remain missing."""
from __future__ import annotations

import numpy as np

from brushbot.xy_comparison.geometry import clean_path, resample_path, _distance_to_path


def measure_widths(mask, xy_px, *, other_paths=(), image_size_px=None):
    """Measure in original Cartesian pixels, even if the binary mask was resized.

    This is a geometric ink-width candidate, not a contact/force estimate.
    Other annotated centre paths conservatively invalidate overlap samples.
    """
    mask = np.asarray(mask, bool)
    if mask.ndim != 2 or min(mask.shape) < 3:
        raise ValueError('width measurement needs a 2D mask')
    size = np.asarray(image_size_px if image_size_px is not None else mask.shape[::-1], float)
    if size.shape != (2,) or not np.isfinite(size).all() or np.any(size < 3):
        raise ValueError('invalid image size for measurement')
    ratio = np.array(mask.shape[::-1])/size
    pixel_step = float(np.min(1/ratio)/2)
    radius = min(float(np.hypot(*size)), 512*pixel_step)
    at = np.arange(0., radius+pixel_step/2, pixel_step)
    path = resample_path(xy_px, 65)
    tangent = np.gradient(path, axis=0)
    zero = np.linalg.norm(tangent, axis=1) < 1e-10
    for i in np.flatnonzero(zero):
        tangent[i] = path[min(i+1, len(path)-1)]-path[max(i-1, 0)]
        if np.linalg.norm(tangent[i]) < 1e-10:
            tangent[i] = path[i]-path[i-1] if i else path[1]-path[0]
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    normals = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    samples = []

    def lookup(points_):
        uv = points_.copy()
        uv[:, 1] = size[1]-1-uv[:, 1]
        uv = np.floor((uv+.5)*ratio).astype(int)
        inside = ((uv >= 0) & (uv < np.array(mask.shape[::-1]))).all(axis=1)
        ink = np.zeros(len(points_), bool)
        ink[inside] = mask[uv[inside, 1], uv[inside, 0]]
        return ink, inside

    other = [clean_path(p) for p in other_paths]
    for i, (point, normal) in enumerate(zip(path, normals)):
        width, reason, ends = None, None, []
        for sign in (1., -1.):
            ink, inside = lookup(point+sign*at[:, None]*normal)
            if not inside[0]:
                reason = 'image_border'
                break
            if not ink[0]:
                reason = 'outside_ink'
                break
            out = np.flatnonzero(~ink)
            if not len(out):
                reason = 'radius_limit'
                break
            end = int(out[0])
            if not inside[end]:
                reason = 'image_border'
                break
            ends.append(float(at[end]))
        if reason is None:
            measured = sum(ends)-pixel_step
            if any(_distance_to_path(point[None, :], p)[0] <= max(ends)+pixel_step for p in other):
                reason = 'overlap'
            else:
                width = float(measured)
        samples.append(dict(u=i/64, xy_px=point.tolist(), width_px=width, reason=reason))
    valid = [s['width_px'] for s in samples if s['width_px'] is not None]
    return dict(width_px=float(np.median(valid)) if valid else None,
        valid_count=len(valid), total_count=len(samples), samples=samples,
        method='normal_scan_candidate_with_annotated_overlap_exclusion', units='original_image_px')
