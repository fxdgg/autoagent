# Task Design Guide for AI Agents

This document is a comprehensive reference for AI agents that generate TODO
tasks (via idea decomposition). Understanding how AutoAgent executes tasks
will help you design tasks that are effective, robust, and easy to evaluate.

---

## 1. Execution Model Overview

AutoAgent is an orchestrator that drives an AI coding agent (e.g., CodeBuddy)
through a sequence of tasks defined in `todos.yaml`. The orchestrator does NOT
execute tasks itself — it sends prompts to the AI agent, which reads/writes
files, runs shell commands, and reports results.

```
┌─────────────┐     prompt      ┌──────────────┐     tools      ┌──────────┐
│  AutoAgent  │ ──────────────► │  AI Agent    │ ─────────────► │ Codebase │
│ Orchestrator│ ◄────────────── │ (CodeBuddy)  │ ◄───────────── │ & Shell  │
└─────────────┘    response     └──────────────┘    results     └──────────┘
```

Key implications for task design:
- The AI agent can do anything a developer can: edit code, run commands,
  read logs, analyze outputs, install packages, use git, etc.
- The AI agent has a **context window limit** — avoid tasks that require
  reading extremely large files or outputs in a single step.
- Each subtask within a nested or looping task runs in its own independent
  AI session (session is reset between subtasks to prevent unbounded
  context growth). A summary of the previous subtask's output is passed
  to the next subtask via the prompt.
- Each top-level `simple` task runs in its own independent AI session.
- The AI session is **reset before each retry attempt** (for both
  top-level simple tasks and subtasks). The full task description and
  previous-attempt context are included in every prompt, so the AI loses
  nothing important. This prevents unbounded context accumulation across
  retries (which can cause output truncation and a vicious retry cycle).
- When the AI does not output a completion status marker (✅/❌/⏳) —
  whether because it forgot, or because the CLI/SDK crashed mid-response —
  AutoAgent uses a **marker-nudge** mechanism: instead of resetting the
  session and replaying the entire task, a lightweight follow-up prompt is
  sent in the same session. The AI may continue unfinished work and read
  files to verify, but is told not to re-run commands it already executed.
  If the AI previously called `autoagent-exec`, the system checks for a
  signal file before nudging — if one exists, the nudge is skipped and a
  synthetic `LONG_RUNNING_IN_PROGRESS` is returned automatically. The
  number of nudge attempts is configurable via `max_marker_nudges` in
  `config.yaml` (default: 2). If all nudges are exhausted without a
  marker, the system falls back to the normal retry loop (which resets
  the session).
- The AI's persona/role can be customized per-task via the
  `system_prompt_prefix` field in `todos.yaml` (see §12 below).

### Top-Level Task Execution Order

Top-level tasks in `todos.yaml` are executed **strictly sequentially in
ascending ID order** (task 1 → task 2 → task 3 → ...). Each top-level task
runs in its own independent AI session.

This means:
- **Later tasks can depend on artifacts produced by earlier tasks** (e.g.,
  task 2 can read files created by task 1), because they share the same
  filesystem.
- **There is no parallel execution** — task N+1 will not start until task N
  is fully completed (or has exhausted its retries).
- **A failed top-level task does NOT block subsequent tasks** — AutoAgent
  will log the failure and proceed to the next top-level task.
- **Design your task ordering carefully**: place setup and prerequisite
  tasks before tasks that depend on their outputs.

---

## 2. Task Types — Detailed Behavior

### 2.1 `simple`

**What happens at runtime:**
1. AutoAgent sends a prompt containing the task name, completion_criteria,
   initial_hint (if first attempt), and any retry context.
2. The AI agent works autonomously — reading files, running commands, making
   code changes — until it believes the task is done.
3. The AI agent ends its response with a status marker:
   - `✅ completed` — task is done
   - `❌ not completed: <reason>` — task failed
4. AutoAgent parses the marker to determine success/failure.

**Scope:** Can be a top-level task OR a subtask inside nested/looping.

**When to use:** Any task the AI can complete in a single session — code
changes, running tests, file analysis, data processing, simple builds, etc.

**Design tips:**
- Keep each simple task focused on ONE logical objective.
- The AI agent has access to `autoagent-exec` for commands that might take
  more than a few minutes. You do NOT need to make those `long_running` —
  the AI will use `autoagent-exec` automatically if needed. Use `long_running`
  only when you KNOW the command will take a long time and want to specify
  the command upfront.
