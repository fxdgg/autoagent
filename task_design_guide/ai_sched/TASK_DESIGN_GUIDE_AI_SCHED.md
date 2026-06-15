# Task Design Guide for AI Agents

Reference for AI agents that generate `todos.yaml` tasks for AutoAgent.

---

## 1. Overview

Here is a minimal skeleton that helps you to understand the required `todos.yaml` structure.
Replace every `<placeholder>` with task-specific content; do not copy the placeholder into real tasks. 
`<!-- xxx -->` are comments that explain this example in detail —— do not copy them into real tasks either.

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

  ## Reference Docs
  ### P0 Must Read
    - <document path 1>: <its responsibility>
    - <document path 2>: <its responsibility>
    ...
  ### P1 Read Before Related Work
    - <document path 1>: <its responsibility>
    - <document path 2>: <its responsibility>
    ...
  ### P2 On Demand:
    - <document path 1>: <its responsibility>
    - <document path 2>: <its responsibility>
    ...

  ## Hard constraints
  - <constraints>

  ## Rules
  <rules>

ai_orchestrator:
  strategy: |
    <scheduling rules>
    <failure recovery rules>
  stop_condition: |
    <stop condition>
  last_result:
    1:
      type: file
      path: ${workspace}/<relative path to file>
    2:
      type: response

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
      - id: 2.2
        name: "<subtask name>"
        type: long_running
        completion_criteria: |
          <task-specific completion_criteria>
        initial_hint: |
          <initial_hint>
