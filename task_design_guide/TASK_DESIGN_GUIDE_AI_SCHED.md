# Task Design Guide — AI Scheduling Mode

Reference for AI agents that generate TODO tasks for AI-scheduled execution.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

I. General Schema Rules

1. **Root `description`** exists and covers: Goal, Architecture, Key file paths, Hard constraints, Rules. See §3 for full guidance.
2. **Every task** has `id`, `name`, `type`, `description`, `completion_criteria`.
3. **ID assignment**: top-level IDs are sequential integers; subtask IDs use dot notation (e.g., 1.1, 1.2).
4. **`*_once` types** (`simple_once`, `long_running_once`) can ONLY be subtasks, not top-level tasks.
5. **`long_running`** is used for any command that may take > 1 minute.

II. AI Scheduling Schema Rules

6. **`ai_orchestrator`** is configured with `strategy`, `stop_condition`, `last_result` (and optionally `max_rounds`). See §5.

### Design Rules

I. General Rules for Task Decomposition

7. **Default flat**: prefer single `simple` / `long_running` top-level tasks; let the scheduler handle ordering and re-execution. Use subtasks only when: (a) enforced sequential ordering is required and the scheduler cannot guarantee it (e.g. anti-hack verification must run after implementation, report must run after tests pass), or (b) bundling several lightweight steps into one top-level task to reduce scheduling overhead. See §4.1.
8. **No over-decomposition**: keep logically dependent work in one task (e.g. when implementing tightly coupled modules A and B). See §4.1.
9. **No under-decomposition**: separate logically independent work into distinct top-level tasks so the scheduler can re-execute them individually. If a single task does too much, the scheduler loses granularity. See §4.1.
10. **State persistence**: inter-subtask data is written to files, not assumed in conversation context. See §4.7.
11. **Failure resilience**: tasks may inherit broken state from (a) their own failed retries, or (b) a predecessor task that failed. The scheduler can handle predecessor failures at the scheduling level via `strategy` and `last_result`, but tasks should still include basic prerequisite checks in `initial_hint` as a safety net. See §4.5.

II. Task Fields

12. **Task-specific `description`** is scheduler-facing, with 1-3 sentences explaining what the task does and produces. See §5.3.
13. **`completion_criteria`** are specific, measurable, and verifiable by the AI — not vague like "code is good". See §4.2.
14. **`initial_hint`** provides key file paths, commands, and constraints — not a rigid step-by-step script. See §4.3.
15. **`max_attempts: 1`** is set on execution-only subtasks (build, benchmark, test) that don't write code. See §6.2.
16. **`model: "lite"`** is set on straightforward execution tasks; use default for tasks that requires complex reasoning. See §6.3.

III. Type-specific Guide

17. **Type-specific patterns**: Read the relevant guide in §8 for your task type.

### AI Scheduling Rules

I. Fields under ai_orchestrator

18. **`strategy`** encodes task dependencies and includes failure recovery rules. See §5.2.
19. **`last_result`** is configured for every task whose output is needed by scheduler. Use `${workspace}` to reference relative paths. See §5.3.
20. **`stop_condition`** is specific, measurable, and includes a fallback (e.g. after N consecutive failures). See §5.4.

II. AI Scheduling Rules for Task Decomposition

21. **Task independence**: each top-level task is self-contained; ordering is encoded in `strategy`.
22. **Max ~5–8 top-level tasks** — more bloats the scheduler prompt.
23. **Design for re-execution**: tasks may run 0, 1, or many times.
24. **Scheduler observables**: design around what the scheduler can see (description, execution count, last result, history).

### Anti-Hack Rules

25. **Negative constraints**: For every "implement X" task, explicitly state what must NOT be modified (test files, configs, unrelated modules).
26. **Verification separation**: Separate "implement" from "verify" into different subtasks. Verify subtask should use `max_attempts: 1` for fast error propagation, use `system_prompt_prefix` to forbid code modification, and include anti-hack checks for complex implementations.
27. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.

---

## 2. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through a sequence of tasks defined in `todos.yaml`.

### 2.1 General Properties

1. **Fully autonomous**

