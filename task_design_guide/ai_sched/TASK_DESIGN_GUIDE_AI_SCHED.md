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
2. **Every task** has `id`, `name`, `type`, `description`, `completion_criteria`, `initial_hint`.
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
11. **State persistence**: write inter-task handoffs to files; never assume the next task can see prior conversation context. See §4.11.
12. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed and left partial changes. Scheduler's failure handling strategy is dominant, while task's prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures are still required as a fallback. See §4.10.

II. Task Fields

13. **Task-specific `description`** is scheduler-facing, with only 1-3 sentences explaining what the task does and produces. See §4.2.
14. **`completion_criteria`** are specific, measurable, and verifiable by the AI —— not vague or subjective like "code is good". See §4.3.
15. **`initial_hint`** lists the exact prerequisites, paths, commands, scope boundaries, and handoff files needed for the task, but never include:
(1) step-by-step instructions;
(2) "potential/recommended approach" (unless the project requires) which can be figured out by AI themselves and only narrows AI's creativity;
(3) Instructions about copying results to a specified path for scheduler since scheduler and executor share the same filesystem. See §4.4.
16. **`system_prompt_prefix`** defines the AI persona, role, expertise, style, and hard behavior constraints for any task, but not a substitute for `initial_hint`. See §7.1.
17. **`max_attempts: 1`** is set on execution-only tasks (build, benchmark, test) that don't write code for fast failure propagation. Do not set `max_attempts: 1` on active coding tasks that benefit from retries. See §4.6 and §4.7.
18. **Explicitly tells the AI to output `❌ not completed: <reason>`** when the prerequisites are already broken for execution-only subtasks. See §4.7.
19. **`model: "lite"`** is set on deterministic execution tasks; use **`model: "default"`** for most reasoning-heavy tasks like debugging, design, optimization, implementation, anti-hack review and keep/discard decisions. See §4.8.
20. **`git commit` is used** to track each task's work (if have) when each task or subtask completes.

III. Type-specific Guide

21. **Type-specific patterns**: read the relevant guide in §7 for domain-specific knowledge.

### AI Scheduling Rules

I. Fields under ai_orchestrator

22. **`strategy`** references task IDs, encodes task dependencies, and includes failure recovery rules. See §5.2.
23. **`last_result`** is configured for every task whose output is needed by scheduler. Use `${workspace}` for workspace-relative paths; it is expanded at runtime. See §5.3.
24. **`stop_condition`** is specific, measurable, and includes a fallback (e.g. after 5 consecutive failures). See §5.4.

II. AI Scheduling Rules for Task Decomposition

25. **Max ~5-8 top-level tasks** —— more bloats the scheduler prompt.
26. **Design for re-execution**: design tasks that can run 0, 1, or many times.
27. **Scheduler observable**: Documentation task or subtask should provide enough information in `last_result` files for scheduler to make precise decisions. 
28. **Designing tail-friendly `last_result`**: keep scheduler-critical status in small summary files (especially when scheduler needs cross-round analysis) or at the end of result files, because the last 5 lines of `last_result` is directly injected into scheduler's prompt.

### Anti-Hack Rules

29. **Negative constraints in `completion_criteria`**: For every "implement X" task, `completion_criteria` should explicitly state what must not happen (e.g. no weakened tests, no unrelated files, no API changes, no regressions, or no forbidden generated outputs).
30. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.
31. **Verification separation**: Separate "implement" from "verify" (e.g. verification, anti-hack check, static quality review) into different subtasks.
Verification subtasks must (a) check for negative constraints in rule 29; (b) use `system_prompt_prefix` to forbid code modification; (c) use `max_attempts: 1` for fast error propagation.

### ⚠️ Critical Pitfalls —— Must Double Check

32. Are inter-task handoffs written to files instead of relying on conversation context?
33. Are completion criteria specific, measurable, and verifiable enough?
34. Does `completion_criteria` include negative constraints, and is there a "verify" task after each "implement" task for complex implementations?
35. Does `description` or `initial_hint` include step-by-step instructions or "potential/recommended approach" (unless the project requires)?
36. Are `last_result` correctly set so that scheduler can see each task's execution results? Will files specified in `last_result` be created by tasks BEFORE scheduler wants to see them?
37. Are `${workspace}` used in `last_result` to reference relative paths?

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

### 4.7 `max_attempts`

Set different `max_attempts` for different types of tasks:

