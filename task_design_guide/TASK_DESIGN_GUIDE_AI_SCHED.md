# Task Design Guide — AI Scheduling Mode

Reference for AI agents that generate `todos.yaml` tasks for AI-scheduled AutoAgent execution.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

I. General Schema Rules

1. **Root `description`** exists and:
(1) covers Goal, Architecture, Key file paths, Hard constraints, Rules;
(2) does not cover step-by-step instructions which should belong to `initial_hint`;
(3) does not include "potential/recommended approach" since AI can figure it out themselves. Doing this only narrows AI's creativity;
(4) does not cover scheduler-only ordering rules (e.g. execute task 2 after 1, this is a two-phase optimization).
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
(1) keep logically dependent work in one task (e.g. when implementing tightly coupled modules A and B).
(2) Keep implement + build + task in one task so the AI can self-correct in the same session. See §4.1.
(3) Split tasks only at trust boundaries (e.g. anti-hack verification must be a separate subtask) or expensive/time-consuming checkpoints (See rule 9).
9. **No under-decomposition**: separate expensive (e.g. idea composition, implementation) and time-consuming steps (e.g. training, benchmark, verification, reporting) into distinct top-level tasks so the scheduler can re-execute them individually. See §4.1.
10. **Search for fast-check build/test modes**: when merging implement + build + test in one subtask, search for fast-check/profile mode in build/test framework instead of running the full test/training. This will significantly speed up self-correction. Split long-running full test/training to subsequent benchmark task.
11. **State persistence**: write inter-task handoffs to named files; never assume the next task can see prior conversation context. See §4.7.
12. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed and left partial changes. Scheduler's failure handling strategy is dominant, while task's prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures are still required as a fallback. See §4.6.

II. Task Fields

13. **Task-specific `description`** is scheduler-facing, with only 1-3 sentences explaining what the task does and produces. See §4.2.
14. **`completion_criteria`** are specific, measurable, and verifiable by the AI —— not vague or subjective like "code is good". See §4.3.
15. **`initial_hint`** lists the exact paths, commands, prerequisites, scope boundaries, and handoff files needed for the task, but it must not duplicate `completion_criteria` or become a rigid click-by-click script. See §4.4.
16. **`system_prompt_prefix`** defines the AI persona, role, expertise, style, and hard behavior constraints for any task, but not a substitute for `initial_hint`. See §7.1.
17. **`max_attempts: 1`** is set on execution-only tasks (build, benchmark, test) that don't write code for fast failure propagation. Do not set `max_attempts: 1` on active coding tasks that benefit from retries. See §7.2.
18. **`model: "lite"`** is set on deterministic execution tasks; use default for most reasoning-heavy tasks like debugging, design, optimization, implementation, anti-hack review and keep/discard decisions. See §7.3.
19. **`git commit` is used** when each task or subtask completes.

III. Type-specific Guide

20. **Type-specific patterns**: Read the relevant guide in §8 for your task type.

### AI Scheduling Rules

I. Fields under ai_orchestrator

21. **`strategy`** references task IDs, encodes task dependencies, and includes failure recovery rules. See §5.2.
22. **`last_result`** is configured for every task whose output is needed by scheduler. Use `${workspace}` for workspace-relative paths; it is expanded at runtime. See §5.3.
23. **`stop_condition`** is specific, measurable, and includes a fallback (e.g. after N consecutive failures). See §5.4.

II. AI Scheduling Rules for Task Decomposition

24. **Task independence**: Task ordering is encoded in scheduler's `strategy`, not in task's own `description` or `initial_hint`.
25. **Max ~5-8 top-level tasks** —— more bloats the scheduler prompt.
26. **Design for re-execution**: tasks may run 0, 1, or many times.
27. **Scheduler observables**: design around what the scheduler can see (description, execution count, last result, history).

### Anti-Hack Rules

