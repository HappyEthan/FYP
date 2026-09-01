import numpy as np
from brushbot.monitor import normconfig as NC


def test_roundtrip_save_get_radius(tmp_path):
    cfg = str(tmp_path)
    ch = NC.radius_to_channels([140.0, 80.0])
    NC.save_preset(cfg, "MLX90393", ch, note="calibrated")
    got = NC.get_preset(cfg, "MLX90393")
    assert got is not None
    assert got["name"] == "MLX90393"
    assert got["channels"]["dBx"]["radius_uT"] == 140.0
    assert got["channels"]["dBy"]["radius_uT"] == 80.0
    assert NC.list_preset_names(cfg) == ["MLX90393"]


def test_channels_to_radius_roundtrip(tmp_path):
    cfg = str(tmp_path)
    NC.save_preset(cfg, "A", NC.radius_to_channels([100.0, 60.0]))
    ch = NC.get_preset(cfg, "A")["channels"]
    R = NC.channels_to_radius(ch)
    assert R.tolist() == [100.0, 60.0]


def test_channels_to_radius_legacy_minmax(tmp_path):
    """兼容旧格式: channels 存 min_uT/max_uT → 转对称半径 max(|min|,|max|)."""
    ch = {
        "dBx": {"min_uT": -140.0, "max_uT": 100.0},
        "dBy": {"min_uT": -50.0, "max_uT": 80.0},
    }
    R = NC.channels_to_radius(ch)
    assert R[0] == 140.0   # max(140,100)
    assert R[1] == 80.0    # max(50,80)


def test_roundtrip_chinese_name(tmp_path):
    cfg = str(tmp_path)
    NC.save_preset(cfg, "新传感器", NC.radius_to_channels([1.0, 1.0]))
    assert NC.list_preset_names(cfg) == ["新传感器"]
    assert NC.get_preset(cfg, "新传感器")["name"] == "新传感器"


def test_missing_returns_empty(tmp_path):
    assert NC.list_preset_names(str(tmp_path)) == []
    assert NC.get_preset(str(tmp_path), "x") is None


def test_upsert_preserves_others(tmp_path):
    cfg = str(tmp_path)
    NC.save_preset(cfg, "A", NC.radius_to_channels([1.0, 1.0]))
    NC.save_preset(cfg, "B", NC.radius_to_channels([2.0, 2.0]))
    assert NC.list_preset_names(cfg) == ["A", "B"]
    NC.save_preset(cfg, "A", NC.radius_to_channels([9.0, 9.0]))
    assert NC.get_preset(cfg, "A")["channels"]["dBx"]["radius_uT"] == 9.0
    assert NC.get_preset(cfg, "B") is not None


def test_corrupted_json_no_crash(tmp_path):
    cfg = str(tmp_path)
    p = cfg + "/norm_presets.json"
    import os
    os.makedirs(cfg, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ this is not json !!!")
    assert NC.list_preset_names(cfg) == []
    assert NC.get_preset(cfg, "x") is None


def test_delete_preset(tmp_path):
    cfg = str(tmp_path)
    NC.save_preset(cfg, "A", NC.radius_to_channels([1.0, 1.0]))
    NC.delete_preset(cfg, "A")
    assert NC.list_preset_names(cfg) == []
    NC.delete_preset(cfg, "不存在")  # 不抛


def test_radius_to_channels_shape():
    ch = NC.radius_to_channels([140.0, 80.0])
    assert ch["dBx"] == {"radius_uT": 140.0}
    assert ch["dBy"] == {"radius_uT": 80.0}


def test_whitening_roundtrip(tmp_path):
    cfg = str(tmp_path)
    W = np.array([[0.003, 0.0], [0.0, 0.002]])
    NC.save_preset(cfg, "W1", NC.whitening_to_channels(W, 1.4))
    ch = NC.get_preset(cfg, "W1")["channels"]
    W2, R2 = NC.channels_to_whitening(ch)
    np.testing.assert_allclose(W2, W)
    assert R2 == 1.4


def test_channels_to_whitening_missing_returns_none():
    ch = {"dBx": {"radius_uT": 100.0}, "dBy": {"radius_uT": 50.0}}
    assert NC.channels_to_whitening(ch) is None


def test_is_gui_free():
    """normconfig 必须不 import 任何 GUI 库(contract 测试同一约束)."""
    import subprocess, sys
    code = "import sys, importlib; m=importlib.import_module('brushbot.monitor.normconfig'); import brushbot.monitor.normconfig as nc; print([x for x in sys.modules if 'PyQt' in x or x=='pyqtgraph'])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip().splitlines()[0].strip() == "[]"
