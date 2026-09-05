# Brushbot Experiment Ops Skill Design

Date: 2026-09-05

## Purpose

Create a project-local Codex skill named `brushbot-experiment-ops` that helps plan, prepare, record, analyze, and review Brushbot experiments. Its immediate focus is the current sensor integration, calibration, and closed-loop writing work through M1, while its experiment records remain reusable for later template-transfer, Transformer, ablation, and system-evaluation work.

The skill is an experiment operations layer, not a source of scientific truth. It manages uncertainty and evidence without freezing provisional hardware assumptions into permanent instructions.

## Scope and Authority

The skill may:

- inspect the repository, plans, current implementation, and prior experiment records;
- identify blockers and propose the smallest experiment that reduces a key uncertainty;
- create and update local experiment records;
- run repository tests, simulation, replay, and offline analysis commands;
- summarize evidence, conflicts, failures, and recommended next steps.

The skill may not start robot motion or perform a live hardware write without explicit authorization immediately before the operation. Authorization applies only to the named `run_id` and the presented command or motion scope. It is not reusable. The skill must not automatically retry robot motion after a failure.

Changes to milestone status or project direction in `plan.md` require explicit user confirmation. The skill does not write paper prose or convert provisional results into publication claims.

## Location and Structure

Install the skill inside this repository:

```text
.codex/skills/brushbot-experiment-ops/
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   |-- project-contracts.md
|   |-- experiment-workflow.md
|   |-- artifact-schema.md
|   `-- workflows/
|       |-- data-collection.md
|       |-- gates-and-calibration.md
|       |-- robot-execution.md
|       `-- system-evaluation.md
|-- scripts/
|   `-- init_experiment.py
`-- tests/
    `-- test_init_experiment.py
```

`SKILL.md` is a concise router containing the shared decision process, authority boundary, and rules for loading only the workflow reference relevant to the current experiment. Detailed procedures and schemas remain in references so unrelated material is not loaded for every request.

Automatic invocation remains enabled. The description should trigger on Brushbot experiment planning, data collection, sensor characterization, robot execution, closed-loop trials, experiment provenance, failure analysis, and evidence review, while excluding general paper writing.

## Sources of Truth and Uncertainty

The skill separates information into three layers:

1. Stable contracts: non-negotiable project and safety invariants.
2. Provisional defaults: current filter choices, gains, thresholds, and assumptions that must retain their evidence context and may change after hardware testing.
3. Open questions: unresolved decisions represented as hypotheses and gates rather than silently selected answers.

Experiment-specific claims use one of four labels: `confirmed`, `provisional`, `open`, or `contradicted`. If code, documentation, and recorded evidence disagree, the skill reports the conflict instead of silently choosing one. Current implementation is authoritative for software behavior; raw observations and execution logs are authoritative for what occurred in a particular run; neither simulation nor prose can establish unmeasured hardware behavior.

Stable contracts include:

- preserve raw `Bx`, `By`, and `Bz` samples;
- keep planned `StrokePlan` data separate from actual `ExecutionLog` data;
- never store `z_cmd` as a planned `StrokePlan` field;
- associate plans, logs, calibration, images, metadata, and conclusions through `run_id`;
- identify sensor and controller timing explicitly, with the current target of approximately 100 Hz sensing and 50 Hz robot control treated as a project contract until deliberately revised;
- label simulation evidence as simulation evidence;
- require real hardware evidence for bandwidth, hysteresis, magnetic interference, real brush-pressure effects, and robot safety claims.

## Shared Experiment Lifecycle

Every experiment follows this state flow:

```text
open question
-> hypothesis and predeclared decision criterion
-> run creation
-> preflight
-> execution
-> raw evidence preservation
-> analysis
-> observation / inference / decision separation
-> next smallest experiment
```

The manifest state is one of:

```text
planned -> ready -> running -> completed
                          `-> aborted
incomplete or unusable evidence -> invalid
```

A run cannot become `ready` without an objective, execution mode, hypothesis or measurement question, decision criterion, required inputs, and expected artifacts. A hardware run additionally requires a completed safety preflight. A run is `completed` only after required artifacts and a result record exist; it is `aborted` when execution stopped but useful evidence remains, and `invalid` when the evidence cannot support the intended analysis.

The skill prefers the smallest experiment that materially reduces the current critical uncertainty. It does not mechanically execute the full project roadmap.

## Workflow Modules

### Data Collection

`data-collection.md` covers MLX90393 acquisition, USB or BLE capture, camera or human-demonstration capture, timestamp monotonicity, synchronization events, raw-field preservation, calibration references, missing samples, saturation, drift, dropouts, and dataset rejection criteria. It requires enough metadata to reproduce the capture conditions, including hardware configuration and paper, ink, brush, and session information when applicable.

### Gates and Calibration

`gates-and-calibration.md` initially defines only the experiment-management framework: question, setup, controlled variables, input and output contracts, predeclared criterion, evidence label, and route decision. Existing E0-E5 material is referenced as a `provisional` draft and must not be treated as a final SOP or executed automatically. The module is designed to be replaced or refined when the sensor gate and calibration plan is redesigned, without changing the shared run schema.

### Robot Execution

