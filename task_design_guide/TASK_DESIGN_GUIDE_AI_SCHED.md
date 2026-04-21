# Task Design Guide — AI Scheduling Mode

Reference for AI agents that generate TODO tasks for AI-scheduled execution.

---

## 1. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through a sequence of tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

### 1.1 General Key Implications

| Property | Implication for task design |
|----------|-----------------------------|
| **Fully autonomous** | No human in the loop. `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification. |
| **Context window limit** | Avoid tasks requiring extremely large files/outputs in a single step. |
| **No shared conversation context between tasks and subtasks** | Tasks and subtasks **share the filesystem only**. Each subtask automatically receives a workflow overview and a summary of the previous step, but **detailed intermediate results must be persisted to files** — conversation context is NOT shared. |
| **Failed tasks don't block** | A failed task does NOT prevent subsequent tasks from running. Later tasks may depend on artifacts produced by earlier tasks. Design ordering carefully. |

### 1.2 Key Implications for AI Scheduling Mode

In AI scheduling mode, an AI scheduler dynamically decides which task to run each round, rather than executing tasks in fixed order.

| Property | Implication for task design |
|----------|-----------------------------|
| **Dynamic execution order** | The AI scheduler decides which task to run each round. **Tasks may run 0, 1, or many times**. |
| **Task dependencies via `strategy`** | Don't assume task N-1 ran before task N; use `strategy` to encode dependencies explicitly. |
| **Task description is critical — but keep it short** | The scheduler AI understands what each task does **only by** root-level `description` and task-specific `description` field. Keep descriptions informative but concise (1–3 sentences). The scheduler prompt includes **every** task's description simultaneously, so verbose descriptions accumulate and degrade scheduler performance. Move step-by-step details to `initial_hint`. |
| **`last_result` feeds execution outcomes to the scheduler** | Configure `last_result` per task so the scheduler can observe what happened. Without it, the scheduler only sees success/failure — not *what* was produced. See §4.3 for full details. |
| **Scheduler AI only decides top-level task** | The scheduler AI only decides **which top-level task** to run. It does NOT control subtask-level execution — subtasks within a selected task execute sequentially as defined. |

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
- **`*_once` subtasks survive re-scheduling**: In AI scheduling mode, `*_once` subtasks execute only once across ALL scheduling rounds. If the scheduler selects the same task again, `*_once` subtasks are skipped.
- **Looping iteration failure stops the loop**: If any single iteration fails after exhausting its retry attempts, the remaining iterations are NOT executed. Design subtask `completion_criteria` to be tolerant of partial or unexpected results if you want the loop to continue through difficult iterations.
- **Nested subtasks**: `nested`/`looping` can be used as subtask types for multi-level nesting. Keep nesting shallow (2–3 levels max).

---

## 3. Task Schema Reference

### 3.1 Root-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | **Yes** | Project-level description: goal, architecture, constraints, key paths |
| `ai_orchestrator` | object | **Yes** | AI scheduling configuration (see §4) |
| `tasks` | list | Yes | List of top-level task definitions |

> **Important:** Always include `description`. Without it, the AI has no overall project context. The root-level `description` is visible to **all AIs** — both the scheduler and every executor. This makes it the right place for project-wide context (goal, architecture, constraints, key paths) that every AI session needs. A good `description` may cover:

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

Conversely, a good `description` should **NOT** cover:

| Anti-pattern | Why | Where it belongs instead |
|--------------|-----|--------------------------|
| **Scheduling strategy** (e.g. "run task 2 before task 3", "this is a two-phase project") | Only the scheduler AI needs this; including it in `description` leaks scheduling concerns to executor AIs that cannot act on them | `ai_orchestrator.strategy` field (scheduler-only prompt) |
| **Task execution order or phasing** (e.g. "Phase 1 is setup, Phase 2 is optimization") | Executors don't need to know the overall schedule — they only see their own task | `ai_orchestrator.strategy` or task-level `description` |
| **Step-by-step implementation details** for a specific task | Overly detailed instructions in the project description distract other tasks' executors | Task-level `initial_hint` (executor-only) |
| **Scheduler behavioral rules** (e.g. "never run the same task twice in a row") | These are scheduling constraints, not project context | `ai_orchestrator.strategy` |

> **Rule of thumb:** If the information is only useful to the scheduler (scheduling order, phasing, task dependencies), put it in `ai_orchestrator.strategy`. If it's only useful to one task's executor (step-by-step details), put it in that task's `initial_hint`. The root `description` is for **shared project context** that every AI benefits from.

See the [Complete Example](#11-complete-example) at the end of this document for a full `description` demonstration.

### 3.2 Common Fields (all types)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | int/float | Yes | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name` | string | Yes | Concise, descriptive task name |
| `type` | string | Yes | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
| `description` | string | **Yes** | What this task does and produces (1–3 sentences). The scheduler uses this for decisions. |
| `completion_criteria` | string | Yes | Clear, specific, measurable success criteria |
| `model` | string | No | `"default"`, `"lite"`, or a direct model name. `"default"` will be used if not specified |
| `system_prompt_prefix` | string | No | Custom AI persona/instructions for this task (see §6.3) |

