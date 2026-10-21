"""Shared offline image geometry primitives; NumPy only, no hardware I/O."""
import numpy as np
from brushbot.xy_comparison.geometry import clean_path


def otsu_threshold(gray):
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    weight = np.cumsum(hist)
    moment = np.cumsum(hist*np.arange(256))
    denominator = weight*(weight[-1]-weight)
    score = np.zeros(256)
    valid = denominator > 0
    score[valid] = (moment[-1]*weight[valid]-moment[valid]*weight[-1])**2/denominator[valid]
    return int(np.argmax(score))



def connected_components(mask):
    height, width = mask.shape
    seen = np.zeros_like(mask)
    components = []
    for flat in np.flatnonzero(mask):
        row, col = divmod(int(flat), width)
        if seen[row, col]:
            continue
        pending, pixels = [(row, col)], []
        seen[row, col] = True
        while pending:
            y, x = pending.pop()
            pixels.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y+dy, x+dx
                    if 0 <= yy < height and 0 <= xx < width and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        pending.append((yy, xx))
        components.append(np.asarray(pixels, dtype=int))
    return sorted(components, key=lambda p: (-len(p), int(p[0, 0]), int(p[0, 1])))



def thin_mask(mask):
    padded = np.pad(mask, 1)
    for _ in range(4096):
        changed = False
        for second in (False, True):
            p = [padded[:-2, 1:-1], padded[:-2, 2:], padded[1:-1, 2:],
                 padded[2:, 2:], padded[2:, 1:-1], padded[2:, :-2],
                 padded[1:-1, :-2], padded[:-2, :-2]]
            count = sum(a.astype(np.uint8) for a in p)
            transitions = sum((~p[i] & p[(i+1) % 8]).astype(np.uint8) for i in range(8))
            first = (p[0] & p[2] & (p[6] if second else p[4]))
            other = ((p[0] if second else p[2]) & p[4] & p[6])
            remove = (padded[1:-1, 1:-1] & (count >= 2) & (count <= 6)
                      & (transitions == 1) & ~first & ~other)
            if remove.any():
                padded[1:-1, 1:-1][remove] = False
                changed = True
        if not changed:
            return padded[1:-1, 1:-1].copy()
    raise ValueError('thinning did not converge; use a smaller cropped stroke image')



def pixel_graph(skeleton):
    nodes = {tuple(map(int, p)) for p in np.argwhere(skeleton)}
    graph = {}
    for y, x in sorted(nodes):
        neighbours = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                other = (y+dy, x+dx)
                if not (dx or dy) or other not in nodes:
                    continue
                # Do not create triangular shortcuts around a 4-connected corner.
                if dx and dy and ((y, x+dx) in nodes or (y+dy, x) in nodes):
                    continue
                neighbours.append((other, float(np.hypot(dx, dy))))
        graph[(y, x)] = neighbours
    return graph



def simplify_path(points, tolerance_px):
    """Ramer-Douglas-Peucker simplification; zero preserves the pixel route.

    The retained polyline stays within the specified point-to-segment tolerance
    of the ordered source pixels. Endpoints and raw evidence are preserved.
    """
    points = clean_path(points)
    if (isinstance(tolerance_px, bool) or not np.isfinite(tolerance_px) or tolerance_px < 0):
        raise ValueError('simplify_px must be finite and nonnegative')
    if tolerance_px == 0:
        return points.copy()
    keep = {0, len(points)-1}
    pending = [(0, len(points)-1)]
    while pending:
        left, right = pending.pop()
        if right-left < 2:
            continue
        middle = points[left+1:right]
        delta = points[right]-points[left]
        length = float(np.hypot(*delta))
        offset = middle-points[left]
        if length > 0:
            unit = delta/length
            offset = offset-np.clip(offset @ unit, 0., length)[:, None]*unit
        distance = np.hypot(*offset.T)
        index = int(np.argmax(distance))
        if distance[index] > tolerance_px:
            split = left+1+index
            keep.add(split)
            pending.extend([(left, split), (split, right)])
    return points[sorted(keep)]
