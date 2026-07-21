# brushbot — 机械臂书法执行端（仿真）

三层架构（算法↔I/O 解耦），见 `docs/control-architecture.md`。当前为 B0+B1：PyBullet 仿真里开环写字。
机械臂为 **Elfin5**（真机同款 6-DOF，URDF 见 `assets/elfin5/`）。

## 环境
    conda create -y -n brushbot python=3.10
    conda run -n brushbot pip install -e .

## 测试
    conda run -n brushbot pytest

## 写任意汉字（真实字形数据）★

轨迹来源为 **Make Me a Hanzi** 的 `graphics.txt`（每字带 medians = 每笔的有序中线点列，覆盖 9574 字）。
数据集 30MB、已 gitignore，首次使用先下载：

    mkdir -p data/makemeahanzi && curl -fsSL https://raw.githubusercontent.com/skishore/makemeahanzi/master/graphics.txt -o data/makemeahanzi/graphics.txt

然后：

    conda run -n brushbot python -c "from brushbot.write_hanzi import write_hanzi; write_hanzi('永', gui=True)"

> 缺数据集时 `tests/test_write_hanzi.py` 会自动 skip。

## 手编笔序写字（CalliRewrite 路线）
    conda run -n brushbot python -c "from brushbot.write_openloop import write; from brushbot.examples.strokes import SHI_SEQ; write(SHI_SEQ, gui=True)"

## 换机械臂 URDF
改 `brushbot/config.py` 的 `ARM_URDF` / `EEF_LINK` / `FIXED_ORI`，其余不动。
注意 `Scene.set_joints` 按**可动关节**顺序映射 IK 结果（Elfin 前有 2 个 FIXED 关节）。

## 现在还缺什么（→ B2）

`StrokePlan = { xy路径, g_press(s) 提按曲线 }`：
- **xy 路径** ✅ 已由 Make Me a Hanzi medians 提供。
- **提按曲线** ⏳ medians 不含笔宽/力度，当前笔画等宽。真提按要靠触觉示范 + 力控闭环：
  加 `AdmittanceController` + 合成 `g_meas`（`ZeroTactile` 换成合成提按源）；实机写 `HuayanBackend`。
  见 `docs/control-architecture.md`。
