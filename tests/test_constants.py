"""常量单一源与滤波器归属 (审计 R7/R12, P2 批).

这些是钉住测试: 值本身没变, 钉住的是"只有一个定义处"——谁想再复制一份字面量,
先让这里的 is/相等断言红掉。
"""
import numpy as np
import pytest

from brushbot import config


def test_fs_single_source():
    """采样主频 FS: config 为唯一定义, 各模块引用而非各写各的 (R12)."""
    from brushbot import demo_pipeline, sim_loop, strokeplan
    assert config.FS == 100.0
    assert sim_loop.FS == config.FS
    assert strokeplan.FS == config.FS
    assert demo_pipeline.FS == config.FS


def test_zcontroller_defaults_from_config():
    """ZController 默认 z_surface/dt 引用 config, 不再靠字面量巧合一致 (R12)."""
    from brushbot.z_control import ZController
    ctrl = ZController(np.array([0.0, 5.0]), np.array([0.0, 250.0]))
    assert ctrl.z_surface == config.PAPER_Z
    assert ctrl.dt == pytest.approx(1.0 / config.FS)


def test_linear_calib_table_single_source():
    """合成线性标定表: sim_loop 为唯一定义 (原 3 份脚本字面量, R12)."""
    from brushbot.sim_loop import CALIB_ABS_DB_LINEAR, CALIB_Z_MM_LINEAR
    np.testing.assert_array_equal(CALIB_Z_MM_LINEAR, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    np.testing.assert_array_equal(CALIB_ABS_DB_LINEAR,
                                  [0.0, 50.0, 100.0, 150.0, 200.0, 250.0])


def test_ema_lives_in_filter_module():
    """EMA 归属修正 (R7): 正典实现在 filter.py, monitor.core 仅 re-export."""
    from brushbot import filter as flt
    from brushbot.monitor import core
    assert core.EMA is flt.EMA
    # NaN 透传策略随实现一起搬家, 不得丢失
    f = flt.EMA(0.3)
    f.update(np.array([10.0, 0.0, 0.0]))
    f.update(np.array([np.nan, 0.0, 0.0]))
    assert np.all(np.isfinite(f.update(np.array([10.0, 0.0, 0.0]))))


def test_control_filter_single_source():
    """控制环滤波器工作点 α=0.3 的唯一常量源与工厂 (R7)."""
    from brushbot.filter import CONTROL_EMA_ALPHA, EMA, make_control_filter
    assert CONTROL_EMA_ALPHA == 0.3
    f = make_control_filter()
    assert isinstance(f, EMA)
    assert f.alpha == CONTROL_EMA_ALPHA
