# 实时笔画识别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 制作兼容现有模型历史的深色桌面实时笔画识别工具。

**Architecture:** 独立采集控制线程维护连续预处理和分笔状态，单独推理线程以最终任务优先、最新中途快照覆盖待执行旧快照。Qt 主线程只展示快照和发出命令；模型加载在线程中完成。复用现有 ModelStore、FeatureConfig、extract、predict_strokes。

**Tech Stack:** Python 3.10+、NumPy、scikit-learn/joblib、PyQt5、pyqtgraph、pyserial、pytest。

**Spec:** `docs/08-system-evaluation/2026-11-11-实时笔画识别工具设计方案.md`，用户于2026-11-11批准实施并明确深色UI。

## Global Constraints

- 默认100ms中途推理；输入为本笔累计片段；最终独立复判。
- 默认共享 `outputs/stroke_classifier`，支持 `--store` 与现有ZIP导入；不修改训练算法。
- 落笔40ms、提笔120ms可调；首次阈值由用户确认，基线及至少100点预热后可识别。
- 连续EMA不在每笔重置；最终结果和相同数据/边界的原离线管线一致。
- 深色独立桌面窗口；不自动连接设备；不接机械臂。
- 保存原生数据、边界、预测及模型快照；异常不是正常提笔。
- 在当前工作区的新分支开发：需要复用尚未提交的分类器源码，保持原有改动，不纳入本次提交。

## Review Focus

1. 极短笔间离纸与阈值振荡：可调确认时间，确认起止位置不包含悬空等待。
2. 推理晚于下一笔/模型切换：历史最终结果仍正确归属，中途不串笔。
3. 外部删除模型或改名：列表刷新不切模型，冻结模型可完成已开始任务。
4. 长会话、原生时钟回绕/缺口和预热：有界缓存，连续特征等价，异常后等待离纸与预热。
5. 写盘失败与关闭时仍有最终任务：保留错误状态及已接纳最终任务，界面正常退出。

### Task 1: 连续传感器缓存与分笔

**Files:** Create `src/brushbot/stroke_recognition/__init__.py`, `core.py`; Test `tests/test_stroke_recognition_core.py`.

**Interfaces:** `SegmentConfig(down_threshold, up_threshold, down_ms=40, up_ms=120)`; `StrokeSegmenter.feed(seq,t,amplitude)` returns boundary events; `SensorBuffer(config).append(row)`, `.pin(seq)`, `.release()`, `.snapshot(first,last)` returns original extract-compatible arrays and continuous EMA state.

- [ ] 写并运行失败测试：抖动、取消提笔、两笔、起终点回溯、异常重置、时钟回绕、缓存裁剪后与prepare_sensor/extract数值一致。
- [ ] 实现无GUI核心，持续处理原生数据；默认最大笔长60秒、空闲缓存至少预热窗口，完整活跃笔有界保留。
- [ ] 验证 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_stroke_recognition_core.py` 通过。
- [ ] 仅提交本任务新文件。

### Task 2: 模型历史及异步预测

**Files:** Create `history.py`, `inference.py`; Test `tests/test_stroke_recognition_inference.py`.

**Interfaces:** `load_model(store,task_id,model_id)->LoadedModel` 包含固定bundle/原文件bytes/哈希/显示信息；`PredictionJob` 包含session/stroke/kind/model/record/first/last；`InferenceWorker.submit(job)`, `.results`, `.close()`。

- [ ] 写并运行失败测试：现有成果加载、SHA拒绝、五类范围、前缀再最终与离线预测一致、最终优先和最新快照替换、关机排空最终任务。
- [ ] 实现历史元数据适配和冻结模型加载；复用extract及predict_strokes，单推理worker/32个最终任务上限。
- [ ] 验证 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_stroke_recognition_inference.py` 通过。
- [ ] 仅提交本任务新文件。

### Task 3: 会话采集控制与保存

**Files:** Create `recording.py`, `controller.py`, `replay.py`; Test `tests/test_stroke_recognition_controller.py`.

**Interfaces:** `LiveController(output_root,source_factory=SerialSource)` 提供 `command(name,**args)`, `snapshot()`, `close()`；其快照包含connection/baseline/readiness/current/history/traces/errors/session_path；`SessionRecorder`持续保存原生帧/事件/结果与模型快照；`replay_final(session_dir)`复判已保存最终笔画。

- [ ] 写并运行失败测试：假串口真实帧进入两笔/异步最终、停止/断流中断、模型切换、磁场基线和预热、写盘故障、关闭排空及最终回放一致。
- [ ] 实现命令队列与独立采集控制线程、后台模型加载、会话保存；模型参数改变时建立明确处理epoch并重新预热。
- [ ] 验证 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_stroke_recognition_controller.py` 通过。
- [ ] 仅提交本任务新文件。

### Task 4: 深色窗口、入口及整体交付

**Files:** Create `ui.py`, `scripts/recognize_strokes_live.py`, `scripts/run_stroke_recognizer.sh`, `tests/test_stroke_recognition_ui.py`, `docs/08-system-evaluation/实时笔画识别工具使用说明.md`.

**Interfaces:** `RecognizerWindow(store,output_root,controller=None)` 展示模型树、传感器连接、阈值/间隔、曲线、当前/上一笔结果、判别分数和历史；CLI支持`--store`, `--output`, `--screenshot`, `--replay-session`。

- [ ] 写并运行失败测试：共享真实模型列表刷新/选择、ZIP入口、启动不自动连接、无阈值不可开始、深色布局及结果隔离、关闭线程清理。
- [ ] 实现Qt界面与入口；从项目根解析路径，QSettings保留选择和配置；2000ms模型刷新，50ms绘图刷新；窗口支持截图验证。
- [ ] 验证 `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_stroke_recognition_*.py` 及相关现有分类/传感器回归。
- [ ] 用现有真实模型和已保存实验只读回放，检查F0～F4的离线一致性与实际预测耗时；生成并查看深色窗口截图。
- [ ] 完成使用文档和验证记录，提交本次文件；进行一次独立代码审阅，修复重要问题并验证。

## 审查与执行记录

计划自查已覆盖设计各节；任务1→2共用extract-compatible snapshot，2→3共用LoadedModel/PredictionJob，3→4共用命令/快照接口。用户已明确开始制作，不重复请求执行许可。
