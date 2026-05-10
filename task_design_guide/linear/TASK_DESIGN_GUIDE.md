# Task Design Guide for AI Agents

Reference for AI agents that generate `todos.yaml` tasks for AutoAgent.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

1. **Root `description`** exists and:
(1) Covers Goal, Architecture, Key file paths, Hard constraints, Rules;
(2) Does not cover step-by-step instructions;
(3) Does not include contents that are only specific to one task (which should belong to `initial_hint`) instead of shared context;
(4) Does not include "potential/recommended approach" (unless the project requires) since AI can figure it out themselves. Doing this only narrows AI's creativity.
See §3 for full guidance.
2. **Every task** has `id`, `name`, `type`, `completion_criteria`, `initial_hint`.
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
If tests are not long-running, this rule should not be applied —— use full test mode.
9. **Choose `nested` vs `looping` by evaluation behavior**: use `nested` to reach a target end state; use `looping` to run a fixed number of iterations. See §4.1 and §5.2.
10. **State persistence**: write inter-task handoffs to files; never assume the next task can see prior conversation context. See §4.10.
11. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed and left partial changes. Include prerequisite checks in `initial_hint` and reports in `completion_criteria` for preceding failures. See §4.9.

II. Task Fields

12. **`completion_criteria`** are specific, measurable, and verifiable by the AI —— not vague or subjective like "code is good". See §4.2.
13. **`initial_hint`** lists the exact prerequisites, paths, commands, scope boundaries, and handoff files needed for the task, but never include:
(1) step-by-step instructions;
(2) "potential/recommended approach" (unless the project requires) which can be figured out by AI themselves and only narrows AI's creativity. See §4.3.
14. **`system_prompt_prefix`** defines the AI persona, role, expertise, style, and hard behavior constraints for any task, but not a substitute for `initial_hint`. See §4.4 and §6.1.
15. **`max_attempts: 1`** is set on execution-only tasks (build, benchmark, test) that don't write code for fast failure propagation. Do not set `max_attempts: 1` on active coding tasks that benefit from retries. See §4.5 and §4.6.
16. **Explicitly tells the AI to output `❌ not completed: <reason>`** when the prerequisites are already broken for execution-only subtasks. See §4.6.
17. **`model: "lite"`** is set on deterministic execution tasks; use **`model: "default"`** for most reasoning-heavy tasks like debugging, design, optimization, implementation, anti-hack review and keep/discard decisions. See §4.7.
18. **`git commit` is used** to track each task's work (if have) when each task or subtask completes.

III. Type-specific Guide

19. **Type-specific patterns**: read the relevant guide in §6 for domain-specific knowledge.

### Anti-Hack Rules

20. **Negative constraints in `completion_criteria`**: For every "implement X" task, `completion_criteria` should explicitly state what must not happen (e.g. no weakened tests, no unrelated files, no API changes, no regressions, or no forbidden generated outputs).
21. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.
22. **Verification separation**: Separate "implement" from "verify" (e.g. verification, anti-hack check, static quality review) into different subtasks.
Verification subtasks must (a) check for negative constraints in rule 20; (b) use `system_prompt_prefix` to forbid code modification; (c) use `max_attempts: 1` for fast error propagation.

### ⚠️ Critical Pitfalls —— Must Double Check

23. Are inter-task handoffs written to files instead of relying on conversation context?
24. Are completion criteria specific, measurable, and verifiable enough?
25. Does `completion_criteria` include negative constraints, and is there a "verify" task after each "implement" task for complex implementations?
26. Does `description` or `initial_hint` include step-by-step instructions or "potential/recommended approach" (unless the project requires)?
27. Your todo file **shouldn't reference this design guide or subguides** —— **Executor AI cannot see this guide**.

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
TODO：加一节Environments，描述路径约定、虚拟环境等
- **Key commands**: build/test/run/validate commands with required working directory, environment variables, and expected output locations.
- **Hard constraints**: files, APIs, tests, data, or behavior that must not change.
- **Rules**: project-wide behavior such as experiment discipline, allowed change size, or reporting format.
- **Reference Docs**: project documentation with reading priority. Keep paths and short reasons here; do not embed full document content.
  - **P0 Must Read**: read before starting any task; use only for essential architecture, API contracts, or safety constraints.
  - **P1 Read Before Related Work**: read before touching the related subsystem, file type, or feature area.
  - **P2 On Demand**: read only when debugging, stuck, or needing deeper historical/troubleshooting context.
- **Optional**:
  - Architecture Coupling Notes: exact files/modules that must be updated together.
TODO：加一节Key Configs：描述关键参数，比如超参、配置等
  - Naming Conventions: required file, branch, metric, or artifact naming patterns.
  - Historical Result Files: paths to prior attempt/iteration outputs that should be read to avoid repeated work.

