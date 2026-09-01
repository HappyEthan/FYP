"""归一化预设(每轴 dBx/dBy 的 min/max)的纯 JSON 存取.

禁止 import 任何 GUI 库(contract 测试强制 core/sources/recorder 及相关模块 GUI-free)。
道 ID: 与 recorder.py 的 JSON 写法一致 (ensure_ascii=False, indent=2)。
"""

import json
import os

import numpy as np

CONFIG_FILENAME = "norm_presets.json"
FORMAT_VERSION = 1


def _path(config_dir: str) -> str:
    return os.path.join(config_dir, CONFIG_FILENAME)


def _read(config_dir: str) -> dict:
    """读整个文件 → dict. 缺失/损坏 → {}."""
    try:
        with open(_path(config_dir), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(config_dir: str, data: dict) -> None:
    os.makedirs(config_dir, exist_ok=True)
    with open(_path(config_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_preset_names(config_dir: str) -> list:
    """所有预设名, 排序."""
    return sorted(_read(config_dir).get("presets", {}).keys())


def get_preset(config_dir: str, name: str):
    """取单个预设 dict; 不存在 → None."""
    return _read(config_dir).get("presets", {}).get(name)


def save_preset(config_dir: str, name: str, channels: dict, note: str = "") -> None:
    """增/改一个预设(channels={'dBx': {'min_uT':..,'max_uT':..}, 'dBy':{...}}).

    保留其他预设. 自动加 format_version + saved_at 时间戳.
    """
    from datetime import datetime, timezone

    data = _read(config_dir)
    presets = data.setdefault("presets", {})
    data["format_version"] = FORMAT_VERSION
    presets[name] = {
        "name": name,
        "channels": channels,
        "note": note,
        "saved_at": datetime.now(timezone.utc).astimezone().isoformat(),
    }
    _write(config_dir, data)


def delete_preset(config_dir: str, name: str) -> None:
    """删除一个预设; 不存在也不报错."""
    data = _read(config_dir)
    data.get("presets", {}).pop(name, None)
    _write(config_dir, data)


def radius_to_channels(radius2) -> dict:
    """每轴对称半径 (Rx, Ry) → channels dict (便于单测与落盘)."""
    return {
        "dBx": {"radius_uT": float(radius2[0])},
        "dBy": {"radius_uT": float(radius2[1])},
    }


def channels_to_radius(channels: dict):
    """从 channels 提取每轴对称半径 (Rx, Ry).

    兼容两种存储:
      - 新格式 {"dBx": {"radius_uT": R}, ...}
      - 旧格式 {"dBx": {"min_uT": m, "max_uT": M}, ...} → R = max(|m|,|M|)
    """
    def _axis_radius(ch):
        if "radius_uT" in ch:
            return float(ch["radius_uT"])
        m = float(ch.get("min_uT", 0.0))
        M = float(ch.get("max_uT", 0.0))
        return max(abs(m), abs(M))
    return np.array([_axis_radius(channels["dBx"]), _axis_radius(channels["dBy"])])


def whitening_to_channels(W, R) -> dict:
    """椭圆白化矩阵 W(2×2) + 统一半径 R → channels dict."""
    return {"db_xy": {"W": np.asarray(W, float).reshape(2, 2).tolist(),
                      "R": float(R)}}


def channels_to_whitening(channels: dict):
    """从 channels 提取白化 (W, R); 无白化 → None."""
    ch = channels.get("db_xy")
    if not ch or "W" not in ch or "R" not in ch:
        return None
    return np.asarray(ch["W"], dtype=float).reshape(2, 2), float(ch["R"])