No human in the loop. 
Implication: `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification.

2. **Context isolation between tasks and subtasks**

Tasks and subtasks **share the filesystem, not conversation or context**. **AI sessions are reset** between tasks and subtasks. No response is passed between top-level tasks; only a summary of the previous subtask is passed between subtasks.
Implication: (1) Design top-level tasks independently; (2) **Detailed intermediate results must be persisted to files** — conversation context is NOT shared.

3. **Failed tasks don't block**

A failed task or subtask does NOT prevent subsequent tasks or subtasks from running.
Implication: (1) Design tasks that are aware of previous failures; (2) AI scheduler's `strategy` should include failure recovery rules.

### 2.2 AI Scheduling Properties

In AI scheduling mode, an AI scheduler dynamically decides which task to run each round, rather than executing tasks in fixed order.

1. **Dynamic execution order**

The AI scheduler decides which task to run each round.
Implication: Design **tasks that can be run 0, 1, or many times**.

2. **Task dependencies via `strategy`**

Implication: Use AI scheduler's `strategy` to encode dependencies explicitly; Don't assume task N-1 ran before task N.

3. **Task description is critical — but keep it short**

The scheduler AI understands what each task does **only by root-level `description` and task-specific `description` field**.
Implication: Keep task-specific `description` informative, but concise (1-3 sentences) to prevent prompt bloat. DO NOT include task details in task-specific `description`.

4. **`last_result` feeds execution outcomes to the scheduler**

Implication: Configure `last_result` so the scheduler knows where to find task execution results.

5. **Scheduler AI only decides top-level task**

The scheduler AI only decides **which top-level task** to run. It does NOT control subtask-level execution — subtasks within a task execute sequentially as defined.
Implication: scheduler's `strategy` should only contain top-level task dependencies.

---

## 3. Root Description Guide

The root-level `description` field provides project-wide context visible to **all AIs** — both the scheduler and every executor. **Always include it.** Without it, the AI has no overall project context.

### Components

| Component | Purpose | Example | When needed |
|-----------|---------|---------|-------------|
| **Goal** | What the project is trying to accomplish | "Iteratively optimize GPU compute shaders for minimum latency" | **Always** |
| **Architecture** | Directory structure and key modules, so AI knows where to find things | "src/shaders — HLSL shaders, src/frame_processor.cpp — GPU dispatch logic" | **Always** |
| **Key file paths** | Frequently referenced paths: configs, output files, data files | "Config: configs/base.yaml, Results: optimization_results.tsv" | **Always** |
| **Hard constraints** | Things the AI must NEVER do or change | "Must maintain correctness; never modify resource/ data files" | **Always** |
| **Rules** | Behavioral rules that apply to every task in this project | "One experiment per round; Keep changes minimal; If you find a bug, fix ONLY the bug." | **Always** |
| **Key commands** | Build, test, run and validation commands the AI will run repeatedly, with environments if specified | "cmake --build build --config Release / conda run -n py312 python test.py" | When the project has build/test/run/validation commands |
| **Architecture notes** | Key technical coupling points where changes in one place require syncing another | "Modifying shader thread group size requires syncing Dispatch() call" | When the codebase has non-obvious cross-file dependencies |
| **Naming conventions** | File/branch naming rules so the AI can derive names programmatically | "Docs named by branch number N: optimization_results_N.tsv" | When the project generates numbered/templated files across iterations |
| **Historical references** | Past work the AI should consult to avoid repeating failures | "doc/optimization_report_*.md — previous branch reports" | When the project runs across multiple branches/iterations |
| **Reference docs** | Documentation the executor AI should read when it needs deeper understanding | "See docs/method.md for complete method understanding when you feel the task difficult to complete" | When external/internal docs exist that the AI should consult on-demand |

Not every project needs every optional component. See subguides in §8 for full details.

### What NOT to Put in `description`

| Anti-pattern | Why | Where it belongs instead |
|--------------|-----|--------------------------|
| **Scheduling strategy** / **Task execution order or phasing** (e.g. "run task 2 before task 3", "this is a two-phase project") | Only the scheduler AI needs this, not executor AI. | `ai_orchestrator.strategy` field (scheduler-only prompt) |
| **Step-by-step implementation details** | Overly detailed instructions in the project description distract other tasks' executors | Task-level `initial_hint` (executor-only) |
| **Scheduler behavioral rules** (e.g. "never run the same task twice in a row") | These are scheduling constraints, not project context | `ai_orchestrator.strategy` |

> **Rule of thumb:** If the information is only useful to the scheduler (scheduling order, phasing, task dependencies), put it in `ai_orchestrator.strategy`. If it's only useful to one task's executor (step-by-step details), put it in that task's `initial_hint`. The root `description` is for **shared project context** that every AI benefits from.

See the [Complete Example](#10-complete-example) at the end of this document for a full `description` demonstration.

---

## 4. Design Principles

💡 **These are best practices you should follow.** They represent lessons learned from real-world task execution.

### 4.1 Task Decomposition

#### Core Principle: Default Flat

In AI scheduling mode, **prefer flat `simple` / `long_running` top-level tasks**. The scheduler handles ordering, re-execution, and retry — you don't need subtasks for these purposes.

Each top-level task should be a **complete, self-contained action** that produces a meaningful result the scheduler can evaluate:

| Granularity | Example | Verdict |
|-------------|---------|---------|
| Too coarse | "Do everything: setup, optimize, test, report" | ❌ Scheduler has no control |
| Right level | "Implement optimization, build, and test" | ✅ Scheduler can repeat or skip |
| Too fine | "Edit line 42 of kernel.cu" | ❌ Scheduler shouldn't micromanage |

**Task independence**: each task should be runnable without assuming a specific prior task ran in the same round. Use `strategy` to encode ordering constraints, and persist all inter-task communication to files (referenced in `last_result`).

#### When to Use Subtasks (and When Not To)

In AI scheduling mode, the scheduler itself handles re-execution and ordering of top-level tasks. **Subtasks are only needed in two scenarios:**

**Scenario A: Enforced sequential ordering** — when step B *must* run after step A succeeds, and the scheduler cannot reliably guarantee this ordering.

The most common case is **trust boundaries / anti-hack**: implementation and verification must be in separate sessions with different `system_prompt_prefix`, and verification must only run after implementation succeeds.

```yaml
# GOOD: Subtasks enforce ordering that the scheduler can't guarantee
- id: 2
  name: "Implement and verify optimization"
  type: nested
  subtasks:
    - id: 2.1
      name: "Implement optimization, build, and test"
      type: simple
      # AI implements, builds, tests — all in one session for fast iteration
    - id: 2.2
      name: "Anti-hack verification"
      type: simple
      max_attempts: 1
      system_prompt_prefix: "You are a code reviewer. Do NOT modify any code."
      # Must run AFTER 2.1 succeeds; must be a different session