- **Auto-upgrade behavior:** If the AI uses `autoagent-exec` within a simple
  task and outputs `LONG_RUNNING_IN_PROGRESS`, AutoAgent automatically
  detects this and switches to the long-running poll + callback flow
  (waiting for the background process to finish, then asking the AI to
  analyze results). You do NOT need to anticipate this in your task design.

### 2.2 `nested`

**What happens at runtime:**
1. AutoAgent executes subtasks sequentially (id order).
2. After ALL subtasks complete, AutoAgent asks the AI to evaluate whether
   the **main task** completion_criteria are met.
3. If not met, the AI decides which subtask to retry from (`retry_from`)
   and provides a `suggested_fix` and `next_strategy`.
4. AutoAgent resets subtasks from `retry_from` onward and re-executes them,
   passing the `suggested_fix` to the retried subtask's prompt.
5. This loop repeats up to `max_attempts` times.

**Scope:** Top-level or subtask (nesting is supported — see §8.4).

**When to use:** Multi-step workflows where the overall success depends on
the combined result of all steps, and the AI should evaluate the final
outcome holistically.

**Design tips:**
- The `completion_criteria` of the nested task is what gets evaluated after
  all subtasks finish. Make it concrete and measurable.
- Subtask completion_criteria are evaluated independently during execution.
  The nested task's criteria is the "final exam."
- Design subtasks so that retrying from a middle subtask makes sense (e.g.,
  if step 3 fails, retrying from step 2 should produce a different input
  for step 3).

### 2.3 `looping`

**What happens at runtime:**
1. AutoAgent executes ALL subtasks sequentially — this is one "loop iteration."
2. After one iteration completes, ALL subtask states are reset.
3. Steps 1–2 repeat for `repeat_count` iterations.
4. There is NO completion evaluation between iterations — the loop always
   runs the full `repeat_count` times.
5. Within a single iteration, if a subtask fails, the AI analyzes the failure
   and decides retry strategy (same as nested).

**Scope:** Top-level or subtask (nesting is supported — see §8.4).

**When to use:** Iterative optimization cycles where you want to repeat the
same workflow N times (e.g., profile → optimize → benchmark → commit).

**Design tips:**
- Each iteration should be self-contained and produce incremental progress.
- Since there's no early termination, use looping when you want a fixed
  number of optimization rounds regardless of intermediate results.
- The last subtask in each iteration often handles "commit or rollback"
  logic to preserve good changes.

### 2.4 `long_running`

**What happens at runtime:**
1. AutoAgent sends a prompt telling the AI to use `autoagent-exec` wrapper
   script to launch the command in the background.
2. The AI runs: `autoagent-exec.bat <command>` (internal parameters like
   `--log-dir` and `--task-id` are pre-filled by the wrapper script).
3. `autoagent-exec` implements a **fast-fail** mechanism (configurable via `fast_fail_timeout` in `config.yaml`):
   - If the command exits within the timeout with an error → smart output
     (short output printed inline, long output shows only the log path),
     AI can fix and retry.
   - If the command exits within the timeout with success → smart output
     (short output printed inline with "not truncated" notice, long output
     shows only the log path), treated as completed.
   - If still running after the timeout → detached to background, AI outputs
     `⏳ LONG_RUNNING_IN_PROGRESS` and the session ends.
4. AutoAgent monitors the background process via a signal file.
5. When the process finishes, AutoAgent calls the AI back with the output
   log path, exit code, and asks it to evaluate the results.

**Scope:** Subtask only (inside nested or looping).

**When to use:** Commands that are KNOWN to take a long time — model training,
large-scale data processing, heavy profiling (e.g., `ncu`), long compilations.

**Design tips:**
- You do NOT need to specify the `command` field — the AI can decide what
  command to run based on the task description and initial_hint.
- If you DO specify `command`, it serves as a strong hint but the AI may
  still modify it.
- The AI will see the full output log after the command finishes, so
  completion_criteria can reference specific output patterns.

### 2.5 `simple_once` and `long_running_once`

**What happens at runtime:**
These behave identically to `simple` and `long_running` respectively, with
one key difference: **once completed, they are never re-executed**, even if:
- The parent nested task's evaluation triggers a retry from an earlier subtask.
- A new loop iteration starts in a looping task.
- A sibling subtask fails and the failure analyzer sets `retry_from` to an
  earlier subtask.

