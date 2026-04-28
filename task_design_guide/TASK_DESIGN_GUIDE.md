# Task Design Guide for AI Agents

Reference for AI agents that generate `todos.yaml` tasks for AutoAgent.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

1. **Root `description`** exists and:
(1) covers Goal, Architecture, Key file paths, Hard constraints, Rules;
(2) does not cover step-by-step instructions which should belong to `initial_hint`;
(3) does not include "potential/recommended approach" since AI can figure it out themselves. Doing this only narrows AI's creativity.
See §3 for full guidance.
2. **Every task** has `id`, `name`, `type`, `completion_criteria`.
3. **ID assignment**: top-level IDs are sequential integers; subtask IDs use dot notation (e.g., 1.1, 1.2).
4. **`*_once` types** (`simple_once`, `long_running_once`) can ONLY be subtasks, not top-level tasks.
5. **`long_running`** is used for any command that may take > 1 minute.

### Design Rules

I. Task Decomposition

6. **No over-decomposition**:
(1) keep logically dependent work in one subtask (e.g. when implementing tightly coupled modules A and B).
(2) Keep implement + build + test in one subtask so the AI can self-correct in the same session.
(3) Split tasks only at trust boundaries (e.g. anti-hack verification must be a separate subtask) or expensive/time-consuming checkpoints (See rule 7).
(4) 2-4 subtasks typical for one task. See §4.1.
7. **No under-decomposition**: separate expensive (e.g. idea composition, implementation) and time-consuming steps (e.g. training, benchmark, verification, reporting) into distinct subtasks. See §4.1.
8. **Search for fast-check build/test modes**: when merging implement + build + test in one subtask, search for fast-check/profile mode in build/test framework instead of running the full test/training. This will significantly speed up self-correction. Split long-running full test/training to subsequent benchmark task.
9. **Choose `nested` vs `looping` by evaluation behavior**: use `nested` to reach a target end state with overall AI evaluation/retry; use `looping` to run a fixed number of iterations without overall completion evaluation. See §4.1 and §5.2.
10. **State persistence**: write inter-task handoffs to named files; never assume the next task can see prior conversation context. See §4.7.
11. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed and left partial changes. Include prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures. See §4.6.

II. Task Fields

12. **`completion_criteria`** are specific, measurable, and verifiable by the AI —— not vague or subjective like "code is good". See §4.2.
13. **`initial_hint`** lists the exact paths, commands, prerequisites, scope boundaries, and handoff files needed for the task, but it must not duplicate `completion_criteria` or become a rigid click-by-click script. See §4.3.
14. **`system_prompt_prefix`** defines the AI persona, role, expertise, style, and hard behavior constraints for any task, but not a substitute for `initial_hint`. See §4.4 and §6.1.
15. **`max_attempts: 1`** is set on execution-only tasks (build, benchmark, test) that don't write code for fast failure propagation. Do not set `max_attempts: 1` on active coding tasks that benefit from retries. See §6.2.
16. **`model: "lite"`** is set on deterministic execution tasks; use default for most reasoning-heavy tasks like debugging, design, optimization, implementation, anti-hack review and keep/discard decisions. See §6.3.
17. **`git commit` is used** when each task or subtask completes.

III. Type-specific Guide

18. **Type-specific patterns**: choose the single guide in §7 matching the task domain before designing task boundaries.

### Anti-Hack Rules

19. **Negative constraints in `completion_criteria`**: For every "implement X" task, `completion_criteria` should explicitly state what must not happen (e.g. no weakened tests, no unrelated files, no API changes, no regressions, or no forbidden generated outputs).
20. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.
21. **Verification separation**: Separate "implement" from "verify" (e.g. verification, anti-hack check, static quality review) into different subtasks.
Verification subtasks must (a) check for negative constraints in rule 18; (b) use `system_prompt_prefix` to forbid code modification and `max_attempts: 1` for fast error propagation.

### ⚠️ Critical Pitfalls —— Must Double Check

