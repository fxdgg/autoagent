# Task Design Guide for AI Agents

This document is a reference for AI agents that generate TODO tasks (via idea
decomposition). It explains how to design tasks that are effective, robust, and
easy to evaluate.

---

## 1. Execution Model Overview

AutoAgent drives an AI coding agent (e.g., Codex, Gemini CLI, Claude Code) 
through a sequence of tasks defined in `todos.yaml`. 
The AI agent can do anything a developer can: edit code, run commands, 
read logs, install packages, use git, etc.

Key implications for task design:
- **Fully autonomous** — there is no human in the loop. The AI must make all
  decisions independently and never ask the user questions.
  The `completion_criteria` and `initial_hint` must be specific enough that the
  AI can act without asking for clarification.
- The AI agent has a **context window limit** — avoid tasks that require
  reading extremely large files or outputs in a single step.
- **Subtasks do not share conversation context** — they share the filesystem,
  and a summary of the previous subtask's output is passed forward. Persist
  important intermediate results to files rather than relying on AI memory.
- The AI's persona/role can be customized per-task via the
  `system_prompt_prefix` field (see §9).

### Top-Level Task Execution Order

Top-level tasks are executed **strictly sequentially in ascending ID order**.

- **Later tasks can depend on artifacts produced by earlier tasks** — they
  share the same filesystem.
- **There is no parallel execution** — task N+1 starts only after task N
  completes (or exhausts its retries).
- **A failed task does NOT block subsequent tasks.**
- **Design your task ordering carefully**: place setup and prerequisite
  tasks before tasks that depend on their outputs.

---

## 2. Task Types

### Quick Choice Guide
- **Need to run a command > 1 minute?** -> Use `long_running`.
- **One-time environment setup?** -> Use `simple_once`.
- **Iterative optimization (e.g., "try, measure, repeat")?** -> Use `looping`.
- **Complex multi-step workflow with logical checkpoints?** -> Use `nested`.
- **Everything else (code edits, quick tests, analysis)?** -> Use `simple`.

### Decision Flow
1. Is it a single logical step with no long-running commands? → **`simple`**
2. Does it involve a command that may take > 1 minute? → Use as a **`long_running`** subtask inside `nested`
3. Is it multi-step with a final success check? → **`nested`**
4. Is it an iterative cycle (repeat the same steps N times)? → **`looping`**
5. Is a subtask one-time setup that should not be re-run on retry? → **`simple_once`** or **`long_running_once`**

### 2.1 `simple`

The AI works autonomously — reading files, running commands, making code
changes — then self-evaluates whether the `completion_criteria` are met.
If not, the task is retried (up to `max_attempts` times) with summaries of
previous attempts.

**Scope:** Can be a top-level task or a subtask inside nested/looping.

**When to use:** Any task the AI can complete in a single session — code
changes, running tests, file analysis, data processing, simple builds, etc.

**Design tips:**
- Keep each simple task focused on ONE logical objective.
- **Prefer `long_running` for any subtask that runs a command which may
  take more than a minute** (builds, tests, benchmarks, training, profiling).
  If a command runs too long inside a `simple` task, the AI session may hit
  a timeout (CLI or SDK), wasting all progress and potentially leaving the
  project in a broken state. `long_running` avoids this by running the
  command in the background with proper monitoring.
  While the AI can use `autoagent-exec` in a `simple` task, explicitly
  marking the subtask as `long_running` is more reliable — it ensures the
  command is always launched in the background from the start.

### 2.2 `nested`

Executes subtasks sequentially. After all subtasks complete, the overall
`completion_criteria` is checked by an AI. If not met, one or more subtasks 
may be retried with guidance from previous failures (up to `max_attempts` rounds).

**Scope:** Can be a top-level task or a subtask inside nested/looping (nesting is supported — see §7.4).

**When to use:** Multi-step workflows where the overall success depends on
the combined result of all steps.

**Design tips:**
- The `completion_criteria` of the nested task is the "final exam" — make it
  concrete and measurable.