> **task-specific `description` is critical in AI scheduling mode.** It's the **only way** the scheduler AI understands what a task does — the scheduler sees `id`, `name`, `type`, `description`, execution count, and last result, nothing else.
>
> ⚠️ **Keep each task's `description` short (1–3 sentences).** The scheduler prompt concatenates the descriptions of **all** tasks into a single context window. If individual descriptions are long, the combined prompt becomes bloated, wastes tokens, and degrades the scheduler's decision quality. This is especially problematic for projects with many tasks.
>
> - State what the task does and what it produces (1–3 sentences)
> - Mention the key output artifact if relevant
> - **Don't include execution steps or implementation details** — those belong in `initial_hint` (which only the executor sees)
> - Don't write multi-paragraph essays — every extra sentence is multiplied by the number of tasks in the scheduler prompt
>
> ```yaml
> 
> # GOOD
> description: |
>   Build the project, verify correctness, and run ncu profiling to
>   establish baseline performance metrics. Produces baseline_profile.txt.
>
> # BAD: too detailed — belongs in initial_hint
> description: |
>   First run cmake -B build, then cmake --build build --config Release,
>   then run ncu --set full --csv ./main.exe > baseline_profile.txt...
>
> # BAD: too vague — scheduler can't make informed decisions
> description: "Run some tests"
> ```

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

## 4. `ai_orchestrator` Configuration

### 4.1 Schema

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

### 4.2 Field Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `strategy` | string | **Yes** | — | Scheduling rules. The scheduler AI reads this verbatim. |
| `max_rounds` | int | No | 50 | Hard cap on scheduling rounds |
| `stop_condition` | string | No | `""` | When to stop. Shown to the scheduler AI. |
| `last_result` | dict | No | `{}` | Per-task result configuration (see §4.3) |
| `max_attempts` | int | No | config default | Maximum retry count for scheduler decisions |

### 4.3 `last_result`

Configures how each task's outcome is surfaced to the scheduler in subsequent rounds.

| Type | What the scheduler sees | When to use |
|------|------------------------|-------------|
| `file` | Contents of the specified file(s) | **`looping` tasks** (which produce cumulative results best captured in a file), or any task that **explicitly produces an output file** (benchmarks, test results) |
| `response` | Auto-saved AI final response | `simple` tasks (default choice); `nested` tasks where the **last subtask is a summary/analysis step** |
| `none` | Nothing (success/failure still visible in history) | Setup/infrastructure tasks with no meaningful output |

**Important**: `last_result` keys are top-level task IDs (integers), not subtask IDs. This is consistent with AI scheduler's responsibility —— It only schedules top-level tasks, not subtasks.

#### 4.3.1 `type: response` behavior