When a reset or new iteration would normally set a subtask back to "pending",
`*_once` subtasks that are already "completed" are skipped.

**Scope:** Subtask only (inside nested or looping).

**When to use:**
- One-time setup tasks: environment preparation, dependency installation,
  data download, initial code scaffolding.
- Expensive operations whose results remain valid across retries: large data
  preprocessing, one-time compilation of a dependency.
- Any subtask where re-execution would be wasteful or harmful (e.g., a
  database migration that should only run once).

**Design tips:**
- Use sparingly. Most subtasks SHOULD be re-executable so the AI can iterate.
- Only use `*_once` when the subtask's output genuinely does not need to
  change across retries or loop iterations.
- If a `*_once` subtask's output might become stale after other subtasks
  change things, do NOT use `*_once` — use the regular variant instead.

---

## 3. Task Schema Reference

### 3.0 Root-Level Fields

| Field         | Type   | Required | Description                                                  |
|---------------|--------|----------|--------------------------------------------------------------|
| `description` | string | **Yes**  | Project-level description injected into every task's prompt  |
| `tasks`       | list   | Yes      | Ordered list of top-level task definitions                   |

The `description` field provides high-level context about what the entire project
is trying to achieve. It is included in the **Context** section of every task
prompt (both top-level and subtask), so the AI always understands the big picture
even when individual tasks are very fine-grained.

> **⚠️ Important:** You **MUST** always include a `description` at the root
> level of `todos.yaml`. Without it, the AI executing individual tasks has no
> way to understand the overall project objective — it only sees the single
> task's name and completion criteria. This is especially critical when tasks
> are decomposed into fine-grained steps: the AI will know *how* to do a step
> but not *why*, leading to poor decisions and missed context.
>
> A good `description` should explain:
> - What the project is trying to accomplish (the goal)
> - Key constraints or invariants the AI must respect at all times
> - Important technical context (language, framework, target platform, etc.)

```yaml
description: |
  Optimize a CUDA image-processing pipeline for maximum throughput.
  The project uses CMake + CUDA 12, targets an RTX 4090, and must
  maintain Score 100/100 on the correctness test at all times.

tasks:
  - id: 1
    name: "Build project and establish baseline timing"
    type: simple
    ...
```

### 3.1 Common Fields (all types)

| Field                | Type   | Required | Description                                    |
|----------------------|--------|----------|------------------------------------------------|
| `id`                 | int/float | Yes   | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name`               | string | Yes      | Concise, descriptive task name                 |
| `type`               | string | Yes      | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
| `completion_criteria` | string | Yes     | Clear, specific, measurable success criteria   |
| `model`              | string | No       | `"default"`, `"lite"`, or a direct model name. Default: `"default"` |
| `system_prompt_prefix` | string | No    | Custom AI persona/instructions for this task (see §12) |

### 3.2 Type-Specific Fields

**simple / simple_once:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `initial_hint` | string | No       | Context/guidance for the AI on first attempt |

**nested:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `subtasks`     | list   | Yes      | Ordered list of subtasks (any valid subtask type, including nested/looping) |
| `max_attempts` | int    | No       | Max retry rounds (default: 5)            |

**looping:**

| Field                   | Type | Required | Description                          |
|-------------------------|------|----------|--------------------------------------|
| `subtasks`              | list | Yes      | Ordered list of subtasks             |
| `repeat_count`          | int  | Yes      | Number of loop iterations (≥ 1)      |
| `max_attempts_per_loop` | int  | No       | Max retries per iteration (default: 5)   |

**long_running / long_running_once:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `command`      | string | No       | Command to run (AI can decide if omitted) |
| `initial_hint` | string | No       | Context/guidance for the AI on first attempt |

### 3.3 Hierarchy Rules

```
Top-level tasks:     simple  |  nested            |  looping
                        │    |     │               |     │
                   (no subtasks)  subtasks:          subtasks:
                             |   simple             |   simple
                             |   simple_once        |   simple_once
                             |   long_running       |   long_running
                             |   long_running_once  |   long_running_once
                             |   nested             |   nested
                             |   looping            |   looping
