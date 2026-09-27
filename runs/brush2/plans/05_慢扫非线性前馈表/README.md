---
project: 04-robot-control
status: active
---

# 首版非线性前馈表：160–240 µT 试验准备

## 文件

- [feedforward.json](feedforward.json)：现有 V3 执行器可读取的独立前馈表，当前保留候选状态。
- [lookup_target_to_z.csv](lookup_target_to_z.csv)：目标 → 名义压深 → TCP Z。
- [forward_knots.csv](forward_knots.csv)：41 个节点及两笔源数据响应。
- [拟合图 PNG](非线性前馈表.png) / [PDF](非线性前馈表.pdf)。
- [渐进目标](01_gradual_160_240.npz)：160→240 µT，[预览](01_preview/stroke_00.png)。
- [单拱目标](02_arch_160_240_160.npz)：160→240→160 µT，[预览](02_preview/stroke_00.png)。
- [离线编译检查](trial_validation.json)：两条目标均通过现有通用执行器预检；不代表旋转进笔或真机效果已验证。

## 数据和方法

来源限定为 2026-09-25 两笔正常慢扫：14:28:57 第2次、15:02:32 第3次。两笔实际采用 Z38、Ry30→15 旋转接触，+X10 mm/s，30 s 下压扫描。未纳入异常慢扫、快扫回升或六笔局部扰动；不同接触历史不混成同一条标定曲线。

每笔 sweep_down 按 0.25 mm 名义压深分箱，每箱至少 5 个样本；各自插值到 d=5–15 mm、间隔 0.25 mm 的共同网格，再按两笔等权平均。两笔以及均值均已严格单调，无须强行更改节点。执行器用分段线性插值反查深度：整条响应关系是非线性的，不强行用单个 K 或高阶多项式。

- 表内幅值范围：72.517–323.539 µT；名义深度 5–15 mm，对应 Z35–25 mm。
- 源数据重复差 MAE：2.135 µT；两笔相对均值的内部拟合偏差 MAE：1.068 µT。两者均不等于目标跟踪误差，没有独立验证集。
- 适用上下文：brush2、Ry15/Rz0、+X10 mm/s、EMA α=0.3、原 TCP/UCS 与安装。不外推，60 µT 会被拒绝。
- **接触参考仍为 Z40 mm**，计算 Z=40−depth。Z38/Z36 是进笔高度，不能替换接触参考，否则全表会平移。

## 你选择的试验范围

| 目标 / µT | 名义压深 / mm | 前馈 Z / mm |
|---:|---:|---:|
| 160 | 9.908 | 30.092 |
| 180 | 11.098 | 28.902 |
| 200 | 11.737 | 28.263 |
| 220 | 12.532 | 27.468 |
| 240 | 13.106 | 26.894 |

160 µT 对应 Z30.09，略高于 Z30；保留用户选定的 160–240 µT，不擅自改成严格 Z≤30 的目标。

两条合成 V3 目标均为 +X400 mm、10 mm/s，书写时间 40.2 s，纸面起点沿用最近实验的 X−370、Y500 mm，终点 X30 mm。目标只含 XY/时间/磁响应，未将 Z 或表嵌入目标文件。

1. 渐进目标：前 30 mm 保持 160；30–330 mm 五次平滑升至 240；最后 70 mm 保持 240。
2. 单拱目标：前 30 mm 保持 160；30–200 mm 平滑升至 240；200–370 mm 平滑回到 160；最后 30 mm 保持 160。

建议实际试验顺序：渐进两次，再单拱两次，每次独立沾水与运行。比较稳态偏差、上升/回升误差、±20 µT 比例和严重偏离，启动段单独报告；不能把初始保持 3 s 自动当成已稳定。

## 当前执行边界

本次生成表、独立目标与离线预览，未连接机械臂，未改全局脚本默认前馈表。settings.json 从最新 completed 实验原样复制运行字段并附来源；不代表新增现场核验。

**已有通用 StrokePlan 执行器在固定 Ry15 下竖直降到起始 Z，不包含辨识脚本的“Z36、Ry30→15 旋转接触，再沿 X 加载”流程。** 本目录的 compiled.csv 和约 101 s 总时长是通用执行器的离线结果。正式试验入口仍需保持用户已确认的旋转接触流程，不能将这里的预检当作该流程已接通。

feedforward.json 的 approved / transient_approved 当前均为 false，遵循候选表生成方式；src/brushbot/feedforward.py 的 require_execution_approval 会拦截 --execute。这里的批准是试验采用确认，不是 ±20 µT 性能认证。本次没有为通过入口而更改批准标志，也没有执行运动。

源数据进笔为 Z38，后续为 Z36，且本表只有下压分支。单拱的回升段特意用于检验这张初版表在回程时的误差，不能预先假定上下行同样准确。

## 可运行的离线预检

在仓库根目录执行，命令不连接硬件：

```bash
trial_dir=runs/brush2/plans/05_慢扫非线性前馈表
PYTHONPATH=src python scripts/run_strokeplan_experiment.py   "$trial_dir/01_gradual_160_240.npz"   --feedforward "$trial_dir/feedforward.json"   --settings "$trial_dir/settings.json"   --record-actual-tcp --dry-run
```

第二条将目标文件替换为 `02_arch_160_240_160.npz`。

## 复现

reproduce_table.py 显式列出两笔正常慢扫，保存源文件 SHA256；需将 OUT 改为新的目录才可重跑。reproduce_targets.py 使用仓库的 V3 生成和编译 API。source_bins.csv 保留分箱统计，fit_metrics.json 保留指标。原始记录均未修改。
