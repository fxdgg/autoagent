# Task Design Guide for AI Agents

Reference for AI agents that generate `todos.yaml` tasks for AutoAgent.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

1. **Root `description`** exists and:
(1) Covers Goal, Architecture, Key file paths, Hard constraints, Rules;
(2) Does not cover step-by-step instructions;
(3) Does not include "potential/recommended approach" (unless the project requires) since AI can figure it out themselves. Doing this only narrows AI's creativity.
See §3 for full guidance.
2. **Every task** has `id`, `name`, `type`, `completion_criteria`.
3. **ID assignment**: top-level IDs are sequential integers; subtask IDs use dot notation (e.g., 1.1, 1.2).
4. **`*_once` types** (`simple_once`, `long_running_once`) can ONLY be subtasks, not top-level tasks.
5. **`long_running`** is used for any command that may take > 1 minute.

### Design Rules

I. Task Decomposition

6. **No over-decomposition**:
(1) Keep logically dependent work in one subtask (e.g. when implementing tightly coupled modules A and B).
(2) Keep implement + build + test in one subtask so the AI can self-correct in the same session.
(3) Split tasks only at trust boundaries (e.g. anti-hack verification must be a separate subtask) or expensive/time-consuming checkpoints (See rule 7).
(4) 2-4 subtasks typical for one task. See §4.1.
7. **No under-decomposition**: separate expensive (e.g. idea composition, implementation) and time-consuming steps (e.g. training, benchmark, verification, reporting) into distinct subtasks. See §4.1.
8. **Search for fast-check training/profiling modes, if it is long-running**: 
when merging implement + build + test into one subtask, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor) when it is long-running.
The key insight is to ensure correctness in implementation before the next task runs full time-consuming training/profiling, while significantly speed up self-correction in implementation task.
9. **Choose `nested` vs `looping` by evaluation behavior**: use `nested` to reach a target end state; use `looping` to run a fixed number of iterations. See §4.1 and §5.2.
10. **State persistence**: write inter-task handoffs to files; never assume the next task can see prior conversation context. See §4.9.
11. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed and left partial changes. Include prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures. See §4.8.

II. Task Fields

12. **`completion_criteria`** are specific, measurable, and verifiable by the AI —— not vague or subjective like "code is good". See §4.2.
13. **`initial_hint`** lists the exact prerequisites, paths, commands, scope boundaries, and handoff files needed for the task, but never include:
(1) step-by-step instructions;
(2) "potential/recommended approach" (unless the project requires) which can be figured out by AI themselves and only narrows AI's creativity. See §4.3.
14. **`system_prompt_prefix`** defines the AI persona, role, expertise, style, and hard behavior constraints for any task, but not a substitute for `initial_hint`. See §4.4 and §6.1.
15. **`max_attempts: 1`** is set on execution-only tasks (build, benchmark, test) that don't write code for fast failure propagation. Do not set `max_attempts: 1` on active coding tasks that benefit from retries. See §4.5.
16. **`model: "lite"`** is set on deterministic execution tasks; use default for most reasoning-heavy tasks like debugging, design, optimization, implementation, anti-hack review and keep/discard decisions. See §4.6.
17. **`git commit` is used** to track each task's work (if have) when each task or subtask completes.

III. Type-specific Guide

18. **Type-specific patterns**: read the relevant guide in §6 for domain-specific knowledge.

### Anti-Hack Rules

19. **Negative constraints in `completion_criteria`**: For every "implement X" task, `completion_criteria` should explicitly state what must not happen (e.g. no weakened tests, no unrelated files, no API changes, no regressions, or no forbidden generated outputs).
20. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.
21. **Verification separation**: Separate "implement" from "verify" (e.g. verification, anti-hack check, static quality review) into different subtasks.
Verification subtasks must (a) check for negative constraints in rule 19; (b) use `system_prompt_prefix` to forbid code modification; (c) use `max_attempts: 1` for fast error propagation.

### ⚠️ Critical Pitfalls —— Must Double Check

