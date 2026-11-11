# Stroke Trainer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved offline dark desktop training, model-history and prediction tool.

**Architecture:** A pure Python classification package handles import, preprocessing, grouped validation, model bundles and storage. A PyQt5 five-page window uses a background process for training and asynchronous import; Matplotlib supplies consistent dark scientific plots.

**Tech Stack:** Python, NumPy, scikit-learn, joblib, PyQt5, Matplotlib.

**Spec:** docs/08-system-evaluation/2026-11-07-训练窗口简化交互与模型评分设计.md and the full numerical research specification.

## Global Constraints

- New training uses seven ordered strokes; old five-stroke sources cannot be silently relabeled.
- Fixed leave-one-run-out outer validation; all transformations and selection fitted on training side only.
- EMA 0.3, 128 normalized time points, first-10%-median fallback; direction validity 5µT, 90% and circular anchor R>=0.2.
- One history record per training task, multiple independently loadable models; recovery deletion never deletes input data.
- Ranking: fewer errors, higher worst-class recall, higher worst-run correct count. Equal results remain tied.
- Offline; no robot imports/connections; preserve existing user changes and historical model.

## Review Focus

- Incomplete/misordered/gapped input: refuse incompatible data without silently losing strokes.
- Duplicate copies of a run: reject duplicate sensor hashes as well as run identifiers.
- Invalid direction and insufficient groups: surface branch conditions without substituting algorithms.
- Cancel/crash/delete: never publish half-written models or delete training sources.
- Wrong model/score/projection provenance: saved metadata and UI always reference the selected model and sample.

## Task 1: Import and numerical contracts

Files: `src/brushbot/stroke_classification/{__init__,data,features}.py`; `tests/test_stroke_classifier_data.py`.

- [ ] Write and observe failing tests for a synthetic seven-stroke brushrun, duplicate sources, five-stroke rejection, time/baseline gaps and first10% invariance.
- [ ] Implement `load_experiment(path, config) -> Experiment`, sensor preprocessing, seven-stroke windows and A0/A1/A2/A4, D1/D2/D3.
- [ ] Run data tests, including real historical A1 parity read-only; preserve invalid-direction masks.

## Task 2: Grouped models and reports

Files: `models.py`, `training.py`, `metrics.py`; `tests/test_stroke_classifier_training.py`.

- [ ] Write failing tests proving run isolation, ranking ties, complete coverage and saved prediction round-trip on synthetic data.
- [ ] Implement masked training-only scaling, linear/RBF families F0–F4, nested leave-one-run-out selection and F3 training-side OOF score scaling; final full-data fit and PCA.
- [ ] Save OOF predictions/scores, splits, configurations, reports, branch/robustness statuses, full bundles and trained-side PCA; verify no fit in inference.

## Task 3: History and reuse

Files: `store.py`, `predict.py`; `tests/test_stroke_classifier_store.py`.

- [ ] Write failing tests for one task/many models, favorite/rename, recoverable individual and whole-task deletion, source preservation, cancellation publication and export.
- [ ] Implement atomic metadata and package persistence, model selection and score/overlap-aware experiment and single CSV prediction.
- [ ] Run round-trip and deletion tests; ensure unknown labels yield no accuracy.

## Task 4: Dark desktop UI

Files: `ui.py`, `plots.py`, `theme.py`, `scripts/train_stroke_classifier.py`, `requirements-stroke-training.txt`; `tests/test_stroke_classifier_ui.py`.

- [ ] Write failing offscreen UI tests for five pages, no manual audit/group/profile controls, grouped history and training-process cancellation.
- [ ] Implement five-page dark sidebar layout, automatic imports, model selection/advanced configuration, background training with progress, linked results/2D/3D plots, history and prediction scores.
- [ ] Verify actual rendered screenshots and synthetic end-to-end train/save/load/predict/rename/delete/restore flows, with no real experiment training launched automatically.

## Task 5: Delivery

- [ ] Run relevant tests and full project suite; record baseline/unrelated failures accurately.
- [ ] Fresh whole-change review, resolve important defects, document launch and input requirements.
- [ ] Deliver the runnable entry point, screenshot and verification report; no commit/push or changes to existing user work.

## Execution ledger

User explicitly authorized implementation; proceed in this session without another approval round.
Ruling: work in current `Tommy` checkout, adding isolated modules only, because existing uncommitted changes and live archives are required; do not switch branches or copy/remove user files. No git commit unless requested.