```

Other examples: "report must be written only after tests pass", "deployment must happen only after build succeeds".

**Scenario B: Bundling lightweight steps** — when several small steps are too trivial to be individual top-level tasks (scheduling overhead > execution cost).

```yaml
# GOOD: Bundle trivial steps to avoid polluting the scheduler with micro-tasks
- id: 1
  name: "Setup and baseline"
  type: nested
  subtasks:
    - id: 1.1
      name: "Build and run tests"
      type: simple
      model: lite
    - id: 1.2
      name: "Run benchmark and record baseline"
      type: long_running
      model: lite
```

**When NOT to use subtasks:**

| Scenario | Why not subtask |
|----------|-----------------|
| "Analyze" and "implement" as two subtasks | Both are high-intensity but independent — scheduler can re-execute each |
| Expensive steps (e.g. training) | Scheduler handles re-execution natively |
| Retry control | Scheduler's re-scheduling is the retry mechanism. Write retry strageties in scheduler's `strategy`. |

#### Anti-Patterns

**Over-decomposition (subtask level)** — using subtasks where separate top-level tasks would be better:

```yaml
# BAD: These should be separate top-level tasks in AI scheduling mode.
# The scheduler can order and re-execute them independently.
- id: 1
  name: "Full optimization cycle"
  type: nested
  subtasks:
    - id: 1.1
      name: "Analyze profiling report"
    - id: 1.2
      name: "Implement optimization"
    - id: 1.3
      name: "Run benchmark"
    - id: 1.4
      name: "Write report"

# GOOD: Flat top-level tasks; scheduler decides ordering and repetition.
tasks:
  - id: 1
    name: "Analyze bottleneck and propose optimization"
    type: simple
  - id: 2
    name: "Implement optimization, build, and test"
    type: simple
  - id: 3
    name: "Benchmark and evaluate"
    type: simple
```

**Over-decomposition (top-level)** — splitting tightly coupled work into separate tasks, forcing the AI to implement without full context:

```yaml
# BAD: Module A and B have tight coupling (shared interfaces, mutual calls).
# Splitting them means each AI session only sees half the picture.
tasks:
  - id: 1
    name: "Implement module A"
    type: simple
  - id: 2
    name: "Implement module B"
    type: simple

# GOOD: Keep coupled modules together so the AI can make coherent cross-module decisions.
tasks:
  - id: 1
    name: "Implement modules A and B"
    type: simple
```

When tightly coupled work is split:
- **Incoherent interfaces** — each AI session designs its half independently, leading to mismatched APIs.
- **Wasted retries** — integration failures force both tasks to re-run, negating any granularity benefit.

**Under-decomposition** — cramming everything into one task, removing scheduler granularity:

```yaml
# BAD: Scheduler can't re-run just the benchmark or just the implementation
- id: 1
  name: "Analyze, implement, benchmark, and report"
  type: simple
```

When a single task does too much:
- **Scheduler loses control** — it can't re-execute just the failed phase.
- **Context explosion** — the AI accumulates too much context, degrading output quality.
- **AI laziness** — faced with too many responsibilities, the AI takes shortcuts.

#### Result-Driven Design

Design tasks around their **observable output**:

```
What does the scheduler need to decide next?
    → That determines what the result file should contain
        → That determines what the task should produce
```

**Example thought process:**
- Scheduler needs to know: "Did the optimization improve performance?"
- Result file should contain: speedup percentage, correctness score
- Task should produce: run benchmark, compare with baseline, write summary

### 4.2 Writing Good `completion_criteria`

**How criteria are evaluated:**

| Task type | Evaluation method |
|-----------|-------------------|
| `simple` / `long_running` | AI self-evaluates. Criteria must be **objectively verifiable by the AI**. |
| `nested` | Subtask criteria determine subtask-level pass/fail. The top-level `completion_criteria` is then evaluated to determine overall pass/fail and whether more rounds are needed. |
| `looping` | Subtask criteria determine subtask-level pass/fail, but no top-level pass/fail evaluation. Done when all `repeat_count` iterations finish. |

> **Note:** While `looping` tasks do not have overall AI evaluation, their top-level `completion_criteria` is still visible to subtask AI executors. This gives each subtask awareness of the overall goal of the parent task, so write meaningful criteria even for `looping` tasks.

**Rules:**
1. Be specific and measurable — the AI must be able to verify by reading files, checking output, or running tests.
2. Reference concrete artifacts — file names, command outputs, specific values.
3. Include positive AND negative conditions when relevant (e.g., "tests pass AND no regressions").
4. Use numbered lists for multiple conditions — makes it clear ALL must be met.
5. Focus on the "What", not the "How" of AutoAgent — criteria should describe the desired state, not AutoAgent internals.

**Top-level vs subtask criteria — they serve different purposes:**

| Level | Role | Example |
|-------|------|---------|
| **Top-level** (`nested`) | The "final exam" — describes the **desired end state**. The AI evaluates this after all subtasks complete to decide if more rounds are needed. Should focus on overall outcome, not individual steps. | "Speedup >= 20% over baseline AND Score 100/100 on correctness test" |
| **Subtask** | Step-level verification — describes **what this step must produce**. The AI self-evaluates after each attempt. Should be narrow and focused on this step's output. | "Code changes applied, project builds without errors, and changes committed to git" |

Don't repeat subtask criteria in the top-level criteria. The top-level criteria should describe what success looks like *after all steps are done*, not re-list each step.

**Per-type guidance:**

| Task type | Guidance |
|-----------|----------|
| Simple (code changes) | Reference specific files and verification steps ("compiles without errors", "tests pass") |
| Simple (running commands) | Specify expected output pattern or exit code; mention where results should be saved |
| Nested (overall evaluation) | Describe the desired end state, not the process; include quantitative thresholds |
| Long-running | Reference patterns in the output log; include exit code expectations |

**Examples:**

```yaml
# GOOD
completion_criteria: |
  1. The project builds successfully: cmake --build build --config Release
  2. The executable runs and outputs "Score: 100/100"
  3. Elapsed time is printed in format "Elapsed: XXX.XX ms"
  4. baseline_timing.txt exists and contains the timing value