- Subtask criteria are evaluated independently during execution.
- Design subtasks so that retrying from a middle subtask makes sense (e.g.,
  if step 3 fails, retrying from step 2 should produce a different input
  for step 3).

### 2.3 `looping`

Executes ALL subtasks sequentially — one "loop iteration" — then repeats
for `repeat_count` iterations. If a subtask fails within an iteration, it
may be retried with guidance, the same as in nested tasks.

**Scope:** Can be a top-level task or a subtask inside nested/looping (nesting is supported — see §7.4).

**When to use:** Iterative optimization cycles where you want to repeat the
same workflow N times (e.g., profile → optimize → benchmark → commit).

**Design tips:**
- Each iteration should be self-contained and produce incremental progress.
- The last subtask in each iteration often handles "commit or rollback"
  logic to preserve good changes.

### 2.4 `long_running`

Tells the AI to launch a command in the background via `autoagent-exec`.
If the command fails quickly, the AI sees the error and can fix & retry. If
it takes a long time, the AI will see the full output after the command
finishes.

**Scope:** Subtask only (inside nested or looping).

**When to use:** **Any subtask that runs a command which may take more than
a minute.** This includes builds, test suites, benchmarks, training,
profiling, data processing, and deployments. When in doubt, prefer
`long_running` over `simple` — the overhead is minimal, but it prevents
session timeouts that waste progress and may leave the project in a broken
state.

**Design tips:**
- You do NOT need to specify the `command` field — the AI can decide what
  command to run based on the task description and `initial_hint`.
- The AI will see the full output log after the command finishes, so
  `completion_criteria` can reference specific output patterns.

### 2.5 `simple_once` and `long_running_once`

Behave identically to `simple` and `long_running` respectively, with one key
difference: **once completed, they are never re-executed**, even on retries
or new loop iterations.

**Scope:** Subtask only (inside nested or looping).

**When to use:**
- One-time setup: environment preparation, dependency installation, data
  download, initial scaffolding.
- Expensive operations whose results remain valid across retries.

**Design tips:**
- Use sparingly. Most subtasks SHOULD be re-executable so the AI can iterate.
- If a `*_once` subtask's output might become stale after other subtasks
  change things, do NOT use `*_once`.

---

## 3. Task Schema Reference

### 3.0 Root-Level Fields

| Field         | Type   | Required | Description                                                  |
|---------------|--------|----------|--------------------------------------------------------------|
| `description` | string | **Yes**  | Project-level description included in every task's prompt    |
| `tasks`       | list   | Yes      | Ordered list of top-level task definitions                   |

> **⚠️ Important:** You **MUST** always include a `description` at the root
> level. Without it, the AI has no way to understand the overall project
> objective. A good `description` should explain:
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

