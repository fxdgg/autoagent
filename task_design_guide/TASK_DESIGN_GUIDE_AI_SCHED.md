# Task Design Guide — AI Scheduling Mode

Reference for AI agents that generate `todos.yaml` tasks for AI-scheduled AutoAgent execution.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

I. General Schema Rules

1. **Root `description`** exists and:
(1) Covers Goal, Architecture, Key file paths, Hard constraints, Rules;
(2) Does not cover step-by-step instructions;
(3) Does not include "potential/recommended approach" (unless the project requires) since AI can figure it out themselves. Doing this only narrows AI's creativity.
(4) Does not cover scheduler-only ordering rules (e.g. execute task 2 after 1, this is a two-phase optimization).
See §3 for full guidance.
2. **Every task** has `id`, `name`, `type`, `description`, `completion_criteria`.
3. **ID assignment**: top-level IDs are sequential integers; subtask IDs use dot notation (e.g., 1.1, 1.2).
4. **`*_once` types** (`simple_once`, `long_running_once`) can ONLY be subtasks, not top-level tasks.
5. **`long_running`** is used for any command that may take > 1 minute.

II. AI Scheduling Schema Rules

6. **`ai_orchestrator`** is configured with `strategy`, `stop_condition`, `last_result` (and optionally `max_rounds`). See §5.

### Design Rules

I. General Rules for Task Decomposition

7. **Default flat**: prefer single `simple` / `long_running` top-level tasks; let the scheduler handle ordering and re-execution. Use subtasks only when:
(a) enforced sequential ordering is required and the scheduler cannot guarantee it (e.g. anti-hack verification must run after implementation, report must run after tests pass);
(b) bundling several lightweight steps into one top-level task to reduce scheduling overhead. See §4.1.
8. **No over-decomposition**:
(1) Keep logically dependent work in one task (e.g. when implementing tightly coupled modules A and B).
(2) Keep implement + build + task in one task so the AI can self-correct in the same session. See §4.1.
(3) Split tasks only at trust boundaries (e.g. anti-hack verification must be a separate subtask) or expensive/time-consuming checkpoints (See rule 9).
9. **No under-decomposition**: separate expensive (e.g. idea composition, implementation) and time-consuming steps (e.g. training, benchmark, verification, reporting) into distinct top-level tasks so the scheduler can re-execute them individually. See §4.1.
10. **Search for fast-check training/profiling modes, if it is long-running**: 
when merging implement + build + test into one subtask, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor) when it is long-running.
The key insight is to ensure correctness in implementation before the next task runs full time-consuming training/profiling, while significantly speed up self-correction in implementation task.
11. **State persistence**: write inter-task handoffs to files; never assume the next task can see prior conversation context. See §4.10.
12. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed and left partial changes. Scheduler's failure handling strategy is dominant, while task's prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures are still required as a fallback. See §4.9.

II. Task Fields

13. **Task-specific `description`** is scheduler-facing, with only 1-3 sentences explaining what the task does and produces. See §4.2.
14. **`completion_criteria`** are specific, measurable, and verifiable by the AI —— not vague or subjective like "code is good". See §4.3.
15. **`initial_hint`** lists the exact prerequisites, paths, commands, scope boundaries, and handoff files needed for the task, but never include:
(1) step-by-step instructions;
(2) "potential/recommended approach" (unless the project requires) which can be figured out by AI themselves and only narrows AI's creativity;
(3) Instructions about copying results to a specified path for scheduler since scheduler and executor share the same filesystem. See §4.4.
16. **`system_prompt_prefix`** defines the AI persona, role, expertise, style, and hard behavior constraints for any task, but not a substitute for `initial_hint`. See §7.1.
17. **`max_attempts: 1`** is set on execution-only tasks (build, benchmark, test) that don't write code for fast failure propagation. Do not set `max_attempts: 1` on active coding tasks that benefit from retries. See §4.6.
18. **`model: "lite"`** is set on deterministic execution tasks; use default for most reasoning-heavy tasks like debugging, design, optimization, implementation, anti-hack review and keep/discard decisions. See §4.7.
19. **`git commit` is used** to track each task's work (if have) when each task or subtask completes.

III. Type-specific Guide

20. **Type-specific patterns**: read the relevant guide in §7 for domain-specific knowledge.

### AI Scheduling Rules

I. Fields under ai_orchestrator