22. Are inter-task handoffs written to named files instead of relying on conversation context?
23. Are completion criteria specific, measurable, and verifiable enough?
24. Does `completion_criteria` include negative constraints, and is there a verify task after each implement task for complex implementations?

---

## 2. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through tasks defined in `todos.yaml`.

1. **Fully autonomous —— No human is in the loop**

**Implication**: `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification.

2. **Context isolation between tasks and subtasks**

Tasks and subtasks **share the filesystem, not conversation context**. AI sessions are reset between tasks and subtasks. No response is passed between top-level tasks; only a summary of the previous subtask may be passed between subtasks.
**Implication**: design top-level tasks independently, and persist detailed intermediate results to files.

3. **Tasks execute in ascending ID order**

**Implication**: Assign IDs in the intended execution order, and make each task consume only files produced by earlier IDs.

4. **Failed tasks do not automatically block later work**

**Implication**: Add prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures.

5. **`long_running` is used to avoid AI session timeout**

**Implication**: Use `long_running` for builds, tests, benchmarks, training, profiling, or data jobs that can run >1 minute.

---

## 3. Root `description`

The root `description` is injected into every executor prompt. It should contain only shared context that most tasks need; put task-specific steps in `initial_hint`.

Include:
- **Goal**: final observable outcome and success threshold.
- **Architecture**: key directories/modules and their responsibilities.
- **Key file paths**: configs, inputs, outputs, reports, logs.
- **Key commands**: build/test/run/validate commands with required working directory, environment variables, and expected output locations.
- **Hard constraints**: files, APIs, tests, data, or behavior that must not change.
- **Rules**: project-wide behavior such as experiment discipline, allowed change size, or reporting format.
- **Reference Docs**: project documentation with reading priority. Keep paths and short reasons here; do not embed full document content.
  - **P0 Must Read**: read before starting any task; use only for essential architecture, API contracts, or safety constraints.
  - **P1 Read Before Related Work**: read before touching the related subsystem, file type, or feature area.
  - **P2 On Demand**: read only when debugging, blocked, or needing deeper historical/troubleshooting context.
- **Optional**:
  - Architecture Coupling Notes: exact files/modules that must be updated together.
  - Naming Conventions: required file, branch, metric, or artifact naming patterns.
  - Historical Result Files: paths to prior attempt/iteration outputs that should be read to avoid repeated work.

Do not include:
- **step-by-step instructions**: put them in task's `initial_hint`.
- **potential/recommended approach**: AI can figure it out themselves. Doing this only narrows AI's creativity.

---

## 4. Design Principles

These principles are not self-contained; they extend rules in §1. Take both principles and rules into account when designing todos.

### 4.1 Task Decomposition

Choose task boundaries by failure mode, context needs, and cost:

| Situation | Prefer |
|-----------|--------|
| Small targeted fix, format run, inspection, or quick test | One `simple` task |
| Multi-step goal with final success evaluation | `nested` |
| Fixed number of repeated experiments or trials | `looping` |
| Command may run >1 minute | `long_running` or `long_running_once` |

Difference between `nested` and `looping`:
- **`nested`**: reach a target end state; parent evaluates overall `completion_criteria` and can retry.
- **`looping`**: run exactly `repeat_count` iterations; do not rely on early overall-completion evaluation.

Recommended splits:
- **Analyze / compose idea**: separate when it produces a plan, hypothesis, or experiment design.
- **Implement + build/test**: keep together so the AI can self-correct.
- **Benchmark / validate / report**: group execution-focused evaluation together.
- **Anti-hack verification**: separate this from implementation because it is a trust boundary and must forbid code changes.

#### Anti-Patterns

- **Over-decomposition**: splitting `edit -> build -> fix build -> test` into separate subtasks will lose local reasoning context. Keep one coding loop together unless:
(1) The `test` command is long-running or verification must be isolated;
(2) Code has substantial changes that are not suitable to implement in one single session. In this case, split code changes by modules.

- **Under-decomposition**: putting everything (analysis, implementation, benchmark, anti-hack review, and reporting) into one task causes context explosion, degrading AI performance and wasting retries. Split when a phase has a separate artifact, high runtime cost, or different trust boundary.

### 4.2 `completion_criteria`

Completion criteria define observable success. They must be specific, measurable, and checkable by running commands, reading files, inspecting artifacts, or comparing metrics.

| Level | Role | Example |
|-------|------|---------|
| Top-level task | Final task success visible to the orchestrator | `doc/perf_result.tsv contains p95 latency and correctness status` |
| Subtask | Step-level pass/fail and retry boundary | `cargo test --all passes with no source changes in tests/` |
| Looping task | Overall goal context; iterations rely on subtask criteria | `Each iteration appends one row to results.tsv` |

Good:

```yaml
completion_criteria: |
  1. The project builds successfully: cmake --build build --config Release
  2. The executable outputs "Score: 100/100"
  3. doc/optimization_results.tsv contains p95 latency and correctness status
  4. git diff --name-only shows changes only under src/
