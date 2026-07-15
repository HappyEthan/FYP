from PIL import Image, ImageDraw

def render_trace(points, surface_z, out_path, px_per_m=4000, pad=0.01, down_margin=0.002):
    """笔尖轨迹 -> 墨迹 PNG。z<=surface_z+down_margin 视为落笔。"""
    down = [(x, y) for (x, y, z) in points if z <= surface_z + down_margin]
    if not down:
        raise ValueError("no pen-down points to render")
    xs = [p[0] for p in down]; ys = [p[1] for p in down]
    minx, maxx = min(xs) - pad, max(xs) + pad
    miny, maxy = min(ys) - pad, max(ys) + pad
    W = max(1, int((maxx - minx) * px_per_m))
    H = max(1, int((maxy - miny) * px_per_m))
    img = Image.new("L", (W, H), 255)
    dr = ImageDraw.Draw(img)

    def to_px(x, y):
        px = int((x - minx) * px_per_m)
        py = int((maxy - y) * px_per_m)   # y 轴翻转
        return px, py

    prev = None
    for (x, y, z) in points:
        if z <= surface_z + down_margin:
            cur = to_px(x, y)
            if prev is not None:
                dr.line([prev, cur], fill=0, width=3)
            prev = cur
        else:
            prev = None                    # 抬笔断开
    img.save(out_path)
    return (W, H)