21. **`strategy`** references task IDs, encodes task dependencies, and includes failure recovery rules. See §5.2.
22. **`last_result`** is configured for every task whose output is needed by scheduler. Use `${workspace}` for workspace-relative paths; it is expanded at runtime. See §5.3.
23. **`stop_condition`** is specific, measurable, and includes a fallback (e.g. after 5 consecutive failures). See §5.4.

II. AI Scheduling Rules for Task Decomposition

24. **Max ~5-8 top-level tasks** —— more bloats the scheduler prompt.
25. **Design for re-execution**: design tasks that can run 0, 1, or many times.
26. **Scheduler observable**: Documentation task or subtask should provide enough information in `last_result` files for scheduler to make precise decisions. 
27. **Designing tail-friendly `last_result`**: keep scheduler-critical status in small summary files (especially when scheduler needs cross-round analysis) or at the end of result files, because the last 5 lines of `last_result` is directly injected into scheduler's prompt.

### Anti-Hack Rules

28. **Negative constraints in `completion_criteria`**: For every "implement X" task, `completion_criteria` should explicitly state what must not happen (e.g. no weakened tests, no unrelated files, no API changes, no regressions, or no forbidden generated outputs).
29. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.
30. **Verification separation**: Separate "implement" from "verify" (e.g. verification, anti-hack check, static quality review) into different subtasks.
Verification subtasks must (a) check for negative constraints in rule 27; (b) use `system_prompt_prefix` to forbid code modification; (c) use `max_attempts: 1` for fast error propagation.

### ⚠️ Critical Pitfalls —— Must Double Check

31. Are inter-task handoffs written to files instead of relying on conversation context?
32. Are completion criteria specific, measurable, and verifiable enough?
33. Does `completion_criteria` include negative constraints, and is there a "verify" task after each "implement" task for complex implementations?
34. Does `description` or `initial_hint` include step-by-step instructions or "potential/recommended approach" (unless the project requires)?
35. Are `last_result` correctly set so that scheduler can see each task's execution results? Will files specified in `last_result` be created by tasks BEFORE scheduler wants to see them?
36. Are `${workspace}` used in `last_result` to reference relative paths?

---

## 2. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

### 2.1 General Properties

1. **Fully autonomous —— No human is in the loop**