# BAD
completion_criteria: "Code is optimized"        # Not measurable
completion_criteria: "Performance is improved"   # No baseline, no metric, no threshold
```

**Anti-patterns:**

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| Prescribing methods | "Use shared memory to achieve 20% speedup" locks the AI into one approach that may not be optimal | "Achieve 20% speedup while maintaining correctness" — describe the goal, let the AI choose the method |
| Describing process | "Run ncu, analyze the output, then identify the top bottleneck" is a to-do list, not criteria | "Key bottleneck identified and analysis saved to ncu_analysis.txt" — describe the outcome |
| Unverifiable criteria | "Code is clean and well-documented" — the AI will always claim success | "All public functions have docstrings AND `pylint src/` scores >= 9.0" — use tool-checkable conditions |

### 4.3 Writing Good `initial_hint`

Context and guidance provided to the executor AI for every attempt of this task.

**`initial_hint` vs `system_prompt_prefix`:**
- `initial_hint` → **"how to do the task"** (file paths, commands, troubleshooting)
- `system_prompt_prefix` → **"who you are and global rules"** (persona, coding style, constraints)

**Provide context, not playbooks.** The AI is a capable coding agent — give it the **information** it needs (key files, commands, constraints), not a rigid step-by-step script. Over-specified hints remove the AI's ability to adapt when conditions differ from what you anticipated.

| Include | Don't include |
|---------|---------------|
| Key file paths | Completion criteria (separate field) |
| Specific commands (if non-obvious) | Obvious instructions |
| Architecture context | Overly detailed step-by-step |
| Step-specific constraints | Project-level constraints (put in `description` instead) |
| Common failure modes + workarounds | Attempt-specific strategies |

**Example:**

```yaml
initial_hint: |
  Key files:
    - CMakeLists.txt: Main build config
    - cufftdx_dct3d.cuh: Kernel header
    - main.cpp: Benchmark program (100 iterations)

  Build: cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build

  IMPORTANT: Do NOT modify the correctness test (Score calculation) logic.

  Troubleshooting:
  - If CUDA OOM: reduce batch_size in configs/model.yaml (16 → 8).
```

**AI scheduling note:** Since tasks may run multiple times, consider adding a note about pre-existing state:

```yaml
initial_hint: |
  NOTE: This task may run multiple times. The workspace may contain
  results from previous optimization rounds. Always read the latest
  profiling data before starting a new optimization.
```

### 4.4 Anti-Hack Patterns

When an AI agent executes tasks autonomously, it may "satisfy" completion criteria through unintended shortcuts — modifying tests, simplifying implementations, or hardcoding expected outputs. These patterns help prevent such reward hacking.

#### Separate Implementation from Verification

Use separate subtasks for "do the work" and "verify the work". The verification subtask should be **forbidden from modifying code**:

```yaml
subtasks:
  - id: 1.1
    name: "Fix the bug in parser module"
    type: simple
    completion_criteria: |
      1. The bug described in issue #42 is fixed
      2. cargo build succeeds
      3. Do NOT modify any test files
    initial_hint: |
      Bug location: src/parser/tokenizer.rs
      Scope: Only modify files under src/parser/

  - id: 1.2
    name: "Verify fix passes all tests"
    type: simple
    max_attempts: 1
    model: lite
    system_prompt_prefix: |
      You are a test runner. Do NOT modify any source code or test files.
    completion_criteria: |
      1. cargo test --all passes (exit code 0)
      2. git diff --name-only shows NO changes to files under tests/
```

#### Explicit Negative Constraints

For every "implement X" task, think about what the AI should NOT do:

```yaml
# BAD: No negative constraints — AI could delete failing tests
completion_criteria: |
  All tests pass.

# GOOD: Explicit protection
completion_criteria: |
  1. All tests in tests/ pass (cargo test --all, exit code 0)
  2. No test files were modified (git diff --name-only shows no files under tests/)
  3. No test cases were removed or weakened
```

#### Scope Boundaries

Restrict which files/directories the AI may modify:

```yaml
initial_hint: |
  Scope: Only modify files under src/handlers/auth/
  Do NOT modify:
  - Any files under tests/
  - config/security.yaml
  - src/middleware/
```

#### Use `git diff` as a Verification Tool

Include `git diff` checks in verification subtasks to detect unexpected changes:

```yaml
completion_criteria: |
  1. All tests pass
  2. git diff --stat shows changes ONLY in src/parser/ directory
  3. No new files created outside src/parser/
```

### 4.5 Failure Resilience

Tasks may inherit broken state from two sources. Design defensively for both.

#### Same-task retry

When a subtask is retried, previous attempts may have modified files. The AI has summaries of previous attempts but **filesystem changes persist**.

- **Mention cleanup in `initial_hint`** when a task modifies shared state:
  ```yaml
  initial_hint: |
    NOTE: If a previous attempt left partial changes, check the state of
    build/ and src/generated/ before starting.
  ```
- **Prefer append/overwrite patterns** over incremental mutations — writing a complete output file is naturally idempotent.
- **Use git as a safety net** in `initial_hint` when appropriate: "Run `git diff` first to check for unexpected changes."
- **Don't over-engineer for idempotency** — it's enough to make the AI *aware* that residual state may exist.

#### Predecessor failure

A preceding task may fail and leave partial or broken state. In AI scheduling mode, this can be handled at **two levels**:

**Level 1 — Scheduler-level (preferred):** Design `last_result` and `strategy` so the scheduler detects predecessor failures and avoids scheduling dependent tasks:
```yaml
# In strategy:
Scheduling rules:
1. Do not run "Optimize" unless "Baseline benchmark" last_result
   contains "benchmark completed successfully".
