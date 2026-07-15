# brushbot — 机械臂书法执行端（仿真）

三层架构（算法↔I/O 解耦），见 `docs/control-architecture.md`。当前为 B0+B1：PyBullet 仿真里开环写字（复现 CalliRewrite）。

## 环境
    conda create -y -n brushbot python=3.10
    conda run -n brushbot pip install -e .

## 测试
    conda run -n brushbot pytest

## 开环写字 demo
    conda run -n brushbot python -c "from brushbot.write_openloop import write; from brushbot.examples.strokes import SHI_SEQ; write(SHI_SEQ, gui=True)"

## 换 Elfin5 URDF
改 `brushbot/config.py` 的 `ARM_URDF` / `EEF_LINK` / `FIXED_ORI`，其余不动。

## 下一步 (B2)
加 `AdmittanceController` + 合成 `g_meas`，`SimBackend` 的 `ZeroTactile` 换成合成提按源；实机写 `HuayanBackend`（见 `docs/control-architecture.md`）。