```

Anti-patterns:

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| Prescribing methods | Locks the AI into one approach. | Describe the target outcome unless method is mandatory. |
| Describing implementation steps or repeating a to-do list | A to-do list is not success evidence. | State the artifact or observable result. |
| Unverifiable criteria | AI can claim success without proof. | Use command output, files, metrics, or diffs. |
| Missing negative conditions | Allows weakened tests or unrelated edits. | State forbidden changes explicitly. |

Bad: `"code is good"`, `"performance is improved"`, `"run tests and fix things"`.

### 4.3 `initial_hint`

`initial_hint` is executor-facing task-local context.

| Put in `initial_hint` | Do not put in `initial_hint` |
|-----------------------|------------------------------|
| Exact files/directories to inspect or modify | Project-wide context already in root `description` |
| Commands, working directory, environment, and output files | `completion_criteria` copied from the separate field |
| Step-specific constraints, scope boundaries, and forbidden changes | Obvious instructions such as "read carefully" |
| Prerequisite checks and handoff artifacts | Persona, role, expertise, or global behavior framing |
| Expected artifacts to read/write | Overly rigid click-by-click scripts or stale guesses |
| Cleanup guidance for previous failed attempts | Unrelated background docs |
| Likely failure modes and safe recovery hints | |

Use `initial_hint` to make retries safe: ask the executor to inspect `git diff`, generated files, partial outputs, and previous result files when relevant.

### 4.4 `system_prompt_prefix`

`system_prompt_prefix` defines the executor persona for the whole task session. It applies to analysis, implementation, verification, benchmarking, and reporting tasks.

Use it for:
- **Persona / expertise**: `You are a careful ML engineer.`
- **Role framing**: `You are a backend performance engineer.`
- **Style constraints**: `Prefer minimal, well-tested changes.`
- **Hard behavior constraints**: `Do NOT modify source code, tests, configs, or data.`

Keep task-specific files, commands, prerequisites, and handoff artifacts in `initial_hint`.

### 4.5 Anti-Hack Patterns

AI agents may satisfy criteria through shortcuts. Prevent that with explicit constraints.

Implementation tasks should specify:
- allowed files/directories;
- files/directories that must not change;
- tests/configs/data that must not be weakened;
- expected `git diff` shape when useful.

Verification subtasks should:
- be separate from implementation when anti-hack risk matters;
- use `system_prompt_prefix` to forbid code/test/config/data edits;
- use `max_attempts: 1` for fast failure propagation;
- use `model: default` when evidence review or reasoning is required;
- use `model: lite` when only running deterministic checks;
- verify both behavior and scope, e.g. tests pass and `git diff --name-only` stays within scope.

### 4.6 Failure Resilience

Design for residual state: tasks may inherit broken filesystem state from their own retries or from earlier linear tasks.

- **Same-task retry**: mention cleanup or residual-state checks in `initial_hint`; prefer overwriting or appending to known files over relying on implicit memory.
- **Predecessor failure**: add prerequisite checks in `initial_hint` and require explicit failure reports in `completion_criteria` when prerequisites are missing.
- **External tools/services**: allow partial success only when useful, and require failures to be documented.
- **Nested/looping subtasks**: align failure boundaries with meaningful checkpoints and independent failure modes.
- **Progress tracking**: store progress in clearly named files instead of relying on prior conversation context.

### 4.7 State Persistence

Tasks and subtasks share files, not conversation memory.

- **Producer**: write findings/results to named files with enough detail for a fresh session.
- **Consumer**: read those files via `initial_hint`; if missing or incomplete, report prerequisite failure.

---

## 5. Schema Reference

### 5.1 Root Fields

| Field | Required | Notes |
|-------|----------|-------|
| `description` | Required by task generation rules | Shared project context. Runtime accepts missing text, but generated tasks must include it. |
| `description@N` | Optional | Scoped description used for tasks with top-level ID >= N. |
| `tasks` | Yes | List of top-level tasks. |

### 5.2 Task Types

| Type | Top-level | Subtask | Use for |
|------|-----------|---------|---------|
| `simple` | Yes | Yes | AI work, quick commands, analysis, code changes. |
| `nested` | Yes | Yes | Ordered subtasks with overall AI evaluation/retry. |
| `looping` | Yes | Yes | Fixed `repeat_count` iterations. |
| `long_running` | Yes | Yes | Background command that may run >1 minute. |
| `simple_once` | No | Yes | One-time setup that should not re-run after completion. |
| `long_running_once` | No | Yes | Expensive one-time setup/baseline command. |

### 5.3 Common Task Fields

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | Top-level positive integer; subtask dot notation matching parent. |
| `name` | Yes | Concise human-readable label. |
| `type` | Yes | One of the task types above. |
| `completion_criteria` | Yes | Specific and verifiable. |
| `description` | Optional in linear mode | Useful short summary; required/recommended in AI scheduling mode. |
| `initial_hint` | Optional | Context for executor attempts. |
| `model` | Optional | `default`, `lite`, role name, or direct model name. |
| `system_prompt_prefix` | Optional | Persona, expertise, style, role, or hard behavior constraints. Set on subtasks, not top-level `nested`/`looping`. |
| `max_attempts` | Optional | Default from config. Use `1` for execution-only subtasks. |

### 5.4 Type-Specific Fields

| Type | Extra fields |
|------|--------------|
| `nested` | `subtasks` required; optional `max_attempts`. |
| `looping` | `subtasks` and positive integer `repeat_count` required; optional `max_attempts_per_loop`. |
| `simple` / `long_running` / `*_once` | Optional `initial_hint`, `max_attempts`, `model`, `system_prompt_prefix`. |

ID rules:
- Top-level IDs must be positive integers and, in linear mode, strictly increasing.
- Subtask IDs must be unique, dot-notated, parent-prefixed, and increasing under the same parent.

---

## 6. Field Usage Cheatsheet

### 6.1 `system_prompt_prefix`

Use for task-wide persona, expertise, role, style, and hard behavior constraints; keep task-specific files and commands in `initial_hint`.

| Need | Example |
|------|---------|
| Analysis / implementation persona | `You are a careful ML engineer.` |
| Domain/style | `You are a GPU performance engineer. Follow Google C++ style.` |
| Scope restriction | `Never modify files under vendor/.` |
| Execution-only | `You are a benchmark runner. Do NOT modify source code.` |
| Verification | `You are a verifier. Do NOT modify source code, tests, configs, or data.` |

### 6.2 `max_attempts`

| Value | Use |
|-------|-----|
| `1` | Execution-only subtasks: build, test, benchmark, lint, format-check, verify. |
| `2-3` | Targeted uncertain work with constrained scope. |
| Default / higher | Active coding, debugging, optimization, refactoring. |

Do not use `max_attempts: 1` for coding tasks that can self-correct after errors.

### 6.3 `model`

| Value | Use |
|-------|-----|
| Omit / `default` | Reasoning-heavy work: design, debug, implement, optimize, anti-hack review. |
| `lite` | Deterministic execution: run commands, format, copy/summarize known outputs. |
| Direct model/role | Only when explicitly required. |

Use `default` when reviewing evidence or making keep/discard decisions.

### 6.4 `long_running`

Use for commands that may exceed 1 minute: full builds/tests, training, profiling, data jobs, benchmarks, deployments.

| Command shape | Prefer |
|---------------|--------|
| Quick inspection or short unit test | `simple` |
| Full command may exceed 1 minute | `long_running` |
| Expensive setup/baseline should not rerun | `long_running_once` subtask |

---

## 7. Task-Type-Specific Guides

Read only the guide relevant to the task domain:

| Domain | Guide |
|--------|-------|
| Build, ship, bug fix, refactor | `build_and_ship.md` |
| Test running, verification, coverage | `testing_and_verification.md` |
| Profiling and optimization loops | `iterative_optimization.md` |
| Data pipelines / ETL | `data_pipelines.md` |
| Setup and deployment | `setup_and_deployment.md` |
| Research, analysis, reports | `research_and_analysis.md` |
| Academic experiments | `academic_experiments.md` |

---

## 8. Complete Example

Below is a complete linear-mode `todos.yaml` demonstrating key patterns: root `description`, reference docs, fixed-count `looping`, file-backed handoffs, anti-hack verification, failure resilience, `completion_criteria`, `initial_hint`, `system_prompt_prefix`, `model` selection, and retry boundaries.

```yaml
description: |
  # Project: Web API Performance Optimization

  ## Goal
  Iteratively optimize the REST API server to reduce p95 latency below 50ms
  while keeping all integration tests passing. Run a fixed number of focused
  optimization iterations, preserve evidence in files, and finish with a report
  that explains the best result and any remaining blocker.

  ## Architecture
  - src/handlers/ —— HTTP route handlers
  - src/db/ —— PostgreSQL query layer
  - src/cache/ —— Redis caching layer
  - tests/ —— integration test suite
  - benchmarks/ —— k6 load testing scripts

  ## Key File Paths
  - Config: config/server.yaml
  - Cumulative results: doc/optimization_results.tsv
  - Optimization log: doc/optimization_log.md
  - Implementation status: doc/implementation_status.md
  - Final report: doc/final_report.md
  - Benchmark script: benchmarks/load_test.js
  - Benchmark JSON output: results.json

  ## Key Commands
  - Build: cargo build --release
  - Test: cargo test --all
  - Benchmark: k6 run benchmarks/load_test.js --out json=results.json

  ## Hard Constraints
  - Do NOT modify public request/response schemas.
  - Do NOT remove, weaken, skip, or rewrite tests to hide failures.
  - Do NOT edit generated benchmark results by hand except to summarize them in docs.
  - Keep each optimization focused, reversible, and limited to its declared scope.

  ## Workflow State Conventions
  - doc/optimization_results.tsv rows include: iteration_id, kind, p95_ms,
    tests, decision, notes.
  - doc/optimization_log.md recommendations include: iteration_id,
    recommendation_id, status, allowed_paths, forbidden_paths, rationale,
    expected_impact, risk.
  - doc/implementation_status.md includes: iteration_id, recommendation_id,
    decision, changed_paths, build_status, test_status, verification_status,
    notes.
  - Each loop iteration should reuse the same recommendation when retrying after
    implementation or verification failure; do not create a new recommendation
    just because the previous implementation attempt failed.

  ## Reference Docs
  - P0 Must Read: doc/architecture.md —— request flow and service boundaries
  - P1 Read Before Related Work: doc/database.md —— read before changing src/db/
  - P1 Read Before Related Work: doc/cache.md —— read before changing src/cache/
  - P2 On Demand: doc/performance_history.md —— read when benchmark results are surprising or repeated work is suspected

  ## Rules
  - Fully autonomous: never ask the user questions.
  - Persist inter-task handoffs in the files listed above.
  - Implement at most one recommendation per loop iteration.
  - If prerequisites are broken before a task starts, report that state in the
    relevant output file instead of broadening scope.
  - If a retry inherits partial changes, inspect git diff before editing.