Do not include:
- **step-by-step instructions**: AI can figure it out themselves.
- **contents that are only specific to one task**: They should belong to `initial_hint`. `description` describes shared context between all tasks.
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
| `1` | Execution-only subtasks: build, test, benchmark, lint, format-check, verify. These tasks do the same within retries, so `max_attempts` = 1 and fast failure propagation is recommended. See §4.6 for how this interacts with `not completed` and failure analysis. |
| `2-3` | Targeted uncertain work with constrained scope. |
| Default / higher | Active coding, debugging, optimization, refactoring. These tasks benefit from retries. |

### 4.6 Explicitly Output Failure Markers

AutoAgent detects task failure by instructing the AI to output `not completed` when they cannot meet the `completion_criteria`. It is recommended to take advantage of this mechanism when failure must propagate correctly.

- **Explicitly tell the AI to output `❌ not completed: <reason>`** when execution-only tasks (e.g. build, test, benchmark, lint, format-check, verify) fail because prerequisites are already broken, such as implementation errors from an earlier task.
The execution-only task is not supposed to modify source code. With `max_attempts: 1`, this enables fast failure propagation. For execution-only subtasks inside `nested` or `looping` tasks, it allows failure analysis to choose the correct retry boundary.

**Important: this only applies to subtasks, not top-level `simple` tasks.**

- **Relationship with "keep implement + build + test together" (rule 6) and "search for fast-check mode" (rule 8)**: 
  - "keep implement + build + test together" reduces self-correction time for implementation AI;
  - "search for fast-check mode" further reduces self-correction time because the implementation AI does not need to wait for the full test, full training, or full benchmark to finish;
  - And "Explicitly tells the AI to output `not completed`" serves as the last safety net for errors that only appear in the later full test, full training, benchmark, or verification step. 

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

Design for residual state: tasks may inherit broken filesystem state from their own retries or from earlier linear tasks. Use the `not completed` marker described in §4.6 when broken state prevents a task or subtask from meeting its criteria.

- **Same-task retry**: mention cleanup or residual-state checks in `initial_hint`; prefer overwriting or appending to known files over relying on implicit memory.
- **Predecessor failure**: add prerequisite checks in `initial_hint` and require explicit failure reports in `completion_criteria` when prerequisites are missing.
- **External tools/services**: allow partial success only when useful, and require failures to be documented.
- **Nested/looping subtasks**: align failure boundaries with meaningful checkpoints and independent failure modes.
- **Progress tracking**: store progress in clearly named files instead of relying on prior conversation context.

### 4.10 State Persistence

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

TODO：加一项Position，用于区分“是否可以出现在任何位置，还是不能出现在nested/looping task的parent fields里）

| Field | Required | Notes |
|-------|----------|-------|
| `id` | Yes | Top-level positive integer; subtask dot notation matching parent. |
| `name` | Yes | Concise human-readable label. |
| `type` | Yes | One of the task types above. |
| `completion_criteria` | Yes | Specific and verifiable. |
| `description` | Optional in linear mode | Useful short summary; required/recommended in AI scheduling mode. |
| `initial_hint` | Yes | Executor-facing context and guidance. |
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
| `simple` / `long_running` / `*_once` | `initial_hint` required; optional `max_attempts`, `model`, `system_prompt_prefix`. |

---

## 6. Minimal Skeleton Example

Use this skeleton to understand the required `todos.yaml` structure. Replace every `<placeholder>` token with task-specific content; do not copy the placeholder wording into real tasks. `<!-- xxx -->` are comments that explain this example in detail, so do not include them into real tasks either.

```yaml
description: |
  # <project name>

  ## Goal
  <goal>

  ## Architecture
  - <component or module 1>: <its responsibility>
  - <component or module 2>: <its responsibility>
  ...

  ## Key file paths
  - <file path 1>: <its purpose>
  - <file path 2>: <its purpose>
  <!-- Only put relevant files here. -->
  ...

  ## Environments
  <environments>

  ## Key commands
  - <command 1>: <command>
  - <command 2>: <command>
  ...

  ## Hard constraints
  - <constraints>

  ## Rules
  <rules>

tasks:
  - id: 1
    name: "<task name>"
    type: simple
    completion_criteria: |
      <completion_criteria>
    initial_hint: |
      <initial_hint>

  - id: 2
    name: "<task name>"
    type: nested 
    completion_criteria: |
      <overall completion_criteria>
    subtasks:
      - id: 2.1
        name: "<subtask name>"
        type: simple
        completion_criteria: |
          <task-specific completion_criteria>
        initial_hint: |
          <initial_hint>

  - id: 3
    name: "<task name>"
    type: looping
    completion_criteria: |
      <overall completion_criteria>
    subtasks:
      - id: 3.1
        name: "<subtask name>"
        type: long_running
        completion_criteria: |
          <task-specific completion_criteria>
        initial_hint: |
          <initial_hint>    
```

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