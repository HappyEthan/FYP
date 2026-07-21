"""纸面墨迹画布: 世界坐标 -> 贴图像素, 供仿真里的"纸"实时显示墨迹。

与 render.py 的区别: render 是运动结束后离线出图; 本类是边写边刷进
PyBullet 贴图, 让墨迹在仿真窗口里逐笔浮现。
"""

from PIL import Image, ImageDraw


class InkCanvas:
    def __init__(self, center_xy, size_m, resolution=256):
        self.cx, self.cy = center_xy
        self.size = size_m
        self.res = resolution
        self.image = Image.new("RGB", (resolution, resolution), (255, 255, 255))
        self._draw = ImageDraw.Draw(self.image)

    def world_to_px(self, x, y):
        """纸面世界坐标 -> 贴图像素 (y 轴翻转: 世界 +y 向上, 贴图行号向下)。"""
        left = self.cx - self.size / 2.0
        top = self.cy + self.size / 2.0
        u = (x - left) / self.size * self.res
        v = (top - y) / self.size * self.res
        return int(round(u)), int(round(v))

    def stroke(self, x0, y0, x1, y1, width_m):
        """在纸上画一段墨迹, 线宽按米给(会换算成像素)。"""
        w = max(1, int(round(width_m / self.size * self.res)))
        self._draw.line([self.world_to_px(x0, y0), self.world_to_px(x1, y1)],
                        fill=(0, 0, 0), width=w)

    def clear(self):
        """擦干净重来(换一张白纸)。"""
        self.image = Image.new("RGB", (self.res, self.res), (255, 255, 255))
        self._draw = ImageDraw.Draw(self.image)

    def pixel(self, px, py):
        """该像素的灰度(0=黑, 255=白), 便于检查。"""
        return self.image.getpixel((px, py))[0]

    def rgb_bytes(self):
        """展平的 RGB 字节, 交给 pybullet changeTexture。"""
        return list(self.image.tobytes())
