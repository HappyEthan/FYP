"""Check image-bound XY against reference ink without clipping or moving the path."""
from __future__ import annotations

import numpy as np

from brushbot.xy_comparison.geometry import clean_path


def ink_consistency(mask, xy_px, image_size_px):
    """Estimate outside travel by uniform arc-length midpoint sampling.

    The one-pixel allowance uses an axis-aligned neighborhood in original-image
    coordinates. This is a raster overlay check, never a brush footprint model.
    """
    mask = np.asarray(mask, bool)
    size = np.asarray(image_size_px, float)
    xy = clean_path(xy_px)
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    count = min(20_000, max(1, int(np.ceil(arc[-1]/.25))))
    at = (np.arange(count)+.5)*arc[-1]/count
    samples = np.column_stack([np.interp(at, arc, xy[:, d]) for d in (0,1)])
    ratio = np.array(mask.shape[::-1])/size

    def inside(points):
        visible = np.zeros(len(points), bool)
        for dx in (-1.,0.,1.):
            for dy in (-1.,0.,1.):
                uv = points+np.array([dx,dy])
                uv[:,1] = size[1]-1-uv[:,1]
                index = np.floor((uv+.5)*ratio).astype(int)
                bounded = ((index>=0)&(index<np.array(mask.shape[::-1]))).all(axis=1)
                visible[bounded] |= mask[index[bounded,1],index[bounded,0]]
        return visible

    outside = ~inside(samples)
    outside_vertices = ~inside(xy)
    fraction = float(np.mean(outside))
    return dict(role='reference_ink_consistency_not_calligraphy_quality',
        outside_fraction=fraction, outside_length_px=float(arc[-1]*fraction),
        path_length_px=float(arc[-1]), outside_endpoint_count=int(np.sum(outside_vertices[[0,-1]])),
        outside_vertex_count=int(np.sum(outside_vertices)),
        tolerance_px=1., tolerance_metric='axis_aligned_original_pixel_neighborhood',
        reference_scope='whole_image_ink_union_not_stroke_labels',
        sampling='uniform_arclength_midpoints', sample_count=count,
        sample_spacing_px=float(arc[-1]/count), reference_role='layout_image_not_independent_motion_truth')
