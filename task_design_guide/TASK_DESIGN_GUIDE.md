# Task Design Guide for AI Agents

Reference for AI agents that generate TODO tasks.

---

## 1. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through a sequence of tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

| Property | Implication for task design |
|----------|---------------------------|
| **Fully autonomous** | No human in the loop. `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification. |
| **Context window limit** | Avoid tasks requiring extremely large files/outputs in a single step. |
| **No shared conversation context between tasks and subtasks** | Tasks and subtasks **share the filesystem only**. Each subtask automatically receives a workflow overview and a summary of the previous step, but **detailed intermediate results must be persisted to files** — conversation context is NOT shared. |
| **Sequential execution** | Top-level tasks run in ascending ID order. Task N+1 starts only after task N completes or exhausts retries. |
| **Failed tasks don't block** | A failed task does NOT prevent subsequent tasks from running. Later tasks may depend on artifacts produced by earlier tasks. Design ordering carefully. |

---

## 2. Task Types

### Overview

| Type | Description | Scope | When to use |
|------|-------------|-------|-------------|
| `simple` | AI works autonomously, then self-evaluates completion | Top-level or subtask | Code changes, running tests, file analysis, quick builds |
| `nested` | Sequential subtasks + AI evaluation of overall completion; When fails consecutively, retries with guidance | Top-level or subtask | Multi-step workflows where overall success depends on combined result |
| `looping` | Repeat all subtasks for fixed N iterations; NO AI evaluation for overall completion | Top-level or subtask | Iterative optimization cycles (profile → optimize → benchmark) |
| `long_running` | AI launches a long-running background command (e.g. training) that runs without session timeout | Top-level or subtask | Any command that may take > 1 minute (builds, tests, benchmarks, training, profiling) |
| `simple_once` | Like `simple`, but never re-executed once completed | Subtask only | One-time setup (env prep, dependency install, data download) |
| `long_running_once` | Like `long_running`, but never re-executed once completed | Subtask only | Expensive one-time operations (Docker build, baseline profiling) |

### Key Notes

- **Prefer `long_running` over `simple`** for any command that may take > 1 minute. If a command runs too long inside `simple`, the AI session may hit a timeout, wasting all progress. `long_running` runs the command in the background with proper monitoring — minimal overhead, prevents session timeouts.
- **`*_once` types**: Use sparingly. Most subtasks SHOULD be re-executable. Don't use `*_once` if a subtask's output might become stale after other subtasks run. Use `long_running_once` instead of `long_running` when the command is **idempotent setup** (e.g., Docker build, baseline profiling) that should survive retries of later subtasks.
- **Looping iteration failure stops the loop**: If any single iteration fails after exhausting its retry attempts, the remaining iterations are NOT executed. Design subtask `completion_criteria` to be tolerant of partial or unexpected results if you want the loop to continue through difficult iterations.
- **Nested subtasks**: `nested`/`looping` can be used as subtask types for multi-level nesting. Keep nesting shallow (2–3 levels max).

---

## 3. Task Schema Reference

### 3.1 Root-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | **Yes** | Project-level description: goal, architecture, constraints, key paths |
| `tasks` | list | Yes | Ordered list of top-level task definitions |

> **Important:** Always include `description`. Without it, the AI has no overall project context. A good `description` may cover:

| Component | Purpose | Example | When needed |
|-----------|---------|---------|-------------|
| **Goal** | What the project is trying to accomplish | "Iteratively optimize GPU compute shaders for minimum latency" | Always |
| **Architecture** | Directory structure and key modules, so the executor AI knows where to find things | "src/shaders — HLSL shaders, src/frame_processor.cpp — GPU dispatch logic" | Always |
| **Key file paths** | Frequently referenced paths: configs, output files, data files | "Config: configs/base.yaml, Results: optimization_results.tsv" | Always (even if short) |
| **Key commands** | Build, test, and validation commands the AI will run repeatedly | "Build: cmake --build build --config Release, Test: build/Release/Simulator.exe" | When the project has build/test/run commands |
| **Architecture notes** | Key technical coupling points where changes in one place require syncing another | "Modifying shader thread group size requires syncing Dispatch() call" | When the codebase has non-obvious cross-file dependencies |
| **Hard constraints** | Things the executor AI must NEVER do or change | "Must maintain correctness score 100/100; never modify resource/ data files" | Always |
| **Rules** | Behavioral rules that apply to every task in this project | "One experiment per round; If you find a bug, fix ONLY the bug." | Always |
| **Naming conventions** | File/branch naming rules so the AI can derive names programmatically | "Docs named by branch number N: optimization_results_N.tsv" | When the project generates numbered/templated files across iterations |
| **Historical references** | Past work the AI should consult to avoid repeating failures | "doc/optimization_report_*.md — previous branch reports" | When the project runs across multiple branches/iterations |
| **Reference docs** | Documentation the executor AI should read when it needs deeper understanding | "See docs/API.md for the REST interface spec" | When external/internal docs exist that the AI should consult on-demand |

> **Not every project needs every component.** The table below shows which components are typical for different project types:

| Scenario | Typical components | Notes |
|----------|-------------------|-------|
| **Iterative optimization** (perf tuning, ML training) | All of the above | Naming conventions + historical references are critical to avoid repeating failed experiments |
| **Build & ship** (implement a feature, fix bugs) | Goal, Architecture, Key file paths, Key commands, Hard constraints, Rules | Usually no iteration history; naming conventions only if generating artifacts |
| **One-shot generation** (scaffold a project, generate configs) | Goal, Architecture, Key file paths, Hard constraints, Rules | Minimal — focus on what to generate and what not to touch |
| **Data pipeline / ETL** | Goal, Architecture, Key file paths, Key commands, Hard constraints, Rules | Emphasize file paths (input/output dirs) and commands (run pipeline, validate) |
| **Research / exploration** (read code, write analysis) | Goal, Architecture, Key file paths, Reference docs, Rules | No build commands; emphasize reference docs and where to write findings |

```yaml
description: |
  ## Project: GPU Compute Shader Performance Optimization

  ### Goal
  Iteratively optimize DX12 GPU compute shaders for minimum latency
  while maintaining numerical correctness.

  ### Architecture
  - src/shaders/ — HLSL compute shaders (optimization targets)
  - src/frame_processor.cpp — GPU dispatch logic
  - src/test_reference.cpp — CPU reference implementation for correctness checks
  - doc/compute_shader_specs.md — documentation for per-stage specifications

  ### Key File Paths
  All paths are relative to the project root, the shell working directory.
  - Results log: doc/optimization_results_N.tsv (N = branch number from opt_<N>)
  - Experiment log: doc/optimization_log_N.md
  - Failure patterns: doc/failure_patterns.md

  ### Key Commands
  - Build: cmake --build build --config Release
  - Correctness test: build/Release/Simulator.exe (exit code 0 = GPU matches CPU reference)

  ### Naming Conventions
  - Optimization docs are named by branch number N (from branch name opt_<N>)
  - optimization_results_N.tsv — performance data table
  - optimization_log_N.md — experiment log
  - optimization_report_N.md — optimization report

  ### Historical Branch References
  - doc/ may contain optimization reports from previous branches (e.g., optimization_report_1.md)
  - These document all previously attempted optimizations (both kept and reverted)
  - New branches MUST reference these to avoid repeating reverted failures
  - Already-kept optimizations are in the baseline code; already-reverted ones should not be retried as-is

  ### Hard Constraints
  - Do NOT modify CPU-side post-processing logic in main.cpp
  - Do NOT modify resource/ binary data files
  - One optimization per experiment, keep changes minimal

  ### Architecture Notes
  - Shaders share a constant buffer register with stage-dependent semantics
  - When modifying shader thread group size, sync Dispatch() call in frame_processor.cpp
  - When modifying GPU buffers, sync resource_manager.cpp and shader register declarations
  - When changing shader algorithms, sync CPU reference in test_reference.cpp

  ### Reference Docs (read only when needed)
  - doc/pipeline_architecture.md — full pipeline overview
  - doc/optimization_report_*.md — previous optimization branch reports

  ### Rules
  - Fully autonomous — never ask the user questions
  - One optimization per experiment, keep changes minimal
  - If you discover a bug, fix ONLY the bug in that round (no optimization)
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

