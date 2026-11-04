# 历史圆板需求入口

圆板和早期 10 mm 双层长条方案已被后续用户需求覆盖。当前要求见 [长条板 AGENTS.md](../pen_sensor_strip_v1/AGENTS.md)，实际文件与检查状态见 [CAD_HANDOFF.md](../pen_sensor_strip_v1/CAD_HANDOFF.md)。

2026-11-04 当前设计为 11 × 40 mm、四层、原 USB-C 尾端轴向插线、电池同端、J4 在另一端；保留单页六格原理图、两路 I²C 与 IMU 四线 SPI。SW1 强制选择 USB 或电池，无自动回退，无板载充电。

旧圆板的尺寸、五页原理图、共用总线、USB 优先供电及 ON/OFF 定义仅在 Git 历史和本地快照中追溯，不再作为当前约束。
