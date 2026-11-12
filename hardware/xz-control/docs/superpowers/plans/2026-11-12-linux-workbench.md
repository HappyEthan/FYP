# Linux XZ Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Linux motor workbench with mouse/keyboard jogging, fixed moves, editable action functions and compatible CSV recording.
**Architecture:** Add an independent xz_workbench package alongside the existing console. A single background I/O thread owns motor/sensor ports and the deterministic motion coordinator; a bounded writer thread persists CSV. Qt only displays snapshots and submits commands.
**Tech Stack:** Python 3.10+, PySide6-Essentials 6.8.3, pyserial 3.5, unittest.
**Spec:** ../specs/2026-11-12-linux-workbench-design.md

## Global Constraints
- Preserve the old console and scripts; add files only.
- Preserve all 23 sensor.csv column names, order, units and meanings from windows_acquire.py.
- Arrow keys hold-to-jog; mouse supports continuous and fixed distance. Z positive means down.
- Zero only when idle and not recording; no automatic zero, arm or motion on connect.
- One motor-port owner, continuous PING, fresh GUI lease required for JKEEP, prioritized STOP.
- Sequential per-axis actions; ACK, done and matching idle state required before advancing.
- No real hardware motion or firmware upload during development.

## Review Focus
- Lost release/focus and keyboard auto-repeat must not leave motion running.
- Missing ACK, stale status and late completion must not advance a function.
- Serial aliases, changed calibration or origin must not silently change loaded function meaning.
- Slow/full storage and sensor loss while recording must stop motion and preserve partial output.
- Disabled/malformed/nonfinite/too-small steps and large coordinates must fail before motion.

## Task 1: Action models and persistent functions
Files: xz_workbench/model.py, tests/test_workbench_model.py.
Interfaces: AxisConfig, Step, Recipe; plan_steps(recipe,current,config) -> list[PlannedStep]; save_recipe/load_recipe.
- [ ] Write tests for mm conversion, relative/absolute/zero/wait semantics, disabled steps, invalid numeric values, save/load and changed configuration.
- [ ] Run tests and confirm missing implementation fails.
- [ ] Implement validation, planning and versioned JSON persistence; run tests to green.

## Task 2: Motion coordinator
Files: xz_workbench/engine.py, tests/test_workbench_engine.py.
Interfaces: Engine(send,clock), connect(status), packet(dict), request(name,payload), tick(); snapshot(). Model planning is consumed from Task 1.
- [ ] Write tests for ACK/done/final-position gate, wait and stop cancellation, lease loss, zero/record interlocks and stale links.
- [ ] Observe RED; implement deterministic coordinator and verify GREEN.

## Task 3: CSV recorder and baseline
Files: xz_workbench/recording.py, tests/test_workbench_recording.py.
Interfaces: Frame; Recorder(root,baseline,context), append(frame,stage,status), close(outcome,reason); SensorDecoder.feed; BaselineCollector.
- [ ] Write tests comparing actual saved CSV to original schema, raw/delta/spike values, time wrap/reset and partial failure output.
- [ ] Observe RED; implement bounded background writer and baseline handling; verify GREEN.

## Task 4: Device worker and demo
Files: xz_workbench/backend.py, tests/test_workbench_backend.py.
Interfaces: Worker.submit(name,**payload), lease(), events queue, shutdown(); owns Engine and Recorder.
- [ ] Write tests for demo without serial, recording ownership, first-sample gate, disconnect, sensor timeout, command ordering and output.
- [ ] Observe RED; implement motor handshake, sensor decoder, worker loop, recording and clearly labelled simulator; verify GREEN.

## Task 5: Qt workbench
Files: xz_workbench/ui.py, xz_workbench/__init__.py, xz_workbench/__main__.py, tests/test_workbench_ui.py.
Interfaces: Window(worker=None), recipe table, controls, event filtering, polling snapshots.
- [ ] Write offscreen UI tests for keyboard hold/release/repeat/focus, mouse modes, editor row order, input locks and thread shutdown.
- [ ] Observe RED; implement interface and run tests to GREEN.

## Task 6: Linux launcher, documentation and release verification
Files: start_linux_workbench.sh, linux_workbench.py, LINUX_WORKBENCH.md.
- [ ] Implement LF executable launcher and startup help; document setup, units, origin, recipes, CSV and limits.
- [ ] Run original and new unittest suites, shell syntax, demo end-to-end capture and Qt offscreen render.
- [ ] Request one independent final review; fix important findings with regression tests.
- [ ] Copy only added deliverables into the user project and re-run verification there.

## Execution ledger
Ruling: Work from a snapshot of the user's dirty source in the native isolated FYP worktree; only new files are delivered back, so no existing modifications are overwritten.
Ruling: User has approved the design and explicitly asked to implement; continue inline without another approval round. Preserve task checkpoints in this plan rather than committing a snapshot of unrelated user changes.

Task 1: complete — action models and persistent functions; RED missing module → GREEN, 6 model tests.
Task 2: complete — deterministic command/arrival gates and leases; RED missing module → GREEN, 10 engine tests.
Task 3: complete — streaming compatible CSV, baseline and decoder; RED missing module → GREEN, 4 recording tests.
Task 4: complete — device worker and simulator; includes real transport framing against a simulated firmware serial boundary.
Task 5: complete — Qt UI implemented and tested, then revised at user's explicit request to simplify and use a dark theme.
Ruling: User requested a simpler dark interface during implementation. Use separate manual/function pages, on-demand connection/parameter/coordinate/capture panels and hidden logs. All approved functions remain available.
Ruling: Settings panels are nonmodal, and Space stops from all owned panels — keeping stop accessible matters while an automatic function is running.
Task 6: complete — independent review findings fixed; delivered 16 new code/test/guide/plan files without changing 39 preexisting source/document files. Delivered-path full suite: 88 tests passed. Launcher shell syntax and --help passed. Both dark UI pages rendered from delivered source with simulated devices only.
Final review: three important findings, all reproduced before fixing: split initial handshake, unreserved first-sample preparation, ignored controller fault during idle recording.
Final: fixed split handshake — test_hello_and_initial_status_can_arrive_in_separate_reads RED→GREEN.
Final: fixed preparation ownership — test_waiting_for_first_sample_reserves_motion_owner RED→GREEN.
Final: fixed recording fault/reference handling — test_idle_recording_fault_stops_and_reports_abort and test_recorded_reference_invalidation_is_not_silently_accepted RED→GREEN; unarmed recording remains supported.
Final verification: QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v — 88/88 passed in the delivered directory. Hardware direction, calibration and braking distance remain unverified without physical equipment. No product source file from the old console was changed, no firmware uploaded, no physical serial device opened.
