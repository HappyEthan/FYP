"""汉字字形笔画 -> 路点.

数据源: Make Me a Hanzi 的 graphics.txt, 每个字带 medians —— 每一笔的
有序中线点列(字体单位, +y 向上), 即"笔往哪走"的真实书写路径。
注意: medians 只给 xy 路径, 不含提按/笔宽 —— 那一半由触觉示范提供。
"""

import json


def load_medians(character, graphics_path):
    """从 graphics.txt 取某字每一笔的中线点列; 字不存在则 KeyError。"""
    with open(graphics_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record["character"] == character:
                return record["medians"]
    raise KeyError(character)


def medians_to_strokes(medians, size=0.032):
    """字体单位 medians -> 局部米制笔画: 等比缩放使长边=size, 包围盒居中到原点。"""
    points = [p for stroke in medians for p in stroke]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    scale = size / max(maxx - minx, maxy - miny)
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    return [[((x - cx) * scale, (y - cy) * scale) for (x, y) in stroke]
            for stroke in medians]


def strokes_to_waypoints(strokes, origin, z_down, z_up):
    """局部笔画 -> 世界 (x,y,z) 路点: 每笔抬笔趋近 -> 落笔走完 -> 抬笔收尾。"""
    ox, oy = origin
    wp = []
    for stroke in strokes:
        sx, sy = stroke[0]
        wp.append((ox + sx, oy + sy, z_up))
        for (x, y) in stroke:
            wp.append((ox + x, oy + y, z_down))
        ex, ey = stroke[-1]
        wp.append((ox + ex, oy + ey, z_up))
    return wp
