# Task Design Guide for AI Agents

Reference for AI agents that generate TODO tasks.

---

## 1. Rules

⚠️ **These rules are mandatory.** Verify every item before submitting your `todos.yaml`.

### Schema Rules

1. **Root `description`** exists and covers: Goal, Architecture, Key file paths, Hard constraints, Rules. See §3 for full guidance.
2. **Every task** has `id`, `name`, `type`, `completion_criteria`.
3. **ID assignment**: top-level IDs are sequential integers; subtask IDs use dot notation (e.g., 1.1, 1.2).
4. **`*_once` types** (`simple_once`, `long_running_once`) can ONLY be subtasks, not top-level tasks.
5. **`long_running`** is used for any command that may take > 1 minute.

### Design Rules

6. **`completion_criteria`** are specific, measurable, and verifiable by the AI — not vague like "code is good". See §4.2.
7. **`initial_hint`** provides key file paths, commands, and constraints — not a rigid step-by-step script. See §4.3.
8. **No over-decomposition**: subtasks are grouped by failure mode, not by individual commands (2–3 subtasks typical). See §4.1.
9. **No under-decomposition**: expensive steps (training, build) are separate from cheap steps (evaluation, reporting). See §4.1.
10. **`max_attempts: 1`** is set on execution-only subtasks (build, benchmark, test) that don't write code. See §6.2.
11. **`model: "lite"`** is set on straightforward execution tasks; complex reasoning uses default. See §6.3.
12. **State persistence**: inter-subtask data is written to files, not assumed in conversation context. See §4.6.
13. **Retry resilience**: tasks that modify shared state mention cleanup in `initial_hint`. See §4.5.
14. **Subtask boundaries** align with logical checkpoints and independent failure modes.
15. **Type-specific patterns**: read the relevant guide in §7 for your task type (build, test, optimization, etc.).

### Anti-Hack Rules

16. **Negative constraints**: For every "implement X" task, explicitly state what must NOT be modified (test files, configs, unrelated modules).
17. **Verification separation**: Separate "implement" from "verify" into different subtasks. Use `system_prompt_prefix` on verification subtasks to forbid code modification.
18. **Measurable criteria only**: Every `completion_criteria` must be checkable by running a command or reading a file — never subjective ("code is clean", "well-optimized").
19. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.

---

## 2. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through a sequence of tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

