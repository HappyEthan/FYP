"""可插拔信号源. 一律输出**原始 B**(非 ΔB), 扣基线由 core 负责.

禁止 import 任何 GUI 库。
"""
import time
import numpy as np
import json
import os

Sample = tuple  # (t_s, Bx, By, Bz)


def parse_serial_line(line: str):
    """固件一行 't_us,Bx,By,Bz' → (t_us, Bx, By, Bz); 表头/空行/坏行 → None."""
    if not isinstance(line, str):
        return None
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    parts = s.split(",")
    if len(parts) != 4:
        return None
    try:
        return (int(float(parts[0])), float(parts[1]), float(parts[2]), float(parts[3]))
    except (ValueError, TypeError):
        return None


class ArraySource:
    """内存数组信号源: 按标称速率流式吐出预先算好的原始 B.

    合成信号与单元测试共用此类(合成 = 先算好数组再交给它)。
    """

    def __init__(self, t_s, B, name: str = "array", rate_hz: float = 100.0):
        self._t = np.asarray(t_s, dtype=float).reshape(-1)
        self._B = np.asarray(B, dtype=float).reshape(-1, 3)
        if len(self._t) != len(self._B):
            raise ValueError("t_s 与 B 长度不一致")
        self.name = name
        self.rate_hz = float(rate_hz)
        self.rate = 1.0            # 播放倍速
        self._i = 0
        self._t0 = None

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._i = 0

    def stop(self) -> None:
        self._t0 = None

    def seek(self, frac: float) -> None:
        """跳到总时长的 frac(0~1) 处."""
        frac = min(max(float(frac), 0.0), 1.0)
        self._i = int(frac * len(self._t))
        now = time.monotonic()
        if self._i < len(self._t):
            offset = (self._t[self._i] - self._t[0]) / max(self.rate, 1e-9)
            self._t0 = now - offset
        else:
            self._t0 = now

    def set_rate(self, multiplier: float) -> None:
        """设置播放倍速(0.5=半速, 1=正常, 2=双倍). seek 会自动对轨."""
        self.rate = max(float(multiplier), 0.01)
        # 重设时间原点, 避免倍速切换瞬间跳帧
        if self._t0 is not None and self._i < len(self._t):
            now = time.monotonic()
            offset = (self._t[self._i] - self._t[0]) / max(self.rate, 1e-9)
            self._t0 = now - offset

    @property
    def done(self) -> bool:
        return self._i >= len(self._t)

    @property
    def info(self) -> dict:
        return {"name": self.name, "nominal_rate_hz": self.rate_hz,
                "units": "uT", "n_samples": int(len(self._t))}

    def read(self) -> list:
        """吐出到当前墙钟时刻为止应该发生的样本."""
        if self._t0 is None or self.done:
            return []
        elapsed = (time.monotonic() - self._t0) * self.rate
        out = []
        base = self._t[0]
        while self._i < len(self._t) and (self._t[self._i] - base) <= elapsed:
            out.append((float(self._t[self._i]), float(self._B[self._i, 0]),
                        float(self._B[self._i, 1]), float(self._B[self._i, 2])))
            self._i += 1
        return out