```

- `nested` and `looping` can be top-level OR subtasks (multi-level nesting
  is supported).
- `long_running`, `long_running_once` can ONLY be subtasks.
- `simple_once` can ONLY be a subtask.
- `simple` can be either top-level or subtask.
- When `nested` or `looping` is used as a subtask, it behaves identically
  to the top-level version — it has its own `subtasks`, `max_attempts` /
  `repeat_count`, and independent retry/evaluation logic.

### 3.4 The `model` Field

The `model` field controls which AI model executes the task:

- `"default"` (or omitted): Uses the default model role, typically a more
  capable model suited for complex reasoning, multi-step code changes, and
  analysis.
- `"lite"`: Uses the lite model role, a lighter/faster model suitable for
  straightforward tasks like running a single command, simple file edits,
  or formatting.
- **Direct model name** (e.g., `"claude-sonnet-4-20250514"`): Uses the
  specified model directly, bypassing the role mapping.

> **⚠️ Note:** `model: "lite"` selects a lighter AI model. It is completely
> independent of `type: simple` (which defines the task execution behavior).
> A task can be `type: simple` with `model: "default"`, or `type: nested`
> with `model: "lite"` on its subtasks — the two fields are orthogonal.

**Guidelines:**
- Use `"lite"` for tasks like: "Run `make test`", "Format code with black",
  "Copy file X to Y", "Run benchmark and save output".
- Use `"default"` for tasks like: "Analyze profiling results and optimize
  kernel code", "Debug failing test and fix root cause", "Refactor module
  architecture".
- Use a direct model name when you need a specific model for a particular
  task, regardless of the role configuration.

---

## 4. How Completion Criteria Are Evaluated

Understanding the evaluation mechanism is critical for writing good criteria.

### 4.1 Simple Tasks — Self-Evaluation

The AI agent evaluates its own work. After completing its actions, it decides
whether the completion_criteria are met and outputs a status marker. This means:

- **Criteria must be objectively verifiable by the AI** — the AI should be
  able to check files, run commands, or read outputs to confirm.
- **Avoid subjective criteria** — the AI has no way to verify "code quality
  is good" or "performance is acceptable" without concrete metrics.

### 4.2 Nested Tasks — AI Holistic Evaluation

After all subtasks complete, a separate AI call evaluates the main task.
The evaluator sees:
- The main task's completion_criteria
- Execution results from all subtasks (success/failure + summaries)
- Relevant log file contents

The evaluator responds with a JSON object including `main_task_completed`,
`analysis`, `retry_from`, and `next_strategy`.

This means:
- **The nested task's criteria should describe the END STATE**, not the
  process. The evaluator checks whether the final outcome is achieved.
- **Subtask results are summarized** — the evaluator doesn't see full
  details of each subtask's execution, only summaries.

### 4.3 Looping Tasks — No Completion Evaluation

Looping tasks run for exactly `repeat_count` iterations. There is no
completion evaluation — the task is "done" when all iterations finish.
Individual subtask failures within an iteration are handled by retry logic.

---

## 5. Retry and Failure Handling

### 5.1 Simple Task Retries

If a simple task fails (AI outputs `❌ not completed`), the orchestrator
retries it with additional context:
- **Previous Attempts**: Summary of what was tried and what happened.
- **Suggested Fix**: If this is a subtask and the parent's failure analyzer
  provided a fix, it's included in the prompt.

**Session reset on retry:** The AI session is reset before each retry
attempt. This prevents context from accumulating across retries (which
can cause the AI's output to be truncated before it emits the completion
marker). The full task description and previous-attempt summaries are
included in every prompt, so no important context is lost.

**Marker-nudge mechanism:** If the AI does not output a status marker
(e.g. it forgot, or the CLI/SDK crashed mid-response), AutoAgent sends a
short follow-up prompt in the same session (without resetting). The AI
may continue unfinished work and read files, but is told not to re-run
commands it already executed. Before sending the nudge, the system checks
for an `autoagent-exec` signal file — if one exists, the nudge is
skipped entirely and a synthetic `LONG_RUNNING_IN_PROGRESS` is returned.
The number of nudge attempts is configurable via `max_marker_nudges` in
`config.yaml` (default: 2). After all nudges are exhausted, the system
falls back to the normal retry loop.

### 5.2 Nested/Looping Failure Analysis

When a subtask fails within a nested or looping task:
1. AutoAgent calls an AI to analyze the failure.
2. The AI sees: the failed subtask info, error output, all subtask statuses,
   and previous retry decisions.
3. The AI decides `retry_from` (which subtask to restart from) and provides
   a `suggested_fix`.
4. The `suggested_fix` is passed to the retried subtask's prompt.

**Implications for task design:**
- Design subtasks so that the failure of one can be diagnosed from its
  error output.
- Make subtask boundaries align with logical checkpoints — if step 3 fails,
  it should be meaningful to retry from step 2 or step 3.
- Avoid subtasks that silently fail — ensure errors are visible in output.

---

## 6. Writing Effective completion_criteria

### 6.1 Rules

1. **Be specific and measurable.** The AI must be able to verify the criteria
   by reading files, checking command output, or running tests.

2. **Reference concrete artifacts.** Mention file names, command outputs,
   specific values, or patterns the AI can check.

3. **Include both positive and negative conditions** when relevant (e.g.,
   "tests pass AND no regressions").

4. **Use numbered lists** for multiple conditions — this makes it clear that
   ALL conditions must be met.

### 6.2 Examples

✅ **Good:**
```yaml
completion_criteria: |
  1. The project builds successfully: cmake --build build --config Release
  2. The executable runs and outputs "Score: 100/100"
  3. Elapsed time is printed in format "Elapsed: XXX.XX ms"
  4. baseline_timing.txt exists and contains the timing value
