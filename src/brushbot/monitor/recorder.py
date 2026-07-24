"""录制成 V0 数据集格式(CSV + JSON), 与 delta_b_v0_20260724/ 字段一致.

禁止 import 任何 GUI 库。
"""
import glob
import json
import os
import re
from datetime import datetime, timezone

import numpy as np

CSV_HEADER = "t_us,t_s,dBx_uT,dBy_uT,dBz_uT"


def next_repetition(out_dir: str, action: str) -> int:
    """扫描同 action 的既有文件, 返回最大编号 + 1(从 1 起).

    锚定完整文件名(YYYYMMDD_HHMMSS_<action>_rNN.csv), 避免 action 名是
    另一个 action 的后缀时被误当同一 action(fullmatch, 而非子串搜索)。
    """
    pat = os.path.join(out_dir, "*_%s_r*.csv" % action)
    best = 0
    fmt = re.compile(r"\d{8}_\d{6}_%s_r(\d+)\.csv" % re.escape(action))
    for p in glob.glob(pat):
        m = fmt.fullmatch(os.path.basename(p))
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


class Recorder:
    """累积 ΔB 样本, 结束时写出 CSV+JSON 并自检."""

    def __init__(self, out_dir: str, action: str, b0, source_info: dict):
        self.out_dir = out_dir
        self.action = action
        self.b0 = np.asarray(b0, dtype=float).reshape(3)
        self.source_info = dict(source_info or {})
        self._t = []
        self._dB = []
        self._start = None
        self._stop = None
        os.makedirs(out_dir, exist_ok=True)

    def add(self, t_s: float, dB) -> None:
        self._t.append(float(t_s))
        self._dB.append([float(v) for v in dB])

    def mark_start(self, t_s: float) -> None:
        self._start = float(t_s)

    def mark_stop(self, t_s: float) -> None:
        self._stop = float(t_s)

    def finish(self, valid: bool = True, note: str = ""):
        if not self._t:
            raise ValueError("没有样本, 拒绝写空记录")
        t = np.array(self._t, dtype=float)
        dB = np.array(self._dB, dtype=float)
        t0 = t[0]
        t = t - t0                                      # 相对秒
        rep = next_repetition(self.out_dir, self.action)
        stem = "%s_%s_r%02d" % (datetime.now().strftime("%Y%m%d_%H%M%S"), self.action, rep)
        csv_path = os.path.join(self.out_dir, stem + ".csv")
        json_path = os.path.join(self.out_dir, stem + ".json")

        with open(csv_path, "w", encoding="utf-8") as f:
            f.write(CSV_HEADER + "\n")
            for k in range(len(t)):
                f.write("%d,%.6f,%.3f,%.3f,%.3f\n"
                        % (round(t[k] * 1e6), t[k], dB[k, 0], dB[k, 1], dB[k, 2]))

        # 动作窗: 标记(START/STOP)是可选的, 且来自 GUI 里未经校验的按钮点击顺序,
        # 可能反了(STOP 早于 START)或落在样本范围之外(比如第一份录制样本前就按了
        # 标记)。analyze_deltab.py 对 action_window_s 要么要求它存在(w["start"]),
        # 要么会拿它去掩码再 .max() 空数组——两种情况都会崩。所以这里保证
        # action_window_s 永远存在且是 [0, t[-1]] 内的合法非空区间:
        #   1) 完全没标记 → 整段记录当作窗口;
        #   2) 有标记但裁剪进样本范围后 start >= stop(顺序反了或都越界到同一侧)
        #      → 同样退化为整段记录。
        # 两种情况都在 note 里注明"自动回退", 不会被误当成人工标注的窗口。
        note_extra = ""
        if self._start is not None and self._stop is not None:
            start_c = min(max(self._start - t0, 0.0), float(t[-1]))
            stop_c = min(max(self._stop - t0, 0.0), float(t[-1]))
            if start_c >= stop_c:
                start_c, stop_c = 0.0, float(t[-1])
                note_extra = "动作窗口: 标记无效(裁剪后 start>=stop), 已自动回退为整段记录"
        else:
            start_c, stop_c = 0.0, float(t[-1])
            note_extra = "动作窗口: 未设置标记, 已自动回退为整段记录"
        full_note = ("%s; %s" % (note, note_extra)) if (note and note_extra) else (note or note_extra)

        dt = np.diff(t)
        name = self.source_info.get("name", "")
        is_synthetic = name.startswith(("synth", "array"))
        is_hardware = name == "serial"
        meta = {
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "action": self.action,
            "repetition": rep,
            "valid": bool(valid),
            "note": full_note,
            "sensor": "synthetic" if is_synthetic else "MLX90393",
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
            "recording_mode": "manual_markers",
            "sample_count": int(len(t)),
            "measured_duration_s": float(t[-1]),
            "mean_sample_rate_hz": float(1.0 / dt.mean()) if len(dt) else None,
            "max_interval_us": int(dt.max() * 1e6) if len(dt) else None,
            "csv_file": os.path.basename(csv_path),
            "action_window_s": {"start": float(start_c), "end": float(stop_c)},
            "action_start_t_us": int(round(start_c * 1e6)),
            "action_end_t_us": int(round(stop_c * 1e6)),
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return csv_path, json_path

    def verify(self, csv_path: str) -> bool:
        """回读刚写的文件对, 确认格式可被消费; 失败返回 False 而不是抛异常."""
        try:
            js = csv_path[:-4] + ".json"
            meta = json.load(open(js, encoding="utf-8"))
            d = np.genfromtxt(csv_path, delimiter=",", names=True)
            need = {"t_us", "t_s", "dBx_uT", "dBy_uT", "dBz_uT"}
            if not need.issubset(set(d.dtype.names or ())):
                return False
            return int(meta["sample_count"]) == int(np.atleast_1d(d["t_s"]).size)
        except Exception:
            return False