tasks:
  # ── Task 1: Establish Baseline ────────────────────────────────────────
  - id: 1
    name: "Build, test, and establish performance baseline"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. cargo build --release exits 0.
      2. cargo test --all exits 0.
      3. k6 benchmark completes and writes results.json.
      4. doc/optimization_results.tsv contains one baseline row with kind=baseline, p95_ms, tests=pass, and decision=baseline.
      5. No source files, tests, configs, benchmark scripts, or generated benchmark results are modified except results.json from the benchmark command.
      6. git diff --name-only shows only doc/optimization_results.tsv and results.json changed by this task.
    subtasks:
      - id: 1.1
        name: "Build and run tests without modifications"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a build engineer. Do NOT modify source code, tests, configs, benchmark scripts, generated data, or documentation.
        completion_criteria: |
          1. cargo build --release exits 0.
          2. cargo test --all exits 0.
          3. No files are modified.
        initial_hint: |
          Run:
          - cargo build --release
          - cargo test --all

          This is a verification-only subtask. If either command fails, report
          the failure and stop; do not edit files.

      - id: 1.2
        name: "Run baseline benchmark and record results"
        type: long_running
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. k6 benchmark exits 0 and writes results.json.
          2. doc/optimization_results.tsv exists and contains one baseline row with kind=baseline, p95_ms, tests=pass, and decision=baseline.
          3. Existing optimization rows, if any, are preserved.
          4. git diff --name-only shows only doc/optimization_results.tsv and results.json changed by this subtask.
        initial_hint: |
          Run:
          - k6 run benchmarks/load_test.js --out json=results.json

          Parse results.json for p95 latency. If doc/optimization_results.tsv
          already exists, preserve existing optimization rows and append or
          refresh only the baseline row. Do not modify source code, tests,
          configs, benchmark scripts, or unrelated docs.

  # ── Task 2: Fixed Iterative Optimization Loop ─────────────────────────
  - id: 2
    name: "Run fixed optimization iterations"
    type: looping
    repeat_count: 5
    max_attempts_per_loop: 3
    completion_criteria: |
      Each iteration completes this linear cycle: analyze current evidence,
      implement or reject exactly one recommendation, verify behavior and scope,
      then benchmark and evaluate the verified change.
    subtasks:
      - id: 2.1
        name: "Analyze bottleneck and write one recommendation"
        type: simple
        system_prompt_prefix: |
          You are a backend performance engineer specializing in Rust async services.
        completion_criteria: |
          1. doc/optimization_log.md contains exactly one new recommendation for the current iteration.
          2. The recommendation includes iteration_id, recommendation_id, status=unused, allowed_paths, forbidden_paths, rationale, expected_impact, and risk.
          3. The recommendation is not a repeat of an experiment already marked failed, reverted, rejected, or kept.
          4. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
        initial_hint: |
          Read doc/optimization_results.tsv and doc/optimization_log.md. Inspect
          only the relevant source files needed to understand the current
          bottleneck. Write exactly one focused recommendation for this loop
          iteration. Keep allowed_paths narrow enough for git diff --name-only
          verification in Task 2.3.

          If this loop iteration is being retried after Task 2.2 or Task 2.3
          failed, do not create a new recommendation. Reuse the current
          iteration's existing unused recommendation and make no changes unless
          the log is missing required fields.

      - id: 2.2
        name: "Implement or reject the latest recommendation"
        type: simple
        completion_criteria: |
          1. Exactly one latest recommendation with status=unused is either implemented or rejected.
          2. If implemented, cargo build --release exits 0 and cargo test --all exits 0.
          3. If implemented, git diff --name-only contains only files listed under allowed_paths for the recommendation plus doc/implementation_status.md.
          4. If rejected, no source/test/config changes remain and doc/implementation_status.md records the concrete safety or feasibility reason.
          5. doc/implementation_status.md records iteration_id, recommendation_id, decision, changed_paths, build_status, test_status, and notes.
          6. No tests, public schemas, benchmark scripts, generated benchmark outputs, or forbidden_paths are modified.
        initial_hint: |
          Read the latest recommendation with status=unused in
          doc/optimization_log.md. Respect its allowed_paths and forbidden_paths.
          Before editing, inspect git diff in case a previous retry left partial
          changes.

          If the recommendation is unsafe or infeasible, do not edit source
          code; write decision=rejected and the reason to
          doc/implementation_status.md. If implemented, keep the change minimal,
          then run cargo build --release and cargo test --all. Do not commit;
          Task 2.4 decides whether the change is kept or reverted.

      - id: 2.3
        name: "Verify implementation behavior and scope"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a verifier. Do NOT modify source code, tests, configs, benchmark scripts, generated data, or documentation files other than doc/implementation_status.md.
        completion_criteria: |
          1. doc/implementation_status.md exists and references the latest recommendation_id.
          2. If decision=implemented, cargo test --all exits 0.
          3. If decision=implemented, git diff --name-only contains only files listed under allowed_paths for the recommendation plus doc/implementation_status.md.
          4. No tests, public API schemas, benchmark scripts, configs, generated benchmark outputs, or forbidden_paths were modified.
          5. doc/implementation_status.md contains verification_status=pass, or the verifier records the exact failed check and stops with failure.
          6. Only doc/implementation_status.md may be updated by this verifier subtask.
        initial_hint: |
          Run verification only. Compare git diff --name-only against the latest
          recommendation's allowed_paths and forbidden_paths. If checks fail,
          record the exact failure in doc/implementation_status.md and stop;
          do not fix code in this subtask. A failed verifier should propagate
          failure so the loop retry re-enters the implementation step for the
          same recommendation instead of adding a nested evaluation layer.

      - id: 2.4
        name: "Benchmark and evaluate the verified change"
        type: long_running
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. If the latest recommendation was rejected, doc/optimization_results.tsv has an iteration row with decision=rejected and no benchmark is required.
          2. If implemented, cargo test --all exits 0 before benchmarking, or the latest result row records tests=fail and decision=reverted.
          3. If implemented and tests pass, k6 benchmark exits 0 and results.json contains p95 latency.
          4. doc/optimization_results.tsv has a new row with iteration_id, kind=optimization, p95_ms or n/a, tests, decision, and notes.
          5. If tests fail or p95_ms regresses by more than 5% versus the previous best kept row, only the latest implementation is reverted and the row has decision=reverted.
          6. If the change is kept, tests=pass and decision=kept, and no unrelated files are modified.
          7. doc/optimization_log.md marks the evaluated recommendation as kept, reverted, or rejected with the same iteration_id.
        initial_hint: |
          Read doc/implementation_status.md and doc/optimization_log.md. If the
          latest decision is rejected, append a rejected row to
          doc/optimization_results.tsv and update the recommendation status.

          If the latest decision is implemented, first run cargo test --all. If
          tests fail, revert only the latest implementation and record
          tests=fail, decision=reverted. If tests pass, run:
          k6 run benchmarks/load_test.js --out json=results.json

          Compare p95_ms to the previous best kept row in
          doc/optimization_results.tsv. Revert only the latest optimization when
          needed; do not modify unrelated files.

  # ── Task 3: Final Report ──────────────────────────────────────────────
  - id: 3
    name: "Write final optimization report"
    type: simple
    max_attempts: 1
    completion_criteria: |
      1. doc/final_report.md exists.
      2. The report includes baseline p95, best/final p95, test status, kept changes, reverted changes, rejected recommendations, and remaining blockers if any.
      3. The report is consistent with doc/optimization_results.tsv, doc/optimization_log.md, and doc/implementation_status.md.
      4. Only doc/final_report.md is modified by this task.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md, and
      doc/implementation_status.md. This is a reporting task only; do not modify
      source code, tests, configs, benchmark scripts, benchmark outputs, or
      result tables.
```