```

✅ **Good:**
```yaml
completion_criteria: |
  All unit tests pass with 0 failures (pytest returns exit code 0).
  Code coverage is at least 80% (check coverage report).
```

❌ **Bad:**
```yaml
completion_criteria: "Code is optimized"
# Why bad: Not measurable. What does "optimized" mean?
```

❌ **Bad:**
```yaml
completion_criteria: "Performance is improved"
# Why bad: No baseline, no metric, no threshold.
```

❌ **Bad:**
```yaml
completion_criteria: "The function works correctly"
# Why bad: No way to verify without specific test cases or expected outputs.
```

### 6.3 Criteria for Different Task Types

**For simple tasks (code changes):**
- Reference the specific files to modify and what the changes should achieve.
- Include a verification step (e.g., "compiles without errors", "tests pass").

**For simple tasks (running commands):**
- Specify the expected output pattern or exit code.
- Mention where results should be saved.

**For nested tasks (overall evaluation):**
- Describe the desired end state, not the process.
- Include quantitative thresholds when possible.

**For long_running tasks:**
- Reference patterns in the output log (the AI will read the log file).
- Include exit code expectations (e.g., "exit code 0").

---

## 7. Writing Effective initial_hint

The `initial_hint` field is shown to the AI ONLY on the first attempt. It
provides context that helps the AI get started efficiently.

### 7.1 What to Include

- **Key file paths** the AI needs to know about.
- **Specific commands** to run (especially if non-obvious).
- **Architecture context** — how the codebase is structured.
- **Constraints** — things the AI should NOT change.

### 7.2 What NOT to Include

- **Completion criteria** — that's a separate field.
- **Obvious instructions** — the AI knows how to read files and run commands.
- **Overly detailed step-by-step** — let the AI figure out the approach.

### 7.3 Example

```yaml
initial_hint: |
  The project uses CMake with a custom CUDA compilation setup.
  Key files:
    - CMakeLists.txt: Main build config
    - cufftdx_dct3d.cuh: Kernel header (DCT/IDCT implementations)
    - main.cpp: Benchmark program (100 iterations)
  
  Build commands:
    cmake -B build -DCMAKE_BUILD_TYPE=Release
    cmake --build build --config Release
  
  IMPORTANT: Do NOT modify the correctness test (Score calculation) logic.