28. **Negative constraints in `completion_criteria`**: For every "implement X" task, `completion_criteria` should explicitly state what must not happen (e.g. no weakened tests, no unrelated files, no API changes, no regressions, or no forbidden generated outputs).
29. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.
30. **Verification separation**: Separate "implement" from "verify" (e.g. verification, anti-hack check, static quality review) into different subtasks.
Verification subtasks must (a) check for negative constraints in rule 27; (b) use `system_prompt_prefix` to forbid code modification and `max_attempts: 1` for fast error propagation.

### ⚠️ Critical Pitfalls —— Must Double Check

31. Are inter-task handoffs written to named files instead of relying on conversation context?
32. Are completion criteria specific, measurable, and verifiable enough?
33. Are `last_result` correctly set so that scheduler can see each task's execution results? Will files specified in `last_result` be created BEFORE scheduler wants to see them?
34. Does `completion_criteria` include negative constraints, and is there a verify task after each implement task for complex implementations?

---

## 2. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through tasks defined in `todos.yaml`.

### 2.1 General Properties

1. **Fully autonomous —— No human is in the loop**

**Implication**: `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification.

2. **Context isolation between tasks and subtasks**

Tasks and subtasks **share the filesystem, not conversation context**. AI sessions are reset between tasks and subtasks. No response is passed between top-level tasks; only a summary of the previous subtask may be passed between subtasks.
**Implication**: design top-level tasks independently, and persist detailed intermediate results to files.

3. **Failed tasks do not automatically block later work**

**Implication**: Scheduler's failure handling strategy is dominant, while task's prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures are still required as a fallback.

4. **`long_running` is used to avoid AI session timeout**

**Implication**: Use `long_running` for builds, tests, benchmarks, training, profiling, or data jobs that can run >1 minute.

### 2.2 AI Scheduling Properties

1. **Dynamic execution**

In AI scheduling mode, an AI scheduler dynamically chooses **one top-level task per round**, or chooses to stop. It does not schedule subtasks; subtasks inside the selected top-level task run sequentially through normal task executors.

**Implication**:
(1) Prefer single `simple` / `long_running` top-level tasks; let the scheduler handle ordering and re-execution. See §4.1 for when to use subtasks.
(2) Design tasks that can be run 0, 1, or many times.

2. **Scheduler has a context limit**

What the scheduler sees each round:
- root `description`;
- `ai_orchestrator.strategy`, `ai_orchestrator.stop_condition`;
- `last_result` paths, with a short preview for the most recently scheduled task;
- every top-level task's `id`, `name`, `type`, `description`, and execution count;
- recent schedule history.

What the scheduler does **not** see directly:
- inner conversation context when `last_result != response`;
- internal subtask state;
- files not exposed through `last_result`;
- details in task's `completion_criteria` and `initial_hint`.

**Implication**:
- Persist task outputs needed for scheduling to files, or expose summaries via `last_result: type: response`.

3. **`last_result` is not scheduler-only**

File paths in `last_result` is shared between scheduler and executor, not scheduler-only.
**Implication**: Use `last_result` to inform the scheduler of where to retrieve results, instead of saying "Executor must copy results to xxx" or "Persist scheduler-relevant outcomes in xxx" elsewhere.

---

## 3. Root `description`

Root `description` is injected into every executor prompt, shared for both scheduler and executors.

Include:
- **Goal**: final observable outcome and success threshold.
- **Architecture**: key directories/modules and their responsibilities.
- **Key file paths**: configs, inputs, outputs, reports, logs.
- **Key commands**: build/test/run/validate commands with required working directory, environment variables, and expected output locations.
- **Hard constraints**: files, APIs, tests, data, or behavior that must not change.
- **Rules**: project-wide behavior such as experiment discipline, allowed change size, or reporting format.
- **Reference Docs**: project documentation with reading priority. Keep paths and short reasons here; do not embed full document content.
  - **P0 Must Read**: read before starting any task; keep this minimal to avoid scheduler/executor context bloat.
  - **P1 Read Before Related Work**: read before touching the related subsystem, file type, or feature area.
  - **P2 On Demand**: read only when debugging, blocked, or needing deeper historical/troubleshooting context.
- **Optional**:
  - Architecture Coupling Notes: exact files/modules that must be updated together.
  - Naming Conventions: required file, branch, metric, or artifact naming patterns.
  - Historical Result Files: paths to prior attempt/iteration outputs that should be read to avoid repeated work.

Do not include:
- **scheduler-only ordering rules** (e.g. execute task 2 after 1, this is a two-phase optimization): put them in `ai_orchestrator.strategy`.
- **step-by-step instructions**: put them in task's `initial_hint`.
- **potential/recommended approach**: AI can figure it out themselves. Doing this only narrows AI's creativity.

Rule of thumb:
root `description` is for shared project context; `strategy` is for scheduler decisions; `initial_hint` is for executor.

---

## 4. Design Principles

These principles are not self-contained; they extend rules in §1. Take both principles and rules into account when designing todos.

### 4.1 Task Decomposition

In AI scheduling mode, the principle is **default flat** —— prefer top-level `simple` / `long_running` tasks. Let the scheduler handle ordering, re-execution, and conditional branching. Avoid hiding scheduler-relevant phases inside one large nested task.

| Situation | Prefer |
|-----------|--------|
| Small targeted fix, format run, inspection, or quick test | Top-level `simple` |
| Command may run >1 minute | Top-level `long_running` |

Use `nested` tasks only when:
- **Enforced sequential ordering** is required and the scheduler cannot guarantee it (e.g. anti-hack verification must run after implementation, report must run after tests pass);
- **bundling several lightweight steps** into one top-level task to reduce scheduling overhead.

`looping` tasks are generally not recommended in AI scheduling mode: let the scheduler perform loop actions instead.

#### Anti-Patterns

- **Over-decomposition**: splitting `edit -> build -> fix build -> test` into separate tasks will lose local reasoning context. Keep one coding loop together unless:
(1) The `test` command is long-running or verification must be isolated;
(2) Code has substantial changes that are not suitable to implement in one single session. In this case, split code changes by modules.

- **Under-decomposition**: putting everything (analysis, implementation, benchmark, anti-hack review, and reporting) into one task causes context explosion, degrading AI performance and wasting retries. Split when a phase has a separate artifact, high runtime cost, or different trust boundary.

### 4.2 Task-specific `description`

Task-specific `description` is the **only way** the scheduler AI understands what a task does. The scheduler sees `id`, `name`, `type`, `description`, execution count, and last result for each task; it does not see `completion_criteria` or `initial_hint`.

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

| Level | Role | Example |
|-------|------|---------|
| Top-level task | Final task success visible to scheduler | `doc/perf_result.tsv contains p95 latency and correctness status` |
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

### 4.4 `initial_hint`

`initial_hint` is executor-facing task-local context. Scheduler cannot see it.

| Put in `initial_hint` | Do not put in `initial_hint` |
|-----------------------|------------------------------|
| Exact files/directories to inspect or modify | Project-wide context already in root `description` |
| Commands, working directory, environment, and output files | Scheduler ordering rules |
| Step-specific constraints, scope boundaries, and forbidden changes | `completion_criteria` copied from the separate field |
| Prerequisite checks and handoff artifacts | Persona, role, expertise, or global behavior framing |
| Expected artifacts to read/write | Long rigid playbooks unless procedure must be exact |
| Cleanup guidance for previous failed attempts | Unrelated background docs |
| Likely failure modes and safe recovery hints | |

Use `initial_hint` to make retries safe: ask the executor to inspect `git diff`, generated files, partial outputs, and previous result files when relevant.

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

Example verification constraints:

```yaml
system_prompt_prefix: |
  You are a verifier. Do NOT modify source code, tests, configs, or generated results.