2. If "Build and test" fails 3 consecutive times, skip to "Report".
```
This is the preferred approach because it avoids wasting tokens on tasks that are doomed to fail.

**Level 2 — Task-level (safety net):** Even with scheduler-level handling, include basic prerequisite checks in `initial_hint` as a fallback, since the scheduler may not always make the right decision:
```yaml
initial_hint: |
  Before starting: verify the project builds and the correctness test passes.
  If either fails, this likely means a previous task did not complete
  successfully. Report the issue and mark as NOT COMPLETED.
```

#### Defensive task design

When tasks depend on external tools or services:

- **In `completion_criteria`** — handle partial success explicitly:
  ```yaml
  completion_criteria: |
    1. At least 8 out of 10 test suites pass.
    2. Any failing suites are documented in test_failures.txt.
  ```
- **In `initial_hint`** — include prerequisite checks:
  ```yaml
  initial_hint: |
    Before starting: verify the project builds and correctness test passes.
    If either fails, fix that FIRST.
  ```

#### Subtask failure in nested/looping tasks

- Design subtasks so failure can be diagnosed from output.
- Align subtask boundaries with logical checkpoints — retrying from step 2 or 3 should be meaningful.
- Avoid subtasks that silently fail — ensure errors are visible in output.

### 4.6 Writing Good Task `description` (AI Scheduling)

> ⚠️ **Task-specific `description` is critical in AI scheduling mode.** It's the **only way** the scheduler AI understands what a task does — the scheduler sees `id`, `name`, `type`, `description`, execution count, and last result, nothing else.

**Keep each task's `description` short (1–3 sentences).** The scheduler prompt concatenates the descriptions of **all** tasks into a single context window. If individual descriptions are long, the combined prompt becomes bloated, wastes tokens, and degrades the scheduler's decision quality.

- State what the task does and what it produces (1–3 sentences)
- Mention the key output artifact if relevant
- **Don't include execution steps or implementation details** — those belong in `initial_hint` (which only the executor sees)
- Don't write multi-paragraph essays — every extra sentence is multiplied by the number of tasks in the scheduler prompt

```yaml
# GOOD
description: |
  Build the project, verify correctness, and run ncu profiling to
  establish baseline performance metrics. Produces baseline_profile.txt.

# BAD: too detailed — belongs in initial_hint
description: |
  First run cmake -B build, then cmake --build build --config Release,
  then run ncu --set full --csv ./main.exe > baseline_profile.txt...

# BAD: too vague — scheduler can't make informed decisions
description: "Run some tests"
```

### 4.7 State Persistence (Passing the Baton)

Subtasks don't share conversation context. Use the filesystem:
- **Producer subtask**: In `initial_hint`, instruct the AI to write results to a specific file (e.g., `step1_out.txt`).
- **Consumer subtask**: In `initial_hint`, instruct the AI to read that file before proceeding.

In AI scheduler mode, top-level tasks also need communication:
1. Producer task: writes output to a well-known file path
2. `last_result` config: points to that file so the SCHEDULER can see it
3. Consumer task's `initial_hint`: tells the EXECUTOR AI to read that file

Note: `last_result` feeds the scheduler; `initial_hint` feeds the executor.
These are two different audiences — configure both.

---

## 5. `ai_orchestrator` Configuration

📖 **AI scheduling mode specific.** This section covers the scheduler configuration that controls dynamic task selection.

### 5.1 Schema

```yaml
ai_orchestrator:
  strategy: |
    <scheduling rules — injected into the AI prompt>

  max_rounds: 20          # Optional, default: 50

  stop_condition: |       # Optional
    <when to stop — injected into the AI prompt>

  last_result:            # Optional
    <task_id>:
      type: file | response | none
      path: <path>        # Required when type=file
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `strategy` | string | **Yes** | — | Scheduling rules. The scheduler AI reads this verbatim. |
| `max_rounds` | int | No | 50 | Hard cap on scheduling rounds |
| `stop_condition` | string | No | `""` | When to stop. Shown to the scheduler AI. |
| `last_result` | dict | No | `{}` | Per-task result configuration (see §5.3) |
| `max_attempts` | int | No | config default | Maximum retry count for scheduler decisions |

### 5.2 `strategy` — Encoding Scheduling Logic

The `strategy` field is injected verbatim into the scheduler AI's prompt. It encodes the decision rules that govern task selection.

**Structure as numbered rules:**

```yaml
strategy: |
  Scheduling rules:
  1. If baseline has not been established (Task 1 never executed), execute Task 1 first.
  2. After baseline, execute Task 2 to analyze profiling results.
  3. After analysis, execute Task 3 to implement one optimization.
  4. After optimization, execute Task 4 to verify correctness.
     - If Task 4 fails, execute Task 3 again to fix the regression.
     - If Task 4 succeeds and improvement >= 20%, execute Task 5 and stop.
     - Otherwise, execute Task 2 again to re-analyze.
  5. If Task 3 fails 3 consecutive times, execute Task 2 to re-analyze.
```

**Guidelines:**

| Guideline | Rationale |
|-----------|-----------|
| Use task IDs and names together | `"Task 1 (Baseline)"` is clearer than just `"Task 1"` |
| Express conditions in terms of observable state | The scheduler sees execution counts, success/failure history, and result files |
| Include failure recovery rules | What should happen when a task fails? |
| Include termination triggers | When should the scheduler stop? (Complements `stop_condition`) |
| Keep rules deterministic where possible | Ambiguous rules lead to inconsistent scheduling |

