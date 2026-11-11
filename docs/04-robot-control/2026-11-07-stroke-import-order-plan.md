---
project: 04-robot-control
status: active
---

# Stroke Import and Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 通用导入独立笔画，并通过界面调整执行顺序。
**Architecture:** 独立 brush_stroke_import 模块负责读取、配置快照、布局与原子合并；PathModel 暴露导入与排序接口，Qt 对话框负责勾选与参数。复用现有保存与执行链。
**Tech Stack:** Python、NumPy、PyQt5、pytest。
**Spec:** docs/04-robot-control/2026-11-07-stroke-import-order-design.md

## Global Constraints

保留当前未提交改动；在当前工作区实施，不提交混合改动。禁止运行硬件。右侧默认间隔 10 mm。保留现有随机场按 ID 独立、排序不重新抽样的约定。

## Review Focus

- 历史存档绝对路径失效或配置与归档目录不同：优先来源目录快照。
- 旋转缩放来源：按纸面毫米布局，转换后物理几何与姿态保持。
- 多笔选择、重复导入：独立 ID、来源顺序与内部间距保持。
- 取消、无选择、未完成起点和非法顺序：不留下部分变更。
- 排序后第一笔及转场：重新编译，导出与范围编号保持一致。

### Task 1: Model import and ordering

**Files:** scripts/brush_stroke_import.py, scripts/brush_path_editor_model.py, tests/test_brush_stroke_import.py
**Interfaces:** load_stroke_source(path) -> PathModel; PathModel.import_strokes(source, stroke_ids=None, side='right', gap_mm=10., offset_mm=(0.,0.)) -> list[str]; PathModel.reorder_strokes(order).
- [x] Write tests for preserved geometry/parameters, transformed layout, selective repeated import, configuration binding, atomic errors, ordering and persistence.
- [x] Run new tests and verify missing-feature failures.
- [x] Implement module and model interfaces, retaining source provenance.
- [x] Run model tests, including real final 永/横 import and reorder export.

### Task 2: Qt integration

**Files:** scripts/brush_stroke_import_dialog.py, scripts/brush_path_editor_ui.py, scripts/edit_brush_path.py, tests/test_brush_stroke_import_ui.py
**Interfaces:** StrokeImportDialog(target, source, parent=None) exposes candidate after accept; Editor.import_strokes(), Editor.move_stroke(step).
- [x] Write Qt interaction tests for modal import, cancellation, ordering buttons, undo and saved state.
- [x] Observe failures, add dialog and menu/buttons, commit focused edits before actions.
- [x] Run Qt and existing editor regression tests.

### Task 3: Documentation and verification

**Files:** docs/04-robot-control/brush-path-editor.md
- [x] Document import, configuration handling, layout, ordering and random batch behavior.
- [x] Run full pytest suite with offscreen Qt; record failures and distinguish pre-existing failures.
- [x] Review only task changes against the design and tests, resolve material findings, report results.