completion_criteria: |
  1. cargo test --all passes.
  2. git diff --name-only shows no files under tests/.
  3. git diff --stat shows changes only under src/parser/.
```

### 4.6 Failure Resilience

Design for residual state: tasks may inherit broken filesystem state from their own retries or from prior scheduled tasks.

- **Same-task retry**: mention cleanup or residual-state checks in `initial_hint`; prefer overwriting or appending to known files over relying on implicit memory.
- **Predecessor failure**: encode preferred handling in `strategy` and expose status through `last_result`.
- **Task-level safety net**: include prerequisite checks in `initial_hint` when a task depends on build/test/data state.
- **External tools/services**: allow partial success only when useful, and require failures to be documented.
- **Nested/looping subtasks**: align failure boundaries with meaningful checkpoints and independent failure modes.
- **Progress tracking**: store progress in clearly named files instead of relying on prior conversation context.

Scheduler-level recovery example:

```yaml
strategy: |
  Scheduling rules:
  1. Do not run Task 3 (Optimize) unless Task 1 last_result reports baseline success.
  2. If Task 3 fails 3 consecutive times, run Task 5 (Diagnose).
```

### 4.7 State Persistence

Tasks and subtasks share files, not conversation memory.

- **Producer**: write findings/results to named files with enough detail for a fresh session.
- **Consumer**: read those files via `initial_hint`; if missing or incomplete, report prerequisite failure.
- **Scheduler**: reads only configured `last_result` plus execution history.
- **Executor**: reads files named in root `description` or `initial_hint`.

Configure both sides when a top-level result affects scheduling: task writes the file, `last_result` exposes it to the scheduler, and dependent task `initial_hint` tells the executor to read it.

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

```yaml
strategy: |
  Scheduling rules:
  1. If Task 1 (Baseline) has never succeeded, run Task 1.
  2. After baseline, run Task 2 (Analyze) unless there is an unused recommendation.
  3. If Task 2 produced a recommendation, run Task 3 (Implement and verify).
  4. After Task 3 succeeds, run Task 4 (Benchmark).
  5. If Task 4 reports p95 < 50ms, stop.
  6. If Task 3 fails 3 consecutive times, run Task 5 (Diagnose).
