# brushbot 源码入口

本目录包含触觉毛笔机器人的数据处理、笔画计划、控制与采集代码。项目的完整研究路线见仓库根目录 `plan.md`；此处不把早期仿真阶段当作当前真机操作说明。

- `experiments/`：梯子实验的轨迹、传感器接入与执行记录。
- `monitor/`：磁信号观察、基线处理和录制。
- `target_strokeplan.py`、`strokeplan_compile.py`、`feedforward.py`：当前目标计划、前馈配置和离线编译。
- `backends/huayan.py`、`runtime.py`：机械臂接口与运行时基础。真机执行须按现场配置和专用入口操作。
- `tactile/`：MuJoCo 接触仿真及平台无关的合成磁信号研究，不代表实测磁场或真机性能。

字形中线和轨迹算法位于 `calligraphy/` 与 `controller.py`；它们可用于不同执行链路，但不自行完成触觉反馈或前馈标定。当前工作以命令 TCP Z 与 `|ΔBxy|` 的重复对应关系为基础，再建立前馈表和可执行 StrokePlan。