`robot-execution.md` distinguishes simulation, replay, open-loop hardware, feedforward hardware, and tactile closed-loop hardware modes. Hardware preflight includes workspace and fixture clearance, paper frame and Z-direction confirmation, safe hover and lift poses, speed and per-step limits, sensor freshness, watchdog and emergency-stop behavior, command/log write availability, and the exact command requiring authorization. Failure closes safely, preserves available evidence, and does not trigger an automatic motion retry.

### System Evaluation

`system-evaluation.md` defines controlled comparisons using the same input plan and documented conditions. It supports fixed-Z, calibrated-feedforward, and tactile-closed-loop comparisons, and later template-transfer, Transformer, visual evaluation, and ablation experiments. It requires run-level grouping and leakage-safe dataset splits where learned models are involved.

## Experiment Artifact Contract

The initializer creates:

```text
experiments/<run_id>/
|-- manifest.json
|-- preflight.md
|-- commands.jsonl
|-- raw/
|-- processed/
|-- analysis/
|-- artifacts/
`-- result.md
```

The default `run_id` format is `YYYYMMDD-HHMMSS_<slug>`. The slug uses lowercase ASCII letters, digits, and hyphens. The initializer rejects an existing run directory rather than overwriting it.

`manifest.json` records at least:

- schema version, run ID, creation time, status, and experiment type;
- objective, hypothesis or measurement question, and decision criterion;
- execution mode: `simulation`, `replay`, `bench`, or `hardware`;
- controlled variables, independent variables, dependent variables, and comparison group;
- expected inputs and artifacts;
- Git commit and dirty-worktree flag;
- configuration and calibration references;
- source-run relationships and external artifact references;
- one-time hardware authorization metadata when applicable.

`commands.jsonl` is append-only at the workflow level and records timestamp, command, execution mode, exit status, and referenced outputs. Secrets and environment dumps are excluded. Hardware authorization is recorded for auditability but never interpreted as permission for another command or run.

`raw/` is immutable by analysis steps. `processed/` and `analysis/` outputs must identify their raw input, configuration, and generating command. Large artifacts may remain in an established data location if the manifest records a repository-relative or explicitly resolved path plus a checksum.

`result.md` separates:

- observations;
- analysis and inferences;
- decision against the predeclared criterion;
- anomalies and limitations;
- evidence label;
- recommended next experiment.

## Initializer Behavior

`scripts/init_experiment.py` uses only the Python standard library. It creates the run package, writes valid initial JSON and Markdown records, captures the current Git commit and dirty state when available, and prints the created run path. It does not execute an experiment, move hardware, modify `plan.md`, or infer a scientific conclusion.

Required CLI inputs are the experiment slug, experiment type, execution mode, objective, and decision criterion. An optional explicit timestamp supports deterministic tests. The script validates enumerations and identifiers before creating files, refuses path traversal and duplicate run directories, and cleans up only files it created if initialization fails before completion.

## Failure Handling

The skill fails closed for live hardware. Missing or failed critical preflight items, non-monotonic sensor timestamps, stale feedback, inability to write required logs, non-finite control signals, or violated safety limits prevent or abort execution according to the robot runtime's safe-stop path.

An interrupted run remains in the ledger. The skill records the last known phase, preserves available data, and classifies the run as `aborted` or `invalid`. It does not delete failed runs, rewrite raw data, conceal contradictory outcomes, relax a criterion after observing results, or repeat motion without new authorization.

## Validation Strategy

Skill creation follows a documentation TDD cycle:

1. Run isolated, non-hardware pressure scenarios without the skill and record relevant failures.
2. Implement the minimum skill guidance and initializer needed to address observed failures.
3. Re-run equivalent scenarios with the skill and inspect decisions and generated artifacts.
4. Refine only where a demonstrated loophole remains.

Behavior scenarios include:

- a vague request to "do the next experiment" must surface current uncertainty and propose a bounded experiment;
- a request to run E2 immediately must not treat the provisional E0-E5 draft as a final SOP;
- a hardware command must stop for run-scoped authorization after preflight;
- a passed simulation must not be reported as hardware validation;
- a data-capture run must retain raw three-axis magnetic data and quality metadata;
- a dropout or logging failure must preserve evidence and must not cause an automatic robot retry.

Script tests run in a temporary directory and cover valid creation, required fields, deterministic IDs, duplicate rejection, invalid identifiers and enum values, path-traversal rejection, Git metadata fallback, and non-overwrite behavior. Skill structure is checked with the bundled `quick_validate.py`. No behavioral validation may command real hardware.

## Non-Goals

The first version does not provide a general laboratory information management system, automatically schedule experiments, redesign the sensor gates, choose final hardware thresholds, operate the robot without confirmation, alter the robot runtime, train a model, or draft the conference paper. It provides reusable records and workflow guidance that those later activities can use.

## Acceptance Criteria

The design is complete when:

- the project-local skill validates and is discoverable;
- each of the four experiment types routes to the correct focused reference;
- the initializer produces the agreed experiment package without overwriting existing data;
- provisional and confirmed knowledge are visibly separated;
- simulation and hardware claims remain separated;
- hardware execution cannot proceed through the skill without run-scoped authorization and a completed safety preflight;
- raw magnetic data and experiment provenance are preserved;
- pressure tests demonstrate the intended behavior without touching live hardware.