```

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
- `looping` or cumulative-result tasks usually need `type: file`;
- if `strategy` references a task's output, configure `last_result` for that task.

```yaml
last_result:
  1:
    type: file
    path: ${workspace}/baseline_profile.txt
  4:
    type: file
    path:
      - ${workspace}/test_result.txt
      - ${workspace}/perf_comparison.txt
  5:
    type: response
```

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
| `description@N` | Optional | Scoped description; latest applicable description is used. |
| `ai_orchestrator` | Yes | AI scheduling configuration. |
| `tasks` | Yes | Top-level task definitions. |

### 6.2 Task Types

| Type | Top-level | Subtask | Use for |
|------|-----------|---------|---------|
| `simple` | Yes | Yes | Code changes, tests, analysis, quick builds. |
| `long_running` | Yes | Yes | Commands that may take >1 minute. |
| `nested` | Yes | Yes | Ordered subtasks inside one selected task. |
| `looping` | Yes | Yes | Fixed repeated cycles. |
| `simple_once` | No | Yes | One-time setup that should survive later retries. |
| `long_running_once` | No | Yes | Expensive one-time setup/baseline command. |

Notes:
- prefer `long_running` over `simple` for commands that may take >1 minute;
- use `*_once` sparingly; most subtasks should be re-executable;
- in AI scheduling mode, completed `*_once` subtasks are not re-executed across scheduling rounds;
- looping iteration failure stops remaining iterations after retries are exhausted;
- keep nested subtasks shallow.

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

### 6.4 Type-Specific Fields

| Type | Extra fields |
|------|--------------|
| `nested` | `subtasks` required; optional `max_attempts`. |
| `looping` | `subtasks` and positive integer `repeat_count` required; optional `max_attempts_per_loop`. |
| `simple` / `long_running` / `*_once` | Optional `initial_hint`, `max_attempts`, `model`, `system_prompt_prefix`. |

### 6.5 Hierarchy and ID Rules

- Top-level tasks may be `simple`, `nested`, `looping`, or `long_running`.
- Subtasks inside nested/looping may use all six types.
- `simple_once` and `long_running_once` can only be subtasks.
- Top-level IDs are positive integers; keep them sequential for readability.
- Subtask IDs must be unique, dot-notated, parent-prefixed, and increasing under the same parent.

---

## 7. Field Usage Cheatsheet

### 7.1 `system_prompt_prefix`

Use `system_prompt_prefix` for persona, role, or hard behavior constraints.

| Use case | Example |
|----------|---------|
| Persona / expertise | `You are a careful ML engineer.` |
| Domain role | `You are a GPU performance engineer.` |
| Task-specific restriction | `Never modify files in vendor/.` |
| Coding style | `Follow Google C++ style guide.` |
| Execution-only verifier | `You are a benchmark runner. Do NOT modify source code.` |

Notes:
- applies to all task types when a persona or hard behavior constraint is useful;
- especially important for verification/execution-only subtasks that must not edit code;
- do not set it on top-level `nested` or `looping`; set it on individual subtasks.

### 7.2 `max_attempts`

| Level | Field | What counts as one attempt |
|-------|-------|----------------------------|
| Top-level `simple` / `long_running` | `max_attempts` | One full task execution. |
| Top-level `nested` | `max_attempts` | One full round: all subtasks then overall evaluation. |
| Top-level `looping` | `max_attempts_per_loop` | Retry round within one iteration. |
| Subtask | `max_attempts` | One execution of that subtask. |

Use `max_attempts: 1` for execution-only subtasks that just run code written by a sibling: build, benchmark, test, export. Do not use `max_attempts: 1` for active coding subtasks.

### 7.3 `model`

| Value | Use for |
|-------|---------|
| `default` or omit | Complex reasoning, debugging, design, optimization, implementation. |
| `lite` | Straightforward execution, formatting, benchmark/report tasks. |
| Direct model name | Cases requiring a specific model. |

### 7.4 `long_running`

| Situation | Prefer |
|-----------|--------|
| Command may take >1 minute | `long_running` / `long_running_once` |
| Quick command whose output guides code edits immediately | `simple` |
| Expensive idempotent setup inside nested/looping | `long_running_once` subtask |

---

## 8. Task-Type-Specific Guides

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

## 9. Complete AI Scheduling Example

Below is a complete `todos.yaml` for AI scheduling mode. It demonstrates scheduler-visible task `description`, file-backed `last_result`, re-executable top-level tasks, anti-hack verification, and durable scheduler state.

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
  - Config: config/server.yaml
  - Cumulative results: doc/optimization_results.tsv
  - Optimization log: doc/optimization_log.md
  - Implementation status: doc/implementation_status.md
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
  - Keep each optimization focused, reversible, and limited to its declared scope.

  ## Scheduler State Conventions
  - doc/optimization_results.tsv rows include: attempt_id, kind, p95_ms,
    tests, decision, notes.
  - doc/optimization_log.md recommendations include: recommendation_id, status,
    allowed_paths, forbidden_paths, rationale, expected_impact, risk.
  - doc/implementation_status.md includes: recommendation_id, decision,
    changed_paths, build_status, test_status, verification_status, notes.
  - doc/diagnosis.md includes: root_cause and scheduler_action.

  ## Reference Docs
  - P0 Must Read: doc/architecture.md —— request flow and service boundaries
  - P1 Read Before Related Work: doc/database.md —— read before changing src/db/
  - P1 Read Before Related Work: doc/cache.md —— read before changing src/cache/
  - P2 On Demand: doc/performance_history.md —— read when benchmark results are surprising or repeated work is suspected

  ## Rules
  - Fully autonomous: never ask the user questions.
  - Persist scheduler-relevant outcomes in the files listed above.
  - Implement at most one unused recommendation per attempt.
  - If prerequisites are broken before a task starts, report that state in the
    task's output file instead of broadening scope.

ai_orchestrator:
  max_rounds: 20
  strategy: |
    Scheduling rules:
    1. If Task 1 (Establish baseline) has never succeeded, run Task 1.
    2. After Task 1 succeeds, run Task 2 (Analyze bottleneck) unless
       doc/optimization_log.md contains an unused recommendation whose
       recommendation_id is newer than the latest attempt row in
       doc/optimization_results.tsv.
    3. If the latest recommendation has status=unused, run Task 3 (Implement
       and verify one change).
    4. After Task 3 succeeds with doc/implementation_status.md containing
       decision=implemented and verification_status=pass, run Task 4 (Benchmark
       and evaluate latest change).
    5. If Task 3 succeeds with decision=rejected, run Task 2 again to choose a
       different focused optimization.
    6. If Task 4 writes a latest row with tests=pass and p95_ms < 50, run
       Task 6 (Write final report), then stop after doc/final_report.md exists.
    7. If Task 4 writes decision=reverted or tests=fail, run Task 2 again.
    8. If Task 3 or Task 4 fails twice consecutively, run Task 5 (Diagnose
       repeated failures).
    9. After Task 5 succeeds, run Task 2 again when scheduler_action=continue;
       run Task 6 when scheduler_action=stop_no_safe_optimization or
       scheduler_action=stop_external_blocker.
  stop_condition: |
    Stop after doc/final_report.md exists and is consistent with the latest
    scheduler-visible artifacts, or after Task 5 reports scheduler_action as
    stop_no_safe_optimization or stop_external_blocker and Task 6 has run, or
    after 3 consecutive unrecoverable scheduler rounds with no new artifact.
  last_result:
    1:
      type: file
      path: ${workspace}/doc/optimization_results.tsv
    2:
      type: file
      path: ${workspace}/doc/optimization_log.md
    3:
      type: file
      path: ${workspace}/doc/implementation_status.md
    4:
      type: file
      path: ${workspace}/doc/optimization_results.tsv
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
      the baseline row in doc/optimization_results.tsv for scheduler decisions.
    completion_criteria: |
      1. cargo build --release exits 0.
      2. cargo test --all exits 0.
      3. k6 benchmark completes and writes results.json.
      4. doc/optimization_results.tsv contains one baseline row with kind=baseline, p95_ms, tests=pass, and decision=baseline.
      5. No source files, tests, configs, benchmark scripts, or generated benchmark results are modified except results.json from the benchmark command.
      6. git diff --name-only shows only doc/optimization_results.tsv and results.json changed by this task.
    initial_hint: |
      Commands:
      - cargo build --release
      - cargo test --all
      - k6 run benchmarks/load_test.js --out json=results.json

      If doc/optimization_results.tsv already exists, preserve existing attempt
      rows and append or refresh only the baseline row. Do not modify source
      code, tests, configs, or benchmark scripts.

  - id: 2
    name: "Analyze bottleneck and propose next optimization"
    type: simple
    description: |
      Analyze current benchmark data and source hotspots, then append one
      focused unused recommendation to doc/optimization_log.md.
    completion_criteria: |
      1. doc/optimization_log.md contains exactly one new recommendation with recommendation_id and status=unused.
      2. The recommendation includes allowed_paths, forbidden_paths, rationale, expected_impact, and risk.
      3. The recommendation is not a repeat of an experiment already marked failed, reverted, rejected, or kept.
      4. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md, and relevant
      source files. Propose exactly one focused optimization. Keep the allowed
      scope narrow enough for Task 3 to verify with git diff --name-only.

  - id: 3
    name: "Implement and verify one change"
    type: nested
    description: |
      Implement the latest unused recommendation, run local build/tests, and use
      a separate verifier subtask to confirm behavior and scope before benchmarking.
    completion_criteria: |
      1. doc/implementation_status.md exists for the latest recommendation_id.
      2. The status file contains decision=implemented or decision=rejected.
      3. If decision=implemented, the status file contains build_status=pass, test_status=pass, verification_status=pass, and changed_paths.
      4. If decision=rejected, the status file contains a concrete safety or feasibility reason and no source/test/config changes remain.
    subtasks:
      - id: 3.1
        name: "Implement focused optimization, build, and test"
        type: simple
        completion_criteria: |
          1. Exactly one latest recommendation with status=unused is either implemented or rejected.
          2. If implemented, cargo build --release exits 0 and cargo test --all exits 0.
          3. If implemented, git diff --name-only contains only files listed under allowed_paths for the recommendation.
          4. doc/implementation_status.md records recommendation_id, decision, changed_paths, build_status, test_status, and notes.
          5. No tests, public schemas, benchmark scripts, generated benchmark outputs, or forbidden_paths are modified.
        initial_hint: |
          Read the latest recommendation with status=unused in
          doc/optimization_log.md. Respect its allowed_paths and forbidden_paths.
          If the recommendation is unsafe or infeasible, do not edit source code;
          write decision=rejected and the reason to doc/implementation_status.md.
          If a previous attempt left partial changes, inspect git diff before editing.

      - id: 3.2
        name: "Verify implementation scope without modifications"
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
          5. doc/implementation_status.md contains verification_status=pass or the verifier reports the exact failed check and stops.
          6. Only doc/implementation_status.md may be updated by this verifier subtask.
        initial_hint: |
          Run verification only. Compare git diff --name-only against the latest
          recommendation's allowed_paths and forbidden_paths. If checks fail,
          report the exact failure in doc/implementation_status.md and stop; do
          not fix code in this subtask.

  - id: 4
    name: "Benchmark and evaluate latest change"
    type: long_running
    description: |
      Test and benchmark the latest verified implementation, append a result row,
      and keep or revert only that implementation based on objective thresholds.
    completion_criteria: |
      1. cargo test --all exits 0 before benchmarking, or the latest result row records tests=fail and decision=reverted.
      2. k6 benchmark completes and results.json contains p95 latency when tests pass.
      3. doc/optimization_results.tsv has a new row with attempt_id, kind=optimization, p95_ms, tests, decision, and notes.
      4. If tests fail or p95_ms regresses by more than 5% versus the previous best kept row, only the latest implementation is reverted and the row has decision=reverted.
      5. If the change is kept, tests=pass and decision=kept, and no unrelated files are modified.
      6. doc/optimization_log.md marks the evaluated recommendation as kept or reverted with the same attempt_id.
    initial_hint: |
      Before benchmarking, run cargo test --all. If tests fail, revert only the
      latest implementation and record tests=fail, decision=reverted. If tests
      pass, run:
      k6 run benchmarks/load_test.js --out json=results.json

      Compare p95_ms to the previous best kept row in
      doc/optimization_results.tsv. Use git revert or manual rollback only for
      the latest optimization change; do not modify unrelated files.

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
      4. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md,
      doc/implementation_status.md, results.json if present, and recent command
      outputs or logs. Do not edit code. Focus on diagnosis and the next
      scheduler action.

  - id: 6
    name: "Write final report"
    type: simple
    max_attempts: 1
    description: |
      Produce doc/final_report.md summarizing baseline, final performance, kept
      and reverted attempts, diagnosis if any, and the stop reason.
    completion_criteria: |
      1. doc/final_report.md exists.
      2. The report includes baseline p95, final/best p95, test status, kept changes, reverted changes, rejected recommendations, diagnosis if present, and stop reason.
      3. The report is consistent with doc/optimization_results.tsv, doc/optimization_log.md, doc/implementation_status.md, and doc/diagnosis.md if present.
      4. Only doc/final_report.md is modified by this task.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
    initial_hint: |
      Read doc/optimization_results.tsv, doc/optimization_log.md,
      doc/implementation_status.md, and doc/diagnosis.md if present. This is a
      reporting task only; do not modify source code, tests, configs,
      benchmark scripts, benchmark outputs, or result tables.
