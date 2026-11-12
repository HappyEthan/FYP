# HBS57 + AccelStepper 1.64.0 使用说明

## 安装

在 Arduino IDE 的库管理器中搜索 `AccelStepper`，选择版本 `1.64.0`。

## 当前引脚

- GPIO35：STEP/PU 控制
- GPIO36：DIR/DR 控制
- ENA、ALM：暂不使用

GPIO35/36 只能驱动外部 MOSFET、NPN、ULN 或光耦接口，不能直接接 HBS57 的 5–24 V 输入。

## 测试命令

```text
ARM
MOVE 100 100
STATUS
MOVE -100 100
STOP
DISARM
```

`MOVE` 是相对移动，单位是脉冲；第二个参数是脉冲/秒。1000 pulse/rev 时，`MOVE 100 100` 对应电机轴转 36°，约 1 秒完成。

## 极性调整

当前假设：GPIO 高电平使低侧接口导通。如果示波器确认 STEP 或 DIR 极性相反，修改：

```cpp
constexpr bool DIR_INVERT  = true;
constexpr bool STEP_INVERT = true;
```

先只改一个信号，并重新测试。