**What the Scheduler Can Observe:**

| Observable | Example |
|------------|---------|
| Execution count per task | "Task 1 executed 0 times" → baseline not established |
| Success/failure history | "Round 3: Task 3 ❌ Failed" |
| Last result contents | Execution results referenced by `last_result` (if it exists) |
| Current round number | "Round 5 / 20" |

The scheduler **cannot** observe:
- Internal subtask states
- Conversation content from task execution
- Files not listed in `last_result`

### 5.3 `last_result`

Configures how each task's outcome is surfaced to the scheduler in subsequent rounds.

| Type | What the scheduler sees | When to use |
|------|------------------------|-------------|
| `file` | Contents of the specified file(s) | **`looping` tasks** (which produce cumulative results best captured in a file), or any task that **explicitly produces an output file** (benchmarks, test results) |
| `response` | Auto-saved AI final response | `simple` tasks (default choice); `nested` tasks where the **last subtask is a summary/analysis step** |
| `none` | Nothing (success/failure still visible in history) | Setup/infrastructure tasks with no meaningful output |

**Important**: `last_result` keys are top-level task IDs (integers), not subtask IDs. This is consistent with AI scheduler's responsibility — it only schedules top-level tasks, not subtasks.

#### `type: response` behavior

The system auto-saves the AI's final response from the last execution unit:
- **Simple task**: The task's AI response
- **Nested task**: The last actually-executed subtask's AI response
- **Looping task**: The last iteration's last subtask's AI response (which also implies that type: response is not suitable for looping tasks)

#### `type: file` syntax

```yaml
last_result:
  1:
    type: file
    path: ${workspace}/baseline_profile.txt    # Single file
  4:
    type: file
    path:                                       # Multiple files
      - ${workspace}/test_result.txt
      - ${workspace}/perf_comparison.txt
```

- `${workspace}` is auto-expanded to the actual workspace path at runtime.

#### Key decision rules

