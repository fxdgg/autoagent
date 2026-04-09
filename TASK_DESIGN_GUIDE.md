# Task Design Guide for AI Agents

Reference for AI agents that generate TODO tasks (via idea decomposition).

---

## 1. Execution Model Overview

AutoAgent drives an AI coding agent (e.g., Codex, Gemini CLI, Claude Code) through a sequence of tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

| Property | Implication for task design |
|----------|---------------------------|
| **Fully autonomous** | No human in the loop. `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification. |
| **Context window limit** | Avoid tasks requiring extremely large files/outputs in a single step. |
| **No shared conversation context between tasks and subtasks** | Tasks and subtasks **share the filesystem only**. Only a summary of the previous subtask is passed forward. Always persist intermediate results to files. |
| **Sequential execution** | Top-level tasks run in ascending ID order. Task N+1 starts only after task N completes or exhausts retries. |
| **Failed tasks don't block** | A failed task does NOT prevent subsequent tasks from running. Later tasks may depend on artifacts produced by earlier tasks. Design ordering carefully. |

---

## 2. Task Types

### Overview

| Type | Description | Scope | When to use |
|------|-------------|-------|-------------|
| `simple` | AI works autonomously, then self-evaluates completion | Top-level or subtask | Code changes, running tests, file analysis, quick builds |
| `nested` | Sequential subtasks + AI evaluation of overall completion; When fails consecutively, retries with guidance | Top-level or subtask | Multi-step workflows where overall success depends on combined result |
| `looping` | Repeat all subtasks for fixed N iterations; NO AI evaluation involved for overall completion | Top-level or subtask | Iterative optimization cycles (profile → optimize → benchmark) |
| `long_running` | AI launches a background command via `autoagent-exec`, avoiding CLI or SDK timeout which wastes time and may cause broken project states | Top-level or subtask | Any command that may take > 1 minute (builds, tests, benchmarks, training, profiling) |
| `simple_once` | Like `simple`, but never re-executed once completed | Subtask only | One-time setup (env prep, dependency install, data download) |
| `long_running_once` | Like `long_running`, but never re-executed once completed | Subtask only | Expensive one-time operations (Docker build, baseline profiling) |

### Key Notes

- **Prefer `long_running` over `simple`** for any command that may take > 1 minute. If a command runs too long inside `simple`, the AI session may hit a timeout, wasting all progress. `long_running` runs the command in the background with proper monitoring — minimal overhead, prevents session timeouts.
- **`*_once` types**: Use sparingly. Most subtasks SHOULD be re-executable. Don't use `*_once` if a subtask's output might become stale after other subtasks run.
- **Nested subtasks**: `nested`/`looping` can be used as subtask types for multi-level nesting. Keep nesting shallow (2–3 levels max).

---

## 3. Task Schema Reference

### 3.1 Root-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | **Yes** | Project-level description included in every task's prompt |
| `tasks` | list | Yes | Ordered list of top-level task definitions |

> **Important:** Always include `description`. Without it, the AI has no overall project context.

A good `description` should cover:

| Component | Purpose | Example |
|-----------|---------|---------|
| **Goal** | What the project is trying to accomplish | "Optimize a CUDA image-processing pipeline for maximum throughput" |
| **Reference docs** | Help the AI understand the project's domain and APIs | "See docs/API.md for the REST interface spec" |
| **Architecture overview** | Help the AI quickly locate the right files | "src/core/ contains the engine, src/api/ is the REST layer, tests/ mirrors src/" |
| **Hard constraints** | Invariants the AI must respect at all times | "Must maintain Score 100/100 on correctness test; never modify vendor/" |

```yaml
description: |
  Optimize a CUDA image-processing pipeline for maximum throughput.
  The project uses CMake + CUDA 12, targets an RTX 4090.

  Reference: See docs/cufftdx_api.md for the cuFFTDx API reference.

  Architecture:
    - src/kernels/dct3d.cuh: Core DCT/IDCT kernel implementations
    - src/main.cpp: Benchmark entry point (100 iterations)
    - CMakeLists.txt: Build configuration
    - tests/correctness_test.py: Correctness validation script

  Constraints:
    - Must maintain Score 100/100 on the correctness test at all times.
    - Do NOT modify the Score calculation logic in tests/correctness_test.py.
```

### 3.2 Common Fields (all types)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int/float | Yes | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name` | string | Yes | Concise, descriptive task name |
| `type` | string | Yes | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
| `completion_criteria` | string | Yes | Clear, specific, measurable success criteria |
| `model` | string | No | `"default"`, `"lite"`, or a direct model name. `"default"` will be used if not specified |
| `system_prompt_prefix` | string | No | Custom AI persona/instructions for this task (see §5.3) |