| Field                  |   Type    | Required | Description                                    |
|------------------------|-----------|----------|------------------------------------------------|
| `id`                   | int/float | Yes      | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name`                 |   string  | Yes      | Concise, descriptive task name                 |
| `type`                 |   string  | Yes      | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
|  `completion_criteria` |   string  | Yes      | Clear, specific, measurable success criteria   |
| `model`                |   string  | No       | `"default"`, `"lite"`, or a direct model name. Default: `"default"` |
| `system_prompt_prefix` |   string  | No       | Custom AI persona/instructions for this task (see §10) |

### 3.2 Type-Specific Fields

**simple / simple_once / long_running / long_running_once:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `initial_hint` | string | No       | Static context/guidance included in every attempt |

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

### 3.3 Hierarchy Rules

- **Top-level tasks**: `simple`, `nested`, or `looping`.
- **Subtasks** (inside nested/looping): all six types are allowed —
  `simple`, `simple_once`, `long_running`, `long_running_once`, `nested`,
  `looping`.
- `long_running`, `long_running_once`, and `simple_once` can ONLY be subtasks.
- `nested`/`looping` as subtasks have their own `subtasks`,
  `max_attempts`/`repeat_count`, and independent retry logic.

### 3.4 The `model` Field

The `model` field controls which AI model executes the task:

- `"default"` (or omitted): More capable model for complex reasoning and
  multi-step code changes.
- `"lite"`: Lighter/faster model for straightforward tasks (running commands,
  simple file edits, formatting).
- **Direct model name** (e.g., `"claude-sonnet-4-20250514"`): Uses the
  specified model directly.

**Guidelines:**
- Use `"lite"` for: "Run `make test`", "Format code with black",
  "Copy file X to Y", "Run benchmark and save output".
- Use `"default"` for: "Analyze profiling results and optimize kernel code",
  "Debug failing test and fix root cause", "Refactor module architecture".

### 3.5 Choosing `max_attempts`

**`max_attempts: 1` — Execution-only subtasks:**

Subtasks whose sole purpose is to **run code written by a previous subtask**
(build, benchmark, test, profile, etc.) should set `max_attempts: 1`.
If the command fails, the cause is almost always a bug in the code produced
by a sibling subtask — retrying the same command will fail the same way.
With `max_attempts: 1`, the failure propagates immediately to the parent's
failure analysis.

```yaml
# ✅ Good: execution subtask with max_attempts: 1
- id: 2.3
  name: "Run benchmark"
  type: simple
  max_attempts: 1        # fail fast → parent handles retry
  model: lite
  completion_criteria: |
    Benchmark exits with code 0 and prints "Score: 100/100".
```

**`max_attempts: 2–3` — Moderately uncertain tasks:**

Use for tasks where the AI may need a second chance but the problem space
is constrained.

**`max_attempts: 5` (default) — Complex code-writing tasks:**

Good for tasks involving open-ended code changes, multi-file refactoring,
or optimization where the AI may need several different strategies.

**Do NOT use `max_attempts: 1`** on subtasks where the AI actively writes or
modifies code — those benefit from multiple attempts with different strategies.

### 3.6 ID Assignment Rules

- **Top-level tasks**: Sequential integers starting from the next available ID.
- **Subtasks**: Dot notation using parent ID as prefix (e.g., 6.1, 6.2, 6.3).
- **Nested subtasks**: Continue the dot notation (e.g., 6.2.1, 6.2.2).
- **IDs must be unique** across the entire todos.yaml file.
- **Subtask IDs determine execution order** — they run in ascending order.

---

## 4. How Completion Criteria Are Evaluated

Different task types evaluate completion criteria differently. Understanding
this helps you write better criteria:

- **Simple tasks** — The AI self-evaluates. Criteria must be **objectively
  verifiable by the AI** (e.g., check files, run commands, read outputs).
  Avoid subjective criteria the AI cannot verify.
- **Nested tasks** — Only the top-level `completion_criteria` determines
  overall pass/fail. Write it as the desired **end state**, not the process.
- **Looping tasks** — No pass/fail evaluation. The task is "done" when all
  `repeat_count` iterations finish.

---

## 5. Retry and Failure Handling

### 5.1 Designing for Retry Resilience

When a subtask is retried, the previous attempt may have modified files or
left the codebase in a half-changed state. The AI on retry has access to
summaries of previous attempts but **the filesystem changes persist**.

**Guidelines:**

- **Mention cleanup in `initial_hint`** when a task modifies shared state:
  ```yaml
  initial_hint: |
    NOTE: If a previous attempt left partial changes, check the state of
    build/ and src/generated/ before starting. Remove stale artifacts if
    needed (rm -rf build/).
  ```
- **Prefer append/overwrite patterns** over incremental mutations. A task
  that writes a complete output file is naturally idempotent; a task that
  appends lines to a config file is not.
- **Use git as a safety net** in `initial_hint` when appropriate: "Run
  `git diff` first to check for unexpected changes from a previous attempt.
  Use `git checkout -- <file>` to reset if needed."
- **Don't over-engineer for idempotency** — it's enough to make the AI
  *aware* that residual state may exist, so it can inspect and adapt.

### 5.2 Defensive Task Design

When tasks depend on external tools, services, or environmental
configurations, design them to handle common failure modes gracefully.

**In `completion_criteria` — handle partial success explicitly:**
```yaml
# ✅ Good: acknowledges that partial results are possible
completion_criteria: |
  1. At least 8 out of 10 test suites pass.
  2. Any failing suites are documented in test_failures.txt with root cause.
  3. No regressions in previously passing tests.

