---
project: 04-robot-control
status: active
---

# 开环写字说明

开环写字从汉字中线生成 XY 路径，按固定下笔高度和固定笔杆姿态执行，不读取磁触觉反馈。它是几何与机械臂运动的基线，不是现行 StrokePlan 文件执行入口。主要代码是[`examples/write_air.py`](../../examples/write_air.py)、[`hanzi.py`](../../src/brushbot/calligraphy/hanzi.py)、[`controller.py`](../../src/brushbot/controller.py)和[`huayan.py`](../../src/brushbot/backends/huayan.py)。

## 数据到动作

1. 从 `data/makemeahanzi/graphics.txt` 读取指定字的逐笔中线，将字体坐标缩放到字框并放到 Base 平面的目标位置。
2. 每笔生成抬笔到起点、在起点落笔、沿中线描画、在终点抬笔的路点；多字按横排布局，笔间移动位于抬笔高度。
3. `OpenLoopController` 按折线路径弧长和设定速度插值 XYZ；启动时读得的 TCP 姿态保持常量。
4. 先 `MoveL` 到起始抬笔位，再按 20 ms 周期将位姿通过 `PushServoP` 下发。控制器内部为 m/弧度，华沿接口边界转换为 mm/度。

中线不包含笔画宽度、提按或磁目标。下笔高度 `z_work` 在描画阶段固定；起笔下压与收笔抬起可能形成墨迹形状，但不能视为闭环笔法控制。

## 运行前准备与命令

使用已配置项目依赖的环境，从仓库根目录先做无硬件预览：

```bash
python examples/write_air.py --char 永 --z-work WORK_Z_MM --z-max CONTACT_Z_MM --z-min LOWER_Z_MM --dry-run
```

命令中的大写名称须替换为本次现场测得的数字。这三个 Z 值必须来自**本次**毛笔、装配、TCP 与纸面现场确认，满足 `z_min < z_work < z_max`；不能照搬旧文档的数值。`--hover-clearance` 默认 10 mm，抬笔高度是 `z_max + hover-clearance`。`--speed` 默认 18 mm/s，代码限制最大 60 mm/s；`--size` 与 `--gap` 同时给出或同时省略。可用 `--x0`、`--y0`、`--yaw` 和 `--x-min/--x-max` 指定布局及 X 限制。预览会打印笔数、路点、范围、总弧长和预计时长。

确认本次参数、夹持、姿态、起点和整条路径后，去掉 `--dry-run` 进入真机流程。脚本要求机械臂为 Standby(33)，检查当前 X 范围，打印方案，并等待操作者输入 `yes`；随后才 `MoveL` 到起点并开始伺服。此操作会真实移动机械臂。

## 保护与解释

- 脚本检查布局 X 边界，并在每拍把**命令** Z 钳到 `[z_min, hover]`。这不证明实际 TCP 严格处在该带内，也不检查整条路径的碰撞净空。
- 起始 `MoveL` 用位姿收敛判定到位；超时或拒绝运动会中止。伺服期间要留意示教器状态与节拍迟到；异常处理以实际脚本为准，不能假设任何异常都会自动抬笔。
- 旧的[`record_hanzi_openloop.py`](../../scripts/record_hanzi_openloop.py) 是另一条固定“永”字、带 Monitor 录制的实验入口：它有脚本内的 Z、姿态、等待位和 XY 范围，先 `--dry-run` 核对，不能与 `write_air.py` 参数混用。

需要沿笔画变化的磁目标和前馈/反馈 Z 时，使用[StrokePlan 执行](strokeplan-execution.md)及其独立配置。