**Implication**: `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification.

2. **Context isolation between tasks and subtasks**

Tasks and subtasks **share the filesystem, not conversation context**. AI sessions are reset between tasks and subtasks. No response is passed between top-level tasks; only a summary of the previous subtask may be passed between subtasks.
**Implication**: design top-level tasks independently; tasks and subtasks should persist detailed intermediate results to files.

3. **Failed tasks do not automatically block later work**

**Implication**: Scheduler's failure handling strategy is dominant, while task's prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures are still required as a fallback.

4. **`long_running` is used to avoid AI session timeout**

When running time-consuming commands like training with native bash tool provided by AI coding agents, the AI session is prone to timeout. This is what `long_running` is designed for.
**Implication**: Use `long_running` for builds, tests, benchmarks, training, profiling, or data jobs that can run >1 minute.

### 2.2 AI Scheduling Properties

1. **Dynamic execution**

In AI scheduling mode, an AI scheduler dynamically chooses **one top-level task per round**, or chooses to stop. It does not schedule subtasks; subtasks inside the selected top-level task run sequentially through normal task executors.
**Implication**:
(1) Prefer single `simple` / `long_running` top-level tasks; let the scheduler handle ordering and re-execution. See §4.1 for when to use subtasks.
(2) Design tasks that can be run 0, 1, or many times.

2. **Scheduler does not see the entire task detail**

Scheduler only sees root `description`, scheduling rules and each top-level task's specific `description`, not inner task details (like `completion_criteria` and `initial_hint`) or subtask information (which is consistent with "not schedule subtask" design). `last_result` is the only way that scheduler can inspect task's execution results.
**Implication**:
- Persist task outputs needed for scheduling to files and use `last_result: type: file`, or expose original AI response for simple tasks via `last_result: type: response`.

3. **The last 5 lines of `last_result` are directly injected into the scheduler prompt**

**Implication**: Put scheduler-critical state near the end of each result file, or maintain a small rolling summary/status file for scheduling decisions (especially when scheduler needs cross-round analysis). Do not bury it in the middle of a large log.

4. **`last_result` is not scheduler-only**

File paths in `last_result` is shared between scheduler and executor, not scheduler-only.
**Implication**: Use `last_result` to inform the scheduler is enough. No need to state "Executor must copy results to a specified path for scheduler" or mention "persist scheduler-relevant outcomes" elsewhere.

---

## 3. Root `description`

Root `description` is injected into every scheduler and executor's prompt, shared for both scheduler and executors.

Include:
- **Goal**: final observable outcome and success threshold.
- **Architecture**: key directories/modules and their responsibilities.
- **Key file paths**: key source files/directories, configs, inputs, outputs, reports, and logs.
- **Key commands**: build/test/run/validate commands with required working directory, environment variables, and expected output locations.
- **Hard constraints**: files, APIs, tests, data, or behavior that must not change.
- **Rules**: project-wide behavior such as experiment discipline, allowed change size, or reporting format.
- **Reference Docs**: project documentation with reading priority. Keep paths and short reasons here; do not embed full document content.
  - **P0 Must Read**: read before starting any task; keep this minimal to avoid scheduler/executor context bloat.
  - **P1 Read Before Related Work**: read before touching the related subsystem, file type, or feature area.
  - **P2 On Demand**: read only when debugging, stuck, or needing deeper historical/troubleshooting context.
- **Optional**:
  - Architecture Coupling Notes: exact files/modules that must be updated together.
  - Naming Conventions: required file, branch, metric, or artifact naming patterns.
  - Historical Result Files: paths to prior attempt/iteration outputs that should be read to avoid repeated work.

Do not include:
- **scheduler-only ordering rules** (e.g. execute task 2 after 1, this is a two-phase optimization): put them in `ai_orchestrator.strategy`.
- **step-by-step instructions**: AI can figure it out themselves.
- **potential/recommended approach**: AI can figure it out themselves. Doing this only narrows AI's creativity.

Key insight:
root `description` is for shared project context, `strategy` is for scheduler only, and `initial_hint` is for executor only.

---

## 4. Design Principles

These principles are not self-contained; they extend rules in §1. Take both principles and rules into account when designing todos.

### 4.1 Task Decomposition

In AI scheduling mode, the principle is **default flat** —— prefer top-level `simple` / `long_running` tasks. Let the scheduler handle ordering, re-execution, and conditional branching.

| Situation | Prefer |
|-----------|--------|
| Small targeted fix, inspection, or quick test | Top-level `simple` task |
| Contains Command may run >1 minute | Top-level `long_running` task |

Use `nested` tasks only when:
- **Enforced sequential ordering** is required and the scheduler cannot guarantee it (e.g. anti-hack verification must run after implementation, report must run after tests pass);
- **bundling several lightweight steps** into one top-level task to reduce scheduling overhead.

`looping` tasks are generally not recommended in AI scheduling mode: scheduler can do looping actions itself.

#### Anti-Patterns

- **Over-decomposition**: splitting `edit -> build -> fix build -> test` into separate tasks will lose local reasoning context. Keep one coding loop together unless:
(1) The `test` is long-running. In this case, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor). The key insight is to ensure correctness in implementation before the next task runs full time-consuming training/profiling, while significantly speed up self-correction in implementation task.
(2) verification must be isolated;
(3) Code has substantial changes that are not suitable to implement in one single session. In this case, split code changes by modules.

- **Under-decomposition**: putting everything (analysis, implementation, benchmark, anti-hack review, and reporting) into one task causes context explosion, degrading AI performance and wasting retries.

### 4.2 Task-specific `description`

For each task, task-specific `description` is the **only way** the scheduler AI understands what a task does. Scheduler cannot see details in `completion_criteria` and `initial_hint`.

- State what the task does, what it produces, and any scheduling-relevant outcome.
- Keep it to 1-3 sentences; otherwise the scheduler prompt becomes bloated.
- Do not include execution steps or implementation details; those belong in `initial_hint`.

Good:

```yaml
description: |
  Run correctness tests and benchmark the latest implementation. Updates
  doc/optimization_results.tsv with pass/fail status and p95 latency.