# ❌ Bad: all-or-nothing with no fallback
completion_criteria: "All 10 test suites pass."
```

**In `initial_hint` — include prerequisite checks:**
```yaml
initial_hint: |
  Before starting optimization:
  1. Verify the project builds: cmake --build build --config Release
  2. Verify correctness: run ./benchmark and confirm "Score: 100/100"
  3. If either fails, fix the build/correctness issue FIRST.
```

### 5.3 Subtask Failure in Nested/Looping Tasks

When a subtask fails, earlier subtasks may be retried with guidance.

**Implications for task design:**
- Design subtasks so that the failure of one can be diagnosed from its output.
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

5. **Focus on the "What", not the "How" of AutoAgent.** The AI executor doesn't need to know about AutoAgent's internal retry mechanisms or session management. The criteria should focus purely on the state of the codebase or the output of commands.

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

## 7. Task Decomposition Strategy

### 7.1 When to Use a Single `simple` Task

Use a single simple task when:
- The idea can be completed in one logical step.
- There's no need for background processes.
- The AI doesn't need to evaluate intermediate results.

Example ideas that should be a single simple task:
- "Fix the bug in the login endpoint"
- "Add input validation to the API"
- "Run the test suite and fix any failures"

### 7.2 When to Use `nested`

Use nested when:
- The idea requires multiple distinct steps.
- The overall success depends on the combined result.
- You want the AI to evaluate the final outcome and potentially retry.

### 7.3 When to Use `looping`

Use looping when:
- The idea involves repeating an optimization cycle.
- Each iteration should follow the same steps.
- You want a fixed number of iterations (no early termination).

### 7.4 When to Use Nested Subtasks

Use `nested` or `looping` as a subtask type when a step within a larger
workflow is itself a multi-step process with its own completion criteria
and retry logic.

**Design tips:**
- Keep nesting shallow (2–3 levels max) to maintain readability.
- Each nested subtask has its own `max_attempts` / `repeat_count`,
  independent of the parent.

### 7.5 State Persistence Pattern (Passing the Baton)

Because subtasks do not share conversation context, the AI must use the filesystem to pass information between steps.

**Best Practice:**
- In the `initial_hint` of the producer subtask, explicitly instruct the AI to write intermediate results (e.g., analysis reports, selected parameters, generated code paths) to a specific file like `workflow_state.json` or `step1_out.txt`.
- In the `initial_hint` of the consumer subtask, instruct the AI to read that specific file before proceeding.

### 7.6 Comprehensive YAML Example

The following example demonstrates all task types and nested structures:

```yaml
# Task 1: A standalone simple task (top-level)
- id: 1
  name: "Fix API input validation"
  type: simple
  completion_criteria: |
    1. All API endpoints validate input parameters (type, range, required).
    2. Invalid requests return 400 with descriptive error messages.
    3. All existing tests pass (pytest returns exit code 0).
  initial_hint: |
    Key files:
      - src/api/routes.py: All endpoint definitions
      - src/api/validators.py: Validation utilities (create if needed)
    IMPORTANT: Do NOT change the response format of successful requests.

