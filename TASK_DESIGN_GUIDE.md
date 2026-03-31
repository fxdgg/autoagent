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
- Within a single subtask, the AI session is NOT reset between retry
  attempts — the AI retains conversation history across retries of the
  same subtask.
- The AI's persona/role can be customized per-task via the
  `system_prompt_prefix` field in `todos.yaml` (see §12 below).

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

**Scope:** Top-level only.

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

**Scope:** Top-level only.

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
1. AutoAgent sends a prompt telling the AI to use `autoagent-exec` to
   launch the command in the background.
2. The AI runs: `python autoagent_exec.py --log-dir <dir> --task-id <id> -- <command>`
3. `autoagent-exec` implements a **fast-fail** mechanism (default 10 seconds, configurable via `fast_fail_timeout` in `config.yaml`):
   - If the command exits within the timeout with an error → error shown immediately,
     AI can fix and retry.
   - If the command exits within the timeout with success → treated as completed.
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

### 3.1 Common Fields (all types)

| Field                | Type   | Required | Description                                    |
|----------------------|--------|----------|------------------------------------------------|
| `id`                 | int/float | Yes   | Unique ID. Integer for top-level, dot notation for subtasks (e.g., `1.1`) |
| `name`               | string | Yes      | Concise, descriptive task name                 |
| `type`               | string | Yes      | `simple`, `nested`, `looping`, `long_running`, `simple_once`, or `long_running_once` |
| `completion_criteria` | string | Yes     | Clear, specific, measurable success criteria   |
| `model`              | string | No       | `"default"`, `"simple"`, or a direct model name. Default: `"default"` |
| `system_prompt_prefix` | string | No    | Custom AI persona/instructions for this task (see §12) |

### 3.2 Type-Specific Fields

**simple / simple_once:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `initial_hint` | string | No       | Context/guidance for the AI on first attempt |

**nested:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `subtasks`     | list   | Yes      | Ordered list of subtasks (simple, long_running, simple_once, or long_running_once) |
| `max_attempts` | int    | No       | Max retry rounds (default: 20)           |

**looping:**

| Field                   | Type | Required | Description                          |
|-------------------------|------|----------|--------------------------------------|
| `subtasks`              | list | Yes      | Ordered list of subtasks             |
| `repeat_count`          | int  | Yes      | Number of loop iterations (≥ 1)      |
| `max_attempts_per_loop` | int  | No       | Max retries per iteration (default: 20) |

**long_running / long_running_once:**

| Field          | Type   | Required | Description                              |
|----------------|--------|----------|------------------------------------------|
| `command`      | string | No       | Command to run (AI can decide if omitted) |
| `initial_hint` | string | No       | Context/guidance for the AI on first attempt |

### 3.3 Hierarchy Rules

```
Top-level tasks:  simple | nested | looping
                     │        │         │
                     │    subtasks:   subtasks:
                     │   simple,     simple,
                     │  long_running, long_running,
                     │  simple_once, simple_once,
                     │  long_running  long_running
                     │    _once        _once
                     │
              (no subtasks)
```

- `nested` and `looping` can ONLY be top-level.
- `long_running`, `long_running_once` can ONLY be subtasks.
- `simple_once` can ONLY be a subtask.
- `simple` can be either top-level or subtask.

### 3.4 The `model` Field

The `model` field controls which AI model executes the task:

- `"default"` (or omitted): Uses the default model role, typically a more
  capable model suited for complex reasoning, multi-step code changes, and
  analysis.
- `"simple"`: Uses the simple model role, a lighter/faster model suitable
  for straightforward tasks like running a single command, simple file
  edits, or formatting.
- **Direct model name** (e.g., `"claude-sonnet-4-20250514"`): Uses the
  specified model directly, bypassing the role mapping.

**Guidelines:**
- Use `"simple"` for tasks like: "Run `make test`", "Format code with black",
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
`analysis`, `retry_from`, `next_strategy`, and `suggested_improvements`.

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

Example: "Optimize database query performance"
```yaml
- id: 1
  name: "Optimize database query performance"
  type: nested
  completion_criteria: |
    Average query response time < 100ms (measured by benchmark).
    All existing tests still pass.
  subtasks:
    - id: 1.1
      name: "Profile slow queries"
      type: simple
      completion_criteria: |
        Identified top 3 slowest queries.
        Analysis saved to query_analysis.txt.
    - id: 1.2
      name: "Add database indexes"
      type: simple
      completion_criteria: |
        Appropriate indexes created.
        Migration file generated.
    - id: 1.3
      name: "Run benchmark"
      type: simple
      completion_criteria: |
        Benchmark completed.
        Results show average response time < 100ms.
```

### 8.3 When to Use `looping`

Use looping when:
- The idea involves repeating an optimization cycle.
- Each iteration should follow the same steps.
- You want a fixed number of iterations (no early termination).

Example: "Iteratively optimize CUDA kernel performance"
```yaml
- id: 1
  name: "Iterative kernel optimization"
  type: looping
  repeat_count: 5
  completion_criteria: |
    5 rounds of profile-optimize-benchmark completed.
  subtasks:
    - id: 1.1
      name: "Profile with ncu"
      type: long_running
      completion_criteria: "ncu profiling completed, output saved."
    - id: 1.2
      name: "Optimize based on profile"
      type: simple
      completion_criteria: "Code changes applied, compiles without errors."
    - id: 1.3
      name: "Benchmark and commit/rollback"
      type: simple
      completion_criteria: "Benchmark run. If improved, committed. If not, rolled back."
```

### 8.4 Decomposition Anti-Patterns

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

# BAD: nested as subtask
- id: 1
  type: nested
  subtasks:
    - id: 1.1
      type: nested  # ERROR: nested cannot be a subtask
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
- When a **retry** happens within the same subtask, the AI session is NOT
  reset — the AI retains conversation history across retries of the same
  subtask. The retried subtask's prompt includes the `suggested_fix` from
  the failure analysis and previous attempt summaries.
- In **looping** tasks, sessions are also reset between iterations. Each
  iteration starts fresh, with only the previous subtask summary carried
  forward within the same iteration.

**Best practice:** Persist important intermediate results to files (e.g.,
analysis reports, configuration changes, benchmark results) rather than
relying on AI memory across subtasks. This ensures information survives
session resets.

---

## 11. Quick Reference Checklist

Before finalizing your task decomposition, verify:

- [ ] Every task has `id`, `name`, `type`, and `completion_criteria`
- [ ] Top-level tasks use `simple`, `nested`, or `looping` (never `long_running`)
- [ ] Subtasks use `simple`, `long_running`, `simple_once`, or `long_running_once` (never `nested` or `looping`)
- [ ] `*_once` subtasks are used only for genuinely one-time operations
- [ ] `looping` tasks have `repeat_count` (positive integer)
- [ ] `nested`/`looping` tasks have non-empty `subtasks` list
- [ ] All `completion_criteria` are specific, measurable, and verifiable
- [ ] Task IDs are unique and follow the correct notation
- [ ] The decomposition matches the complexity of the idea (not over/under-decomposed)
- [ ] `model` field is appropriate (`simple` for easy tasks, `default` for complex, or direct model name)
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