| Value | Use |
|-------|-----|
| `1` | Execution-only subtasks: build, test, benchmark, lint, format-check, verify. These tasks do the same within retries, so `max_attempts` = 1 and fast failure propagation is recommended. See §4.7 for how this interacts with `not completed`, failure analysis, and scheduler-visible results. |
| `2-3` | Targeted uncertain work with constrained scope. |
| Default / higher | Active coding, debugging, optimization, refactoring. These tasks benefit from retries. |

AutoAgent detects task failure by instructing the AI to output `not completed` when they cannot meet the `completion_criteria`. It is recommended to take advantage of this mechanism when failure must propagate correctly.

- **Explicitly tell the AI to output `❌ not completed: <reason>`** when execution-only tasks (e.g. build, test, benchmark, lint, format-check, verify) fail because prerequisites are already broken, such as implementation errors from an earlier task.
The execution-only task is not supposed to modify source code. With `max_attempts: 1`, this enables fast failure propagation. For execution-only subtasks inside `nested` tasks, it allows failure analysis to choose the correct retry boundary.

**Important: this only applies to subtasks, not top-level `simple` tasks.**

- **Relationship with "keep implement + build + test together" (rule 8) and "search for fast-check mode" (rule 10)**: 
  - "keep implement + build + test together" reduces self-correction time for implementation AI;
  - "search for fast-check mode" further reduces self-correction time because the implementation AI does not need to wait for the full test, full training, or full benchmark to finish;
  - And "Explicitly tells the AI to output `not completed`" serves as the last safety net for errors that only appear in the later full test, full training, benchmark, or verification step.

### 4.8 `model`

Set different `model` by:

| Value | Use |
|-------|-----|
| Omit / `default` | Reasoning-heavy work: design, debug, implement, optimize, anti-hack review. |
| `lite` | Deterministic execution: run commands, format, copy/summarize known outputs. |
| Direct name | Only when the project specifies a tailored model name. |

### 4.9 Anti-Hack Patterns

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

### 4.10 Failure Resilience

Design for residual state: tasks may inherit broken filesystem state from their own retries or from prior scheduled tasks. Use the `not completed` marker described in §4.7 when broken state prevents a task or subtask from meeting its criteria.

- **Same-task retry**: mention cleanup or residual-state checks in `initial_hint`; prefer overwriting or appending to known files over relying on implicit memory.
- **Predecessor failure**: encode preferred handling in `strategy` and expose status through `last_result`.
- **Task-level safety net**: include prerequisite checks in `initial_hint` when a task depends on build/test/data state.
- **External tools/services**: allow partial success only when useful, and require failures to be documented.
- **Nested subtasks**: align failure boundaries with meaningful checkpoints and independent failure modes.
- **Progress tracking**: store progress in clearly named files instead of relying on prior conversation context.

### 4.11 State Persistence

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
| `description` | Yes | Scheduler-facing summary of what the task does and produces. |
| `completion_criteria` | Yes | Specific, measurable success criteria. |
| `initial_hint` | Yes | Executor-facing context and guidance. |
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
| `simple` / `long_running` / `*_once` | `initial_hint` required; optional `max_attempts`, `model`, `system_prompt_prefix`. |

---

## 7. Minimal Skeleton Example

Use this skeleton to understand the required `todos.yaml` structure. Replace every `<placeholder>` token with task-specific content; do not copy the placeholder wording into real tasks.

```yaml
description: |
  # <project-name>

  ## Goal
  <goal>

  ## Architecture
  - <component-or-path>: <responsibility>

  ## Key file paths
  - <path>: <purpose>

  ## Key commands
  - <command-name>: <command>

  ## Hard constraints
  - <constraint>

  ## Rules
  - <rule>

ai_orchestrator:
  strategy: |
    <scheduling-rule>
    <failure-recovery-rule>
  stop_condition: |
    <observable-stop-condition>
  last_result:
    1:
      type: file
      path: ${workspace}/<path-to-result>
    2:
      type: response

tasks:
  - id: 1
    name: "<task-name>"
    type: simple
    description: |
      <scheduler-facing-summary>
    completion_criteria: |
      <measurable-condition>
    initial_hint: |
      <prerequisites-paths-commands-scope>

  - id: 2
    name: "<task-name>"
    type: nested
    description: |
      <scheduler-facing-summary>
    completion_criteria: |
      <measurable-condition>
    subtasks:
      - id: 2.1
        name: "<subtask-name>"
        type: long_running
        description: |
          <scheduler-facing-summary>
        completion_criteria: |
          <measurable-condition>
        initial_hint: |
          <prerequisites-paths-commands-scope>
```

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