# Task 2: A nested task with mixed subtask types
- id: 2
  name: "Optimize database query performance"
  type: nested
  max_attempts: 5
  completion_criteria: |
    1. Average query response time < 100ms (measured by benchmark).
    2. All existing tests pass with 0 failures.
    3. Benchmark results saved to benchmark_results.txt.
  subtasks:
    - id: 2.1
      name: "Install profiling tools and establish baseline"
      type: simple_once          # one-time setup, never re-executed on retry
      model: "lite"
      completion_criteria: |
        1. pg_stat_statements extension is enabled.
        2. Baseline benchmark completed, results saved to baseline.txt.
    - id: 2.2
      name: "Profile slow queries and design optimizations"
      type: simple
      completion_criteria: |
        1. Top 5 slowest queries identified with execution plans.
        2. Analysis and optimization plan saved to query_analysis.txt.
      initial_hint: |
        Use EXPLAIN ANALYZE on the slow queries.
        Check for missing indexes, N+1 queries, and full table scans.
    - id: 2.3
      name: "Apply database optimizations"
      type: simple
      completion_criteria: |
        1. Indexes created via migration file (migrations/add_indexes.sql).
        2. Query rewrites applied where needed.
        3. Application compiles and starts without errors.
    - id: 2.4
      name: "Run benchmark and validate"
      type: simple
      max_attempts: 1            # execution-only → fail fast
      model: "lite"
      completion_criteria: |
        1. Benchmark completed, results saved to benchmark_results.txt.
        2. Average response time < 100ms.
        3. All tests pass (pytest returns exit code 0).

# Task 3: A looping task for iterative optimization
- id: 3
  name: "Iterative CUDA kernel optimization"
  type: looping
  repeat_count: 3
  max_attempts_per_loop: 5
  completion_criteria: |
    3 rounds of profile-optimize-benchmark completed.
  subtasks:
    - id: 3.1
      name: "Profile kernel with Nsight Compute"
      type: long_running
      system_prompt_prefix: |
        You are a GPU performance engineer. Focus on memory throughput,
        occupancy, and warp efficiency metrics.
      completion_criteria: |
        ncu profiling completed with exit code 0.
        Output log contains "PROF" section with kernel metrics.
    - id: 3.2
      name: "Optimize kernel based on profile results"
      type: simple
      completion_criteria: |
        1. Code changes applied based on profiling bottlenecks.
        2. Project builds: cmake --build build --config Release succeeds.
        3. Correctness test passes: output contains "Score: 100/100".
    - id: 3.3
      name: "Benchmark and commit or rollback"
      type: simple
      model: "lite"
      completion_criteria: |
        1. Benchmark run (100 iterations), timing saved to timing.txt.
        2. If faster than previous best → changes committed with git.
        3. If slower or equal → changes rolled back with git checkout.
```

### 7.7 Decomposition Anti-Patterns

❌ **Over-decomposition:** Breaking a task into too many fine-grained subtasks.

Each subtask runs in a separate AI session with context isolation. More
subtasks means more session resets, more token overhead for passing context
between steps, and less flexibility for the AI to adapt its approach. A
common mistake is creating 4–5 subtasks per task when 2–3 would suffice.

**Rule of thumb:** Only create a separate subtask when the step has a
**genuinely different failure mode** that benefits from independent retry.
If two steps always succeed or fail together, merge them.

```yaml
# BAD: 5 subtasks where 2–3 would do
subtasks:
  - id: 1.1
    name: "Read and analyze the profiling report"      # ← merge into 1.1
  - id: 1.2
    name: "Identify the top bottleneck"                 # ← merge into 1.1
  - id: 1.3
    name: "Implement the optimization"                  # ← this is the real work
  - id: 1.4
    name: "Build the project"                           # ← merge into 1.3 or 1.5
  - id: 1.5
    name: "Run benchmark and validate"

# GOOD: 2–3 subtasks with clear boundaries
subtasks:
  - id: 1.1
    name: "Analyze profiling report and implement optimization"
    # AI reads the report, identifies the bottleneck, and writes the fix
    # — all in one session with full context.
  - id: 1.2
    name: "Build, benchmark, and validate"
    max_attempts: 1    # fail fast → parent retries from 1.1
    model: lite
```

Similarly, avoid splitting "analyze → plan → implement" into three subtasks.
The AI works best when it can analyze, plan, and implement in a single
session — splitting these forces context to be summarized and passed between
sessions, losing nuance.

❌ **Under-decomposition:** Putting everything in one simple task when steps
are logically independent and may need separate retry strategies.
```yaml
# BAD: Training + evaluation + deployment should be separate subtasks
- id: 1
  name: "Train, evaluate, and deploy the model"
  type: simple