22. Are inter-task handoffs written to files instead of relying on conversation context?
23. Are completion criteria specific, measurable, and verifiable enough?
24. Does `completion_criteria` include negative constraints, and is there a "verify" task after each "implement" task for complex implementations?
25. Does `description` or `initial_hint` include step-by-step instructions or "potential/recommended approach" (unless the project requires)?

---

## 2. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

1. **Fully autonomous —— No human is in the loop**

**Implication**: `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification.

2. **Context isolation between tasks and subtasks**

Tasks and subtasks **share the filesystem, not conversation context**. AI sessions are reset between tasks and subtasks. No response is passed between top-level tasks; only a summary of the previous subtask may be passed between subtasks.
**Implication**: design top-level tasks independently; tasks and subtasks should persist detailed intermediate results to files.

3. **Tasks execute in ascending ID order**

**Implication**: Assign IDs in the intended execution order, and make each task consume only files produced by earlier IDs.

4. **Failed tasks do not automatically block later work**

**Implication**: Add prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures.

5. **`long_running` is used to avoid AI session timeout**

When running time-consuming commands like training with native bash tool provided by AI coding agents, the AI session is prone to timeout. This is what `long_running` is designed for.
**Implication**: Use `long_running` for builds, tests, benchmarks, training, profiling, or data jobs that can run >1 minute.

---

## 3. Root `description`

The root `description` is injected into every executor's prompt.

Include:
- **Goal**: final observable outcome and success threshold.
- **Architecture**: key directories/modules and their responsibilities.
- **Key file paths**: key source files/directories, configs, inputs, outputs, reports, and logs.
- **Key commands**: build/test/run/validate commands with required working directory, environment variables, and expected output locations.
- **Hard constraints**: files, APIs, tests, data, or behavior that must not change.
- **Rules**: project-wide behavior such as experiment discipline, allowed change size, or reporting format.
- **Reference Docs**: project documentation with reading priority. Keep paths and short reasons here; do not embed full document content.
  - **P0 Must Read**: read before starting any task; use only for essential architecture, API contracts, or safety constraints.
  - **P1 Read Before Related Work**: read before touching the related subsystem, file type, or feature area.
  - **P2 On Demand**: read only when debugging, stuck, or needing deeper historical/troubleshooting context.
- **Optional**:
  - Architecture Coupling Notes: exact files/modules that must be updated together.
  - Naming Conventions: required file, branch, metric, or artifact naming patterns.
  - Historical Result Files: paths to prior attempt/iteration outputs that should be read to avoid repeated work.

Do not include:
- **step-by-step instructions**: AI can figure it out themselves.
- **potential/recommended approach** (unless the project requires): AI can figure it out themselves. Doing this only narrows AI's creativity.

---

## 4. Design Principles

These principles are not self-contained; they extend rules in §1. Take both principles and rules into account when designing todos.

### 4.1 Task Decomposition

| Situation | Prefer |
|-----------|--------|
| Small targeted fix, inspection, or quick test | `simple` task |
| Contains command that may run >1 minute | `long_running` task |
| Multi-step goal with final success evaluation | `nested` top-level task with 2-4 `simple` / `long_running` tasks |
| Fixed number of repeated experiments or trials | `looping` top-level task with 2-4 `simple` / `long_running` tasks |

Difference between `nested` and `looping`:
- **`nested`**: useful when the purpose is to reach a target end state. Contains an AI session that checks whether the main task criteria is met.
- **`looping`**: useful when the purpose is to run a fixed number of iterations/experiments. No AI session for main task criteria check: only stops after a fixed number of loops.

Recommended splits:
- **Analyze / compose idea**: expensive since it produces a plan, hypothesis, or experiment design.
- **Implement + build/test**: keep together so the AI can self-correct.
- **Anti-hack verification**: separate this from implementation because of trust boundary.
- **Benchmark / validate / report**: group execution-focused evaluation together.

#### Anti-Patterns

- **Over-decomposition**: splitting `edit -> build -> fix build -> test` into separate subtasks will lose local reasoning context. Keep one coding loop together unless:
(1) The `test` is long-running. In this case, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor). The key insight is to ensure correctness in implementation before the next task runs full time-consuming training/profiling, while significantly speed up self-correction in implementation task.
(2) verification must be isolated;
(3) Code has substantial changes that are not suitable to implement in one single session. In this case, split code changes by modules.

- **Under-decomposition**: putting everything (analysis, implementation, benchmark, anti-hack review, and reporting) into one task causes context explosion, degrading AI performance and wasting retries.

### 4.2 `completion_criteria`

Completion criteria define observable success. They must be specific, measurable, and checkable by running commands, reading files, inspecting artifacts, or comparing metrics.

| Level | Role |
|-------|------|
| Top-level simple / long_running task | Single source of final success condition |
| Subtask | Subtask's `completion_criteria` determine subtask-level goal; after all subtask completes, an AI session is invoked to check top-level `completion_criteria` |
| Looping task | Top-level `completion_criteria` is not checked by separate AI sessions after each iteration, but still visible to all subtask executors |

Important: For `nested` / `looping` task, top-level criteria should describe the combined final outcome of the whole nested task, while subtask criteria should describe local checkpoint evidence. Top-level criteria should not become a copy of all subtask criteria.

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
| Prescribing methods | AI can figure it out themselves. Doing this only narrows AI's creativity. | Describe the target outcome unless the project requires a specific method. |
| Describing implementation steps | A to-do list is not success evidence. | State the artifact or observable result. |
| Unverifiable criteria | AI can claim success without proof. | Use command output, files, metrics, or diffs. |
| Missing negative conditions | Allows weakened tests or unrelated edits. | State forbidden changes explicitly. |

Bad: `"code is good"`, `"performance is improved"`, `"run tests and fix things"`.

### 4.3 `initial_hint`

`initial_hint` is executor-facing task-local context.

What to put in `initial_hint`:
- Prerequisite checks / Cleanup guidance for previous failed attempts
- Commands, working directory, environment, and output files
- Step-specific constraints, scope boundaries, and forbidden changes
- Files that contain previous attempts to avoid repeated approach 
- Exact files/directories to inspect or modify
- Expected artifacts to read/write

Do not put:
- project-wide context already in root `description`
- Contents copied from `completion_criteria`
- Step-by-step instructions
- Potential/Recommended approach (unless the project requires)

### 4.4 `system_prompt_prefix`

`system_prompt_prefix` defines the executor persona for the whole task session. It applies to analysis, implementation, verification, benchmarking, and reporting tasks.

Use it for:
- **Persona / expertise**: `You are a careful ML engineer.`
- **Role framing**: `You are a backend performance engineer.`
- **Style constraints**: `Prefer minimal, well-tested changes.`
- **Hard behavior constraints**: `Do NOT modify source code, tests, configs, or data.`

Keep prerequisites, task-specific files, commands, and artifacts in `initial_hint`.

### 4.5 `max_attempts`

Set different `max_attempts` by:

| Value | Use |
|-------|-----|
| `1` | Execution-only subtasks: build, test, benchmark, lint, format-check, verify. These tasks do the same within retries, so `max_attempts` = 1 and fastly propagate errors to failure analysis step is recommended. |
| `2-3` | Targeted uncertain work with constrained scope. |
| Default / higher | Active coding, debugging, optimization, refactoring. These tasks benefit from retries. |

### 4.6 `model`

Set different `model` by:

| Value | Use |
|-------|-----|
| Omit / `default` | Reasoning-heavy work: design, debug, implement, optimize, anti-hack review. |
| `lite` | Deterministic execution: run commands, format, copy/summarize known outputs. |
| Direct name | Only when the project specifies a tailored model name. |

### 4.7 Anti-Hack Patterns

AI agents may satisfy criteria through shortcuts (like directly modifying test files). Prevent that with explicit constraints.

Implementation tasks should specify:
- allowed files/directories
- files/directories that must not change
- tests/configs/data that must not be weakened

Verification / Anti-hack / Static quality review subtasks should be contained unless the project itself or implementation is straightforward, and should:
- be separate from implementation
- use `system_prompt_prefix` to forbid code/test/config/data edits
- use `max_attempts: 1` for fast failure propagation
- use `model: default` for deep and complex review and reasoning; use `model: lite` when only running deterministic checks
- verify both behavior and scope

### 4.8 Failure Resilience

Design for residual state: tasks may inherit broken filesystem state from their own retries or from earlier linear tasks.

- **Same-task retry**: mention cleanup or residual-state checks in `initial_hint`; prefer overwriting or appending to known files over relying on implicit memory.
- **Predecessor failure**: add prerequisite checks in `initial_hint` and require explicit failure reports in `completion_criteria` when prerequisites are missing.
- **External tools/services**: allow partial success only when useful, and require failures to be documented.
- **Nested/looping subtasks**: align failure boundaries with meaningful checkpoints and independent failure modes.
- **Progress tracking**: store progress in clearly named files instead of relying on prior conversation context.

### 4.9 State Persistence

Tasks and subtasks share files, not conversation memory.

- **Producer**: write findings/results to named files with enough detail for a fresh session.
- **Consumer**: read those files via `initial_hint`; if missing or incomplete, report prerequisite failure.

---

## 5. Schema Reference

### 5.1 Root Fields

| Field | Required | Notes |
|-------|----------|-------|
| `description` | Required by task generation rules | Shared project context. Runtime accepts missing text, but generated tasks must include it. |
| `description@N` | Optional | Scoped description used for tasks with top-level ID >= N. Only used when there are existing todos, and the existing `description` needs to be modified to match new tasks's context. |
| `tasks` | Yes | List of top-level tasks. |

### 5.2 Task Types

| Type | Top-level | Subtask | Use for |
|------|-----------|---------|---------|
| `simple` | Yes | Yes | AI work, quick commands, analysis, code changes. |
| `nested` | Yes | Yes | Ordered subtasks with overall AI evaluation/retry. |
| `looping` | Yes | Yes | Fixed `repeat_count` iterations. |
| `long_running` | Yes | Yes | Background command that may run >1 minute. |
| `simple_once` | **No** | Yes | One-time setup that should not re-run after completion. |
| `long_running_once` | **No** | Yes | Expensive one-time setup/baseline command. |

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

ID rules:
- Top-level IDs must be positive integers and strictly increasing.
- Subtask IDs must be unique, dot-notated, parent-prefixed, and increasing under the same parent.

### 5.4 Type-Specific Fields

| Type | Extra fields |
|------|--------------|
| `nested` | `subtasks` required; optional `max_attempts`. |
| `looping` | `subtasks` and positive integer `repeat_count` required; optional `max_attempts_per_loop`. |
| `simple` / `long_running` / `*_once` | Optional `initial_hint`, `max_attempts`, `model`, `system_prompt_prefix`. |

---

## 6. Task-Type-Specific Guides

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

## 7. Complete Example

Below is a complete linear-mode `todos.yaml` demonstrating key patterns: root `description`, reference docs, fixed-count `looping`, file-backed handoffs, optimization hypotheses, anti-hack verification, per-round optimization reporting, failure-pattern tracking, failure resilience, `completion_criteria`, `initial_hint`, `system_prompt_prefix`, `model` selection, and retry boundaries.

```yaml
description: |
  # Project: Web API Performance Optimization

  ## Goal
  Iteratively optimize the REST API server to reduce p95 latency below 50ms
  while keeping all integration tests passing. Run a fixed number of focused
  optimization iterations, preserve evidence in files, update the rolling report
  after every optimization round, and finish with a final summary.

  ## Architecture
  - src/handlers/ —— HTTP route handlers
  - src/db/ —— PostgreSQL query layer
  - src/cache/ —— Redis caching layer
  - tests/ —— integration test suite
  - benchmarks/ —— k6 load testing scripts

  ## Key File Paths
  - Route handlers: src/handlers/
  - Database query layer: src/db/
  - Cache layer: src/cache/
  - Config: config/server.yaml
  - Cumulative results: doc/optimization_results.tsv
  - Optimization log: doc/optimization_log.md
  - Implementation status: doc/implementation_status.md
  - Rolling optimization report: doc/optimization_report.md
  - Failure patterns: doc/failure_patterns.md
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
  - Do NOT change benchmark scripts, load shape, config thresholds, or server config to hide performance or correctness problems.
  - Keep each optimization focused, reversible, and limited to its declared scope.

  ## Workflow State Conventions
  - doc/optimization_results.tsv rows include: attempt_id, kind, p95_ms,
    tests, decision, commit, notes.
  - doc/optimization_log.md experiment entries include: attempt_id, status,
    target_area, hypothesis, expected_impact, risk, allowed_paths,
    forbidden_paths, result, and decision_reason.
  - doc/implementation_status.md includes: attempt_id, decision,
    changed_paths, build_status, test_status, verification_status, notes.
  - doc/optimization_report.md is the rolling report updated after every
    benchmark/evaluation round with baseline, current best, experiment summary table,
    kept/reverted/rejected attempts, and next directions.
  - doc/failure_patterns.md contains proven failure patterns and promising
    directions. It is read before new hypotheses and updated after every
    keep/revert/reject decision.
  - Each loop iteration should reuse the same planned hypothesis when retrying
    after implementation or verification failure; do not create a new hypothesis
    just because the previous implementation attempt failed.

  ## Reference Docs
  - P0 Must Read: doc/architecture.md —— request flow and service boundaries
  - P1 Read Before Related Work: doc/database.md —— read before changing src/db/
  - P1 Read Before Related Work: doc/cache.md —— read before changing src/cache/
  - P2 On Demand: doc/performance_history.md —— read when benchmark results are surprising or repeated work is suspected

  ## Rules
  - Fully autonomous: never ask the user questions.
  - Persist inter-task handoffs in the files listed above.
  - Propose and implement at most one optimization hypothesis per loop iteration.
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
      5. doc/optimization_log.md exists with baseline context and experiment numbering format.
      6. doc/optimization_report.md exists with baseline p95 and an empty experiment summary table.
      7. doc/failure_patterns.md exists, created from the template if missing.
      8. No source files, tests, configs, benchmark scripts, or generated benchmark results are modified except results.json from the benchmark command.
      9. git diff --name-only shows only doc/optimization_results.tsv, doc/optimization_log.md, doc/optimization_report.md, doc/failure_patterns.md, and results.json changed by this task.
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
        name: "Run baseline benchmark and initialize tracking docs"
        type: long_running
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. k6 benchmark exits 0 and writes results.json.
          2. doc/optimization_results.tsv exists and contains one baseline row with kind=baseline, p95_ms, tests=pass, and decision=baseline.
          3. doc/optimization_log.md exists with baseline context and experiment numbering format.
          4. doc/optimization_report.md exists with baseline p95 and an empty experiment summary table.
          5. doc/failure_patterns.md exists with proven failure patterns and promising directions sections.
          6. Existing optimization rows, experiment entries, and report history are preserved.
          7. git diff --name-only shows only doc/optimization_results.tsv, doc/optimization_log.md, doc/optimization_report.md, doc/failure_patterns.md, and results.json changed by this subtask.
        initial_hint: |
          Run:
          - k6 run benchmarks/load_test.js --out json=results.json

          Parse results.json for p95 latency. If doc/optimization_results.tsv
          already exists, preserve existing optimization rows and append or
          refresh only the baseline row. Ensure doc/optimization_log.md exists
          with baseline context and the attempt_id format.

          Initialize doc/optimization_report.md with baseline p95 and an empty
          experiment summary table if it does not exist. Initialize
          doc/failure_patterns.md with this template if it does not exist:
            # Web API Optimization Failure Patterns & Insights
            ## Proven Failure Patterns
            (none yet)
            ## Promising Directions
            (none yet)

          Do not modify source code, tests, configs, benchmark scripts, or
          unrelated docs.

  # ── Task 2: Fixed Iterative Optimization Loop ─────────────────────────
  - id: 2
    name: "Run fixed optimization iterations"
    type: looping
    repeat_count: 5
    max_attempts_per_loop: 3
    completion_criteria: |
      Each iteration completes this linear cycle: analyze current evidence,
      propose or reuse exactly one optimization hypothesis, implement or reject
      it, run anti-hack verification, then benchmark, evaluate, and update the
      rolling report and failure patterns.
    subtasks:
      - id: 2.1
        name: "Analyze bottleneck and propose optimization hypothesis"
        type: simple
        system_prompt_prefix: |
          You are a backend performance engineer specializing in Rust async services.
        completion_criteria: |
          1. doc/optimization_log.md contains exactly one new experiment entry for the current iteration with attempt_id, status=planned, target_area, hypothesis, expected_impact, risk, allowed_paths, and forbidden_paths.
          2. The hypothesis is not a repeat of an experiment already marked reverted, rejected, failed, or kept.
          3. doc/failure_patterns.md and doc/optimization_report.md have been read and consulted.
          4. No source code, tests, configs, benchmark scripts, benchmark outputs, result tables, or status files are modified.
        initial_hint: |
          Read doc/optimization_results.tsv, doc/optimization_log.md,
          doc/optimization_report.md, and doc/failure_patterns.md. If the last
          3+ experiments failed in the same category, choose a different
          direction. Inspect only the relevant source files needed to understand
          the current bottleneck. Write exactly one focused optimization
          hypothesis for this loop iteration. Keep allowed_paths narrow enough
          for git diff --name-only verification in Task 2.3, and list explicit
          forbidden_paths.

          If this loop iteration is being retried after Task 2.2 or Task 2.3
          failed, do not create a new hypothesis. Reuse the current iteration's
          existing planned hypothesis and make no changes unless the log is
          missing required fields.

      - id: 2.2
        name: "Implement or reject the latest hypothesis"
        type: simple
        completion_criteria: |
          1. Exactly one latest hypothesis with status=planned is either implemented or rejected.
          2. If implemented, cargo build --release exits 0 and cargo test --all exits 0.
          3. If implemented, git diff --name-only contains only files listed under allowed_paths for the hypothesis plus doc/implementation_status.md.
          4. If rejected, no source/test/config changes remain and doc/implementation_status.md records the concrete safety or feasibility reason.
          5. doc/implementation_status.md records attempt_id, decision, changed_paths, build_status, test_status, and notes.
          6. No tests, public schemas, benchmark scripts, generated benchmark outputs, configs, or forbidden_paths are modified.
        initial_hint: |
          Read the latest experiment entry with status=planned in
          doc/optimization_log.md. Respect its allowed_paths and forbidden_paths.
          Before editing, inspect git diff in case a previous retry left partial
          changes.

          If the hypothesis is unsafe or infeasible, do not edit source code;
          write decision=rejected and the reason to doc/implementation_status.md.
          If implemented, keep the change minimal, then run cargo build --release
          and cargo test --all. Do not commit; Task 2.4 decides whether the
          change is kept or reverted.

      - id: 2.3
        name: "Anti-hack verification"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are an anti-hack verifier. Your sole job is to detect constraint violations.
          Do NOT modify source code, tests, configs, benchmark scripts, generated data,
          public schemas, or any file other than doc/implementation_status.md.
        completion_criteria: |
          1. doc/implementation_status.md exists and references the latest attempt_id.
          2. If decision=implemented, cargo test --all exits 0.
          3. If decision=implemented, git diff --name-only contains only files listed under allowed_paths for the hypothesis plus doc/implementation_status.md.
          4. No tests, public API schemas, benchmark scripts, generated benchmark outputs, configs, or forbidden_paths were modified.
          5. Tests are not weakened: no skipped assertions, relaxed tolerances, removed test cases, or conditional bypasses.
          6. Benchmark integrity is preserved: load shape, benchmark duration, thresholds, and result JSON are not hand-edited to hide regressions.
          7. Config integrity is preserved: server config and performance thresholds are not changed to hide performance or correctness problems.
          8. API behavior is preserved: public request/response schemas and endpoint semantics are unchanged unless explicitly listed in allowed_paths and justified by the hypothesis.
          9. doc/implementation_status.md contains verification_status=pass or the verifier records the exact failed check and stops with failure.
          10. Only doc/implementation_status.md may be updated by this verifier subtask.
        initial_hint: |
          This is anti-hack verification only. Compare git diff --name-only and
          git diff against the latest hypothesis's allowed_paths and
          forbidden_paths. Check every hard constraint systematically:
          allowed_paths, forbidden_paths, public schema stability, test
          integrity, benchmark integrity, config integrity, endpoint behavior,
          and generated-result integrity.

          If any check fails, record the exact violation in
          doc/implementation_status.md and stop; do not fix code in this subtask.
          A failed verifier should propagate failure so the loop retry re-enters
          the implementation step for the same hypothesis instead of adding a
          nested evaluation layer.

      - id: 2.4
        name: "Benchmark, evaluate, and update report"
        type: long_running
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. If the latest hypothesis was rejected, doc/optimization_results.tsv has an iteration row with decision=rejected and no benchmark is required.
          2. If implemented, cargo test --all exits 0 before benchmarking, or the latest result row records tests=fail and decision=reverted.
          3. If implemented and tests pass, k6 benchmark exits 0 and results.json contains p95 latency.
          4. doc/optimization_results.tsv has a new row with attempt_id, kind=optimization, p95_ms or n/a, tests, decision, commit, and notes.
          5. If tests fail or p95_ms regresses by more than 5% versus the previous best kept row, only the latest implementation is reverted and the row has decision=reverted.
          6. If the change is kept, tests=pass and decision=kept, and no unrelated files are modified.
          7. doc/optimization_log.md marks the evaluated attempt as kept, reverted, or rejected with evidence and decision_reason.
          8. doc/optimization_report.md is updated for this round with baseline vs current best, experiment summary table, kept/reverted/rejected attempts, and next directions.
          9. doc/failure_patterns.md is updated: reverted/rejected attempts are classified under proven failure patterns, and kept changes are added to promising directions.
          10. git commit completed for doc updates and any revert.
        initial_hint: |
          Read doc/implementation_status.md and doc/optimization_log.md. If the
          latest decision is rejected, append a rejected row to
          doc/optimization_results.tsv, update the experiment status, update
          doc/optimization_report.md, and update doc/failure_patterns.md without
          running the benchmark.

          If the latest decision is implemented, first run cargo test --all. If
          tests fail, revert only the latest implementation and record
          tests=fail, decision=reverted. If tests pass, run:
          k6 run benchmarks/load_test.js --out json=results.json

          Compare p95_ms to the previous best kept row in
          doc/optimization_results.tsv. Revert only the latest optimization when
          needed; do not modify unrelated files. Update doc/optimization_log.md
          with results and decision. Update doc/failure_patterns.md:
          - If reverted or rejected: classify the failure (new pattern or existing?).
          - If kept: add to "Promising Directions" with what worked and why.
          Update doc/optimization_report.md by overwriting the rolling report
          with the latest baseline, current best, experiment summary table,
          kept/reverted/rejected attempts, and next directions. Commit doc
          changes and any revert.

  # ── Task 3: Final Report ──────────────────────────────────────────────
  - id: 3
    name: "Write final optimization report"
    type: simple
    max_attempts: 1
    completion_criteria: |
      1. doc/final_report.md exists.
      2. The report includes baseline p95, best/final p95, test status, kept changes, reverted changes, rejected hypotheses, failure patterns, and remaining blockers if any.
      3. The report is consistent with doc/optimization_results.tsv, doc/optimization_log.md, doc/implementation_status.md, doc/optimization_report.md, and doc/failure_patterns.md.
      4. Only doc/final_report.md is modified by this task.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, result tables, rolling report, or failure-pattern database are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md,
      doc/implementation_status.md, doc/optimization_report.md, and
      doc/failure_patterns.md. This is a final reporting task only; do not
      modify source code, tests, configs, benchmark scripts, benchmark outputs,
      result tables, rolling report, or failure-pattern database.
```