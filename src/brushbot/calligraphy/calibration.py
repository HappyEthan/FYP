def func_brush(radii: float) -> float:
    """CalliRewrite 毛笔 r->z 标定曲线 (米). 见 reference/2024_CalliRewrite_精读.md."""
    r = radii
    if 0 <= r <= 7.72667536e-04:
        return -5.9701493 * (r - 7.72667536e-04) + 4.34974603e-03
    elif r <= 1.78125854e-03:
        return -1.538473 * (r - 7.72667536e-04) + 4.34974603e-03
    elif r <= 2.45866277e-03:
        return -6.028019 * (r - 1.78125854e-03) + 2.79805600e-03
    elif r < 0.0045:
        return -2.37843574 * (r - 2.45866277e-03) - 1.28534957e-03
    return -0.006   # 溢出保护

def piecewise_linear(r, xs, ys, k0, k1):
    """通用分段线性; xs 升序断点, ys 对应值, k0/k1 两端外斜率. 供自标定用。"""
    if r <= xs[0]:
        return k0 * (r - xs[0]) + ys[0]
    for i in range(len(xs) - 1):
        if r <= xs[i + 1]:
            t = (r - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return k1 * (r - xs[-1]) + ys[-1]
