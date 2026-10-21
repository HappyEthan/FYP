"""Arclength-weighted, fixed-frame polyline comparisons in millimetres."""
from __future__ import annotations

import numpy as np


def clean_path(xy_mm):
    """Drop stationary geometry samples, without changing direction or retracing."""
    xy = np.asarray(xy_mm, dtype=float)
    if (xy.ndim != 2 or xy.shape[1] != 2 or not 2 <= len(xy) <= 20000
            or not np.isfinite(xy).all()):
        raise ValueError('path must contain 2..20000 finite XY pairs in mm')
    lengths = np.hypot(*np.diff(xy, axis=0).T)
    if not np.isfinite(lengths).all() or not np.isfinite(lengths.sum()):
        raise ValueError('path length is not finite')
    xy = xy[np.r_[True, lengths > 0]]
    if len(xy) < 2:
        raise ValueError('path must have positive length')
    return xy


def _arc(xy):
    return np.r_[0., np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]


def resample_path(xy_mm, samples=501):
    """Uniform total-travel sampling; repeated visits remain part of the path."""
    if type(samples) is not int or not 2 <= samples <= 10000:
        raise ValueError('samples must be an integer between 2 and 10000')
    xy = clean_path(xy_mm)
    arc = _arc(xy)
    positions = np.linspace(0., arc[-1], samples)
    return np.column_stack([np.interp(positions, arc, xy[:, i]) for i in range(2)])


def _distance_to_path(points, path):
    """Point-to-segment distances, with bounded intermediate allocations."""
    result = np.full(len(points), np.inf)
    for i in range(0, len(points), 64):
        p = points[i:i+64, None, :]
        best = np.full(len(p), np.inf)
        for j in range(0, len(path)-1, 512):
            end = min(j+512, len(path)-1)
            a, b = path[j:end], path[j+1:end+1]
            delta = b-a
            length = np.hypot(*delta.T)
            unit = delta/length[:, None]
            projected = np.clip(np.sum((p-a)*unit, axis=2), 0., length)
            offset = p-a-projected[:, :, None]*unit
            distance = np.hypot(offset[:, :, 0], offset[:, :, 1])
            best = np.minimum(best, distance.min(axis=1))
        result[i:i+len(p)] = best
    return result


def compare_paths(reference_xy_mm, candidate_xy_mm, samples=501):
    """Return metrics and plotting arrays; never fit scale, pose or direction.

    Nearest distances are evaluated at uniform arclength samples against the
    opposite original polyline segments. Ordered errors pair equal fractions
    of total travelled distance, and do not measure timing or real brush motion.
    """
    reference = clean_path(reference_xy_mm)
    candidate = clean_path(candidate_xy_mm)
    ref = resample_path(reference, samples)
    plan = resample_path(candidate, samples)
    ref_to_plan = _distance_to_path(ref, candidate)
    plan_to_ref = _distance_to_path(plan, reference)
    vertex_max = max(float(_distance_to_path(reference, candidate).max()),
                     float(_distance_to_path(candidate, reference).max()))
    ordered = np.hypot(*(plan-ref).T)
    distances = np.r_[ref_to_plan, plan_to_ref]
    ref_length, plan_length = float(_arc(reference)[-1]), float(_arc(candidate)[-1])
    metrics = dict(
        bidirectional_mean_distance_mm=float(distances.mean()),
        bidirectional_p95_distance_mm=float(np.percentile(distances, 95)),
        vertex_max_distance_mm=vertex_max,
        reference_to_plan_mean_mm=float(ref_to_plan.mean()),
        plan_to_reference_mean_mm=float(plan_to_ref.mean()),
        ordered_mean_distance_mm=float(ordered.mean()),
        ordered_p95_distance_mm=float(np.percentile(ordered, 95)),
        start_error_mm=float(np.hypot(*(candidate[0]-reference[0]))),
        end_error_mm=float(np.hypot(*(candidate[-1]-reference[-1]))),
        reference_length_mm=ref_length, plan_length_mm=plan_length,
        length_error_mm=plan_length-ref_length, length_ratio=plan_length/ref_length,
        sample_count=samples,
    )
    return dict(metrics=metrics, progress=np.linspace(0., 1., samples),
                reference_xy_mm=ref, candidate_xy_mm=plan,
                reference_vertices_mm=reference, candidate_vertices_mm=candidate,
                reference_to_plan_mm=ref_to_plan, plan_to_reference_mm=plan_to_ref,
                ordered_error_mm=ordered)
