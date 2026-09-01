# DH AG-160-95 Python 库使用说明

本库通过华沿控制柜的 HYGripper 插件控制夹爪，不需要电脑直连 RS485。
夹爪宽度统一使用毫米：`0 mm` 为全闭，`95 mm` 为全开。

## 安装

在仓库目录执行：

```bash
python -m pip install -e .
```

## 最小示例

```python
from brushbot.backends.vendor.CPS import CPSClient
from brushbot.gripper import Gripper, GripperError

client = CPSClient("192.168.0.10")
gripper = Gripper(client, gid=1)

try:
    gripper.open(speed=30, force=30)  # 命令为非阻塞
    state = gripper.wait_done(timeout=5.0)
    print(state.width_mm, state.error_code)

    gripper.move_to_width(10.0, speed=20, force=30)
    state = gripper.wait_done()
    print(state)
except GripperError as exc:
    print(f"夹爪操作失败: {exc}")
```

## API

- `open()` / `close()`：全开或全闭，非阻塞。
- `move_to_width(mm)`：移动到绝对开度，范围 `0..95 mm`。
- `move_rel(delta_mm)`：相对当前开度移动；正数张开、负数闭合。
- `stop()`：停止当前运动。
- `clear_fault()`：调用插件的 `GripperClearFault` 清错。
- `is_connected()` / `is_moving()`：读取连接或运动状态。
- `read()`：返回不可变的 `GripperState` 状态快照。
- `wait_done(timeout=5, poll_interval=0.05)`：等待到位并返回状态；默认超时后发停止命令。

速度必须为整数 `1..100`，力必须为整数 `20..100`。所有越界参数都会在发往
真机前抛出 `ValueError`。控制柜错误会抛出带错误码及可读原因的
`GripperCommandError`；异常回复会抛出 `GripperProtocolError`。

## 首次真机验收

先清空夹爪指间区域并把急停放在手边，然后运行：

```bash
python examples/gripper_test.py
```

脚本会要求输入 `yes`，之后依次全闭、全开、移动到 10 mm，并在每步打印回读状态。
只检查通信而不运动可运行：

```bash
python examples/gripper_probe.py --once
```

若出现错误码 `60002`，优先检查夹爪供电、RS485 线序以及示教器 HYGripper
插件的连接参数。