```

### 1.1 Roles

There are multiple agents for the entire workflow:

- Todo author or reviewer AI (You): Write or review a `todos.yaml` that will be executed by AutoAgent. **This guide and subguides (See §9) are not visible to all the other AIs, so DO NOT reference this guide or subguide in your `todos.yaml`**.

- Executor AI: AutoAgent drives one AI agent to execute one task defined in `todos.yaml`. Key characteristics for Executor AIs:
    - **Executor AIs are coding agents that can do anything a developer can** (e.g. Codex, Gemini CLI, Claude Code): read or grep, edit code, run commands, web search, etc. 
    - **Fully autonomous —— No human is in the loop**. 
    **Implication**:
    1. `completion_criteria` and `initial_hint` must be specific enough for the AI to act without clarification.
    2. The whole `todos.yaml` should not include sentences that ask the user to confirm a plan, implementation, etc.
    3. AutoAgent will automatically insert the "fully autonomous" constraint into prompts, so you don't need to add "fully autonomous —— DO NOT ask user questions" by yourself.
    - **Each Executor AI executes exactly one top-level task or subtask**.
    - **Tasks and subtasks share the filesystem, not conversation context** (See §3.1 for more details).
    - **Executor AIs can only see a partial of `todos.yaml`** (See §3.1 for more details).

- Scheduler AI: Scheduler AI dynamically chooses one top-level task per round, or chooses to stop. It does not schedule subtasks —— subtasks inside the selected top-level task run sequentially in ID ascending order. See §4 for more details.

- Evaluator AI: Evaluates whether a task has met `completion_criteria`. Key characteristics for Evaluator AIs:
    - **Its prompt format is controlled by AutoAgent** —— What can control Evaluator AIs' behaviour are root `description`, top-level `completion_criteria`, subtask's `name` and `completion_criteria`.
    - **When does AutoAgent trigger Evaluator AI**: See §3.5 for more details.

- Failure Analysis AI: Triggered when a subtask exhausts its `max_attempts`. It sees all subtasks' `name` and `completion_criteria`, and choose a subtask ID. Chosen subtask and all subsequent subtasks are retried. See §3.2 for more details.
    - **Its prompt is fully controlled by AutoAgent and is not editable**.

All the other roles use the same coding agent as Executor AIs. Scheduler AI, Evaluator AI and Failure Analysis AI automatically includes system prompts about not modifying source code, tests, configs, data, generated artifacts, etc.

### 1.2 Root Field Schema

| Field | Required | Notes |
|-------|----------|-------|
| `description` | Yes | Shared project context. `description` is injected into every role's prompt |
| `ai_orchestrator` | Yes | AI scheduling configuration |
| `tasks` | Yes | List of normal top-level tasks |

**More on `tasks`**:
- In AI scheduling mode, ID ascending order is not checked by AutoAgent. However, it is still recommended to write task ID in ascending order.

### 1.3 All Task Types

| Type | Top-level | Subtask | Use for |
|------|-----------|---------|---------|
| `simple` | Yes | Yes | General AI sessions |
| `long_running` | Yes | Yes | Generally the same as `simple`; must be used when containing commands that may run >1 minute. See §3.3 for **why `long_running` must be used**. |
| `nested` | Yes | **No** | A list of ordered subtasks with overall AI evaluation |
| `looping` | Yes | **No** | Fixed number of iterations |

**More on task types**:
- Do not use recursive `nested` / `looping` in your todo.
- `looping` are generally not recommended in AI scheduling mode (See §2 for more details).

### 1.4 Common Task Fields

| Field | Required | Notes | Can be a top-level `nested`/`looping` parent field? |
|-------|----------|-------|-----------------------------------------------------|
| `id` | Yes | Normal top-level tasks use positive integers; subtasks use dot notation (e.g. 2.1, 2.2). DO NOT add double quotes for numeric subtasks. | Yes |
| `name` | Yes | Title of this task. | Yes |
| `type` | Yes | One of the task types in §1.3. | Yes |
| `description` | Yes | Scheduler-facing ummary of what the task does and produces (See §4.1.2). | Yes |
| `completion_criteria` | Yes | Specific and verifiable completion criteria (See §7.2). | Yes |
| `max_attempts` | Optional | Maximum number of attempts (See §7.5). | Yes (Use `max_attempts_per_loop` for top-level looping task) |
| `max_attempts_per_loop` | Optional | Same as `max_attempts`, but used for top-level looping task (See §7.5). | Yes (Only for top-level looping task) |
| `initial_hint` | Yes, for executable tasks only | Task-specific context and guidance for the Executor AI (See §7.3). | **No** |
| `system_prompt_prefix` | Optional, for executable tasks only | Persona, expertise, style, role, or hard behavior constraints for the Executor AI (See §7.4). | **No** |
| `model` | Optional, for executable tasks only | `default`, `lite`, or direct model name for the Executor AI (See §7.6). | **No** |
| `repeat_count` | Yes, for top-level `looping` only | Defines the number of iterations | Yes |

Top-level `nested` and `looping` tasks are orchestration containers, not executable units. Therefore, executor-only fields —— `initial_hint`, `system_prompt_prefix` and `model` must be put on executable tasks/subtasks instead of the top-level parent.

### 1.5 `ai_orchestrator` Configuration

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| `strategy` | Yes | - | Scheduler decision policy (See §4.2). |
| `max_rounds` | No | 50 | Maximum scheduling rounds. |
| `stop_condition` | Yes | - | Observable stopping rule (See §4.3). |
| `last_result` | Yes | - | Per-task result exposure (See §4.1). |
| `max_attempts` | No | config default | Maximum retry count for schedulers. AutoAgent will end when this `max_attempts` is exhausted |

**More on `max_rounds`**: 
In AI scheduling mode, `max_rounds` is not a hard constraint —— the actual rounds can slightly exceed `max_rounds`. 
When `max_rounds` reached, a system reminder is injected into scheduler's prompt, instructing it to finish essential remaining works before it chooses to stop. 

**Implications:**
- With this soft constraint mechanism, you don't need to worry scenarios like "benchmark, report, etc. will not be executed after implementation when `max_rounds` reached". 
- You are recommended to add "No essential remaining works are left when maximum rounds reached" to `stop_condition` instead of "Stop when maximum rounds reached".

---

## 2. Default Flat Principle

In AI scheduling mode, the principle is **default flat** —— prefer top-level `simple` / `long_running` tasks instead of `nested` / `looping` tasks. Let the scheduler handle control flows like ordering, iteration, re-execution, conditional branching, etc.

Use `nested` tasks only when:
- **Sequential ordering should be enforced and the scheduler cannot guarantee it** (e.g. anti-hack verification must be run after implementation);
- **bundling several lightweight steps** into one top-level `nested` task to reduce scheduling overhead.

`looping` tasks are generally not recommended in AI scheduling mode: schedulers can handle looping iterations themselves.

---

## 3. AutoAgent's Key Execution Details

### 3.1 Context Isolation

#### 3.1.1 Session Management

AutoAgent creates separate AI sessions for each role to keep context growth under control. This has direct consequences for todo design.

The followings are exceptions (i.e. the same session is used):
- Relaunch the session after `long_running` commands have finished;
- User interruption;
- External API / Coding Agent issues like stream timeout, server error, etc. —— AutoAgent has an internal exponential backoff mechanism

#### 3.1.2 Tasks and Subtasks Share Filesystem, not Conversation or Reasoning Context

AI sessions are reset between tasks and subtasks —— almost no response or reasoning context is passed between executors. 

The only response that is passed between sessions is a truncated raw response between subtasks (e.g. last 5000 characters in 2.1's raw response is passed to 2.2).

**Implication**: 

1. Top-level tasks are generally independent unless scheduler strategy explicitly re-executes or branches between them.

2. **Important intermediate results should always be saved to files** (e.g. idea generation task writes its ideas to a file, and the subsequent implementation task reads it).

3. Although truncated raw responses are passed between subtasks, they are still not reliable handoffs —— they are only enhancements. Important intermediate results should still be saved to files.

#### 3.1.3 Executor AIs can only see a partial of `todos.yaml`

**What Each Session can See**:

- Top-level `simple` / `long_running`: Root-level `description`, this task's full information.

- Subtasks inside `nested` / `looping`: Root-level `description`, this task's full information, parent top-level `completion_criteria`, and other sibling subtask's `name` field.

**What Every Session cannot See**:

- `looping` task's iteration count;
- full `todos.yaml`;
- AutoAgent's source code and key execution details;
- This guide or subguides.

**Implication**: 

1. Each executor is a fresh AI session. You write more into `description` and `initial_hint`, AIs guess and explore less. However, you should act as a context provider, not a step-by-step instructor. See §4 and §6.4 for more details.

2. Do not write `completion_criteria` or `initial_hint` that says things like "see the previous task in `todos.yaml`". 

3. If you need to reference a previous task, you must explicitly state what the previous task are doing, what files it generate should be read by this task, etc. in `initial_hint`.

4. If subsequent tasks depend on earlier task's judgement calls, earlier tasks should be instructed to write its decision, raw evidence, analysis, etc. into a file. Subsequent tasks should be instructed to read this file to do branching logic.

5. For iterative tasks, it is recommended to let scheduler control the looping workflow instead of defining a `looping` task (See §2). An explicit file should be introduced to maintain looping count information (e.g. EXP-001, EXP-002, ...), and each iteration's status (e.g. pending, finished) should be explicitly recorded to correctly handle retry behaviour.

### 3.2 Retry Strategy & Failure Handling

This section is about **ordinary retryable failures** that can be resolved by retrying previous tasks. For **prerequisite failure handling**, see §6.1 for more details.

Examples:

- Failed anti-hack check, failed benchmark because of implementation bugs —— retry implementation task
- Insufficient raw data evidence —— retry benchmark / data collection task

**Inner retry**:
- When each execution unit outputs `❌ not completed: <reason>`, the same unit will be retried until its `max_attempts` are exhausted. Only failed completion markers will be injected into next attempt's prompt.

- Inner `max_attempts` are reset between failure analyses, evaluator actions or looping iterations.

- `max_attempts` defaults to AutoAgent's global default if not set on the task.

**Inter-task retry**:
- Top-level tasks are generally independent. Subsequent top-level tasks will not trigger previous top-level tasks' retry (e.g. task 5 will not trigger task 4 retry).

- When top-level `max_attempts` are exhausted, the entire top-level `simple` / `long_running` / `nested` / `looping` task will fail (remaining subtasks will not be executed), and scheduler AI will be invoked after that.

**Inter-subtask retry**:
- Inter-subtask retry only happens between subtasks in `nested` / `looping`. When a subtask exhausts its `max_attempts`, failure analysis AI is triggered. It sees each subtask's `name` and `completion_criteria`, and choose a subtask ID. Chosen subtask and all subsequent subtasks are retried.

Top-level `max_attempts` / `max_attempts_per_loop` inside `nested` / `looping`'s fields define the maximum attempts of failure analyses (per iteration for `looping`). The whole `nested` / `looping` task will fail after its `max_attempts` are exhausted.

**Implication**:
1. For top-level tasks:

- For top-level `simple` / `long_running` tasks, no inter-task retry is invoked. It is the scheduler's responsibility to correctly handle top-level retry behaviours. `max_attempts: 1` is recommended if inner retry has no benefit.

- For top-level `nested` / `looping` tasks, use `max_attempts: 1` if subtasks will introduce prerequisite failures for fast propagation. Use omit / default / higher `max_attempts` or `max_attempts_per_loop` if only ordinary retryable failures occurs (e.g. implementation + anti-hack) to utilize failure analysis strategy.

- Since scheduler cannot control subtasks, and the principle is **default flat**, DO NOT fill everything into a large `nested` task which makes prerequisite failures hard to propagate.

2. For subtasks:

- Use `max_attempts: 1` when inner retry has no benefit (e.g. anti-hack check, execution-only subtask that are not allowed to modify anything). This enables fast failure propagation —— Previous subtasks can be fastly retried without wasting attempts on this task.

- Use `max_attempts: 1` when a subtask is explicitly instructed to output `❌ not completed: <reason>` —— This also enables fast failure propagation.

- DO NOT use `max_attempts: 1` for tasks that benefit from inner retries (e.g. implementation).

3. Executor AIs should be instructed to be aware of residual states from previous attempts, and should be instructed to check prerequisites by themselves.

4. An explicit failure record file (e.g. `error_report.md`) should be maintained and written in root `description`'s Reference Doc P1. Executors should be instructed to write an entry when output `❌ not completed: <reason>`, and scheduler or fatal handling task (See §6.1) can read from it for further diagnosis. Only scheduler or fatal handling task must read this file; normal executor tasks only need to write to it.

⚠️ If users explicitly say that they believe retries and fatal conditions are abnormal, and wants to reduce todo's length, do as they want. But DO NOT delete retry handling entirely. 
- At least include marker instructions on anti-hack checks, training / testing / benchmarking / profiling failed due to implementation errors, and key data / metric missing.
- An explicit failure record file should be maintained for scheduler diagnosis.
- A separate fatal handling task can be deleted (See §6.1) since the user believes retries and fatal conditions are abnormal —— Scheduler re-execution is sufficient for this.

### 3.3 `long_running` Mechanism

For most AI coding agents, directly running time-consuming commands (e.g. training, large test suites, long builds, data preprocessing) will trigger native bash timeout. 

When `long_running` is used, AutoAgent will instruct executors to launch a background command with internal tools and stop their sessions. AutoAgent will automatically relaunch the session, and tell the AI stdout/stderr file path & exit code when it detects that background commands have finished. Therefore, native bash timeout constraints are addressed.

**Implication**:
1. You don't need to write extra prompts to reflect this —— AutoAgent will internally inject system instructions. Just set the task type to `long_running`.

2. The internal tool captures stdout/stderr automatically. Todo author should not instruct AI to run long-running commands with shell redirection such as `>`, `2>`, `&>`, or `| tee`, and make sure that your command does not include interactive flags. If command results must be written to a specific file, use natural language to instruct AI —— AutoAgent will provide system instructions to handle this. If not, just remove your redirection.

3. Multiple long-running commands are allowed to run inside one `long_running` task. You don't need to split tasks because of this, but be aware of retry cost.

4. Sessions are not reset when relaunching after `long_running` commands have finished.

### 3.4 Interacting with Internal Markers

AutoAgent will instruct the executor to output one of two markers below when it finished working:

`✅ completed`: The executor believes `completion_criteria` are satisfied.
`❌ not completed: <reason>`: The executor believes criteria are not satisfied.

**Implications**:
1. You don't need to restate all marker system instructions —— AutoAgent automatically injects those into executor prompts.

2. You should instruct executors to explicitly output `❌ not completed: <reason>` (DO NOT omit the emoji) when it encounters hard-to-decide situations. In other words, what you should do is to guide executors to utilize this marker mechanism. 

The `<reason>` text is visible and not truncated when propagating errors to scheduler or failure analysis, so instruct executors to provide meaningful `<reason>`.

See other sections for full guidance.

### 3.5 Evaluator AI Mechanism

Evaluator AI is automatically triggered for `nested` tasks to check whether it has met `completion_criteria`. Its prompt is controlled by AutoAgent and is not editable.

1. Top-level simple / long_running task: Not triggered —— executors themselves check its `completion_criteria`.

2. Nested task: Triggered when all subtasks are completed —— if it finds that the top-level `completion_criteria` is not satisfied, it will choose a subtask and all subsequent subtasks to retry (See §3.2). This retry does not count `max_attempts`. Inner subtask `completion_criteria` are still evaluated by executors themselves.

3. Looping task: Not triggered —— A looping task's goal is to run a fixed number of iterations, so top-level `completion_criteria` will not be evaluated when one iteration finishes, and looping will not stop until it reaches the maximum number of iterations. However, top-level `completion_criteria` is still visible to subtask executors.

**Implications**:
1. Root `description`, top-level `completion_criteria`, subtasks' `name` and `completion_criteria` are only ways to control evaluator AI's behaviour.

2. Top-level `completion_criteria` for `nested` tasks should cover all subtask's `completion_criteria` so that evaluator AIs have full decision context (since `looping` task has no evaluators, this rule is not mandatory for `looping`).

### 3.6 What AutoAgent DOES NOT Control

AutoAgent never invokes extra AI sessions to automatically maintain high-level principles in this guide or subguides. They are all contracts that should be fully defined in `todos.yaml`.

What AutoAgent DOES NOT control:
- The entire filesystem, including residual states, cleanup, etc. —— All files must be maintained by inter-task coordination;
- The entire `git` behaviour —— All `git` actions must be performed by executors themselves, including revert actions. AutoAgent will not control `git`, or use `git` for judgements either.
- File reading —— AutoAgent will never inject file contents into executors' prompts. All files are accessed by their native read tools. If you want to ensure that a file must be read, enhance your prompts.

## 4. Guidance on AI Scheduling

### 4.1 Scheduler Execution Details

#### 4.1.1 `last_result` Exposure

`last_result` explicitly exposes top-level task outcomes to the scheduler. There are three configuration types: 

| Type | What Scheduler sees | Use for |
|------|---------------------|---------|
| `none` | Success/failure status only | Generally not recommended |
| `response` | AI's final response | Default for most tasks |
| `file` | Contents of specified files | Complex scheduling strategy that requires scheduler to do conditional branching based on outcomes |

Schema for `type: file` with multiple specified files:

```yaml
  last_result:
    1:
      type: file
      path:
        - ${workspace}/<relative path to file 1>
        - ${workspace}/<relative path to file 2>