```

### 4.3 `completion_criteria`

Completion criteria define observable success. They must be specific, measurable, and checkable by running commands, reading files, inspecting artifacts, or comparing metrics.

| Level | Role |
|-------|------|
| Top-level simple / long_running task | Single source of final success condition |
| Subtask | Subtask's `completion_criteria` determine subtask-level goal; after all subtask completes, an AI session is invoked to check top-level `completion_criteria` |
| Looping task (Generally not recommended) | Top-level `completion_criteria` is not checked by separate AI sessions after each iteration, but still visible to all subtask executors |

Important: For `nested` task, top-level criteria should describe the combined final outcome of the whole nested task, while subtask criteria should describe local checkpoint evidence. Top-level criteria should not become a copy of all subtask criteria.

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

### 4.4 `initial_hint`

`initial_hint` is executor-facing task-local context. Scheduler cannot see it.

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

### 4.5 `system_prompt_prefix`

`system_prompt_prefix` defines the executor persona for the whole task session. It applies to analysis, implementation, verification, benchmarking, and reporting tasks.

Use it for:
- **Persona / expertise**: `You are a careful ML engineer.`
- **Role framing**: `You are a backend performance engineer.`
- **Style constraints**: `Prefer minimal, well-tested changes.`
- **Hard behavior constraints**: `Do NOT modify source code, tests, configs, or data.`

Keep prerequisites, task-specific files, commands, and artifacts in `initial_hint`.

### 4.6 `max_attempts`

Set different `max_attempts` for different types of tasks:

| Value | Use |
|-------|-----|
| `1` | Execution-only subtasks: build, test, benchmark, lint, format-check, verify. These tasks do the same within retries, so `max_attempts` = 1 and fastly propagate errors to failure analysis step is recommended. |
| `2-3` | Targeted uncertain work with constrained scope. |
| Default / higher | Active coding, debugging, optimization, refactoring. These tasks benefit from retries. |

### 4.7 `model`

Set different `model` by:

| Value | Use |
|-------|-----|
| Omit / `default` | Reasoning-heavy work: design, debug, implement, optimize, anti-hack review. |
| `lite` | Deterministic execution: run commands, format, copy/summarize known outputs. |
| Direct name | Only when the project specifies a tailored model name. |

### 4.8 Anti-Hack Patterns

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

### 4.9 Failure Resilience

Design for residual state: tasks may inherit broken filesystem state from their own retries or from prior scheduled tasks.

- **Same-task retry**: mention cleanup or residual-state checks in `initial_hint`; prefer overwriting or appending to known files over relying on implicit memory.
- **Predecessor failure**: encode preferred handling in `strategy` and expose status through `last_result`.
- **Task-level safety net**: include prerequisite checks in `initial_hint` when a task depends on build/test/data state.
- **External tools/services**: allow partial success only when useful, and require failures to be documented.
- **Nested subtasks**: align failure boundaries with meaningful checkpoints and independent failure modes.
- **Progress tracking**: store progress in clearly named files instead of relying on prior conversation context.

### 4.10 State Persistence

Tasks and subtasks share files, not conversation memory.

- **Producer**: write findings/results to named files with enough detail for a fresh session. Ensure that scheduler can obtain enough information for decision making via `last_result`.
- **Consumer**: read those files via `initial_hint`; if missing or incomplete, report prerequisite failure.
- **Scheduler**: reads only configured `last_result` plus execution history.

---

## 5. `ai_orchestrator` Configuration

AI scheduling mode requires `ai_orchestrator`.

### 5.1 Schema

```yaml
ai_orchestrator:
  strategy: |
    <scheduling rules —— injected into the scheduler prompt>
  max_rounds: 20          # Optional, default: 50
  stop_condition: |       # Optional
    <when to stop —— injected into the scheduler prompt>
  last_result:            # Required by design when scheduler needs task outputs
    <task_id>:
      type: file | response | none
      path: <path>        # Required when type=file
```

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `strategy` | Yes | - | Scheduler decision policy. |
| `max_rounds` | No | 50 | Hard cap on scheduling rounds. |
| `stop_condition` | No | `""` | Observable stopping rule. |
| `last_result` | No by schema; required by design when referenced | `{}` | Per-task result exposure. |
| `max_attempts` | No | config default | Retry count relevant to scheduler decisions. |

### 5.2 `strategy`

`strategy` is the scheduler's decision policy. Use deterministic numbered rules with task IDs and names.

Include:
- bootstrap behavior;
- dependencies expressed through execution counts, history, and `last_result`;
- success, failure, regression, and missing-result handling;
- rerun/skip/diagnose/report/stop rules;
- fallback after repeated failures.

| Guideline | Rationale |
|-----------|-----------|
| Use task IDs and names together | `Task 1 (Baseline)` is clearer than `Task 1`. |
| Use observable state | Scheduler sees counts, history, current round, and `last_result`. |
| Include failure recovery | Prevents repeated bad scheduling. |
| Include termination triggers | Complements `stop_condition`. |
| Keep rules deterministic | Ambiguity causes inconsistent scheduling. |

The scheduler cannot observe internal subtask state, task conversations, or files not listed in `last_result`.

### 5.3 `last_result`

`last_result` exposes top-level task outcomes to the scheduler.

| Type | Scheduler sees | Use for |
|------|----------------|---------|
| `file` | Contents/previews of specified files | Metrics, reports, logs, cumulative results, anything referenced by `strategy`. |
| `response` | Auto-saved AI final response | Single `simple` tasks or `nested` tasks whose last subtask summarizes the result. |
| `none` | Success/failure history only | Setup tasks with no meaningful scheduler-visible output. |

Rules:
- keys are top-level task IDs, not subtask IDs;
- use `${workspace}` for workspace-relative paths; it is expanded at runtime;
- `type: file` may use a single path or a list of paths;
- if `strategy` references a task's output, configure `last_result` for that task.

### 5.4 `stop_condition`

Make stopping observable from scheduler-visible history and `last_result`.

Good:

```yaml
stop_condition: |
  Stop when p95 latency is below 50ms and correctness is 100/100 as reported
  in doc/optimization_results.tsv, or after 3 consecutive optimization failures
  with doc/diagnosis.md written.