The system auto-saves the AI's final response from the last execution unit:
- **Simple task**: The task's AI response
- **Nested task**: The last actually-executed subtask's AI response
- **Looping task**: The last iteration's last subtask's AI response (which also implies that type: response is not suitable for looping tasks)

#### 4.3.2 `type: file` syntax

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

#### 4.3.3 Key decision rules

1. **Single-layer `simple` task** → prefer `type: response`. The AI's final answer naturally summarizes what happened.
2. **`nested` task** → `type: response` works well, but the **last subtask must be summary-oriented** (the system saves the last-executed subtask's response). If the last subtask is a build/run step with no useful prose, use `type: file` instead.
3. **`looping` task** or any task that **explicitly writes a result file** → prefer `type: file`. Point `path` at the file the task produces.
4. **Setup tasks** → `type: none`. The scheduler already sees success/failure in the history.

**Key insight:** If the scheduler's `strategy` references a task's output to make decisions (e.g., "if speedup >= 20%"), that task **must** have a `last_result` configured — otherwise the scheduler is flying blind.

---

### 4.4 `strategy` — Encoding Scheduling Logic

The `strategy` field is injected verbatim into the scheduler AI's prompt. It encodes the decision rules that govern task selection.

#### 4.4.1 Writing Effective Strategies

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

When writing `strategy`, remember the scheduler AI has access to:

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

### 4.5 `stop_condition` — When to Stop

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

## 5. Best Practice: Task Decomposition

### 5.1 Choosing the Right Structure

| Scenario | Recommended structure |
|----------|-----------------------|
| Single logical step (fix a bug, add validation, run tests) | Single `simple` task |
| Multi-step workflow where the goal is **achieving a target** | `nested` task |
| Iterative cycle where the goal is **running N rounds of experimentation** | `looping` task |
| One step within a workflow is itself multi-step | Nested subtask (`nested`/`looping` as subtask type) |

**`nested` vs `looping`:**
- Use `nested` when the core goal is **reaching a specific end state** (e.g., "achieve 20% speedup", "all tests pass"). The AI evaluates the overall `completion_criteria` after each round and can stop early or retry intelligently.
- Use `looping` when the core goal is **performing N rounds of work** (e.g., "do 5 rounds of optimization", "run 3 experiments with different configs"). There is no AI evaluation of overall completion — it simply repeats for `repeat_count` iterations.

### 5.2 Anti-Patterns

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

### 5.3 Task Granularity for AI Scheduling

In AI scheduling mode, each top-level task represents a **logical unit of work** that the scheduler can independently select. Design tasks at the right granularity:

| Granularity | Example | Verdict |
|-------------|---------|---------|
| Too coarse | "Do everything: setup, optimize, test, report" | ❌ Scheduler has no control |
| Right level | "Run one optimization round" | ✅ Scheduler can repeat or skip |
| Too fine | "Edit line 42 of kernel.cu" | ❌ Scheduler shouldn't micromanage |

**Rule of thumb:** Each task should be a complete, self-contained action that produces a meaningful result the scheduler can evaluate.

### 5.4 Task Independence

Tasks should be as independent as possible:
- Each task should be runnable without assuming a specific prior task ran in the same round
- Use `strategy` to encode ordering constraints, not implicit assumptions
- Persist all inter-task communication to files (referenced in `last_result`)

### 5.5 Result-Driven Design

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

### 5.6 State Persistence (Passing the Baton)

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

## 6. Best Practice: Common Fields

### 6.1 `completion_criteria`

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

### 6.2 `initial_hint`

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

### 6.3 `system_prompt_prefix`

Customizes the AI's persona, role, or task-specific instructions.

| Use case | Example |
|----------|---------|
| Domain expertise | `"You are a GPU performance engineer."` |
| Task-specific constraints | `"Never modify files in vendor/."` |
| Coding style | `"Follow Google C++ style guide."` |
| **Restrict behavior** (execution-only subtasks) | `"You are a benchmark runner. Do NOT modify any source code."` |

Using `system_prompt_prefix` to restrict behavior is especially useful for execution-only subtasks (build, benchmark, data export) where you want to prevent the AI from "helpfully" editing code when a command fails — the failure should propagate to the parent for proper failure analysis instead.

> **Note:** `system_prompt_prefix` on a top-level `nested` or `looping` task is not supported — set it on individual subtasks instead.

### 6.4 `max_attempts`

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

### 6.5 `model`

| Value | When to use |
|-------|-------------|
| `"default"` (or omit) | Complex reasoning: "Analyze profiling results and optimize kernel", "Debug and fix root cause" |
| `"lite"` | Straightforward execution: "Run `make test`", "Format code with black", "Run benchmark and save output" |
| Direct model name (e.g., `"claude-sonnet-4-20250514"`) | When a specific model is needed |

---

## 7. Retry and Failure Handling

### 7.1 Designing for Retry Resilience

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

### 7.2 Defensive Task Design

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

### 7.3 Subtask Failure in Nested/Looping Tasks

When a subtask fails, earlier subtasks may be retried with guidance.

- Design subtasks so failure can be diagnosed from output.
- Align subtask boundaries with logical checkpoints — retrying from step 2 or 3 should be meaningful.
- Avoid subtasks that silently fail — ensure errors are visible in output.

## 8. Task-Type-Specific Best Practices

The patterns above apply universally. For detailed patterns tailored to specific task types, read the relevant guide:

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

## 9. Checklist
Use this checklist to verify your `todos.yaml` before submission:

- [ ] **Root `description`** exists and covers: Goal, Architecture, Key file paths, Hard constraints, Rules
- [ ] **`ai_orchestrator`** is configured with `strategy` (and optionally `stop_condition`, `max_rounds`, `last_result`)
- [ ] **`strategy`** references task IDs by name, encodes dependencies, and includes failure recovery rules
- [ ] **`last_result`** is configured for every task whose output the scheduler needs to make decisions
- [ ] **Every task** has `id`, `name`, `type`, `description`, `completion_criteria`
- [ ] **Task-specific `description`** is 1–3 sentences explaining what the task does and produces (scheduler-facing)
- [ ] **`completion_criteria`** are specific, measurable, and verifiable by the AI (not vague like "code is good")
- [ ] **`initial_hint`** provides key file paths, commands, and constraints — not a rigid step-by-step script
- [ ] **No over-decomposition**: subtasks are grouped by failure mode, not by individual commands (2–3 subtasks typical)
- [ ] **No under-decomposition**: expensive steps (training, build) are separate from cheap steps (evaluation, reporting)
- [ ] **`long_running`** is used for any command that may take > 1 minute
- [ ] **`max_attempts: 1`** is set on execution-only subtasks (build, benchmark, test) that don't write code
- [ ] **`model: "lite"`** is set on straightforward execution tasks; complex reasoning uses default
- [ ] **`*_once` types** are used only for true one-time setup that should survive retries
- [ ] **State persistence**: inter-subtask data is written to files, not assumed in conversation context
- [ ] **Retry resilience**: tasks that modify shared state mention cleanup in `initial_hint`
- [ ] **ID assignment**: top-level IDs are sequential integers; subtask IDs use dot notation (e.g., 1.1, 1.2)
- [ ] **Task independence**: each top-level task is self-contained; ordering is encoded in `strategy`, not assumed
- [ ] **Subtask boundaries** align with logical checkpoints and independent failure modes
- [ ] **Use `${workspace}` in file paths** within `last_result` (auto-expanded at runtime)
- [ ] **Max ~5–8 top-level tasks** — more bloats the scheduler prompt
- [ ] **Design for re-execution**: tasks may run 0, 1, or many times
- [ ] **Scheduler observables**: design around what the scheduler can see (description, execution count, last result, history)
- [ ] **`stop_condition`** is specific, measurable, and includes a fallback
- [ ] **Type-specific patterns**: read the relevant guide in §8 for your task type (build, test, optimization, etc.)

---

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
