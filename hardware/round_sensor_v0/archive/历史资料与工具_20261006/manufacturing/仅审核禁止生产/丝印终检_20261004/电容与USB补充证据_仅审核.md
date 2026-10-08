# 电容与 USB 补充证据｜仅审核，2026-10-04

## C9/C10：新增支持证据，不等于已经不合格或已完全闭合

当前精确型号 GRM155R61A105KE15D，1 µF、10 V、X5R、0402。Nordic 原厂《Power Supply Decoupling Capacitor Selection》引用 Murata SimSurfing：同系列 GRM155R61A105KE15 在 3 V DC 下典型容量变化 −20%；另一个例子在 3 V DC、10 mV AC、−40～85°C 条件下给出约 0.71～0.73 µF 下限。该证据说明不能仅凭“0402、1 µF”判定容量不足，也不应盲目换成同尺寸更大标称容量。

当前 C10 为 3.3 V，C9 在 USB 供电时约为 VBUS 减 D4 压降。上述 3 V 数据不能替代这两个工作点下包含容差、温度及老化的有效容量核算。TLV755 的 >0.47 µF 要求沿用已存 TI 手册。下一步应取得该精确系列的工作电压曲线并计算裕量；如不足，再选有明确曲线的替代料并核对封装/BOM。当前未更换电容，也未确认现料必然失败。

来源：
- [Nordic：DC bias](https://docs.nordicsemi.com/r/bundle/nwp_030/page/wp/nwp_030/dc_bias.html)
- [Nordic：0402 REG0 example](https://docs.nordicsemi.com/r/bundle/nwp_030/page/wp/nwp_030/nrf52840_example_reg0_0402.html)

## USB：区分自供电应用和下载验证

本轮重新读取 Espressif ESP-IDF v6.0 官方 USB Device Stack：电池自供电 USB 应用应经电平转换检测 VBUS，GPIO 应在拔线后 3 ms 内检测到低。当前 PCB 没有这一通路，前轮缺口结论保持。这不能直接推导为 ROM USB Serial/JTAG 下载一定失败；下载功能仍须首板验证。

固定约 109 mA 充电及没有充电禁止控制的发现仍有效。降低充电电流不能单独保证整机枚举前或暂停电流。后续具体方案需同时列明：VBUS 检测、掉电隔离/放电、复位默认禁止充电、总输入电流预算，以及固件状态。只有 GPIO 分压草图不足以宣布电源/USB收尾。

本项目 AGENTS.md 要求新增功能器件/电源架构变更前列明障碍、收益、代价并由用户决定；所以当前没有新增检测器件、改变充电器或覆盖原理图。先完成有确切器件、阈值、默认状态和局部布置的方案，再请求决定。

来源：[Espressif USB Device Stack, Self-Powered Device](https://docs.espressif.com/projects/esp-idf/en/v6.0/esp32s3/api-reference/peripherals/usb_device.html#self-powered-device)。现有逐脚和充电证据见上一级 `整板复审_20261004/electrical_review.md`。