# GOOD: 3 subtasks with clear boundaries
subtasks:
  - id: 1.1
    name: "Analyze profiling report and compose an optimization idea"
    # AI reads the report, identifies the bottleneck, and formulates
    # a concrete optimization plan — but does NOT implement yet.
    # Thinking and coding are both high-intensity; separating them
    # lets the AI focus fully on analysis without rushing to code.
  - id: 1.2
    name: "Implement the optimization and build"
    # AI takes the idea from 1.1 and implements it. If build fails,
    # the AI can fix immediately without a costly failure_analysis
    # round-trip. Keeping implement + build together is key.
  - id: 1.3
    name: "Benchmark, validate, make keep/discard decision, and write report"
    max_attempts: 1    # fail fast → parent decides retry strategy
```

**Recommended pattern**: Group strongly dependent steps into one subtask, but **separate "thinking" from "doing"**:
- **"analyze + compose idea" vs "implement + build"** — both are high-intensity tasks. When combined, the AI tends to rush the analysis to get to coding, or take shortcuts in implementation because it spent too much context on analysis. Give each its own session.
- **"implement + build"** — if build fails, the AI can fix code immediately in the same session, saving a failure_analysis round-trip. These always belong together.
- **"benchmark + validate + report"** — evaluation is a distinct phase. Separating it lets you fail fast and retry from the implementation step without re-running analysis.

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

### 5.2 `initial_hint`

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

### 5.3 `system_prompt_prefix`

Customizes the AI's persona, role, or task-specific instructions.

| Use case | Example |
|----------|---------|
| Domain expertise | `"You are a GPU performance engineer."` |
| Task-specific constraints | `"Never modify files in vendor/."` |
| Coding style | `"Follow Google C++ style guide."` |
| **Restrict behavior** (execution-only subtasks) | `"You are a benchmark runner. Do NOT modify any source code."` |

Using `system_prompt_prefix` to restrict behavior is especially useful for execution-only subtasks (build, benchmark, data export) where you want to prevent the AI from "helpfully" editing code when a command fails — the failure should propagate to the parent for proper failure analysis instead.

> **Note:** `system_prompt_prefix` on a top-level `nested` or `looping` task is not supported — set it on individual subtasks instead.

### 5.4 `max_attempts`

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

## 7. Task-Type-Specific Best Practices

The patterns above (§6.1–6.3) apply universally. For detailed patterns tailored to specific task types, read the relevant guide:

| Task type | Guide | When to use |
|-----------|-------|-------------|
| **Build & Ship** | `build_and_ship.md` | Implement features, fix bugs, refactor code |
| **Testing & Verification** | `testing_and_verification.md` | Run tests, fix failures, improve coverage |
| **Iterative Optimization** | `iterative_optimization.md` | Profiling → optimize → benchmark → evaluate cycles |
| **Data Pipelines / ETL** | `data_pipelines.md` | Extract, transform, load, and validate data |
| **Setup & Deployment** | `setup_and_deployment.md` | Environment setup, dependency install, deployment |
| **Research & Analysis** | `research_and_analysis.md` | Code analysis, architecture review, report writing |

> **Note:** Read only the guide relevant to your task — you don't need to read all of them.

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
| Type-specific patterns | Read the relevant guide in §7 for your task type (build, test, optimization, etc.) |