```

Bad: `Stop when done` or `Stop when code is clean`.

Tips:
- reference metrics in result files;
- include a fallback such as consecutive failures or diagnosis complete;
- be explicit about AND/OR logic.

---

## 6. Schema Reference

### 6.1 Root Fields

| Field | Required | Notes |
|-------|----------|-------|
| `description` | Yes | Shared project context: goal, architecture, constraints, key paths. |
| `description@N` | Optional | Used to override existing `description`. Only used when there are existing todos, and the existing `description` needs to be modified to match new context. |
| `ai_orchestrator` | Yes | AI scheduling configuration. |
| `tasks` | Yes | Top-level task definitions. |

### 6.2 Task Types

| Type | Top-level | Subtask | Use for |
|------|-----------|---------|---------|
| `simple` | Yes | Yes | Code changes, tests, analysis, quick builds. |
| `long_running` | Yes | Yes | Commands that may take >1 minute. |
| `nested` | Yes | Yes | Ordered subtasks inside one selected task. |
| `looping` | Yes | Yes | Fixed repeated cycles (Generally not recommended). |
| `simple_once` | **No** | Yes | One-time setup that should survive later retries. |
| `long_running_once` | **No** | Yes | Expensive one-time setup/baseline command. |

### 6.3 Common Task Fields

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | Integer for top-level, dot notation for subtasks. |
| `name` | Yes | Concise task name. |
| `type` | Yes | Valid task type. |
| `description` | Yes by guide | Scheduler-facing summary of what the task does and produces. |
| `completion_criteria` | Yes | Specific, measurable success criteria. |
| `initial_hint` | Optional | Executor-facing context and guidance. |
| `model` | Optional | `default`, `lite`, role name, or direct model name. |
| `system_prompt_prefix` | Optional | Persona, role, or hard behavior constraints. |
| `max_attempts` | Optional | Max retry attempts for this task/subtask. |

ID rules:
- Top-level IDs must be positive integers and, in linear mode, strictly increasing.
- Subtask IDs must be unique, dot-notated, parent-prefixed, and increasing under the same parent.

### 6.4 Type-Specific Fields

| Type | Extra fields |
|------|--------------|
| `nested` | `subtasks` required; optional `max_attempts`. |
| `looping` | `subtasks` and positive integer `repeat_count` required; optional `max_attempts_per_loop`. |
| `simple` / `long_running` / `*_once` | Optional `initial_hint`, `max_attempts`, `model`, `system_prompt_prefix`. |

---

## 7. Task-Type-Specific Guides

Read only the guide relevant to the task domain:

| Domain | Guide |
|--------|-------|
| Build & Ship | `build_and_ship.md` |
| Testing & Verification | `testing_and_verification.md` |
| Iterative Optimization | `iterative_optimization.md` |
| Data Pipelines / ETL | `data_pipelines.md` |
| Setup & Deployment | `setup_and_deployment.md` |
| Research & Analysis | `research_and_analysis.md` |
| Academic Experiments | `academic_experiments.md` |

---

## 8. Complete AI Scheduling Example

Below is a complete `todos.yaml` demonstrating key patterns: 

- General: root `description`, reference docs, file-backed handoffs, optimization hypotheses, anti-hack verification, per-round optimization reporting, failure-pattern tracking, failure resilience, `completion_criteria`, `initial_hint`, `system_prompt_prefix`, `model` selection, and retry boundaries.
- Scheduler: scheduler-visible task `description`, file-backed `last_result`, durable scheduler state.

```yaml
description: |
  # Project: Web API Performance Optimization

  ## Goal
  Reduce REST API p95 latency below 50ms while keeping all integration tests
  passing. Iterate through analysis, one focused implementation, benchmark
  evaluation, diagnosis, and final reporting until the target is met or no safe
  optimization remains.

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
  - Failure diagnosis: doc/diagnosis.md
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
    keep/revert decision.
  - doc/diagnosis.md includes: root_cause and scheduler_action.

  ## Reference Docs
  - P0 Must Read: doc/architecture.md —— request flow and service boundaries
  - P1 Read Before Related Work: doc/database.md —— read before changing src/db/
  - P1 Read Before Related Work: doc/cache.md —— read before changing src/cache/
  - P2 On Demand: doc/performance_history.md —— read when benchmark results are surprising or repeated work is suspected

  ## Rules
  - Fully autonomous: never ask the user questions.
  - Persist scheduler-relevant outcomes in the files listed above.
  - Propose and implement at most one optimization hypothesis per attempt.
  - Commit hypothesis documentation separately before implementation so later
    code rollback does not erase the reasoning.
  - If prerequisites are broken before a task starts, report that state in the
    task's output file instead of broadening scope.