```

---

## 8. Task Decomposition Strategy

### 8.1 When to Use a Single `simple` Task

Use a single simple task when:
- The idea can be completed in one logical step.
- There's no need for background processes.
- The AI doesn't need to evaluate intermediate results.

Example ideas that should be a single simple task:
- "Fix the bug in the login endpoint"
- "Add input validation to the API"
- "Run the test suite and fix any failures"

### 8.2 When to Use `nested`

Use nested when:
- The idea requires multiple distinct steps.
- The overall success depends on the combined result.
- You want the AI to evaluate the final outcome and potentially retry.

### 8.3 When to Use `looping`

Use looping when:
- The idea involves repeating an optimization cycle.
- Each iteration should follow the same steps.
- You want a fixed number of iterations (no early termination).

### 8.4 When to Use Nested Subtasks

Use `nested` or `looping` as a subtask type when a step within a larger
workflow is itself a multi-step process with its own completion criteria
and retry logic.

**Design tips for nested subtasks:**
- Use nested subtasks when a step has its own independent retry logic
  that should not affect sibling subtasks.
- Keep nesting shallow (2–3 levels max) to maintain readability.
- Each nested subtask has its own `max_attempts` / `repeat_count`,
  independent of the parent.
- When a nested/looping subtask is reset by the parent's retry logic,
  all of its inner subtasks are also recursively reset.

### 8.5 Comprehensive YAML Example

The following example demonstrates all task types (`simple`, `nested`,
`looping`, `long_running`, `simple_once`, `long_running_once`) and nested
subtask structures in a single `todos.yaml` file:

```yaml
# ============================================================
# Task 1: A standalone simple task (top-level)
# ============================================================
- id: 1
  name: "Fix API input validation"
  type: simple
  model: "default"
  completion_criteria: |
    1. All API endpoints validate input parameters (type, range, required).
    2. Invalid requests return 400 with descriptive error messages.
    3. All existing tests pass (pytest returns exit code 0).
  initial_hint: |
    Key files:
      - src/api/routes.py: All endpoint definitions
      - src/api/validators.py: Validation utilities (create if needed)
    IMPORTANT: Do NOT change the response format of successful requests.

# ============================================================
# Task 2: A nested task with mixed subtask types
# ============================================================
- id: 2
  name: "Optimize database query performance"
  type: nested
  max_attempts: 5
  completion_criteria: |
    1. Average query response time < 100ms (measured by benchmark).
    2. All existing tests pass with 0 failures.
    3. Benchmark results saved to benchmark_results.txt.
  subtasks:
    # simple_once: one-time setup, never re-executed on retry
    - id: 2.1
      name: "Install profiling tools and establish baseline"
      type: simple_once
      model: "lite"
      completion_criteria: |
        1. pg_stat_statements extension is enabled.
        2. Baseline benchmark completed, results saved to baseline.txt.

    # simple: profile and analyze (re-runs on retry)
    - id: 2.2
      name: "Profile slow queries and design optimizations"
      type: simple
      completion_criteria: |
        1. Top 5 slowest queries identified with execution plans.
        2. Analysis and optimization plan saved to query_analysis.txt.
      initial_hint: |
        Use EXPLAIN ANALYZE on the slow queries.
        Check for missing indexes, N+1 queries, and full table scans.

    # simple: apply optimizations
    - id: 2.3
      name: "Apply database optimizations"
      type: simple
      completion_criteria: |
        1. Indexes created via migration file (migrations/add_indexes.sql).
        2. Query rewrites applied where needed.
        3. Application compiles and starts without errors.

    # simple: final benchmark
    - id: 2.4
      name: "Run benchmark and validate"
      type: simple
      model: "lite"
      completion_criteria: |
        1. Benchmark completed, results saved to benchmark_results.txt.
        2. Average response time < 100ms.
        3. All tests pass (pytest returns exit code 0).

# ============================================================
# Task 3: A looping task for iterative optimization
# ============================================================
- id: 3
  name: "Iterative CUDA kernel optimization"
  type: looping
  repeat_count: 3
  max_attempts_per_loop: 5
  completion_criteria: |
    3 rounds of profile-optimize-benchmark completed.
  subtasks:
    # long_running: GPU profiling takes a long time
    - id: 3.1
      name: "Profile kernel with Nsight Compute"
      type: long_running
      system_prompt_prefix: |
        You are a GPU performance engineer. Focus on memory throughput,
        occupancy, and warp efficiency metrics.
      completion_criteria: |
        ncu profiling completed with exit code 0.
        Output log contains "PROF" section with kernel metrics.

    # simple: analyze profile and optimize code
    - id: 3.2
      name: "Optimize kernel based on profile results"
      type: simple
      system_prompt_prefix: |
        You are a senior C++/CUDA engineer. Prefer modern C++17 features.
        Always check CUDA error codes with a macro.
      completion_criteria: |
        1. Code changes applied based on profiling bottlenecks.
        2. Project builds: cmake --build build --config Release succeeds.
        3. Correctness test passes: output contains "Score: 100/100".

    # simple: benchmark and decide commit/rollback
    - id: 3.3
      name: "Benchmark and commit or rollback"
      type: simple
      model: "lite"
      completion_criteria: |
        1. Benchmark run (100 iterations), timing saved to timing.txt.
        2. If faster than previous best → changes committed with git.
        3. If slower or equal → changes rolled back with git checkout.

