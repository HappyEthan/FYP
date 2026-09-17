"""首轮磁触觉实验平台的无硬件公共接口。

真实设备适配器必须由调用方显式构造；导入本包不会连接任何设备。
"""

from .config import load_experiment, validate_experiment, validate_installation

__all__ = ["load_experiment", "validate_experiment", "validate_installation"]