```
*Why it's bad:* If the deployment step fails due to a network timeout, the AI will retry the entire `simple` task, which means it will re-run the expensive training step from scratch, wasting significant time and compute. These should be separate subtasks in a `nested` task so deployment can be retried independently.

❌ **Wrong type choice:**
```yaml
# BAD: long_running can only be a subtask
- id: 1
  type: long_running
```

❌ **Vague criteria with nested tasks:**
```yaml
# BAD: Not measurable
- id: 1
  type: nested
  completion_criteria: "The system performs well"
```

---

## 8. Writing Effective initial_hint

The `initial_hint` field provides static context included on **every attempt**
(first attempt and retries alike).

> **💡 `initial_hint` vs `system_prompt_prefix`**
> - Use `initial_hint` for **"how to do the task"** (file paths, specific commands, troubleshooting guides).
> - Use `system_prompt_prefix` for **"who you are and global rules"** (expert persona, coding style, strict constraints).

### 8.1 What to Include

- **Key file paths** the AI needs to know about.
- **Specific commands** to run (especially if non-obvious).
- **Architecture context** — how the codebase is structured.
- **Constraints** — things the AI should NOT change.
- **Common failure modes** and how to work around them.

### 8.2 What NOT to Include

- **Completion criteria** — that's a separate field.
- **Obvious instructions** — the AI knows how to read files and run commands.
- **Overly detailed step-by-step** — let the AI figure out the approach.
- **Attempt-specific strategies** — avoid "start by trying X" that could
  cause the AI to repeat the same failed approach on retries.
- **AutoAgent internals** — Do not explain how AutoAgent works to the AI executor. It only needs to know about the project it is working on.

### 8.2.1 Where Does This Information Belong?

| Information                                      | `completion_criteria` | `initial_hint` |
|--------------------------------------------------|-----------------------|----------------|
| "All tests pass with 0 failures"                 | ✅                    | ❌             |
| "Build succeeds with no warnings"                | ✅                    | ❌             |
| "Key files: src/api/routes.py, src/models/"      | ❌                    | ✅             |
| "If previous attempt left residual, clean first" | ❌                    | ✅             |
| "Use cmake -B build -DCMAKE_BUILD_TYPE=Release"  | ❌                    | ✅             |
| "Output saved to results.txt"                    | ✅                    | ❌             |

### 8.3 Example

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

### 8.4 Including Troubleshooting Guidance

```yaml
initial_hint: |
  Key files: src/training/train.py, configs/model.yaml

  Troubleshooting:
  - If CUDA OOM occurs, reduce batch_size in configs/model.yaml (try 16 → 8).
  - If pip install fails on torch, use: pip install torch --index-url https://...
  - The database may take ~10s to start; if connection refused, retry after wait.
```

---

## 9. Customizing the AI Persona — `system_prompt_prefix`

Set `system_prompt_prefix` on any task or subtask to customize the AI's
persona, role, or add task-specific instructions.

**When to use:**
- **Domain expertise:** "You are a GPU performance engineer."
- **Task-specific constraints:** "Never modify files in the vendor/ directory."
- **Coding style:** "Follow Google C++ style guide."

> **Note:** Setting `system_prompt_prefix` on a top-level `nested` or
> `looping` task is not supported — set it on individual subtasks instead.

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
    completion_criteria: |
      Optimization applied, builds without errors, correctness preserved.
```

---

## 10. Quick Reference

- **ALWAYS include a root-level `description`** — without it, the AI has no
  project context. Explain the goal, constraints, and technical stack.
- Every task needs `id`, `name`, `type`, and `completion_criteria`.
- `long_running`, `long_running_once`, `simple_once` can ONLY be subtasks.
- All `completion_criteria` must be specific, measurable, and verifiable.
- Use `model: "lite"` for simple execution tasks, `"default"` for complex
  reasoning tasks.
- Use `*_once` sparingly — only for genuinely one-time operations.
- Persist important intermediate results to files rather than relying on
  AI memory across subtasks.