ai_orchestrator:
  max_rounds: 20
  strategy: |
    Scheduling rules:
    1. If Task 1 (Establish baseline) has never succeeded, run Task 1.
    2. After Task 1 succeeds, run Task 2 (Analyze bottleneck and propose hypothesis).
    3. After Task 2 succeeds and doc/optimization_log.md contains a latest
       hypothesis entry with status=planned, run Task 3 (Implement and verify
       one change).
    4. After Task 3 succeeds with doc/implementation_status.md containing
       decision=implemented and verification_status=pass, run Task 4 (Benchmark,
       evaluate, and update report).
    5. If Task 3 succeeds with decision=rejected, run Task 4 only to update
       doc/failure_patterns.md and doc/optimization_report.md for that rejected
       hypothesis, then return to Task 2.
    6. After Task 4 completes with decision=kept or decision=reverted, run
       Task 2 again unless the latest result row shows tests=pass and p95_ms < 50.
    7. If Task 4 writes a latest row with tests=pass and p95_ms < 50, run
       Task 6 (Write final report), then stop after doc/final_report.md exists.
    8. If Task 3 or Task 4 fails twice consecutively, run Task 5 (Diagnose
       repeated failures).
    9. After Task 5 succeeds, run Task 2 again when scheduler_action=continue;
       run Task 6 when scheduler_action=stop_no_safe_optimization or
       scheduler_action=stop_external_blocker.
  stop_condition: |
    Stop after doc/final_report.md exists and is consistent with the latest
    scheduler-visible artifacts, or after Task 5 reports scheduler_action as
    stop_no_safe_optimization or stop_external_blocker and Task 6 has run, or
    after 5 consecutive reverted or rejected experiments with no p95 improvement.
  last_result:
    1:
      type: file
      path:
        - ${workspace}/doc/optimization_results.tsv
        - ${workspace}/doc/failure_patterns.md
    2:
      type: file
      path: ${workspace}/doc/optimization_log.md
    3:
      type: file
      path: ${workspace}/doc/implementation_status.md
    4:
      type: file
      path:
        - ${workspace}/doc/optimization_results.tsv
        - ${workspace}/doc/optimization_log.md
        - ${workspace}/doc/optimization_report.md
        - ${workspace}/doc/failure_patterns.md
    5:
      type: file
      path: ${workspace}/doc/diagnosis.md
    6:
      type: file
      path: ${workspace}/doc/final_report.md

