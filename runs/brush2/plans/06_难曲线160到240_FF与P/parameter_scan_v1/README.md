---
project: 04-robot-control
status: active
---

# 非线性前馈：Kp与修正行程六组扫描

沿用160–240 µT难曲线、10 mm/s、450 mm纸面总行程、Z36固定XYZ旋转进笔和实际TCP采集。六组均Ki=0，修正速度2 mm/s、加速度30 mm/s²、首尾渐变50拍（1秒），由 --p-dynamics smooth 明确选择。

| 组别 | Kp | 修正幅值 |
|---|---:|---:|
| A | 0.25 | ±0.4 mm |
| B | 0.25 | ±0.8 mm |
| C | 0.5 | ±0.4 mm |
| D | 0.5 | ±0.8 mm |
| E | 1 | ±0.4 mm |
| F | 1 | ±0.8 mm |

第一轮A→B→C→D→E→F；第二轮F→E→D→C→B→A，每组两次，降低线性顺序漂移对组均值的影响，但无法消除沾水和接触状态差异。12笔完整动作约26.4分钟，另加基线、沾水和准备。

每次只执行一条命令，每笔重新按相同方式沾水。等待位XYZ=[−370,500,130] mm、RPY=[0,15,0]°；纸面X−370→80、Y500 mm。完整指令如下，在 /home/ethan/FYP 目录执行：

```bash
# 第1笔：A组，第1次，Kp=0.25，修正±0.4 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.25 --max-correction-mm 0.4 --execute

# 第2笔：B组，第1次，Kp=0.25，修正±0.8 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.25 --max-correction-mm 0.8 --execute

# 第3笔：C组，第1次，Kp=0.5，修正±0.4 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.5 --max-correction-mm 0.4 --execute

# 第4笔：D组，第1次，Kp=0.5，修正±0.8 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.5 --max-correction-mm 0.8 --execute

# 第5笔：E组，第1次，Kp=1，修正±0.4 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 1 --max-correction-mm 0.4 --execute

# 第6笔：F组，第1次，Kp=1，修正±0.8 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 1 --max-correction-mm 0.8 --execute

# 第7笔：F组，第2次，Kp=1，修正±0.8 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 1 --max-correction-mm 0.8 --execute

# 第8笔：E组，第2次，Kp=1，修正±0.4 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 1 --max-correction-mm 0.4 --execute

# 第9笔：D组，第2次，Kp=0.5，修正±0.8 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.5 --max-correction-mm 0.8 --execute

# 第10笔：C组，第2次，Kp=0.5，修正±0.4 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.5 --max-correction-mm 0.4 --execute

# 第11笔：B组，第2次，Kp=0.25，修正±0.8 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.25 --max-correction-mm 0.8 --execute

# 第12笔：A组，第2次，Kp=0.25，修正±0.4 mm
PYTHONPATH=src python scripts/run_nonlinear_ff_comparison.py --mode p --p-dynamics smooth --kp 0.25 --max-correction-mm 0.4 --execute
```

将任意命令末尾 --execute 改为 --dry-run 可预检；省略动作参数也默认为离线。真机仍需操作者逐笔输入RUN。原来不带扫描选项的 --mode p 保留旧Kp=2、±0.4 mm、5 mm/s、70 mm/s²、0.5秒参数，并保存至06目录。

扫描数据保存在 runs/brush2/<日期>/07_非线性前馈P参数扫描/raw/。目录名含Kp、幅值、动态配置、渐变时间、修正速度和加速度，自动编号；resolved.json/control 保存实际生效的完整参数。中止笔仍保留，后续按完整性核对有效重复次数。

本批6组之间只改变Kp和修正幅值。和旧06批次比较时，还包含修正速度、加速度和渐变时间的变化，不能把新旧差异单独归因于Kp。

离线回放只能验证在旧实测磁信号输入下能否满足指令限制，不能预测调整后的闭环响应。各组均需实测。分析使用完整40秒段，逐笔比较±20 µT比例、MAE、P95、>50 µT持续时间、实际修正幅值饱和比例及重复差，不按误差好坏挑选数据。

## 本次验证

- 15项新增CLI测试及29项相关入口/记录测试通过（44项）。
- 6组实际输入的离线预检通过；6组×4笔完整原始记录的指令回放全部通过，每次6600条指令。详情见 shadow_validation.json。
- 全套测试：3 failed, 768 passed, 7 skipped in 38.40s；下列为既有回原点测试失败（测试期待X−200，当前脚本X−370）：

- tests/test_return_to_origin.py::test_confirmed_return_sends_one_direct_move_to_code_defined_origin
- tests/test_return_to_origin.py::test_main_uses_hardcoded_connection_defaults_without_cli_arguments
- tests/test_return_to_origin.py::test_main_allows_return_from_140_mm_high_position

未连接或操作机械臂。
