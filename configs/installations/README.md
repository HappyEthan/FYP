# installation 配置填写说明

`validate_installation(..., hardware=True)` 要求下列字段全部非空且 `verified: true`。
`template.json` 故意全部留 `null`，它只能用于预览，不能用于真机执行。

填写后另存为 `configs/installations/<installation_id>.json`，不要把实测值写回模板。

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
| `max_tick_lateness_s` | 单拍最大迟到 | **须先量 `HRIF_ReadActTcpPos` 单次耗时**，见下 |
| `stop_timeout_s` | 停止超时 | 按现场确定 |
| `gripper_width_mm` / `gripper_speed` / `gripper_force` | 夹持参数 | 按已标定的夹笔参数 |
| `filter` | 控制滤波配置 | 与标定表必须一致 |

## 有历史候选值但仍需复核

以下数值来自历史交接，**不得直接沿用**，必须现场复核：

- `origin_x_mm` / `origin_y_mm`：候选 `-300` / `500`
- `wait_z_mm`：候选 `130`
- `workspace_min_mm` / `workspace_max_mm`：候选 X `[-400, 100]`、Y `[400, 600]`、Z `[17, 130]`

`contact_z_mm` 历史候选为 `40`，但历史脚本使用 `START_Z = 36`、`ENTRY_Z = 30`，
三者不一致。**必须实测确认，不得沿用历史数字。**

## 梯子实验对 installation 的额外要求

- `transit_z_mm`（实验 JSON 中为 `50`）必须落在工作空间 Z 范围内。
- `max_depth_mm` ≥ `20`（梯子最深档）。
- `max_z_speed_mm_s` ≥ `approach_speed_mm_s`（接近与抬笔段）。
- `max_step_mm` ≥ 最大单拍位移：回程段 `100 mm / return_speed_mm_s * 0.02 s`。
- `max_xy_speed_mm_s` ≥ 实验 JSON 的 `motion.speed_mm_s`（当前为 `10`），
  **且 ≥ `return_speed_mm_s`**（回程段同样是 XY 运动，当前为 `30`）。
  即 `max_xy_speed_mm_s` 至少要 `30`；若实机安全的 XY 速度低于 `30`，
  应下调 `return_speed_mm_s` 而不是抬高这个上限。

## 上机前必须完成的两项测量

1. **`HRIF_ReadActTcpPos` 单次耗时。** 引擎每拍读一次实际位姿，若单拍总耗时
   超过 `max_tick_lateness_s`，运行会被 `deadline_miss` 中止。超预算时需把
   读取降频为每 N 拍一次。
2. **`contact_z_mm` 实测。** 梯子第 0 档的幅值应接近静置底噪（历史实测量级
   20–39 μT）；明显偏高说明该值标低，整条曲线不可用。