# ============================================================
# Task 4: Deeply nested structure (nested containing looping)
# ============================================================
- id: 4
  name: "Build, optimize, and deploy service"
  type: nested
  max_attempts: 3
  completion_criteria: |
    Service deployed to staging, health check returns HTTP 200.
    Response time p99 < 200ms (measured by load test).
  subtasks:
    # nested subtask: build pipeline with its own retry logic
    - id: 4.1
      name: "Build and test"
      type: nested
      max_attempts: 3
      completion_criteria: |
        All tests pass and Docker image is built successfully.
      subtasks:
        - id: 4.1.1
          name: "Fix lint and type errors"
          type: simple
          completion_criteria: "pylint and mypy return exit code 0."
        - id: 4.1.2
          name: "Run test suite"
          type: simple
          completion_criteria: "pytest returns exit code 0, coverage >= 80%."
        - id: 4.1.3
          name: "Build Docker image"
          type: simple
          model: "lite"
          completion_criteria: "Docker image built: docker build -t myservice:latest ."

    # looping subtask: optimize response time iteratively
    - id: 4.2
      name: "Optimize response time"
      type: looping
      repeat_count: 2
      completion_criteria: "2 optimization rounds completed."
      subtasks:
        - id: 4.2.1
          name: "Profile with load test"
          type: long_running
          command: "k6 run loadtest.js --out json=profile.json"
          completion_criteria: "Load test completed, profile.json generated."
        - id: 4.2.2
          name: "Apply optimization"
          type: simple
          completion_criteria: |
            Optimization applied based on profile. Builds without errors.

    # simple: final deploy
    - id: 4.3
      name: "Deploy to staging"
      type: simple
      completion_criteria: |
        1. Deployed to staging environment.
        2. Health check endpoint returns HTTP 200.
        3. Smoke test passes (curl returns expected response).
```

### 8.6 Decomposition Anti-Patterns

❌ **Over-decomposition:** Breaking a simple task into 5 trivial subtasks.
```yaml
# BAD: These should be one simple task
- id: 1.1
  name: "Open the config file"
- id: 1.2
  name: "Change the port number"
- id: 1.3
  name: "Save the file"
- id: 1.4
  name: "Restart the server"
```

❌ **Under-decomposition:** Putting everything in one simple task when steps
are logically independent and may need separate retry strategies.
```yaml
# BAD: Training + evaluation + deployment should be separate subtasks
- id: 1
  name: "Train, evaluate, and deploy the model"
  type: simple
```

❌ **Wrong type choice:**
```yaml
# BAD: long_running as top-level
- id: 1
  type: long_running  # ERROR: long_running can only be a subtask
```

❌ **Vague criteria with nested tasks:**
```yaml
# BAD: The evaluator can't verify "good performance"
- id: 1
  type: nested
  completion_criteria: "The system performs well"