| Property | Implication for task design |
|----------|-----------------------------|
| **Fully autonomous** | No human in the loop. `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification. |
| **Context window limit** | Avoid tasks requiring extremely large files/outputs in a single step. |
| **No shared conversation context between tasks and subtasks** | Tasks and subtasks **share the filesystem only**. Each subtask automatically receives a workflow overview and a summary of the previous step, but **detailed intermediate results must be persisted to files** — conversation context is NOT shared. |
| **Sequential execution** | Top-level tasks run in ascending ID order. Task N+1 starts only after task N completes or exhausts retries. |
| **Failed tasks don't block** | A failed task does NOT prevent subsequent tasks from running. Later tasks may depend on artifacts produced by earlier tasks. Design ordering carefully. |

---

## 3. Root Description Guide

The root-level `description` field provides project-wide context visible to every AI session. **Always include it.** Without it, the AI has no overall project context.

### Components

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

### Which Components for Which Project Type

Not every project needs every component:

| Scenario | Typical components | Notes |
|----------|-------------------|-------|
| **Iterative optimization** (perf tuning, ML training) | All of the above | Naming conventions + historical references are critical to avoid repeating failed experiments |
| **Build & ship** (implement a feature, fix bugs) | Goal, Architecture, Key file paths, Key commands, Hard constraints, Rules | Usually no iteration history; naming conventions only if generating artifacts |
| **One-shot generation** (scaffold a project, generate configs) | Goal, Architecture, Key file paths, Hard constraints, Rules | Minimal — focus on what to generate and what not to touch |
| **Data pipeline / ETL** | Goal, Architecture, Key file paths, Key commands, Hard constraints, Rules | Emphasize file paths (input/output dirs) and commands (run pipeline, validate) |
| **Research / exploration** (read code, write analysis) | Goal, Architecture, Key file paths, Reference docs, Rules | No build commands; emphasize reference docs and where to write findings |

See the [Complete Example](#8-complete-example) at the end of this document for a full `description` demonstration.

---

## 4. Design Principles

💡 **These are best practices you should follow.** They represent lessons learned from real-world task execution.

### 4.1 Task Decomposition

#### Choosing the Right Structure

| Scenario | Recommended structure |
|----------|-----------------------|
| Single logical step (fix a bug, add validation, run tests) | Single `simple` task |
| Multi-step workflow where the goal is **achieving a target** | `nested` task |
| Iterative cycle where the goal is **running N rounds of experimentation** | `looping` task |
| One step within a workflow is itself multi-step | Nested subtask (`nested`/`looping` as subtask type) |

**`nested` vs `looping`:**
- Use `nested` when the core goal is **reaching a specific end state** (e.g., "achieve 20% speedup", "all tests pass"). The AI evaluates the overall `completion_criteria` after each round and can stop early or retry intelligently.
- Use `looping` when the core goal is **performing N rounds of work** (e.g., "do 5 rounds of optimization", "run 3 experiments with different configs"). There is no AI evaluation of overall completion — it simply repeats for `repeat_count` iterations.

#### Anti-Patterns

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

### 4.5 Retry and Failure Handling

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

**Defensive task design** — when tasks depend on external tools or services:

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

**Subtask failure in nested/looping tasks:**
- Design subtasks so failure can be diagnosed from output.
- Align subtask boundaries with logical checkpoints — retrying from step 2 or 3 should be meaningful.
- Avoid subtasks that silently fail — ensure errors are visible in output.

### 4.6 State Persistence (Passing the Baton)

Subtasks don't share conversation context. Use the filesystem:
- **Producer subtask**: In `initial_hint`, instruct the AI to write results to a specific file (e.g., `step1_out.txt`).
- **Consumer subtask**: In `initial_hint`, instruct the AI to read that file before proceeding.

---

## 5. Schema Reference

📖 **Reference section — consult as needed.** You don't need to read this top-to-bottom; look up specific types and fields when designing tasks.

### 5.1 Task Types

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
- **Looping iteration failure stops the loop**: If any single iteration fails after exhausting its retry attempts, the remaining iterations are NOT executed. Design subtask `completion_criteria` to be tolerant of partial or unexpected results if you want the loop to continue through difficult iterations.
- **Nested subtasks**: `nested`/`looping` can be used as subtask types for multi-level nesting. Keep nesting shallow (2–3 levels max).

### 5.2 Root-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | **Yes** | Project-level description: goal, architecture, constraints, key paths. See §3. |
| `tasks` | list | Yes | Ordered list of top-level task definitions |

### 5.3 Common Fields (all types)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int/float | Yes | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name` | string | Yes | Concise, descriptive task name |
| `type` | string | Yes | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
| `completion_criteria` | string | Yes | Clear, specific, measurable success criteria |
| `description` | string | No | Task-specific description. In AI scheduling mode, the scheduler uses this to understand the task — recommended to fill in. |
| `model` | string | No | `"default"`, `"lite"`, or a direct model name. `"default"` will be used if not specified |
| `system_prompt_prefix` | string | No | Custom AI persona/instructions for this task (see §6.1) |

### 5.4 Type-Specific Fields

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

### 5.5 Hierarchy and ID Rules

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

## 6. Field Usage Guide

📖 **Reference section** for `system_prompt_prefix`, `max_attempts`, and `model` fields.

### 6.1 `system_prompt_prefix`

Customizes the AI's persona, role, or task-specific instructions.

| Use case | Example |
|----------|---------|
| Domain expertise | `"You are a GPU performance engineer."` |
| Task-specific constraints | `"Never modify files in vendor/."` |
| Coding style | `"Follow Google C++ style guide."` |
| **Restrict behavior** (execution-only subtasks) | `"You are a benchmark runner. Do NOT modify any source code."` |

Using `system_prompt_prefix` to restrict behavior is especially useful for execution-only subtasks (build, benchmark, data export) where you want to prevent the AI from "helpfully" editing code when a command fails — the failure should propagate to the parent for proper failure analysis instead.

