# installation 配置填写说明

`validate_installation(..., hardware=True)` 要求全部 **35 个字段**非空且 `verified: true`。
`template.json` 故意全部留 `null`，它只能用于预览，不能用于真机执行。

填写后另存为 `configs/installations/<installation_id>.json`，不要把实测值写回模板。
该文件被 `.gitignore` 忽略，只在本地保留。

下面按"怎么取值"分三节：**必须现场实测**、**有历史候选但仍需复核**、**梯子实验的额外约束**。
三节合起来覆盖全部 35 个字段——**不要只填第一节的表格**，漏填会在硬件校验时被逐项拒绝。

## 必须现场实测

| 字段 | 含义 | 获取方式 |
|---|---|---|
| `installation_id` | 本次装配的标识 | 自定义，装配变更时更换 |
| `tcp_name` | 控制器中的 TCP 名称 | 控制器示教器读取 |
| `ucs_name` | 控制器中的用户坐标系名称 | 控制器示教器读取 |
| `tool_coord_si` | 工具坐标 `[x,y,z,rx,ry,rz]`（米/弧度） | 控制器读取后换算 |
| `user_coord_si` | 用户坐标 `[x,y,z,rx,ry,rz]`（米/弧度） | 控制器读取后换算 |
| `vertical_rpy_rad` | 笔杆垂直姿态（弧度） | 实测确认后填入 |
| `sensor_mount_id` | 传感器安装标识 | 传感器重新安装时更换 |
| `contact_z_mm` | **纸面零压接触的 TCP Z** | 实测。梯子第 0 档就是这一高度，是整条曲线的原点 |
| `pose_tolerance_mm` | 起始位姿位置容差 | 按现场稳定性确定 |
| `orientation_tolerance_rad` | 起始姿态容差 | 按现场稳定性确定 |
| `baseline_window_s` | 基线采样窗口 | 按现场噪声确定 |
| `baseline_timeout_s` | 基线超时 | 按现场确定 |
| `baseline_min_samples` | 基线最少样本数 | 按采样率确定 |
| `baseline_max_std_uT` | 基线三轴标准差上限 | 实测静置噪声后确定 |
| `baseline_max_drift_uT_s` | 基线漂移速率上限 | 实测静置漂移后确定 |
| `sensor_max_age_s` | 传感器样本最大年龄 | 按控制周期确定 |
| `max_tick_lateness_s` | 单拍最大迟到 | 根据 RUN 中实际调用与现场调度测量；当前 RUN 不逐拍调用 `HRIF_ReadActTcpPos`，见下 |
| `stop_timeout_s` | 停止超时 | 按现场确定 |
| `gripper_width_mm` / `gripper_speed` / `gripper_force` | 夹持参数 | 按已标定的夹笔参数 |
| `filter` | 控制滤波配置 | 与标定表必须一致 |

## 有历史候选值但仍需复核

以下数值来自历史交接，**不得直接沿用**，必须现场复核：

- `origin_x_mm` / `origin_y_mm`：候选 `-300` / `500`
- `wait_z_mm`：候选 `130`
- `workspace_min_mm` / `workspace_max_mm`：候选 X `[-400, 100]`、Y `[400, 600]`、Z `[17, 130]`

`contact_z_mm` 的历史候选曾出现 `30`、`36` 和 `40` 三个互相冲突的值。
这些数字仅保留为风险记录；**必须实测确认，不得沿用历史数字。**

## 梯子实验对 installation 的额外要求

- `transit_z_mm`（实验 JSON 中为 `50`）必须落在工作空间 Z 范围内。
- `max_depth_mm` ≥ `20`（梯子最深档）。
- `max_z_speed_mm_s` ≥ `approach_speed_mm_s`（接近与抬笔段）。
- `max_step_mm` ≥ 最大单拍位移：回程段 `return_speed_mm_s * 0.02 s`（当前 `30 × 0.02 = 0.6` mm）。
  **不是** `100 / return_speed_mm_s * 0.02`——那个式子量纲不对，算出 0.067 mm，按它填会被编译期
  `trajectory exceeds max_step_mm` 直接拒绝。推导：回程耗时 `travel / return_speed`，拍数是它除以 dt，
  故每拍位移 = `travel / 拍数 = return_speed * dt`，与 travel 无关。
- `max_xy_speed_mm_s` ≥ 实验 JSON 的 `motion.speed_mm_s`（当前为 `10`），
  **且 ≥ `return_speed_mm_s`**（回程段同样是 XY 运动，当前为 `30`）。
  即 `max_xy_speed_mm_s` 至少要 `30`；若实机安全的 XY 速度低于 `30`，
  应下调 `return_speed_mm_s` 而不是抬高这个上限。

## 三个速度/加速度字段怎么取

前面两节没有正面交代这三个字段的取值，但它们同样是必需的：

| 字段 | 含义 | 获取方式 |
|---|---|---|
| `max_accel_mm_s2` | 允许的最大加速度。实验 JSON 的 `motion.accel_mm_s2` 为 `null` 时，它直接作为整轮的加速度预算，决定每一段的加减速斜坡长度与最大单拍位移 | 按实机可用的安全加速度确定；过小会让各段斜坡变长、整轮变久 |
| `approach_speed_mm_s` | 接近与抬笔段的 Z 向速度（接触前的最后一段、以及抬离段） | 按接触过程的柔和程度确定；越慢越稳，但 16 趟各两次会显著拉长总时长 |
| `return_speed_mm_s` | 回程段的 XY 速度（在 `transit_z_mm` 高度返回起点） | 按实机安全的 XY 速度确定，且必须 ≤ `max_xy_speed_mm_s`，见上节 |

设好 `max_accel_mm_s2` 后建议先 `compile_experiment` 编译一次确认不报错再上机。

## 上机前必须核对的两件事

1. **RUN 阶段的节拍与位姿证据。** 当前真机适配器将 `realtime_state_reads` 设为 `False`；引擎在 50 Hz Servo 循环内不调用 `read_state()`。因此 `control.jsonl` 逐拍保存命令位姿，`actual_pose_available` 通常为 `false`，不能据此声称取得了实际 TCP Z。`PushServoP` 仍在同一循环中同步等待网络回复，当前 `transport_timeout_s` 未设置到底层 socket；`max_tick_lateness_s` 只能在调用返回后检测迟到，不能保证某次网络调用不会阻塞。若正式标定要求实际 TCP Z，应另行确定不阻塞伺服周期的采集与时间对齐办法，并核对精度；不能仅把命令 Z 改名为实际 Z。
2. **`contact_z_mm` 实测。** 梯子第 0 档的幅值应接近静置底噪（历史实测量级
   20–39 μT）；明显偏高说明该值标低，整条曲线不可用。