### 3.3 Type-Specific Fields

**simple / simple_once / long_running / long_running_once:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `initial_hint` | string | No | Static context/guidance included in every attempt |

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

### 3.4 Hierarchy Rules

- **Top-level**: `simple`, `nested`, `looping`, `long_running`.
- **Subtasks** (inside nested/looping): all six types allowed.
- `simple_once` and `long_running_once` can ONLY be subtasks.
- Nested subtasks have their own `max_attempts`/`repeat_count`, independent of the parent.

### 3.5 ID Assignment Rules

- **Top-level tasks**: Sequential integers starting from the next available ID.
- **Subtasks**: Dot notation using parent ID as prefix (e.g., 6.1, 6.2, 6.3).
- **Nested subtasks**: Continue the dot notation (e.g., 6.2.1, 6.2.2).
- IDs must be unique across the entire `todos.yaml`. Subtask IDs determine execution order.

---

## 4. Best Practice: Task Decomposition

### 4.1 Choosing the Right Structure

| Scenario | Recommended structure |
|----------|-----------------------|
| Single logical step (fix a bug, add validation, run tests) | Single `simple` task |
| Multi-step workflow where the goal is **achieving a target** | `nested` task |
| Iterative cycle where the goal is **running N rounds of experimentation** | `looping` task |
| One step within a workflow is itself multi-step | Nested subtask (`nested`/`looping` as subtask type) |

**`nested` vs `looping`:**
- Use `nested` when the core goal is **reaching a specific end state** (e.g., "achieve 20% speedup", "all tests pass"). The AI evaluates the overall `completion_criteria` after each round and can stop early or retry intelligently.
- Use `looping` when the core goal is **performing N rounds of work** (e.g., "do 5 rounds of optimization", "run 3 experiments with different configs"). There is no AI evaluation of overall completion — it simply repeats for `repeat_count` iterations.

### 4.2 Anti-Patterns

**Over-decomposition** — too many fine-grained subtasks:

Each subtask runs in a separate AI session with context isolation. More subtasks = more session resets + token overhead. Only create a separate subtask when the step has a **genuinely different failure mode** that benefits from independent retry. If two steps always succeed or fail together, merge them.

```yaml
# BAD: 5 subtasks where 2–3 would do
subtasks:
  - id: 1.1
    name: "Read and analyze the profiling report"    
  - id: 1.2
    name: "Identify the top bottleneck"  
  - id: 1.3
    name: "Implement the optimization" 
  - id: 1.4
    name: "Build the project"  
  - id: 1.5
    name: "Run benchmark and validate"

# GOOD: 2–3 subtasks with clear boundaries
subtasks:
  - id: 1.1
    name: "Analyze profiling report, implement optimization, and build"
    # AI reads the report, identifies the bottleneck, writes the fix,
    # and builds — all in one session. If build/tests fail, the AI can
    # fix immediately without a costly failure_analysis round-trip.
  - id: 1.2
    name: "Benchmark and validate"
    max_attempts: 1    # fail fast → parent retries from 1.1
    model: lite        # use lite model for lower cost
```

**Recommended pattern**: Group strongly dependent steps into one subtask. In particular:
- **"implement + build + test"** — if tests fail, the AI can fix code immediately in the same session, saving a failure_analysis round-trip.
- **"analyze + plan + implement"** — the AI works best when it can analyze, plan, and implement in a single session. Splitting these forces context to be summarized between sessions, losing nuance.

**Under-decomposition** — everything in one task when steps are logically independent:

```yaml
# BAD: Training + evaluation + deployment should be separate subtasks
- id: 1
  name: "Train, evaluate, and deploy the model"
  type: simple
```