class SerialSource:
    """pyserial 串口源. 固件格式 't_us,Bx,By,Bz' @115200."""

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200):
        self.port = port
        self.baud = baud
        self._ser = None
        self._buf = b""
        self._t0_us = None
        self.bad_lines = 0

    def start(self) -> None:
        import serial                       # 延迟导入: 没插硬件也能 import 本模块
        self._ser = serial.Serial(self.port, self.baud, timeout=0)
        self._buf = b""
        self._t0_us = None
        self.bad_lines = 0

    def stop(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    @property
    def info(self) -> dict:
        return {"name": "serial", "nominal_rate_hz": 100.0, "units": "uT",
                "port": self.port, "baud": self.baud}

    def read(self) -> list:
        """非阻塞读, 按行解析; 正确处理跨包截断的半行."""
        if self._ser is None:
            return []
        self._buf += self._ser.read(4096)
        out = []
        while b"\n" in self._buf:
            raw, self._buf = self._buf.split(b"\n", 1)
            rec = parse_serial_line(raw.decode("utf-8", errors="replace"))
            if rec is None:
                if raw.strip() and not raw.strip().startswith(b"#"):
                    self.bad_lines += 1
                continue
            t_us, bx, by, bz = rec
            if self._t0_us is None:
                self._t0_us = t_us
            out.append(((t_us - self._t0_us) / 1e6, bx, by, bz))
        return out


def load_v0_record(csv_path: str) -> dict:
    """读一对 V0 CSV+JSON. CSV 存的是 ΔB, 这里加回 B0 还原成原始 B."""
    js_path = csv_path[:-4] + ".json" if csv_path.endswith(".csv") else csv_path + ".json"
    if not os.path.exists(js_path):
        raise FileNotFoundError("缺少配套 JSON: %s" % js_path)
    meta = json.load(open(js_path, encoding="utf-8"))
    b0d = meta["baseline_B0_uT"]
    b0 = np.array([b0d["Bx_uT"], b0d["By_uT"], b0d["Bz_uT"]], dtype=float)
    d = np.genfromtxt(csv_path, delimiter=",", names=True)
    dB = np.c_[d["dBx_uT"], d["dBy_uT"], d["dBz_uT"]]
    return {"t_s": np.atleast_1d(d["t_s"]).astype(float),
            "B_raw": dB + b0, "b0": b0, "meta": meta}


class ReplaySource(ArraySource):
    """回放已录制的 V0 数据集(还原成原始 B 后走 ArraySource 的流式逻辑)."""

    def __init__(self, csv_path: str):
        rec = load_v0_record(csv_path)
        super().__init__(rec["t_s"], rec["B_raw"],
                         name="replay:" + os.path.basename(csv_path))
        self.b0 = rec["b0"]
        self.meta = rec["meta"]

    @property
    def info(self) -> dict:
        d = super().info
        d["action"] = self.meta.get("action")
        return d


def synth_writing_B(n: int = 600, rate_hz: float = 100.0,
                    b0=(270.0, 710.0, -5500.0), peak_uT: float = 400.0) -> ArraySource:
    """合成信号源: 构造一段"落笔-横拖-抬笔"轨迹 → 合成 ΔB → 叠加标称 B0 得原始 B.

    不依赖字形数据集与 PyBullet, 确定性可测。

    注意单位: tactile_from_trace() 输出的是该触觉模型的**任意内部单位**,
    量纲上与真实磁场(µT)毫无关系——直接拿它当 µT 用会比真机数据小 ~7 个
    数量级(峰值 ~1e-4 vs 真实数据集的 ~461 µT), 录出来的 CSV 用 "%.3f" 格式化
    后全部四舍五入成 0.000。这里显式把整段合成轨迹的峰值 |ΔB| 缩放到 peak_uT
    (默认 400 µT, 真实数据集量级), 使合成信号成为一段"看起来合理的信号",
    而不是任何物理量的预测——它只用于联调/演示/无硬件测试, 不代表真实传感器响应。
    """
    from brushbot import config
    from brushbot.tactile.writing_tactile import tactile_from_trace

    k = np.arange(n)
    # 前 15% 悬空, 中间落笔并横向匀速拖行, 末 15% 抬笔
    down = (k > 0.15 * n) & (k < 0.85 * n)
    z = np.where(down, config.PAPER_Z - 0.0015, config.PAPER_Z + 0.01)
    x = config.CHAR_ORIGIN[0] + np.linspace(-0.015, 0.015, n)
    y = np.full(n, config.CHAR_ORIGIN[1], dtype=float)
    trace = np.c_[x, y, z]
    dB, _ = tactile_from_trace(trace)
    dB = np.asarray(dB, dtype=float)
    peak = np.abs(dB).max()
    if peak > 1e-9:                     # 防止全零轨迹除零; 全零时不缩放, 仍是全零
        dB = dB * (peak_uT / peak)
    B_raw = dB + np.asarray(b0, dtype=float)
    t = k / float(rate_hz)
    return ArraySource(t, B_raw, name="synth:writing", rate_hz=rate_hz)