> **Note:** `system_prompt_prefix` on a top-level `nested` or `looping` task is not supported — set it on individual subtasks instead.

### 6.2 `max_attempts`

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

### 6.3 `model`

| Value | When to use |
|-------|-------------|
| `"default"` (or omit) | Complex reasoning: "Analyze profiling results and optimize kernel", "Debug and fix root cause" |
| `"lite"` | Straightforward execution: "Run `make test`", "Format code with black", "Run benchmark and save output" |
| Direct model name (e.g., `"claude-sonnet-4-20250514"`) | When a specific model is needed |

---

## 7. Task-Type-Specific Best Practices

📖 **Read only the guide relevant to your task** — you don't need to read all of them.

| Task type | Guide | When to use |
|-----------|-------|-------------|
| **Build & Ship** | `build_and_ship.md` | Implement features, fix bugs, refactor code |
| **Testing & Verification** | `testing_and_verification.md` | Run tests, fix failures, improve coverage |
| **Iterative Optimization** | `iterative_optimization.md` | Profiling → optimize → benchmark → evaluate cycles |
| **Data Pipelines / ETL** | `data_pipelines.md` | Extract, transform, load, and validate data |
| **Setup & Deployment** | `setup_and_deployment.md` | Environment setup, dependency install, deployment |
| **Research & Analysis** | `research_and_analysis.md` | Code analysis, architecture review, report writing |

---

## 8. Complete Example

Below is a concise `todos.yaml` demonstrating key patterns: root `description`, task types (`simple`, `long_running`, `looping`), `completion_criteria`, `initial_hint`, `system_prompt_prefix`, `model` selection, and `max_attempts`.

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

tasks:
  # ── Task 1: Establish Baseline ────────────────────────────────────────
  - id: 1
    name: "Build, test, and establish performance baseline"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. cargo test --all passes (exit code 0)
      2. doc/optimization_results.tsv exists with a baseline row
      3. Baseline p95 latency is recorded
    subtasks:
      - id: 1.1
        name: "Build and run tests"
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
        name: "Run baseline benchmark and record results"
        type: long_running
        model: lite
        completion_criteria: |
          1. k6 benchmark completed successfully
          2. doc/optimization_results.tsv created with baseline row
        initial_hint: |
          Run: k6 run benchmarks/load_test.js --out json=results.json
          Parse results.json for p95 latency, create optimization_results.tsv.

  # ── Task 2: Iterative Optimization Loop ───────────────────────────────
  - id: 2
    name: "Iterative API performance optimization"
    type: looping
    repeat_count: 5
    max_attempts_per_loop: 3
    completion_criteria: |
      One complete cycle of: analyze → implement → benchmark → evaluate.
    subtasks:
      - id: 2.1
        name: "Analyze bottleneck and propose optimization"
        type: simple
        system_prompt_prefix: |
          You are a backend performance engineer specializing in Rust async services.
        completion_criteria: |
          1. Bottleneck identified and documented in doc/optimization_log.md
          2. Proposed optimization does not violate hard constraints
        initial_hint: |
          Read doc/optimization_results.tsv for current metrics.
          Read doc/optimization_log.md for past experiments (avoid repeating failures).
          Identify the current bottleneck, propose one focused optimization.

      - id: 2.2
        name: "Implement optimization, build, and test"
        type: simple
        completion_criteria: |
          1. Code changes implemented (minimal, focused)
          2. cargo build --release succeeds
          3. cargo test --all passes
          4. Changes committed: git commit -m "opt: <description>"
        initial_hint: |
          Read doc/optimization_log.md for the latest proposed optimization.
          Implement it, build, test. If tests fail, fix or revert.

      - id: 2.3
        name: "Benchmark and evaluate"
        type: simple
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. Benchmark completed, new row appended to optimization_results.tsv
          2. If regression > 5%: git revert HEAD, record as "reverted"
          3. If improvement: record as "kept"
          4. doc/optimization_log.md updated with results
        initial_hint: |
          Run: k6 run benchmarks/load_test.js --out json=results.json
          Compare p95 with previous best in optimization_results.tsv.
          Keep if improved, revert if regressed. Update docs either way.
```
