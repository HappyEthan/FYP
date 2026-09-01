# 交接文档：大寰 AG-160-95 电动夹爪（DHAG）+ HYGripper 插件操控

> 目的：让另一个项目/会话不依赖本仓库上下文即可通过华沿机械臂操控这台电动夹爪。
> 一切协议结论均为 **2026-08-28 真机实测**（Elfin E05 + 华沿控制柜 + DH AG-160-95），非纸面推断。
> 本文档路径：`docs/handoff-gripper-dhag.md`
> 配套机械臂交接文档：[`handoff-e05-arm.md`](handoff-e05-arm.md)（网络、MoveL/伺服、速度倍率等通用背景先看它）

---

## 1. 系统现状（2026-08-28 实测当时）

**全链路已验证通过**：笔记本 → 控制柜 TCP(10003) → HYGripper 插件 → ModbusRTU(RS485) → DH 夹爪。

| 项 | 值 | 说明 |
|---|---|---|
| 机械臂 | 华沿 Elfin E05 | 网络等通用信息见 `handoff-e05-arm.md` |
| 夹爪 | **大寰 DH AG-160-95** | 最大夹持力 160N，全行程 **95mm**，二指无旋转 |
| 夹爪侧接口 | ModbusRTU，ID=1，115200，8N1 | 出厂默认；接在机器人末端法兰 RS485 |
| 控制柜插件 | **HYGripper v3.6.1** | 示教器启用，1 个夹爪已注册 |
| 插件逻辑名 | **`hr_gri_plugins`** | HRApp 的第一个参数，固定 |
| 夹爪编号 | **GID = 1** | 真机确认有效编号从 **1 起**，GID=0 → 报错 60000 |
| 电脑有线口 | `enp3s0` 静态 `192.168.0.100/24` | 控制器 `192.168.0.10`，ping RTT ~0.15ms |

验收时的一个教训：夹爪没接好时命令报 **60002（连接失败）**，先查供电 / 485 线序 / 示教器插件连接参数，就会恢复（当日从 60002 → GRIPPEROK 就是这么修好的）。

## 2. 操控链路（三层）

```
你的代码 --HRApp(name,param)--> CPS.vendor (明文TCP 10003)
        --> 控制柜HYGripper插件 (libHR_hansgripper.so 解析命令)
        --> ModbusRTU 读写 DH 夹爪寄存器 (RS485)
```

- 唯一入口：`c.HRApp("hr_gri_plugins", f"{Cmd},{GID},...")`，vendor 拼成
  `HRAppCmd,hr_gri_plugins,<Cmd>,<GID>,<params>,;` 发到 TCP。
- 控制柜把命令路由给 `hr_gri_plugins` 插件，插件转成夹爪 Modbus 寄存器读写；**你不需要知道 Modbus 细节**。

## 3. 命令与协议（实测锁定）

### 3.1 移动命令（非阻塞，发起即返回）

```
GripperAbsCatchMove,<GID>,<pos>,<speed>,<force>
GripperRelCatchMove,<GID>,<delta_pos>,<speed>,<force>
GripperStop,<GID>
```

- **参数序 = pos, speed, force**（实测：`GripperAbsCatchMove,1,105,30,30` 成功执行）。
- **单位**：pos 是插件原始计数 **0–1000**，`width_mm = raw × 0.095`（每计数 95μm，全行程 95mm）。
- **极性**：raw 大 = **张开**；`raw=1000` 全开(95mm)，`raw=0` 全闭。→ 模块里 `open()=1000 / close()=0`。
- **力/速度**：DH 规格 speed ∈[1,100]、force ∈[20,100]（%），超范围插件会报错（60008/60009）或行为异常。

### 3.2 查询命令

```
IsMoving,<GID>              # 移动中=1，到位=0（完成判定靠轮询它，实测可靠）
GetCatchState,<GID>         # 0=未夹住，1=夹住（"夹住/完成"；带物件抓取还待实测）
GetCatchPosition,<GID>      # 当前位置 raw
GetConnectState,<GID>       # GRIPPEROK / GRIPPERFAIL
GetGripperErrorCode,<GID>
```

### 3.3 回复布局（vendor `sendAndRecv` 已剥命令名、OK→'0'、去尾 ';'）

| 形态 | 例 | 值在哪 |
|---|---|---|
| 查询成功 | `['0','GRIPPEROK','105']` | 值在 **索引 2** |
| 移动成功 | `['0','GRIPPEROK']` | 无值段 |
| 命令失败 | `['60002']` | 错误码在索引 0（单元素） |
| 连接失败查询 | 曾见 `['0','GRIPPERFAIL','60000']` | — |

注意：不是插件源码 wait 函数里看到的"值在索引 3"——那是给**裸 `sendAndRecv` 之后**的原始列表；本项目 vendor 已把布局规整成上面的形态。

## 4. 常用错误码（完整表在插件包 `GripperConfig/gri_ErrorCode.json`）

| 码 | 含义 | 处置 |
|---|---|---|
| 60000 | 无效参数 | 常见是 GID 用 0；从 1 起 |
| 60002 | 连接失败 | 查供电 / 485 线序 / 示教器连接参数 |
| 60005/60006 | 激活/初始化失败 | 查型号配置与电气 |
| 60007/60008/60009 | 位置/速度/力越界 | 按 DH 规格限幅 |
| 60015 | 夹爪不存在 | 换 GID |
| 60021 | 无效命令 | 命令名拼写/大小写 |
| 60025 | GID 超阈值 | — |

