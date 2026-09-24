"""录制成 V0 数据集格式(CSV + JSON), 与 delta_b_v0_20260724/ 字段一致.

禁止 import 任何 GUI 库。
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from brushbot.monitor.core import frame_quality_mask

CSV_HEADER = "t_us,t_s,dBx_uT,dBy_uT,dBz_uT,sample_valid"


class Recorder:
    """累积 ΔB 样本, 结束时写出 CSV+JSON 并自检."""

    def __init__(self, out_dir: str, b0, source_info: dict):
        self.out_dir = Path(out_dir)
        self.b0 = np.asarray(b0, dtype=float).reshape(3)
        self.source_info = dict(source_info or {})
        self._t = []
        self._dB = []
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def add(self, t_s: float, dB) -> None:
        self._t.append(float(t_s))
        self._dB.append([float(v) for v in dB])

    def finish(self, valid: bool = True, note: str = ""):
        if not self._t:
            raise ValueError("没有样本, 拒绝写空记录")
        t = np.array(self._t, dtype=float)
        dB = np.array(self._dB, dtype=float)
        t0 = t[0]
        t = t - t0                                      # 相对秒
        quality = frame_quality_mask(dB + self.b0)
        stem = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")
        csv_path = self.out_dir / f"{stem}.csv"
        json_path = self.out_dir / f"{stem}.json"

        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(CSV_HEADER + "\n")
            for k in range(len(t)):
                f.write("%d,%.6f,%.3f,%.3f,%.3f,%d\n"
                        % (round(t[k] * 1e6), t[k], dB[k, 0], dB[k, 1], dB[k, 2],
                           int(quality[k])))

        dt = np.diff(t)
        name = self.source_info.get("name", "")
        is_hardware = name == "serial"
        meta = {
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "valid": bool(valid),
            "note": note,
            "sensor": "MLX90393" if is_hardware else (name or "offline"),
            "board": "Seeed Studio XIAO ESP32-C3" if is_hardware else None,
            "port": self.source_info.get("port"),
            "baud": self.source_info.get("baud"),
            "units": {"t_us": "us", "t_s": "s",
                      "dBx_uT": "uT", "dBy_uT": "uT", "dBz_uT": "uT"},
            "delta_definition": "dB = B - B0",
            "baseline_B0_uT": {"Bx_uT": float(self.b0[0]),
                               "By_uT": float(self.b0[1]),
                               "Bz_uT": float(self.b0[2])},
            "display_smoothing_applied": False,
            "recording_mode": "manual_start_stop",
            "sample_count": int(len(t)),
            "invalid_sample_count": int((~quality).sum()),
            "sample_quality": {
                "column": "sample_valid",
                "rule": "finite and not isolated >1000uT spike returning within 250uT",
                "raw_values_preserved": True,
            },
            "measured_duration_s": float(t[-1]),
            "mean_sample_rate_hz": float(1.0 / dt.mean()) if len(dt) else None,
            "max_interval_us": int(dt.max() * 1e6) if len(dt) else None,
            "csv_file": csv_path.name,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return csv_path, json_path

    def verify(self, csv_path: str) -> bool:
        """回读刚写的文件对, 确认格式可被消费; 失败返回 False 而不是抛异常."""
        try:
            csv_path = Path(csv_path)
            js = csv_path.with_suffix(".json")
            meta = json.load(open(js, encoding="utf-8"))
            d = np.genfromtxt(csv_path, delimiter=",", names=True)
            need = {"t_us", "t_s", "dBx_uT", "dBy_uT", "dBz_uT", "sample_valid"}
            if not need.issubset(set(d.dtype.names or ())):
                return False
            valid = np.atleast_1d(d["sample_valid"])
            return (int(meta["sample_count"]) == int(np.atleast_1d(d["t_s"]).size)
                    and np.isin(valid, [0, 1]).all()
                    and int(meta["invalid_sample_count"]) == int((valid == 0).sum()))
        except Exception:
            return False