```

---

## 9. ID Assignment Rules

- **Top-level tasks**: Sequential integers starting from the next available ID.
  Example: if existing tasks go up to id 5, new tasks start from 6.
- **Subtasks**: Dot notation using parent ID as prefix.
  Example: task 6's subtasks are 6.1, 6.2, 6.3, etc.
- **Nested subtasks**: Continue the dot notation for deeper levels.
  Example: subtask 6.2 (type: nested) has subtasks 6.2.1, 6.2.2, etc.
- **IDs must be unique** across the entire todos.yaml file.
- **Subtask IDs determine execution order** — they run in ascending order.

---

## 10. Context Isolation Between Subtasks

Within a nested or looping task, each subtask runs in its own **independent
AI session** (the session is reset between subtasks). This prevents
unbounded context growth when there are many subtasks or loop iterations.

To maintain continuity, the orchestrator passes a **summary of the previous
subtask's output** to the next subtask via the prompt. This means:

- A later subtask can reference files created by an earlier subtask
  (because the files exist on disk), but the AI does NOT have direct
  memory of earlier subtask conversations.
- Design subtasks to be self-contained: include enough context in
  `completion_criteria` and `initial_hint` so the AI can work without
  relying on memory from previous subtasks.
- When a **retry** happens within the same subtask, the AI session is
  reset before each retry attempt. The retried subtask's prompt includes
  the `suggested_fix` from the failure analysis and previous attempt
  summaries, so no important context is lost despite the session reset.
- In **looping** tasks, sessions are also reset between iterations. Each
  iteration starts fresh, with only the previous subtask summary carried
  forward within the same iteration.

**Resume behavior:** The previous subtask summary is **persisted to disk**
(`previous_subtask_summary.txt` in the session directory). If execution is
interrupted and resumed, the summary is restored from disk so that the
next subtask still receives context from its predecessor — even though the
completed subtasks are skipped on resume.

For **looping** tasks, the current loop index is also persisted. If a
looping task is interrupted mid-iteration, it resumes from the last saved
loop index rather than restarting from iteration 1.

**Best practice:** Persist important intermediate results to files (e.g.,
analysis reports, configuration changes, benchmark results) rather than
relying on AI memory across subtasks. This ensures information survives
session resets.

---

## 11. Quick Reference Checklist

Before finalizing your task decomposition, verify:

- [ ] Every task has `id`, `name`, `type`, and `completion_criteria`
- [ ] Top-level tasks use `simple`, `nested`, or `looping` (never `long_running`)
- [ ] Subtasks use `simple`, `long_running`, `simple_once`, `long_running_once`, `nested`, or `looping`
- [ ] `*_once` subtasks are used only for genuinely one-time operations
- [ ] `looping` tasks have `repeat_count` (positive integer)
- [ ] `nested`/`looping` tasks have non-empty `subtasks` list
- [ ] All `completion_criteria` are specific, measurable, and verifiable
- [ ] Task IDs are unique and follow the correct notation
- [ ] The decomposition matches the complexity of the idea (not over/under-decomposed)
- [ ] `model` field is appropriate (`"lite"` for easy tasks, `"default"` for complex, or direct model name)
- [ ] `initial_hint` provides useful context without duplicating criteria
- [ ] `system_prompt_prefix` is set on tasks that need a specific AI persona or constraints

---

## 12. Customizing the AI Persona — `system_prompt_prefix`

You can set a `system_prompt_prefix` field on any task (top-level or
subtask) in `todos.yaml` to customize the AI's persona, role, or add
global instructions for that specific task.

```yaml
- id: 1
  name: "Optimize CUDA kernel"
  type: simple
  system_prompt_prefix: "You are a senior CUDA engineer specializing in GPU optimization."
  completion_criteria: |
    Kernel performance improved by at least 10%.
```

### How It Works

- The prefix text is **appended to the system prompt** for that task's AI
  calls (task execution and failure analysis).
- If the prefix is empty or omitted, no extra persona text is added.
- Each task can have its own prefix — different tasks can have different
  AI personas.

### Where to Set It

- **On a top-level `simple` task:** The prefix applies to that task's
  execution.
- **On subtasks inside `nested` or `looping`:** Each subtask can have its
  own prefix. This is useful when different steps require different
  expertise (e.g., a profiling step vs. an optimization step).
- **On a top-level `nested` or `looping` task:** Not directly supported —
  set the prefix on individual subtasks instead.

### When to Use

- **Domain expertise:** Set the AI's persona to match the task's domain
  (e.g., "You are a machine learning engineer" or "You are a backend
  developer specializing in distributed systems").
- **Task-specific constraints:** Add instructions that should apply to a
  particular task (e.g., "Always write code in Python 3.12+" or "Never
  modify files in the vendor/ directory").
- **Coding style:** Enforce conventions (e.g., "Follow Google C++ style
  guide" or "Use type hints in all Python functions").

### Example

```yaml
subtasks:
  - id: 1.1
    name: "Profile kernel with Nsight Compute"
    type: long_running
    system_prompt_prefix: |
      You are a GPU performance engineer. Focus on memory throughput,
      occupancy, and warp efficiency metrics.
    completion_criteria: |
      ncu profiling completed and output saved.

  - id: 1.2
    name: "Optimize kernel code"
    type: simple
    system_prompt_prefix: |
      You are a senior C++/CUDA engineer. Follow these rules:
      - Prefer modern C++17 features.
      - Always check CUDA error codes with a macro.
      - Write concise comments for non-obvious logic.
    completion_criteria: |
      Optimization applied, builds without errors, correctness preserved.
```