```

**Schema Rules**:
1. Keys are top-level task IDs without double quotes, not subtask IDs;
2. Use `${workspace}` for workspace-relative `type: file` paths —— it is expanded at runtime. `${workspace}` references the project root (where coding agents are launched), not todo file's position;
3. Dynamic relative file path for `type: file` is not supported by AutoAgent. For iterative tasks, maintain one file only or use a rolling summary for scheduler decisions instead of listing file paths for all iterations.

**Design Rules**:
1. Prefer `type: response` for most tasks. For most projects that does not require complex scheduling strategy, **schedulers just simply follow the step-by-step script in `strategy` instead of reasoning by themselves**. `type: response` is sufficient for scheduler to identify task execution status and make correct error handling in this scenario.

2. Use `type: file` only when the project requires scheduler to inspect specific file contents across rounds for complex scheduling strategy.

3. While files specified by `type: file` must be read by scheduler's native read tool to retrieve full content, the last 5 lines of these files are directly injected into the scheduler's prompt —— put scheduler-critical state near the end of each result file, or maintain a small rolling summary/status file for scheduling decisions. Do not bury it in the middle of a large log.

4. File paths in `last_result: type: file` are shared between schedulers and executors, not scheduler-only. You don't need to instruct executors with sentences like "copy results to a specified path for scheduler" or mention "persist scheduler-relevant outcomes" elsewhere.

5. Always ensure that files defined in `last_result: type: file` are already present or created inside this task after the task has been executed for the first time. Otherwise scheduler may treat this task as "not completed" and make wrong retry decisions.

#### 4.1.2 Scheduler does not See the Entire Task Detail

Scheduler only sees:
- root `description`, scheduler's `strategy`, `stop_condition` and `last_result`;
- Each top-level task's `name`, `type`, `description` and total execute times;
- Schedule history: task ID, name, completion marker (last 10 rounds only).
- A system reminder when maximum schedule rounds reached (See §1.5).

Scheduler does not see:
- Inner task details (`completion_criteria`, `initial_hint` and `system_prompt_prefix`);
- Subtask information.

**Implication**:
1. Top-level task's `description` should be scheduler-facing instead of executor-facing. All top-level task's `description` are injected into schedulers' prompt, so keep it to 1-3 sentences, otherwise the scheduler prompt becomes bloated.

2. Task-specific `description` should not cover success conditions or task-specific context that should belong to `completion_criteria`, `initial_hint` and `system_prompt_prefix`.

3. For task with `last_result: type: file`, also state how should scheduler read these files, and each file's responsibility. Restate them even when these files are already mentioned in root `description`.

4. Explicitly maintain a schedule history file and tells the scheduler AI to write its decisions only when you think that scheduler truly needs older histories.

### 4.2 `strategy`

`strategy` encodes the scheduler's decision policy. For most projects that does not require complex scheduling strategy, A deterministic step-by-step script is recommended:

- bootstrap behavior;
- the next executed task after each task succeeded (use specific task ID);
- failure handling after task fails;
- When to trigger fatal handling task.

### 4.3 `stop_condition`

`stop_condition` encodes when should scheduler stop scheduling. Examples like:

- Goal or success threshold if the project explicitly states;
- Fatal handling task outputs `❌ not completed: <reason>`;
- Interaction with system reminders like "No essential remaining works are left when maximum rounds reached" (See §1.5).

## 5. Guidance on Root `description`

Root `description` is the shared project context for all tasks, injected into every role's prompt.

### 5.1 What to Include

Required Fields:

- **Goal**: State the final observable objective and important success threshold.
- **Architecture**: Key modules, directories or pipelines and their responsibilities.
- **Key file paths**: Relevant source files, configs, inputs, outputs, logs, reports, and generated artifacts. Do not list unrelated files.
- **Environments**: Runtime versions, environment variables, containers, hardware requirements, and important setup assumptions. Also for workspace and path conventions.
- **Key commands**: Build, test, run, benchmark, format, lint, data, or deployment commands with environments used and expected outputs when relevant.
- **Reference Docs** List document paths with short reasons and priority levels:
    - **P0 Must Read**: essential architecture, API contracts, safety constraints, schema definitions, or project rules. Use sparingly —— too many P0 docs dilute attention.
    - **P1 Read Before Related Work**: docs that matter only when touching a subsystem, file type, benchmark, deployment path, or experiment family.
    - **P2 On Demand**: troubleshooting notes, deep background, or optional references for debugging and edge cases.
- **Hard constraints**: Include files, APIs, tests, data, configs, metrics, or behavior that must not be changed.
- **Rules**: Include reporting discipline, experiment discipline, git/commit expectations, allowed change size, or other project-wide norms.

Optional Fields: 

- **Architecture Coupling Notes**: files, modules, schemas, generated code, migrations, or API contracts that usually must be changed together.
- **Naming Conventions**: required names for files, branches, metrics, reports, experiments, datasets, or artifacts.
- **Historical Result Files**: previous reports, failed attempts, benchmark tables, investigation notes, or experiment logs that should prevent repeated work.

### 5.2 What Belongs Somewhere Else

- **Task-local context belongs in `initial_hint`**: current task inputs, exact files to inspect, commands to run, output artifacts to write, and prerequisite checks.
- **Success condition belongs in `completion_criteria`**: commands, files, metrics, diffs, reports, or other evidence that proves the task is complete.
- **Persona and hard role constraints belong in `system_prompt_prefix`**: verifier role, read-only role, domain expertise, or strict no-edit behavior.
- **Scheduler-only ordering rules belongs in `ai_orchestrator`**.

See §7 for detailed field-writing rules.

### 5.3 What Must Not Include

- **Step-by-step Instructions**: AI can figure it out themselves. Todo author should be a **context provider** that tells executors where to obtain information, not a step-by-step instructor. 
- **Potential/Recommended Approach**: AI can figure out the best approach themselves. Locking them into one approach only narrows AI's creativity.

Exceptions are:
- The project explicitly requires
- User-defined document format specifications
- Exact procedural protocols that AI cannot invent

## 6. Guidance on Task Decomposition

### 6.1 Define a Fatal Handling Task

In AI scheduling mode, fatal handling should be modeled as an **explicit ordinary task** that the scheduler can choose. 

Examples of fatal conditions:
- Missing dataset, credential, hardware, remote server, etc.;
- The workspace is in a state that must be repaired before any task can proceed;
- recovery requires bounded remediation work that should not be mixed into normal tasks.

Design Rules:
1. This task should handle **hard prerequisites or global blockers**. Scheduler should schedule this task when other tasks output `❌ not completed: <hard prerequisites or global blocker issues>`.

2. This task is not dedicated for normal retry behaviours. If retry can be handled directly by scheduler themselves (e.g. report task output `❌ not completed: missing benchmark` -> retry benchmark task), do not schedule this task.

3. Scheduler's `stop_condition` should state "stop when this task outputs `❌ not completed: <reason>`.

#### 6.1.1 Defining Fatal Handling Task

1. In `initial_hint`, point to durable evidence such as `error_report.md`, logs, benchmark outputs, setup reports, `last_result` files, etc. Do not rely on prior executor conversations for diagnosis.

2. Define authority boundaries in this task —— specify whether it may edit code, modify config, install dependencies, clean generated files, revert task-owned changes, rerun checks, etc. Also define what it must not touch.

3. Explicitly instruct this task to output `❌ not completed: <reason>` when it cannot fix failures or the fix is out of user-defined scope.

4. Use `max_attempts: 1` and `last_result: file` for this task —— Repeating the same blocker diagnosis many times rarely helps. `last_result` should reference durable evidence such as `error_report.md`.

5. This task should be instructed to append a specific entry to `error_report.md` so that scheduler can decide the next scheduling action.

### 6.2 Split at Expensive Checkpoints

Split work when a checkpoint is expensive enough that repeating everything would waste time or require high reasoning.
If not, the following two situations may happen:
- Excessive work are retried by failure analysis, wasting time or leaving project into a broken state.
- AI becomes lazy and tries to find simplified solutions when it has too much work to do.

Common expensive checkpoints:

- **Analysis / idea composition**: requires extensive reasoning to produce a plan or idea.
- **Implementation**: usually requires extensive work. 
- **Time-consuming execution tasks like training / testing / benchmarking / profiling**: may take minutes or hours and should often be isolated from implementation.
- **Decision Making and Reporting**: requires results from time-consuming execution tasks that are not available before these tasks complete.

A good checkpoint leaves a durable artifact: a plan file, modified code, result table, benchmark log, verification report, etc. Later tasks should read that artifact, not rely on conversation memory.

**More on implementation**: For large implementation tasks with substantial code changes (e.g. >10000 lines), implementation tasks should split into multiple top-level `nested` tasks at module level, each with two subtasks called "implement" and "anti-hack". See "Build and Ship" subguide in §9 for more details.

#### 6.2.1 Fast Validation for Time-consuming Execution Tasks

For time-consuming execution tasks like training, large test suites, benchmarking, or profiling, a failed full run can waste minutes or hours. 

Todo author should instruct implementation tasks to make cheap and fast self-corrections in the same session before launching the expensive run, i.e.

implement + fast self-correction → full long-running execution → analyze/report results

To achieve this, todo author should actively look for fast validation modes. Common forms include:

- `--validate`, `--doctor`, `--dry-run`, `--check`, `--smoke`, `--quick`, or similar arguments;
- Method that runs one epoch, one batch, etc. instead of full training;
- reduced dataset, reduced sample count, short time limit, or smaller benchmark case;
- smoke test, import test, config validation, schema validation, or shape check;
- profiling or benchmark warmup mode that checks wiring without collecting the final metric.

Design rules:
1. Do not over-apply this rule. If the full validation is quick enough for self-correction, keep it inside the implementation task.

2. Fast validation is only a preflight check, not a replacement for the full run. For full long-running execution tasks, you should use `max_attempts: 1` and explicitly instruct them to output `❌ not completed: <reason>` when full-run fails.

3. If no fast validation mode exists, warn the user if you can.

### 6.3 Split at Trust Boundaries

Also split work when the next step must not use the previous step's conversation or reasoning context.

Common trust boundaries:

- **Implementation vs. Anti-hack verification**: the verifier should not be the same session that wrote the code.
- **Plan maker vs. Plan reviewer** (for complex plans only): reviewer should not be the same session to avoid self-hallucination.

Design rules:
- When a verification subtask finds an issue, it should usually report failures by `❌ not completed: <reason>` rather than fix it.

### 6.4 Merge to Reduce Unnecessary Sessions or Retries

Splitting creates independent sessions and retry boundaries. This is useful for expensive checkpoints and trust boundaries, but unnecessary splits make simple work slower. Merge steps when they share the same local context or save unnecessary retries.

Common cases:

- **Implement + build + fast validation / full test**: keep these together so the implementation task can self-correct errors in the same session, which save retries for trivial implementation mistakes.
- **Analyze + implement for low-complexity work**: if the analysis is a small local inspection and does not need a durable decision artifact, merge it with implementation.
- **Benchmark + report when benchmark is not long-running or complex**: merge these two steps when benchmarking has low workload.
- **Use top-level task instead of subtasks when only one subtask is needed after merging**.

### 6.5 Typical Subtask Count

For one `nested` or `looping` task, **2-5 subtasks** is usually enough. See task-specific subguides in §8 for more task decomposition details.

## 7. Guidance on Common Task Fields

### 7.1 Write Clear, not Vague Fields

This rule is about avoiding subjective or unverifiable wording which applies to every text field.

Do not write requirements that are not specific or measurable, depend on taste, unstated expectations, or the executor's private judgement. Replace them with observable evidence such as commands, files, diffs, metrics, reports, logs, artifacts, thresholds, or explicitly forbidden changes.

Bad field text often contains words like `good`, `clean`, `robust`, `better`, etc. without saying how those qualities are checked.

### 7.2 `completion_criteria`

`completion_criteria` should be specific and measurable task success conditions, not implementation steps.

Include when relevant:

- commands that must exit successfully;
- files or artifacts that must exist and contain required content;
- metrics, thresholds, baselines, or comparison rules;
- exact scope boundaries for changed files;
- negative constraints such as no weakened tests, no unrelated edits, no API changes, no data loss, no skipped validation;
- interaction with internal markers when needed (See §3.4).

Top-level `completion_criteria` for `nested` tasks should cover all subtask's `completion_criteria` so that evaluator AIs have full decision context (See §3.5).

Avoid:

- prescribing implementation steps instead of outcomes;
- success without specific and measurable evidence;
- missing negative conditions;
- copying `initial_hint` into `completion_criteria`.

### 7.3 `initial_hint`

`initial_hint` is task-local context for the executor. It should help the executor begin safely and recover from potential previous attempts without turning the task into a rigid step-by-step script.

Include when relevant:

- prerequisite checks, what to do if prerequisites are missing, and interaction with internal markers when needed (See §3.4);
- cleanup guidance for failed previous attempts or dirty working tree state;
- task-specific files/directories to inspect or modify;
- task-specific commands, working directory, environment variables, input files, and expected output files;
- task-specific scope boundaries and forbidden changes;
- handoff files from earlier tasks and what information to extract from them;
- expected handoffs this task should write for later tasks.

Do not put these in `initial_hint`:

- project-wide context that already belongs in root `description`;
- success conditions from `completion_criteria`;
- step-by-step instructions unless the project requires / specifying user-defined document format specifications / specifying exact procedural protocols that AI cannot invent;
- potential/recommended approach unless the project requires;
- references like "see previous task", see this guide or subguides, etc. (See §3.1).

### 7.4 `system_prompt_prefix`

`system_prompt_prefix` sets the executor's persona, expertise, style, role, or hard behavior constraints.

Good examples like:

- `You are a careful backend performance engineer.`
- `Do NOT modify source code, tests, configs, data, or generated artifacts.`
- `Prefer minimal, well-tested changes and preserve public APIs unless explicitly instructed otherwise.`

Do not use it for success conditions or task-specific context that should belong to `completion_criteria` and `initial_hint`.

### 7.5 `max_attempts`

Choose `max_attempts` by:

| Situation | Suggested value | Reason |
|-----------|-----------------|--------|
| Top-level tasks that does not benefit from inner retries | `1` | Fastly propagate failures to scheduler |
| Execution-only subtasks such as build, test, benchmark, verify | `1` | Repeating the same check usually does not help; paired with internal marker instructions so that failure should propagate quickly. |
| Subtasks that does not benefit from inner retries | `1` | Retrying the same task does not help; failure should propagate quickly. |
| Subtasks that are explicitly instructed to output `❌ not completed: <reason>` | `1` | If not, this marker will trigger inner retry instead of failure analysis |
| Targeted uncertain work with constrained scope | `2-3` | Gives the executor room to recover from local mistakes without wasting many attempts. |
| Active coding, debugging, optimization, or refactoring | omit / default / higher when justified | These tasks often benefit from retries because the executor can inspect failures and revise its work. |

**More on `max_attempts`**:
- Top-level `nested` / `looping`'s `max_attempts` are generally unnecessary to modify; for top-level `looping`, use `max_attempts_per_loop` rather than `max_attempts`.
- Default `max_attempts` are defined by user.

See §3.2 for further analysis.

### 7.6 `model`

Choose `model` by reasoning demand.

| Situation | Suggested value | Reason |
|-----------|-----------------|--------|
| Design, debugging, implementation, optimization, anti-hack review, complex analysis | omit / `default` | Requires deeper reasoning and tradeoff handling. |
| Deterministic execution such as running commands, copying known outputs, or summarizing fixed logs | `lite` | Mainly needs instruction following instead of reasoning. |
| Project or environment requires a specific model | direct model name | Use only when the project explicitly needs it. |

Do not overuse `lite` for tasks that require judgement, debugging, security review, anti-hack reasoning, or ambiguous tradeoffs.

## 8. Other Important Rules

### 8.1 Anti-Hack Patterns

Anti-hack design prevents an executor from satisfying a task through shortcuts that violate the user's intent: weakening tests, modifying benchmarks, hardcoding outputs, changing unrelated APIs, deleting difficult cases, silently dropping data, or claiming success without evidence.

Use two complementary layers to defend:

1. **Field boundaries**: `completion_criteria` and `initial_hint` should define allowed scope, forbidden changes, raw command evidence, etc.
2. **Session separation**: a separate anti-hack subtask must be introduced for complex implementations.

Use a separate verification or anti-hack subtask when the implementation is non-trivial, risky, or easy to game.

**Pattern 1: A subtask after implementation task** —— e.g. 2.1 is implementation subtask, 2.2 is the anti-hack subtask. 
**Pattern 2: An anti-hack subtask after each implementation task when there a multiple** —— e.g. 2.1 implements module A, 2.2 anti-hacks module A; 3.1 implements module B, 3.2 anti-hacks module B, etc. 

Design Rules:

1. Always split them into two subtasks for trust boundary.

2. Always put implementation subtask and anti-hack subtask under one top-level `nested` task, and instruct the anti-hack subtask to output `❌ not completed: <reason>` when anti-hack fails so that the implementation subtask could be retried.

3. Anti-hack subtask's `system_prompt_prefix` should cover rules about "Do NOT modify source code, tests, configs, data, generated artifacts, etc.".

4. DO NOT add anti-hacks extensively. Anti-hacks should not be added when they are actually doing repeated work (e.g. anti-hacking benchmark is generally re-benchmark, anti-hacking report is generally useless), or anti-hack itself is not trustable either. Executors are AIs that are not intrinsically prone to hack when they are not encountering difficulties and with reasonable workload.

5. Anti-hack subtask can be lighter when the change is small and low-risk, or the user explicitly prioritizes brevity over robustness.

These rules cover cross-cutting operational details that do not belong to schema, task decomposition, field-writing, retry, long-running, fatal-analysis, or anti-hack sections.

### 8.2 `git` Usage

Use `git` as the durable ledger of task progress and evidence.

Design rules:
1. **Commit completed work when there is work to commit**: If a task or subtask changes tracked files, it should normally commit those changes before completion.

2. **Make commit boundaries match task boundaries**: A commit should correspond to one coherent task/subtask outcome. Avoid one large commit that mixes multiple unrelated tasks, and avoid many tiny commits that later tasks cannot interpret.

3. **Use informative commit messages**: Commit messages should identify the task/subtask and purpose for further tasks to inspect.

4. **Check the working tree before editing**: Tasks should inspect `git status` before making changes. If residual changes exist, the task should decide whether they are intended handoff state, leftovers from its own failed retry, or unrelated user/project changes. Do not silently overwrite unrelated changes.

5. **Be explicit about branches only when branches are part of the design**: Branch-per-condition is useful for isolated experiments, ablations, or risky alternatives. Ordinary linear implementation should usually stay on the current branch unless the project asks otherwise.

6. **Forbid destructive git operations unless intentionally allowed**: Do not instruct executors to use broad `git reset --hard`, `git clean`, force-push, branch deletion, or checkout commands that may discard unrelated work unless the task explicitly owns that state and the user, project rules, or subguides explicitly allow it. Prefer targeted reverts or task-owned commit rollback.

7. **Revert with preservation of decision evidence**: For optimization or experiment tasks, if an implementation is rejected, preserve the hypothesis, measurements, and decision record even if the implementation commit is reverted.

### 8.3 For Todo Authors (You)

**DO NOT read this guide or subguides only once. When you feel ambiguity in writing todos, read it once more to check if this guide already answers your concern —— This guide and subguides has substantial amount of information, you may not pay attention to all of them at once.**

## 9. Task-Specific Subguides

Read only the guide relevant to the task domain:

| Domain | Guide |
|--------|-------|
| Iterative optimizations | `iterative_optimization.md` |
| Build, ship, bug fix, refactor | `build_and_ship.md` |
| Test running, verification, coverage | `testing_and_verification.md` |
| Data pipelines / ETL | `data_pipelines.md` |
| Setup and deployment | `setup_and_deployment.md` |
| Research, analysis, reports | `research_and_analysis.md` |
| Academic experiments | `academic_experiments.md` |

## 10. Checklist

⚠️ Verify every item before submitting your `todos.yaml`.

### 10.1 Overview

[ ] `todos.yaml` does not reference AutoAgent's source code, execution details, this guide or subguides.
[ ] `todos.yaml` does not restate AutoAgent's system instructions (fully autonomous, long-running mechanism and marker instructions).
[ ] `todos.yaml` is fully autonomous and does not ask the user to confirm plans, choices, implementation, validation, or next steps.
[ ] Root fields include `description`, `ai_orchestrator`, and `tasks`.
[ ] Every task has `id`, `name`, `type`, `description`, and `completion_criteria`; every executable task has `initial_hint`. Top-level `nested` and `looping` task does not have `initial_hint`, `system_prompt_prefix` or `model`.
[ ] Top-level task IDs are sequential integers; subtask IDs use dot notation without double quotes. Write numeric IDs in ascending order even though AI scheduling mode does not depend on ID order.
[ ] No recursive `nested` / `looping` tasks are used.

### 10.2 Default Flat Principle

[ ] The design follows the default flat principle: prefer top-level `simple` / `long_running` tasks and let the scheduler handle ordering, branching, re-execution, and iteration.
[ ] `nested` is used only when sequential ordering must be enforced inside one top-level task, or when bundling several lightweight steps to reduce scheduling overhead. `looping` is generally avoided.

### 10.3 AutoAgent's Key Execution Details

#### 10.3.1 Context Isolation

[ ] Top-level tasks are designed as independent units unless scheduler strategy explicitly re-executes or branches between them.
[ ] Important intermediate results are written to files; never assume the next task can see prior conversation or reasoning context.
[ ] `description` and `initial_hint` act as context providers, not step-by-step scripts unless the project requires / specifying user-defined document format specifications / specifying exact procedural protocols that AI cannot invent.
[ ] If cross-task communication is required, prior tasks must write information to files. Subsequent task's `initial_hint` must explicitly state what prior tasks are doing, what files it generate should be read by this task. Does not say things like "see the previous task in `todos.yaml`". 
[ ] Iterative workflows use scheduler-controlled looping when possible, with explicit files recording iteration IDs and status.

#### 10.3.2 Retry Strategy & Failure Handling

[ ] Normal retryable failures should be explicitly instructed with `❌ not completed: <reason>`. The `<reason>` text is meaningful enough for retry decisions.
[ ] Executor AIs should be instructed to be aware of residual states from previous attempts.
[ ] Top-level failures that need inter-task recovery are handled by `ai_orchestrator.strategy`, not by assuming later top-level tasks will automatically retry earlier tasks.
[ ] An explicit failure record file should be maintained and written in root `description`'s Reference Doc P1. Executors should be instructed to write an entry when output `❌ not completed: <reason>`; only failure/fatal analysis tasks need to read it.
[ ] Fatal handling, when needed, is modeled as an explicit ordinary top-level task scheduled by `strategy`, with clear inputs, authority boundaries, low retry budget, and scheduler-readable output.
[ ] Retry handling may be simplified when the user explicitly requests brevity, but marker usage and scheduler-visible failure reporting are not removed entirely.

#### 10.3.3 `long_running` Mechanism

[ ] `long_running` is used for tasks containing commands that may run >1 minute.
[ ] No output redirection or interactive flags are used for long-running commands; use natural language to instruct explicit output paths instead.

#### 10.3.4 Interacting with Internal Markers

[ ] `❌ not completed: <reason>` are explicitly instructed for hard-to-decide cases when:
- Anti-hack subtask states 'fail';
- Training / testing / benchmarking / profiling failed because of implementation errors;
- Insufficient raw data evidence that can be replenished by retrying previous subtasks.
[ ] Errors that belong to current task's responsibility should be self-corrected instead of outputing markers (e.g. implementation task should fix compilation bugs introduced by itself).
[ ] Marker instructions do not restate AutoAgent's internal system instructions; they only guide when the executor should use `❌ not completed: <reason>`.

#### 10.3.5 Other Details

[ ] Never assume that AutoAgent will internally maintain filesystem, `git`, read behaviour, etc. They should be contracts that must be fully defined in `todos.yaml`.

### 10.4 AI Scheduling

#### 10.4.1 `strategy`

[ ] `ai_orchestrator.strategy` defines bootstrap behavior, success transitions, failure handling, and when to schedule any explicit fatal handling task.
[ ] For simple projects, `strategy` is a deterministic step-by-step script using concrete task IDs instead of vague reasoning instructions.
[ ] Subtasks are not assumed to be scheduled, and scheduler-critical information is not hidden only in subtask details.

#### 10.4.2 `stop_condition`

[ ] `ai_orchestrator.stop_condition` is specific and observable, and includes a fallback such as no essential remaining work after the maximum-round reminder.
[ ] `max_rounds` is treated as a soft reminder, not the only stopping rule.

#### 10.4.3 `last_result`

[ ] `ai_orchestrator.last_result` is configured for top-level task IDs, not subtask IDs.
[ ] `last_result: type: response` is used for ordinary step-by-step scheduling; `type: file` is used only when scheduler decisions require reading specific files.
[ ] Every `last_result: type: file` path is static, uses `${workspace}` for workspace-relative paths, and points to files that executors also know how to create or update.
[ ] Scheduler-critical status is kept in the final response or near the end of files used by `last_result: type: file`.

#### 10.4.4 `description`

[ ] Top-level task `description` is scheduler-facing: 1-3 sentences stating what the task does, what it produces, and any scheduling-relevant outcome.

### 10.5 Root `description`

[ ] Root `description` covers Goal, Architecture, Key file paths, Environments, Key commands, Reference Docs with priority levels, Hard constraints and Rules.
[ ] Root `description` only covers shared project context; task-local context are put in `initial_hint`, success condition are put in `completion_criteria`, and persona & hard role constraints are put in `system_prompt_prefix`, scheduler-only ordering rules are put in `ai_orchestrator`.
[ ] Root `description` does not cover step-by-step instructions or potential/recommended approach unless the project requires / specifying user-defined document format specifications / specifying exact procedural protocols that AI cannot invent.

### 10.6 Guidance on Task Decomposition

[ ] Tasks are not under-split —— split at expensive checkpoints and trust boundaries.
[ ] Tasks are not over-split —— merge when reducing unnecessary sessions or retries.
[ ] Extensive implementation is split into module-level top-level `nested` tasks with sibling implementation and anti-hack subtasks when appropriate.
[ ] When full validation is long-running, fast validation modes are detected and used in implementation tasks if present, while full validation tasks are still instructed with `❌ not completed: <reason>`. 
[ ] If fast validation modes are not present and full validation is long-running, warn the user when possible.
[ ] Typically 2-5 substasks for one `nested` or `looping` task.

### 10.7 Guidance on Common Task Fields

[ ] Every field is clear, specific, measurable, and verifiable, not vague or subjective.
[ ] Task `description` is scheduler-facing and does not duplicate `completion_criteria`, `initial_hint`, or `system_prompt_prefix`.
[ ] `completion_criteria` are specific, measurable, and verifiable task success conditions, including positive and negative conditions, not implementation steps.
[ ] Top-level `completion_criteria` for `nested` tasks should cover all subtask's `completion_criteria` so that evaluator AIs have full decision context.
[ ] `initial_hint` covers task-local context, with prerequisite checks, residual state awareness, task-specific information, and handoff file handling.
[ ] `initial_hint` does not cover project-wide context, success conditions, step-by-step scripts or potential/recommended approach unless the project requires / specifying user-defined document format specifications / specifying exact procedural protocols that AI cannot invent.
[ ] `system_prompt_prefix` sets the executor's persona, expertise, style, role, or hard behavior constraints, not a duplicate of `completion_criteria` or `initial_hint`.
[ ] Use `max_attempts: 1` for execution-only subtasks, tasks that not benefit from inner retries, and with explicit `❌ not completed: <reason>` instructions.
[ ] Use `max_attempts: 2-3` for top-level tasks and targeted uncertain work. Use more for active implementation tasks.
[ ] Use `model: default` for reasoning-heavy tasks; use `model: lite` for deterministic execution tasks.

### 10.8 Other Important Rules

#### 10.8.1 Anti-Hack Patterns

[ ] `completion_criteria` and `initial_hint` should define negative constraints.
[ ] Complex implementations include a separate sibling anti-hack subtask after implementation.
[ ] Anti-hack subtasks use `system_prompt_prefix` to forbid modifying source code, tests, configs, data, generated artifacts, or other protected files.
[ ] Anti-hack subtasks are not used extensively, and should not be added when they are actually doing repeated work or themselves are not trustworthy.
[ ] Anti-hack subtasks can be lighter when the change is small and low-risk, or the user explicitly prioritizes brevity.

#### 10.8.2 `git` Usage

[ ] `git` is used as a durable ledger of task progress and evidence when the project uses git.
[ ] Tasks should inspect `git status` for residual states from previous attempts, and identify related changes.
[ ] Multiple branches are used for isolated experiments, ablations, or risky alternatives.
[ ] Destructive git operations are forbidden unless intentionally allowed by the user or project rules.
[ ] Reverts preserve decision evidence for experiments or optimization work even when implementation code is removed.

#### 10.8.3 For Todo Authors (You)

[ ] This guide or subguides are re-read when you feel ambiguity when writing todos.

### 10.9 Task-Specific Subguides

[ ] The relevant task-specific subguide is read before writing domain-specific tasks.
[ ] Only relevant subguides are read; do not force unrelated domain guidance into `todos.yaml`.

### ⚠️ 10.10 Critical Pitfalls —— Double Check

⚠️ Double check these rules —— They are not only runtime-fatal issues, but also high-cost design mistakes that can waste a whole day's work:

[ ] Does `todos.yaml` avoid referencing AutoAgent's source code, execution details, this guide or subguides? —— Executors cannot see them
[ ] Is `todos.yaml` fully autonomous asking the user to confirm plans, choices, or next steps? —— May cause unexpected stops or confusions
[ ] Are `ai_orchestrator.strategy`, `stop_condition`, and `last_result` sufficient for Scheduler AI to choose, retry, branch, and stop correctly? —— Otherwise scheduler will not schedule correctly
[ ] Does files configured by `last_result: type: file` exist, or created BEFORE scheduler could analyze? —— Otherwise scheduler will misleadingly think this task is not completed
[ ] Is `${workspace}` used in `last_result: type: file` to reference relative paths? —— Otherwise scheduler will not find the correct path, misleadingly thinking that task is not completed
[ ] Are important intermediate results written to files instead of relying on conversation and reasoning context? —— Without this, subsequent tasks will never finish their work
[ ] Does `initial_hint` explicitly state what prior tasks are doing, what files it generate should be read by this task, when cross-task communication is required? —— Otherwise they cannot obtain prior task's information
[ ] Are `long_running` used for commands that may run >1 minute without redirections or interactive flags? —— Otherwise long-running commands will never succeed
[ ] Are internal markers explicitly instructed for hard-to-decide situations? —— Otherwise failures cannot be correctly identified and confusions will be introduced
[ ] Are you assuming that AutoAgent will internally maintain filesystem, `git`, read behaviour, etc? —— May cause AI confusion since AutoAgent doesn't maintain them
[ ] Are fast validation mode used if present before expensive full validation runs? —— Otherwise efficiency will be significantly degraded 
[ ] Are `completion_criteria` specific, measurable, and verifiable enough? —— May largely degrade AI's output quality
[ ] Does `completion_criteria` and `initial_hint` include negative constraints, and are anti-hack sibling subtask introduced for complex implementations? —— Otherwise AI may hack when encountering difficulty
[ ] Does `description` or `initial_hint` include potential/recommended approach unless the project requires? —— May largely degrade AI's creativity
[ ] Are `git` used to track each task's work if the project uses `git`? —— Otherwise work cannot be traced or audited when finished
[ ] Are destructive `git` operations forbidden unless the user, project rules, or subguides explicitly allow them? —— May accidentally break project state
[ ] Are documentations preserved when reverting code for iterative optimization or experiments? —— May largely degrade AI's output quality since they may do repeated failed work