1. **Single-layer `simple` task** → prefer `type: response`. The AI's final answer naturally summarizes what happened.
2. **`nested` task** → `type: response` works well, but the **last subtask must be summary-oriented** (the system saves the last-executed subtask's response). If the last subtask is a build/run step with no useful prose, use `type: file` instead.
3. **`looping` task** or any task that **explicitly writes a result file** → prefer `type: file`. Point `path` at the file the task produces.
4. **Setup tasks** → `type: none`. The scheduler already sees success/failure in the history.

**Key insight:** If the scheduler's `strategy` references a task's output to make decisions (e.g., "if speedup >= 20%"), that task **must** have a `last_result` configured — otherwise the scheduler is flying blind.

### 5.4 `stop_condition` — When to Stop

Tells the scheduler AI when to stop. Complements `strategy` by providing a clear termination criterion.
DO NOT repeat "maximum rounds reached" in `stop_condition`: the scheduler AI already has this information.

```yaml
# GOOD: Specific, measurable, references observable state
stop_condition: |
  Stop when:
  - Performance improvement reaches at least 20% compared to baseline
    AND correctness is verified (Score: 100/100).

# BAD: Vague
stop_condition: "Stop when done"

# BAD: References unobservable state
stop_condition: "Stop when the code is clean and well-optimized"
```

**Tips:**
- Reference metrics that appear in result files
- Include a fallback condition (max rounds, max consecutive failures)
- Be explicit about AND/OR logic

---

## 6. Schema Reference

📖 **Reference section — consult as needed.** You don't need to read this top-to-bottom; look up specific types and fields when designing tasks.

### 6.1 Task Types

| Type | Description | Scope | When to use |
|------|-------------|-------|-------------|
| `simple` | AI works autonomously, then self-evaluates completion | Top-level or subtask | Code changes, running tests, file analysis, quick builds |
| `nested` | Sequential subtasks + AI evaluation of overall completion; When fails consecutively, retries with guidance | Top-level or subtask | Multi-step workflows where overall success depends on combined result |
| `looping` | Repeat all subtasks for fixed N iterations; NO AI evaluation for overall completion | Top-level or subtask | Iterative optimization cycles (profile → optimize → benchmark) |
| `long_running` | AI launches a long-running background command (e.g. training) that runs without session timeout | Top-level or subtask | Any command that may take > 1 minute (builds, tests, benchmarks, training, profiling) |
| `simple_once` | Like `simple`, but never re-executed once completed | Subtask only | One-time setup (env prep, dependency install, data download) |
| `long_running_once` | Like `long_running`, but never re-executed once completed | Subtask only | Expensive one-time operations (Docker build, baseline profiling) |

**Key Notes:**

- **Prefer `long_running` over `simple`** for any command that may take > 1 minute. If a command runs too long inside `simple`, the AI session may hit a timeout, wasting all progress. `long_running` runs the command in the background with proper monitoring — minimal overhead, prevents session timeouts.
- **`*_once` types**: Use sparingly. Most subtasks SHOULD be re-executable. Don't use `*_once` if a subtask's output might become stale after other subtasks run. Use `long_running_once` instead of `long_running` when the command is **idempotent setup** (e.g., Docker build, baseline profiling) that should survive retries of later subtasks.
- **`*_once` subtasks survive re-scheduling**: In AI scheduling mode, `*_once` subtasks execute only once across ALL scheduling rounds. If the scheduler selects the same task again, `*_once` subtasks are skipped.
- **Looping iteration failure stops the loop**: If any single iteration fails after exhausting its retry attempts, the remaining iterations are NOT executed. Design subtask `completion_criteria` to be tolerant of partial or unexpected results if you want the loop to continue through difficult iterations.
- **Nested subtasks**: `nested`/`looping` can be used as subtask types for multi-level nesting. Keep nesting shallow (2–3 levels max).

### 6.2 Root-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | **Yes** | Project-level description: goal, architecture, constraints, key paths. See §3. |
| `ai_orchestrator` | object | **Yes** | AI scheduling configuration. See §5. |
| `tasks` | list | Yes | List of top-level task definitions |

### 6.3 Common Fields (all types)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int/float | Yes | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name` | string | Yes | Concise, descriptive task name |
| `type` | string | Yes | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
| `description` | string | **Yes** | What this task does and produces (1–3 sentences). The scheduler uses this for decisions. |
| `completion_criteria` | string | Yes | Clear, specific, measurable success criteria |
| `model` | string | No | `"default"`, `"lite"`, or a direct model name. `"default"` will be used if not specified |
| `system_prompt_prefix` | string | No | Custom AI persona/instructions for this task (see §7.1) |

### 6.4 Type-Specific Fields

**simple / simple_once / long_running / long_running_once:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `initial_hint` | string | No | Context and guidance for the executor AI (file paths, commands, troubleshooting) |
| `max_attempts` | int | No | Max retry attempts (default: 5). When a task fails, it is retried up to this many times with feedback from previous attempts. |

**nested:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subtasks` | list | Yes | Ordered list of subtasks (any valid type, including nested/looping) |
| `max_attempts` | int | No | Max retry rounds (default: 5) |

**looping:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `subtasks` | list | Yes | Ordered list of subtasks |
| `repeat_count` | int | Yes | Number of loop iterations (>= 1) |
| `max_attempts_per_loop` | int | No | Max retries per iteration (default: 5) |

### 6.5 Hierarchy and ID Rules

**Hierarchy:**
- **Top-level**: `simple`, `nested`, `looping`, `long_running`.
- **Subtasks** (inside nested/looping): all six types allowed.
- `simple_once` and `long_running_once` can ONLY be subtasks.
- Nested subtasks have their own `max_attempts`/`repeat_count`, independent of the parent.

**ID Assignment:**
- **Top-level tasks**: Sequential integers starting from the next available ID.
- **Subtasks**: Dot notation using parent ID as prefix (e.g., 6.1, 6.2, 6.3).
- **Nested subtasks**: Continue the dot notation (e.g., 6.2.1, 6.2.2).
- IDs must be unique across the entire `todos.yaml`. Subtask IDs determine execution order.

---

## 7. Field Usage Guide

📖 **Reference section** for `system_prompt_prefix`, `max_attempts`, and `model` fields.

### 7.1 `system_prompt_prefix`

Customizes the AI's persona, role, or task-specific instructions.

| Use case | Example |
|----------|---------|
| Domain expertise | `"You are a GPU performance engineer."` |
| Task-specific constraints | `"Never modify files in vendor/."` |
| Coding style | `"Follow Google C++ style guide."` |
| **Restrict behavior** (execution-only subtasks) | `"You are a benchmark runner. Do NOT modify any source code."` |

Using `system_prompt_prefix` to restrict behavior is especially useful for execution-only subtasks (build, benchmark, data export) where you want to prevent the AI from "helpfully" editing code when a command fails — the failure should propagate to the parent for proper failure analysis instead.

> **Note:** `system_prompt_prefix` on a top-level `nested` or `looping` task is not supported — set it on individual subtasks instead.

### 7.2 `max_attempts`

**Scope of `max_attempts` differs by level:**

| Level | Field | What counts as one attempt |
|-------|-------|---------------------------|
| Top-level `simple` / `long_running` | `max_attempts` | One full execution of the task |
| Top-level `nested` | `max_attempts` | One full round: all subtasks run → overall evaluation |
| Top-level `looping` | `max_attempts_per_loop` | One retry round within a single iteration |
| Subtask (any type) | `max_attempts` | One execution of that subtask within the parent's current round |

**Choosing a value:**

| Value | When to use |
|-------|-------------|
| `1` | **Execution-only subtasks** that just run code written by a sibling (build, benchmark, test). If the command fails, the cause is in sibling code — retrying won't help. `max_attempts: 1` propagates failure immediately to the parent's failure analysis. |
| `2–3` | Moderately uncertain tasks with a constrained problem space. |
| `5` (default) | Complex code-writing tasks — open-ended changes, multi-file refactoring, optimization. |

**Do NOT** set `max_attempts: 1` on subtasks where the AI actively writes code — those benefit from multiple attempts with different strategies.

### 7.3 `model`

| Value | When to use |
|-------|-------------|
| `"default"` (or omit) | Complex reasoning: "Analyze profiling results and optimize kernel", "Debug and fix root cause" |
| `"lite"` | Straightforward execution: "Run `make test`", "Format code with black", "Run benchmark and save output" |
| Direct model name (e.g., `"claude-sonnet-4-20250514"`) | When a specific model is needed |

---

## 8. Task-Type-Specific Best Practices

📖 **Read only the guide relevant to your task** — you don't need to read all of them.

| Task type | Guide | When to use |
|-----------|-------|-------------|
| **Build & Ship** | `build_and_ship.md` | Implement features, fix bugs, refactor code |
| **Testing & Verification** | `testing_and_verification.md` | Run tests, fix failures, improve coverage |
| **Iterative Optimization** | `iterative_optimization.md` | Profiling → optimize → benchmark → evaluate cycles |
| **Data Pipelines / ETL** | `data_pipelines.md` | Extract, transform, load, and validate data |
| **Setup & Deployment** | `setup_and_deployment.md` | Environment setup, dependency install, deployment |
| **Research & Analysis** | `research_and_analysis.md` | Code analysis, architecture review, report writing |
| **Academic Experiments** | `academic_experiments.md` | Multi-branch comparison experiments, controlled variables, ablation studies |

---

## 10. Complete Example

Below is a concise `todos.yaml` for AI scheduling mode, demonstrating: root `description`, `ai_orchestrator` with `strategy`/`stop_condition`/`last_result`, task-specific `description`, and all key patterns.

```yaml
description: |
  ## Project: Web API Performance Optimization

  ### Goal
  Iteratively optimize the REST API server to reduce p95 latency below 50ms
  while maintaining all integration tests passing.

  ### Architecture
  - src/handlers/ — HTTP route handlers
  - src/db/ — Database query layer (PostgreSQL)
  - src/cache/ — Redis caching layer
  - tests/ — Integration test suite
  - benchmarks/ — Load testing scripts (k6)

  ### Key File Paths
  - Config: config/server.yaml
  - Results: doc/optimization_results.tsv
  - Benchmark script: benchmarks/load_test.js

  ### Key Commands
  - Build: cargo build --release
  - Test: cargo test --all
  - Benchmark: k6 run benchmarks/load_test.js --out json=results.json

  ### Hard Constraints
  - Do NOT modify the public API contract (request/response schemas)
  - Do NOT remove or weaken any existing integration test
  - One optimization per experiment, keep changes minimal

  ### Rules
  - Fully autonomous — never ask the user questions
  - One optimization per experiment
  - If you discover a bug, fix ONLY the bug (no optimization in the same commit)

ai_orchestrator:
  max_rounds: 15

  strategy: |
    Scheduling rules:
    1. If Task 1 (Baseline) has never succeeded, execute Task 1 first.
    2. After baseline is established, execute Task 2 (Optimize) to run one optimization round.
    3. After Task 2 succeeds, check its result:
       - If p95 latency < 50ms → stop (goal achieved).
       - If improvement was made but target not reached → execute Task 2 again.
       - If Task 2 was reverted (regression) → execute Task 2 again with a different approach.
    4. If Task 2 fails 3 consecutive times, execute Task 3 (Diagnose) to analyze the situation.
    5. After Task 3, resume with Task 2.

  stop_condition: |
    Stop when p95 latency < 50ms as reported in doc/optimization_results.tsv.

  last_result:
    1:
      type: file
      path: ${workspace}/doc/optimization_results.tsv
    2:
      type: file
      path: ${workspace}/doc/optimization_results.tsv
    3:
      type: file
      path: ${workspace}/doc/diagnosis.md

tasks:
  - id: 1
    name: "Establish performance baseline"
    type: nested
    description: |
      Build the project, run tests, run benchmark, and record baseline p95 latency
      in doc/optimization_results.tsv.
    max_attempts: 3
    completion_criteria: |
      1. cargo test --all passes
      2. doc/optimization_results.tsv exists with a baseline row containing p95 latency
    subtasks:
      - id: 1.1
        name: "Build and test"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a build engineer. Do NOT modify any source code.
        completion_criteria: |
          1. cargo build --release succeeds
          2. cargo test --all passes
        initial_hint: |
          Run: cargo build --release && cargo test --all

      - id: 1.2
        name: "Run benchmark and record baseline"
        type: long_running
        model: lite
        completion_criteria: |
          1. Benchmark completed, results.json exists
          2. doc/optimization_results.tsv created with baseline row
        initial_hint: |
          Run: k6 run benchmarks/load_test.js --out json=results.json
          Parse p95 from results.json, create doc/optimization_results.tsv with header + baseline row.

  - id: 2
    name: "Run one optimization round"
    type: nested
    description: |
      Analyze the current bottleneck, implement one optimization, benchmark it,
      and keep or revert based on results. Updates doc/optimization_results.tsv.
    max_attempts: 3
    completion_criteria: |
      1. New row appended to doc/optimization_results.tsv (kept or reverted)
      2. If kept: tests still pass, p95 improved
      3. If reverted: code is back to previous state
    subtasks:
      - id: 2.1
        name: "Analyze and implement optimization"
        type: simple
        system_prompt_prefix: |
          You are a backend performance engineer specializing in Rust async services.
        completion_criteria: |
          1. Bottleneck identified
          2. Optimization implemented, build succeeds, tests pass
          3. Changes committed
        initial_hint: |
          Read doc/optimization_results.tsv for current metrics.
          Identify bottleneck, implement one focused optimization, build, test, commit.

      - id: 2.2
        name: "Benchmark and evaluate"
        type: simple
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. Benchmark completed, new row in optimization_results.tsv
          2. Decision made: kept (improved) or reverted (regressed)
        initial_hint: |
          Run: k6 run benchmarks/load_test.js --out json=results.json
          Compare with previous best. Keep if improved, revert if regressed.
          Append result row to doc/optimization_results.tsv.

  - id: 3
    name: "Diagnose repeated failures"
    type: simple
    description: |
      Analyze why recent optimization attempts failed. Read optimization_results.tsv
      and source code to identify root causes and suggest new directions.
    completion_criteria: |
      1. doc/diagnosis.md exists with root cause analysis and suggested next steps
    initial_hint: |
      Read doc/optimization_results.tsv (focus on recent reverted rows).
      Read relevant source code to understand why optimizations regressed.
      Write doc/diagnosis.md with analysis and actionable suggestions.
```
