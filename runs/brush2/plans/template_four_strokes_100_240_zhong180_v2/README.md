# brush2 四笔画执行说明

本目录是通过现有方向姿态执行器离线预检的 v2 候选计划。未连接硬件。

v1 的四条计划均在姿态角加速度检查中被拒绝，峰值分别为 82.88、40.49、54.32、45.01 °/s²，执行限制为 40 °/s²。v2 仅延长时间；每个原始支持点的 `s`、`xy`、`g_target`、`orientation` 均逐值保留，未提高执行器限值。

| STROKE | 笔画 | 时间倍率 | 接触书写时长 | 含进出笔、转场的运动时长 |
| --- | --- | --- | --- | --- |
| `heng` | 长横 | 3 | 127.38 s | 149.64 s |
| `shu` | 悬针竖 | 2 | 74.40 s | 97.54 s |
| `pie` | 斜撇 | 2 | 100.56 s | 123.16 s |
| `na` | 斜捺 | 2 | 72.80 s | 95.84 s |

运动时长之外还需启动基线采集。各笔单独运行、各自采集基线；四条路径占用同一中心区域，下一笔前更换纸张或留出干净区域。

## 输入与现场对应关系

执行入口为 `scripts/run_strokeplan_experiment.py`，需要同时提供 V3 计划、前馈表、现场设置和方向姿态进笔配置。

本次预检使用：

- 前馈表：`runs/brush2/plans/11_中字底横延长30mm_实测第9次/feedforward.json`。
- 现场设置：同目录 `settings.json`。
- 进笔配置：同目录 `entry_profile.json`，模式为 `directional_character`。
- brush2 旧安装信息：`TCP_brush` / `Base`；接触参考 Z = 40 mm。
- 等待位：XYZ = `[-370, 500, 130]` mm，RPY = `[0, 15, 0]` °。
- 纸面坐标朝向：图中右方对应机器人 +X，上方对应 +Y。
- 进笔倾角 30°、书写倾角 15°；接触旋转时反向移动 5 mm；书写姿态随平滑切线变化。

执行前核对这些旧现场参数与当前 brush2 装笔、TCP 和纸面相符。前馈表来自 +X、10 mm/s、固定 Ry15° 数据；这些曲线中的其他方向、较低速度和动态姿态仍沿用同一表，属于本次探索实验的假设，尚未验证实际笔宽。

## 先预检一笔

在项目根目录、已有 Brushbot Python 环境中运行：

```bash
cd /home/ethan/FYP
PLAN_DIR=runs/brush2/plans/template_four_strokes_100_240_zhong180_v2
SETUP_DIR=runs/brush2/plans/11_中字底横延长30mm_实测第9次
STROKE=heng

PYTHONPATH=src:. python scripts/run_strokeplan_experiment.py \
  "$PLAN_DIR/$STROKE/strokeplan.npz" \
  --feedforward "$SETUP_DIR/feedforward.json" \
  --settings "$SETUP_DIR/settings.json" \
  --entry-profile "$SETUP_DIR/entry_profile.json" \
  --control-mode feedforward \
  --record-actual-tcp \
  --run-label "template_${STROKE}_100_240_v2" \
  --dry-run
```

`--dry-run` 只编译、检查并显示等待位、Z 范围和时长，不连接硬件、不创建实验 run。

## 实际执行

先完成现场核对、手动沾水，并让机器人处于上述等待位。将同一命令最后的 `--dry-run` 改为 `--execute`。脚本显示执行信息后，在终端输入 `RUN` 才会连接硬件、采集基线并开始这一笔。

默认机器人 IP 为 `192.168.0.10`，传感器串口为 `/dev/ttyACM0`、115200 baud；不同现场连接可用 `--ip`、`--serial-port`、`--baud` 覆盖。

先用 `heng` 做一笔纯前馈，再查看纸面结果和磁记录；其余三笔把 `STROKE` 分别改为 `shu`、`pie`、`na` 后重复预检和单笔执行。运行结果保存在 `runs/brush2/` 下，包含计划与配置快照、磁记录和独立实际 TCP 记录。

## 离线证据

- [预检报告](preflight.json)：配置哈希、时长、空间范围和完整轨迹限值检查。
- `preflight/compiled_*.npz`：独立派生的名义轨迹；包含前馈 Z，不是目标 StrokePlan，也不是已执行命令记录。
- 各笔 `preview/`：V3 重新加载后生成的 CSV、三联图和输入哈希。
- [generate.py](generate.py)：从 v1 目标生成本次时间调整版的离线脚本。

此版的时间延长会影响纸笔接触过程；离线通过仅确认当前执行器约束，不能替代纸面结果和磁响应的实测。