## 5. 坑清单（真机踩出来的）

1. **GID 从 1 起**，不是 0（配置文件 `gri_agent_cfg.json` 显示 gripper_num=0 只是模板缺省，会误导）。
2. **`position 0 = 全闭`**，别按直觉当"张开"写死 open=0（当初差点定反）。
3. **vendor `sendHRLog` 原版会崩**：回复为 Fail 时 `sendAndRecv` 调 XML-RPC(20000) 的 `HRLog`，这台控制器没实现该方法 → 抛 `xmlrpc Fault` 把真错误码（如 60002）盖成 traceback。**已补丁**：`sendHRLog` 用 try/except 包住（`CPS.py:2631`），日志失败不再阻断协议。别再退回原版。
4. 夹爪**上电前**查询一路 60002——先查硬件别先改代码（当日就是这么定位的）。
5. 控制器偶发对 10003 全命令空回复（几分钟的瞬时），稍等重连即可，不是代码问题。
6. 夹爪移动是准静态、单程 <1s，用简单超时轮询即可，不需要机械臂那套停滞检测。

## 6. 相关资料（绝对路径）

| 资料 | 路径 | 内容 |
|---|---|---|
| 夹爪插件 UI 手册 | `~/下载/HY Robot Gripper Plugin Instruction_EN(1).pdf` | 仅示教器插件**界面**用法（添加工爪/调试/拖编程），不含协议 |
| AG 系列 Modbus 手册 | `~/下载/AG-系列操作手册_V2.5MODBUS-版-.pdf` | AG-95 **寄存器表**（本节 7）；夹爪自身 RS485 协议 |
| HYGripper 插件包源码 | `~/文档/xwechat_files/wxid_ohyf1uadilvj32_42e6/msg/file/2026-08/HYGripper.zip` | Vue JS + `plugin_hr_gri_plugins.py`（wait 辅助函数）+ `libHR_hansgripper.so` + `GripperConfig/*.json`（型号表/错误码表） |
| 机械臂 SDK 手册 | 本地厂商手册（不纳入公开仓库） | CPS.py 对应手册（字段布局 +1 详见 handoff-e05-arm） |

插件 zip 里最有用的三件：`config.json`（逻辑名/gripper 名）、`GripperConfig/gri_ErrorCode.json`（错误码全表）、`plugin_hr_gri_plugins.py`（命令名与 wait 逻辑的参考实现）。

## 7. DH 夹爪自己寄存器表（手册抄录，备份用）

| 功能 | 地址 | 写 | 读 |
|---|---|---|---|
| 初始化夹爪 | 0x0100 | 0x01 回零 / 0xA5 重标定 | 0/1/2 初始化过程 |
| 力值 | 0x0101 | 20–100% | 当前设定力 |
| 位置 | 0x0103 | 0–1000 千分比 | 当前设定位置 |
| 初始化状态 | 0x0200 | — | 0 未初始化 / 1 成功 |
| 夹持状态 | 0x0201 | — | 0 运动 / 1 到达 / 2 夹住 / 3 掉落 |
| 位置反馈 | 0x0202 | — | 实时位置 |

（与插件配置 `DHAG *95μm 0..1000` 吻合。日常不用碰，插件全包了。）

## 8. 代码现状与下一步

**已在仓库**（未提交）：
- `examples/gripper_probe.py` — 原始协议探针：只读状态 / 绝对移动验证。已按实测修好值索引（查询值在 [2]）与 GID=1。
- `src/brushbot/backends/vendor/CPS.py` — `sendHRLog` 补丁（见坑 #3）。
- `tests/test_huayan_backend.py` — 新增 `test_fail_reply_returns_error_when_hrlog_raises`。全量 235 测试绿。

**待办（设计已定，未写 spec/未实现）**：
- 命令层模块 `src/brushbot/gripper.py`：`Gripper(client, gid=1, model="DHAG")`，API `open/close/move_to_width(mm)/move_rel/mm/stop/clear_fault/read→GripperState/wait_done`；单位 mm=raw×0.095、极性 open=1000/close=0、参数校验（speed 1–100 / force 20–100 / width 0–95）、回复解析三形态、错误码可读提示。
- 验收例子 `examples/gripper_test.py`：close → open → move_to_width(10)，每步 wait_done + 确认（对齐 `move_test.py` 安全模式）。

**带物件抓取（CatchState=1 语义）与真实夹持力**还没实测——加入抓取流程前提一下。

## 9. 二次 bring-up 清单（下次会话直接抄）

```
1. ping 192.168.0.10；nc -zv 192.168.0.10 10003
2. python examples/gripper_probe.py --once
   -> 期望三条查询都 ['0','GRIPPEROK',...]，Position 随当前开度
   -> 若报 ['60002']：夹爪没连上，查供电/线序/示教器插件参数
3. python examples/gripper_probe.py --move 30
   -> 应执行、回读 Position≈316，肉眼看到张开
4. 模块实现后改用 examples/gripper_test.py 自测
```