tasks:
  - id: 1
    name: "Establish baseline"
    type: long_running
    description: |
      Build the project, run all tests, run the baseline benchmark, and create
      the baseline row plus initial optimization tracking documents for scheduler decisions.
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
    initial_hint: |
      Commands:
      - cargo build --release
      - cargo test --all
      - k6 run benchmarks/load_test.js --out json=results.json

      If doc/optimization_results.tsv already exists, preserve existing attempt
      rows and append or refresh only the baseline row. Initialize
      doc/failure_patterns.md with this template if it does not exist:
        # Web API Optimization Failure Patterns & Insights
        ## Proven Failure Patterns
        (none yet)
        ## Promising Directions
        (none yet)
      Do not modify source code, tests, configs, or benchmark scripts.

  - id: 2
    name: "Analyze bottleneck and propose optimization hypothesis"
    type: simple
    description: |
      Analyze current benchmark data, rolling report, failure patterns, and source
      hotspots, then append one focused optimization hypothesis to doc/optimization_log.md.
    completion_criteria: |
      1. doc/optimization_log.md contains exactly one new experiment entry with attempt_id, status=planned, target_area, hypothesis, expected_impact, risk, allowed_paths, and forbidden_paths.
      2. The hypothesis is not a repeat of an experiment already marked reverted, rejected, failed, or kept.
      3. doc/failure_patterns.md and doc/optimization_report.md have been read and consulted.
      4. No source code, tests, configs, benchmark scripts, benchmark outputs, result tables, or status files are modified.
      5. The hypothesis documentation is committed separately before implementation.
    initial_hint: |
      First: git status. If not clean:
      - Documentation changes from earlier completed tasks → commit them.
      - Code changes → stash or revert them unless they are the latest verified implementation awaiting benchmark.

      Read doc/optimization_results.tsv, doc/optimization_log.md,
      doc/optimization_report.md, and doc/failure_patterns.md. If the last 3+
      experiments failed in the same category, choose a different direction.
      Read relevant source files only as needed, such as src/handlers/, src/db/,
      and src/cache/. Identify the current most plausible bottleneck from data,
      not from stale assumptions. Propose exactly one focused optimization
      hypothesis with narrow allowed_paths and explicit forbidden_paths.

      Commit documentation separately, for example:
        git add doc/optimization_log.md
        git commit -m "perf: hypothesis for <attempt_id>"
      This ensures the hypothesis survives a later code rollback.

  - id: 3
    name: "Implement and verify one change"
    type: nested
    description: |
      Implement the latest planned hypothesis, run local build/tests, and use a
      separate anti-hack verifier subtask to confirm behavior and constraint compliance.
    completion_criteria: |
      1. doc/implementation_status.md exists for the latest attempt_id.
      2. The status file contains decision=implemented or decision=rejected.
      3. If decision=implemented, the status file contains build_status=pass, test_status=pass, verification_status=pass, and changed_paths.
      4. If decision=rejected, the status file contains a concrete safety or feasibility reason and no source/test/config changes remain.
    subtasks:
      - id: 3.1
        name: "Implement focused optimization, build, and test"
        type: simple
        completion_criteria: |
          1. Exactly one latest hypothesis with status=planned is either implemented or rejected.
          2. If implemented, cargo build --release exits 0 and cargo test --all exits 0.
          3. If implemented, git diff --name-only contains only files listed under allowed_paths for the hypothesis.
          4. doc/implementation_status.md records attempt_id, decision, changed_paths, build_status, test_status, and notes.
          5. No tests, public schemas, benchmark scripts, generated benchmark outputs, configs, or forbidden_paths are modified.
          6. If implemented, a code commit for the attempt is completed separately from the hypothesis documentation commit.
        initial_hint: |
          Read the latest experiment entry with status=planned in
          doc/optimization_log.md. Respect its allowed_paths and forbidden_paths.
          If the hypothesis is unsafe or infeasible, do not edit source code;
          write decision=rejected and the reason to doc/implementation_status.md.
          If a previous attempt left partial changes, inspect git diff before editing.

      - id: 3.2
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
          3. If decision=implemented, git diff --name-only against the hypothesis documentation commit contains only files listed under allowed_paths plus doc/implementation_status.md.
          4. No tests, public API schemas, benchmark scripts, generated benchmark outputs, configs, or forbidden_paths were modified.
          5. Tests are not weakened: no skipped assertions, relaxed tolerances, removed test cases, or conditional bypasses.
          6. Benchmark integrity is preserved: load shape, benchmark duration, thresholds, and result JSON are not hand-edited to hide regressions.
          7. API behavior is preserved: public request/response schemas and endpoint semantics are unchanged unless explicitly listed in allowed_paths and justified by the hypothesis.
          8. doc/implementation_status.md contains verification_status=pass or the verifier records the exact failed check and stops.
          9. Only doc/implementation_status.md may be updated by this verifier subtask.
        initial_hint: |
          This is anti-hack verification only. Compare git diff --name-only and
          git diff against the latest hypothesis documentation commit. Check every
          hard constraint systematically: allowed_paths, forbidden_paths, public
          schema stability, test integrity, benchmark integrity, config integrity,
          and generated-result integrity. If any check fails, record the exact
          violation in doc/implementation_status.md and stop; do not fix code in
          this subtask.

  - id: 4
    name: "Benchmark, evaluate, and update report"
    type: long_running
    description: |
      Test and benchmark the latest implementation or record a rejected hypothesis,
      then update results, optimization log, rolling report, and failure patterns for this round.
    completion_criteria: |
      1. For implemented changes, cargo test --all exits 0 before benchmarking, or the latest result row records tests=fail and decision=reverted.
      2. For implemented changes with passing tests, k6 benchmark completes and results.json contains p95 latency.
      3. doc/optimization_results.tsv has a new row with attempt_id, kind=optimization, p95_ms when available, tests, decision, commit, and notes.
      4. If tests fail or p95_ms regresses by more than 5% versus the previous best kept row, only the latest implementation is reverted and the row has decision=reverted.
      5. If the change is kept, tests=pass and decision=kept, and no unrelated files are modified.
      6. If Task 3 rejected the hypothesis, doc/optimization_results.tsv records decision=rejected without running the benchmark.
      7. doc/optimization_log.md marks the evaluated attempt as kept, reverted, or rejected with evidence and decision_reason.
      8. doc/optimization_report.md is updated for this round with baseline vs current best, experiment summary table, kept/reverted/rejected attempts, and next directions.
      9. doc/failure_patterns.md is updated: reverted/rejected attempts are classified under proven failure patterns, and kept changes are added to promising directions.
      10. git commit completed for doc updates and any revert.
    initial_hint: |
      Read doc/implementation_status.md first. If it says decision=rejected,
      update doc/optimization_log.md, doc/optimization_results.tsv,
      doc/optimization_report.md, and doc/failure_patterns.md for the rejected
      attempt; do not run benchmarks.

      For implemented changes, run cargo test --all. If tests fail, revert only
      the latest implementation commit and record tests=fail, decision=reverted.
      If tests pass, run:
        k6 run benchmarks/load_test.js --out json=results.json

      Compare p95_ms to the previous best kept row in
      doc/optimization_results.tsv. Use git revert or manual rollback only for
      the latest optimization change; do not modify unrelated files. Update
      doc/optimization_log.md with results and decision. Update
      doc/failure_patterns.md:
      - If reverted or rejected: classify the failure (new pattern or existing?).
      - If kept: add to "Promising Directions" with what worked and why.
      Update doc/optimization_report.md by overwriting the rolling report with
      the latest baseline, current best, experiment summary table, and next
      directions. Commit doc changes and any revert.

  - id: 5
    name: "Diagnose repeated failures"
    type: simple
    description: |
      Analyze repeated implementation or benchmark failures and write
      doc/diagnosis.md with root cause and the next scheduler action.
    completion_criteria: |
      1. doc/diagnosis.md exists and summarizes recent failures with evidence from scheduler-visible artifacts.
      2. doc/diagnosis.md contains root_cause.
      3. doc/diagnosis.md contains exactly one scheduler_action: continue, stop_no_safe_optimization, or stop_external_blocker.
      4. doc/failure_patterns.md has been read and referenced in the diagnosis.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md,
      doc/implementation_status.md, doc/optimization_report.md,
      doc/failure_patterns.md, results.json if present, and recent command
      outputs or logs. Do not edit code. Focus on diagnosis and the next
      scheduler action.

  - id: 6
    name: "Write final report"
    type: simple
    max_attempts: 1
    description: |
      Produce doc/final_report.md summarizing final outcome from existing rolling
      artifacts after the target is reached or the scheduler decides to stop.
    completion_criteria: |
      1. doc/final_report.md exists.
      2. The report includes baseline p95, final/best p95, test status, kept changes, reverted changes, rejected hypotheses, failure patterns, diagnosis if present, and stop reason.
      3. The report is consistent with doc/optimization_results.tsv, doc/optimization_log.md, doc/implementation_status.md, doc/optimization_report.md, doc/failure_patterns.md, and doc/diagnosis.md if present.
      4. Only doc/final_report.md is modified by this task.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, result tables, rolling report, or failure-pattern database are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md,
      doc/implementation_status.md, doc/optimization_report.md,
      doc/failure_patterns.md, and doc/diagnosis.md if present. This is a final
      reporting task only; do not modify source code, tests, configs,
      benchmark scripts, benchmark outputs, result tables, rolling report, or
      failure-pattern database.