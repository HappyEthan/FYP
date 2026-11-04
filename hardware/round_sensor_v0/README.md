# 圆形传感板历史工程

本目录已停止作为当前板卡入口。**2026-11-04 当前设计为 11 × 40 mm 四层长条笔杆板**，原 USB-C 位于尾端，电池焊盘同端，J4 在另一端。

- [当前板子的详细信息与操作指南](../pen_sensor_strip_v1/README.md)
- [当前原理图、PCB、网表和检查证据](../pen_sensor_strip_v1/CAD_HANDOFF.md)
- [当前工程审核包](../pen_sensor_strip_v1/deliverables/pen_sensor_11x40_4layer_3V3_junction_review_20261104.zip)

当前板已采用两路独立 I²C＋IMU 四线 SPI；SW1 强制选择 USB 或电池，所选电源缺失时不上电。原圆板的共用 I²C、IMU 地址 0x6A、USB 优先和 SW1 ON/OFF 操作不适用于当前板。

本目录中的原生源、制造审阅资料和归档保留作历史追溯，不用于当前长条板接线或下单。此前发布的说明可在 Git 历史中查看；发布前尚未提交的本地交接也已另作快照保存。