If deployment fails, the AI retries the entire task including expensive training. Use `nested` so deployment can be retried independently. Beyond wasted compute, under-decomposition also causes:
- **Context explosion** — the AI accumulates too much context across many steps, degrading output quality.
- **AI laziness** — when faced with too many responsibilities in one task, the AI tends to take shortcuts (e.g., choosing the simplest optimization because there's so much else to do).

### 4.3 State Persistence (Passing the Baton)

Subtasks don't share conversation context. Use the filesystem:
- **Producer subtask**: In `initial_hint`, instruct the AI to write results to a specific file (e.g., `step1_out.txt`).
- **Consumer subtask**: In `initial_hint`, instruct the AI to read that file before proceeding.

---

## 5. Best Practice: Common Fields

### 5.1 `completion_criteria`

**How criteria are evaluated:**

| Task type | Evaluation method |
|-----------|-------------------|
| `simple` / `long_running` | AI self-evaluates. Criteria must be **objectively verifiable by the AI**. |
| `nested` | Only the top-level `completion_criteria` determines overall pass/fail. |
| `looping` | No pass/fail evaluation. Done when all `repeat_count` iterations finish. |

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

### 5.2 `initial_hint`

Static context included on **every attempt** (first and retries alike).

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

### 5.3 `system_prompt_prefix`

Customizes the AI's persona, role, or task-specific instructions.

| Use case | Example |
|----------|---------|
| Domain expertise | `"You are a GPU performance engineer."` |
| Task-specific constraints | `"Never modify files in vendor/."` |
| Coding style | `"Follow Google C++ style guide."` |

> **Note:** `system_prompt_prefix` on a top-level `nested` or `looping` task is not supported — set it on individual subtasks instead.

### 5.4 `max_attempts`

| Value | When to use |
|-------|-------------|
| `1` | **Execution-only subtasks** that just run code written by a sibling (build, benchmark, test). If the command fails, the cause is in sibling code — retrying won't help. `max_attempts: 1` propagates failure immediately to the parent's failure analysis. |
| `2–3` | Moderately uncertain tasks with a constrained problem space. |
| `5` (default) | Complex code-writing tasks — open-ended changes, multi-file refactoring, optimization. |

**Do NOT** set `max_attempts: 1` on subtasks where the AI actively writes code — those benefit from multiple attempts with different strategies.

### 5.5 `model`

| Value | When to use |
|-------|-------------|
| `"default"` (or omit) | Complex reasoning: "Analyze profiling results and optimize kernel", "Debug and fix root cause" |
| `"lite"` | Straightforward execution: "Run `make test`", "Format code with black", "Run benchmark and save output" |
| Direct model name (e.g., `"claude-sonnet-4-20250514"`) | When a specific model is needed |

---

## 6. Retry and Failure Handling

### 6.1 Designing for Retry Resilience

When a subtask is retried, previous attempts may have modified files. The AI has summaries of previous attempts but **filesystem changes persist**.

**Guidelines:**
- **Mention cleanup in `initial_hint`** when a task modifies shared state:
  ```yaml
  initial_hint: |
    NOTE: If a previous attempt left partial changes, check the state of
    build/ and src/generated/ before starting.
  ```
- **Prefer append/overwrite patterns** over incremental mutations — writing a complete output file is naturally idempotent.
- **Use git as a safety net** in `initial_hint` when appropriate: "Run `git diff` first to check for unexpected changes."
- **Don't over-engineer for idempotency** — it's enough to make the AI *aware* that residual state may exist.

### 6.2 Defensive Task Design

When tasks depend on external tools or services:

- **In `completion_criteria`** — handle partial success explicitly:
  ```yaml
  # GOOD: acknowledges partial results
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

### 6.3 Subtask Failure in Nested/Looping Tasks

When a subtask fails, earlier subtasks may be retried with guidance.

- Design subtasks so failure can be diagnosed from output.
- Align subtask boundaries with logical checkpoints — retrying from step 2 or 3 should be meaningful.
- Avoid subtasks that silently fail — ensure errors are visible in output.

### 6.4 Looping Tasks: Record History

For iterative tasks (optimization, training), use git and documentation files to prevent the AI from repeating failed strategies across iterations:

- **Git commit after each successful iteration** — preserves progress and enables rollback.
- **Maintain an optimization log** — instruct the AI (via `initial_hint`) to append a summary after each iteration: what was tried, what worked, what failed, and why. This prevents the AI from re-attempting the same failed approach in the next loop.

```yaml
initial_hint: |
  After each iteration, append a summary to optimization_log.md:
  - What optimization was attempted
  - Results (speedup, correctness)
  - Why it succeeded or failed
  Read this log at the start of each iteration to avoid repeating failed strategies.
```

---

## 7. YAML Examples

A complete `todos.yaml` for a realistic CUDA kernel optimization project. Note how each subtask explicitly states what files it writes and reads, ensuring information flows correctly across context-isolated sessions.

```yaml
description: |
  Optimize the cuFFTDx-based 3D DCT kernel for maximum throughput.
  The project uses CMake + CUDA 12, targets an RTX 4090.

  Reference: See docs/cufftdx_api.md for the cuFFTDx API reference.

  Architecture:
    - cufftdx_dct3d.cuh: Core DCT/IDCT kernel implementations
    - main.cpp: Benchmark entry point (runs 100 iterations, prints Score and Elapsed)
    - CMakeLists.txt: Build configuration (cmake -B build -DCMAKE_BUILD_TYPE=Release)

  Constraints:
    - Must maintain Score 100/100 on the correctness test at all times.
    - Do NOT modify the Score calculation logic in main.cpp.

tasks:
  # Task 1: Build and establish baseline
  # Writes: baseline.txt (timing value for later comparison)
  - id: 1
    name: "Build project and record baseline performance"
    type: simple
    model: "lite"
    completion_criteria: |
      1. Project builds: cmake --build build --config Release succeeds.
      2. Benchmark runs and prints "Score: 100/100".
      3. Elapsed time recorded in baseline.txt (format: "150.00").
    initial_hint: |
      Build: cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --config Release
      Run: ./build/bin/benchmark
      Save the Elapsed value (just the number) to baseline.txt.

  # Task 2: Iterative optimization — nested because the goal is
  # "achieve 20% speedup" (a target), not "do N rounds"
  # Reads: baseline.txt (from Task 1)
  # Writes: optimization_result.txt (per-round results)
  - id: 2
    name: "Optimize kernel to achieve >= 20% speedup"
    type: nested
    max_attempts: 10
    completion_criteria: |
      Speedup >= 20% compared to the value in baseline.txt,
      while maintaining Score 100/100.
    subtasks:
      # Subtask 2.1: Profile
      # Reads: (current binary)
      # Writes: ncu_analysis.txt (profiling findings for subtask 2.2)
      - id: 2.1
        name: "Profile kernel with ncu"
        type: long_running
        model: "lite"
        system_prompt_prefix: |
          You are a GPU performance engineer. Focus on memory throughput,
          occupancy, and warp efficiency metrics.
        completion_criteria: |
          ncu profiling completed and key findings saved to ncu_analysis.txt.
        initial_hint: |
          Run ncu on the benchmark binary. Write a structured analysis to
          ncu_analysis.txt covering: SM occupancy, memory throughput,
          compute throughput, and top bottlenecks.

      # Subtask 2.2: Analyze + implement + build + test (grouped)
      # Reads: ncu_analysis.txt (from 2.1), baseline.txt (from Task 1),
      #         optimization_log.md (history from previous rounds)
      # Writes: optimization_result.txt (speedup and score)
      - id: 2.2
        name: "Implement optimization, build, and benchmark"
        type: simple
        completion_criteria: |
          1. Optimization applied based on ncu_analysis.txt findings.
          2. Project builds without errors.
          3. Score: 100/100 (correctness preserved).
          4. Results written to optimization_result.txt:
             baseline, current elapsed, speedup percentage.
        initial_hint: |
          FIRST read optimization_log.md to see what has been tried before.
          Do NOT attempt optimizations that were previously rolled back.
          Then read ncu_analysis.txt for profiling findings.
          Read baseline.txt for the baseline timing.
          After implementing changes, build and run the benchmark.
          If Score < 100, fix correctness before reporting.
          Write results to optimization_result.txt.

      # Subtask 2.3: Git commit if improved, rollback if not + record history
      # Reads: optimization_result.txt (from 2.2)
      # Writes: optimization_log.md (append), baseline.txt (update)
      - id: 2.3
        name: "Commit or rollback, and record to optimization log"
        type: simple
        model: "lite"
        max_attempts: 1
        completion_criteria: |
          1. If speedup > 0%: changes committed with descriptive message.
          2. If no improvement: changes rolled back with git checkout.
          3. baseline.txt updated to reflect current best timing.
          4. Summary appended to optimization_log.md.
        initial_hint: |
          Read optimization_result.txt for speedup percentage.
          If positive: git add -A && git commit -m "perf: <description> - X% speedup"
          If not: git checkout -- cufftdx_dct3d.cuh
          Update baseline.txt with the new best timing.
          Append a summary to optimization_log.md:
            - What optimization was attempted
            - Results (speedup %, correctness score)
            - Whether committed or rolled back, and why
```

---

## 8. Quick Reference

| Rule | Details |
|------|---------|
| Always include root `description` | Explain the goal, constraints, and technical stack |
| Required fields | `id`, `name`, `type`, `completion_criteria` |
| `*_once` types | Subtask only — use sparingly |
| `completion_criteria` | Must be specific, measurable, verifiable |
| `model: "lite"` | For simple execution tasks |
| `model: "default"` | For complex reasoning tasks |
| Persist intermediate results | Write to files, not AI memory |
| `max_attempts: 1` | For execution-only subtasks (build, benchmark) |
| Subtask boundaries | Align with logical checkpoints and independent failure modes |
| Don't over-decompose | 2–3 subtasks usually suffice; merge steps that succeed/fail together |
