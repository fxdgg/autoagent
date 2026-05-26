# Best Practice: Build & Ship

## 1. Four Core Principles

Patterns for **implementing features, fixing bugs, and refactoring** — the most common software engineering task. These tasks typically involve **large codebases (10k+ lines)** where changes span multiple modules, so the four core principles below must be enforced:

1. **Module-based splitting at the top level** — Split by module/subsystem boundary into **independent top-level tasks**, not subtasks of one big nested task. Each top-level task owns one module's changes end-to-end (replan + implement + anti-hack). Top-level tasks are the unit of independent retry (see §3).

2. **Replan before implement** — Every module task begins with a lightweight replan subtask that reads the current codebase state (which may have changed from earlier modules) and the original design plan, then updates the design doc as needed: fix issues left by earlier tasks, add missing constraints, adjust interfaces, extend the file scope. Since linear mode cannot retry earlier tasks, the replan subtask is responsible for making `design_plan/` the accurate single source of truth before implementation starts.

3. **Anti-hack verification** — Every top-level module task must contain (as its last subtask) a dedicated `max_attempts: 1` verification subtask that re-runs the module's tests AND checks explicit diff evidence (`git diff --name-only <recorded-base>..HEAD` plus targeted `git diff` on tests/contracts) for scope violations, weakened assertions, skipped-test annotations, and modified public schemas. Without this, the AI can silently "pass" by gaming the tests (see main guide §6.1).

4. **Unit test discipline** — Every implementation subtask that changes behavior must include unit tests for that behavior, written in the same subtask as the code (not a later subtask). Tests cover: happy path, edge cases, error cases, and any regression scenario that motivated the change.

---

## 2. Recommended Structure

```
├── nested (prerequisite check + design)
|   ├── build and run tests without modifications           (simple or long_running, max_attempts: 1, model: lite, fatal: true) <!-- OPTIONAL: skip if project is built from scratch, or cannot be partially built / tested. -->
|   ├── write design_plan/ + guardrails.md                  (simple)
|   └── review design_plan/ for completeness                (simple, max_attempts: 5) <!-- If user provided design_plan/, review only the diff from the write subtask -->
├── nested (module 1)
|   ├── replan: review current state + update local plan    (simple)
|   ├── implement + test                                    (simple or long_running)
|   └── anti-hack verify                                    (simple or long_running, max_attempts: 1)
├── nested (module 2)
|   ├── replan: review current state + update local plan    (simple)
|   ├── implement + test                                    (simple or long_running)
|   └── anti-hack verify                                    (simple or long_running, max_attempts: 1)
...
├── nested (module N)
|   ├── replan: review current state + update local plan    (simple)
|   ├── implement + test                                    (simple or long_running)
|   └── anti-hack verify                                    (simple or long_running, max_attempts: 1)
└── nested (integration)
    ├── integration tests + cross-module fixes              (simple or long_running)
    └── global anti-hack + full suite verification          (simple or long_running, max_attempts: 1)
```

Key Considerations:

- **Separate analysis from implementation**: design plan in one task, implementation in others (see main guide §4.2).
- The "review design_plan/ for completeness" task should have high `max_attempts` so that the design plan can be thoroughly reviewed multiple times.
- Anti-hack verification subtasks should use `max_attempts: 1` — failures should propagate to the parent for proper retry.
- Build/test subtask in the prerequisite task should use `fatal: true` — if the project cannot build or pass tests without any modification, this is a prerequisite failure that `fatal_analysis` should handle. It is fatal analysis task's responsibility to define the fix boundary. **Skip build/test subtask entirely if the project is built from scratch, or cannot be partially built / tested.**.
- Use `long_running` for build / test / verification a if they contain commands that may exceed one minute.
- Executors that output `❌ not completed` or `❌ FATAL` must append an entry to `error_report.md` before outputting the marker.

---

## 3. Key Insights

1. **Why top-level splitting (not one big nested)?**

In AI scheduling mode, the scheduler selects one top-level task per round and can redispatch a failed or stale task according to `ai_orchestrator.strategy`. Splitting by module gives the scheduler small, independent recovery units: if the DB task fails, the scheduler can rerun that task without rerunning the CSV parser, service, route, or integration tasks.

Do not put all modules into one large `nested` task. The scheduler cannot partially select inner subtasks; once it selects a top-level `nested` task, its subtasks run through the normal sequential executor. A one-big-nested design therefore hides useful scheduling boundaries and makes recovery coarser.

2. **`looping` is generally not recommended for Build & Ship**, since the goal of implementation is typically "to reach a specific end state".

3. **Details for task decomposition when module-based splitting is required**:
  - **Each `nested` task generally has three subtasks**: `replan`, `implement + test`, and `anti-hack verify`.
  - **A final top-level integration task is added at the end**. This task sees the full codebase, runs the whole test suite, and fixes cross-module bugs only now visible. Its workload is not large because each module has already been unit-tested in isolation.

4. **Anti-hack subtask should explicitly output `❌ not completed: <reason>` when anti-hack check fails** for correct failure propagation (see main guide rule 18 / §4.7).

---

## 4. The Role of `design_plan/` and `guardrails.md`

The analysis task produces **two artifacts of different kinds**:

- **`design_plan/`** — a real design doc (architecture + per-submodule design). Long-lived intent. What the system *is*.
- **`guardrails.md`** — a short audit-data file (baseline, scope whitelist, revision log). Consumed only by anti-hack. What the build is *allowed* to touch.

AutoAgent system does **not** enforce `design_plan/` or `guardrails.md` semantics automatically. They are file-backed conventions. Every task that depends on them must read them explicitly, and every verifier must check them explicitly.

### 4.1 What each artifact holds

| Artifact | Holds | Consumed by |
|----------|-------|-------------|
| `design_plan/index.md` | System overview, architecture, document directory | Every module task (reads for system context and to locate module-specific docs) |
| `design_plan/<module>.md` | One per top-level module task: responsibility, public interface, internal design (error handling, state management, validation rules), test strategy, dependencies | The owning module task (authoritative); adjacent modules may peek |
| `guardrails.md` | Clean baseline commit (SHA + timestamp), scope whitelist (allowed files per module), append-only revision log, and module-start SHA markers | All anti-hack subtasks — the single oracle for "what changed", "what was allowed", and "was the change declared" |

### 4.2 Artifact structure

Three skeletons below. `design_plan/` must be **thorough on all design decisions** — error handling protocols, state transitions, edge-case behavior, validation rules, concurrency semantics, etc. — because any design point not explicitly specified will be "freely invented" by the implementation AI. The only thing excluded from design_plan/ is pseudocode / line-level implementation details. `guardrails.md` is audit data only.

**`design_plan/index.md`:**

```markdown
# Design Plan — Index

## §1 Overview
One paragraph: goal, scope, non-goals.

## §2 Architecture
- Components / layers and their responsibilities (high-level; details per module live in <module>.md)
- Major control flows
- ASCII diagram (optional)

## §3 Document Directory
| Document | Description |
| <relative/path/to/document> | <one-line description of this document> |

## §4 Task-Module Assignment
Which task is responsible for which module document(s).
| Module Document | Responsible Task(s) |
| design_plan/<module_1>.md | <task id(s)> |
| design_plan/<module_2>.md | <task id(s)> |
```

**IMPORTANT**: Task decomposition is performed by YOU, not the executor that writes design plan. Executor can only change each module's **assignment**. Therefore, you MUST explicitly tell the plan executor each subsequent task's responsibility, otherwise it doesn't know how will this plan be executed. See the complete example in §5 for guidance.

**`design_plan/<module>.md`** (one per top-level module task):

```markdown
# Design Plan — <Module Name>

## §1 Responsibility
- What this module owns: <one sentence>
- Explicitly NOT owned: <what callers must handle themselves>

## §2 Public Interface
Signatures this module exposes with full semantics: parameters, return values, error conditions, side effects.

## §3 Internal Design
- Key data structures: <what and why>
- Key algorithms / control flow: <the non-obvious parts>
- Design choices and reasoning: <alternatives considered, why this one>
- Error handling protocol: <how each error type is detected, propagated, and recovered>
- State management: <what state is held, lifecycle, invariants>
- Validation rules: <input validation, preconditions, postconditions>

## §4 Test Strategy
Test *categories* only (concrete cases are designed by the implementation task).
- happy: <shape of happy-path cases>
- edge: <specific edge conditions>
- error: <failure modes to cover, expected error behavior>
- regression (if any): <specific scenarios this module must not regress>

## §5 Dependencies
- Calls into: <list of other modules>
- Called from: <list of other modules>
```

**`guardrails.md`:**

```markdown
# Guardrails

<!-- RULES: §1 is immutable after Task 1. §2 may only grow via `scope-extend:` markers in §3. §3 is append-only. -->

## §1 Baseline
- baseline commit SHA: <sha>
- baseline timestamp: <ISO-8601>
- <validation command 1> result: <result>
- <validation command 2>: <result>

## §2 Scope Whitelist (Module → Allowed Files)
Initial estimate. Replan subtasks may extend this via `scope-extend:` markers in §3.
- module <id> (<module_name>): <file1>, <file2>, ...
- ... (one line per module task)
- integration: <file1>, <file2>, ...
- design_plan/ and guardrails.md itself: <update rules of design_plan/ and guardrails.md>

## §3 Revision Log (Append-Only)
Covers edits to **both** `design_plan/**` and `guardrails.md`.
- baseline: task 1 — <sha> — scope whitelist written; design_plan/ authored
- module-start: <module> — <sha> — before task <id> edits
- scope-extend: <module> — <new files> — <why needed>
- contract-update: design_plan/<module>.md §<sec> — <old> → <new> — <why>
- gap-fill: design_plan/<module>.md §<sec> — <what> — <why substantial>
- ... (append-only; never rewrite earlier entries)
```

Reality often diverges during large implementations. The rule: **let design_plan evolve, let guardrails §2 extend with justification, keep guardrails §1 immutable**.

**design_plan/**: A module task may edit its own `<module>.md`, or append to `index.md`, when implementation surfaces a real contract bug. Changes should be committed **with** the dependent code.
**guardrails.md**: `§2` may be extended by replan subtasks via `scope-extend:` entries in `§3`. `§3 Revision Log` is always append-only. `§1` is immutable.

Revision-log entries should use machine-readable marker prefixes so anti-hack can match diffs mechanically:

- `module-start: <module> — <sha> — before task <id> edits`
- `scope-extend: <module> — <new files> — <why needed>`
- `contract-update: <path> §<sec> — <old> → <new> — <why>`
- `gap-fill: <path> §<sec> — <what> — <why substantial>`
- `contract-hack-detected: <path> §<sec> — <reason>` (only used by verifiers when reporting a failure; do not commit this as a fix)

### 4.4 Prerequisite, module-start, and diff baseline policy

Every top-level task after Task 1 must begin with a replan subtask that inspects the current state. Since linear mode cannot retry earlier tasks, the replan subtask is responsible for fixing any issues and making design_plan/ the single source of truth.

Required policy:

1. **Replan as prerequisite handling**: the replan subtask verifies design_plan/ and guardrails.md exist and are consistent with the current codebase. If earlier tasks left errors or gaps, fix them directly — do not output `❌ not completed` to retry earlier tasks (impossible in linear mode). Update design_plan/ so it is accurate, then the implementation subtask can work purely from the design doc.
2. **Module-start SHA**: each module's replan subtask records the current `HEAD` as `module-start: <module> — <sha> — before task <id> edits` in `guardrails.md §3` before making any changes. The module anti-hack subtask diffs from that SHA, not from an implicit "previous task completion commit".
3. **Diff commands**: use `git diff --name-only <recorded-sha>..HEAD` for scope checks, and targeted `git diff <recorded-sha>..HEAD -- tests/ design_plan/ guardrails.md <schema/api paths>` for integrity checks. `git diff --stat` is useful as a summary, but is not sufficient evidence by itself.
4. **Global baseline**: final global anti-hack diffs from `guardrails.md §1` baseline SHA. `guardrails.md §1` must not change after Task 1. `§2` may only grow via `scope-extend:` entries recorded in `§3`.

### 4.5 When the user provides a design doc themselves

**Key insight**: User-provided design docs are **NOT authoritative** either. But the main difference is that user-provided design docs typically have **higher quality** since they have undergone multiple optimizations. In this case, what the analysis task (Task 1) should do is **not re-authoring, but gap-filling**:

- Read the user's design plan end-to-end.
- **Only if a section is materially missing** (e.g. a module has no `<module>.md`, `index.md` has no Architecture section, or a contract needed by anti-hack is entirely undefined) may Task 1 edit the design_plan directly to fill the gap. "Could be clearer" / stylistic / reorganization do NOT qualify.
- Always produce `guardrails.md` from scratch (baseline + scope whitelist + initial revision log entry — including a `gap-fill:` log entry for any substantial gap-fill performed in step 2).
- The commit at the end of Task 1 **is** the baseline; `guardrails.md §1` records its SHA.

**Module tasks** in this mode behave exactly as in default mode: they may edit `design_plan/**` under the same "contract-bug-forces-update" rules. The fact that the user originally provided the doc grants no special immunity — but the default tendency remains "edit minimally".

**Global anti-hack** is identical to default mode: diff every file under `design_plan/**` and `guardrails.md` against the Task-1 baseline commit. Every diff chunk must have a matching machine-readable `guardrails.md §3` marker.

**IMPORTANT**: It is strongly recommended to ask the user to provide a design plan by themselves. Designing a whole plan automatically in a single task will typically degrade plan's quality significantly. **ALWAYS ask the user if they have not provided a design plan, when possible**.

---

## 5. Complete Example

Use this example to understand the recommended AI-scheduling-mode structure for Build & Ship. Replace every `<placeholder>` token with project-specific content; do not copy placeholder wording into real tasks. `<!-- xxx -->` are comments that explain this example in detail, so do not include them into real tasks either.

```yaml
description: |
  # Project: E-Commerce Order Management

  ## Goal
  Add a bulk order processing feature that allows administrators to upload a CSV
  of orders, validate them, process payments, and send confirmation emails. The
  feature spans database, service, API, and notification modules.

  ## Architecture
  - src/db/orders.py — Order database models and queries
  - src/db/payments.py — Payment transaction records
  - src/services/order_service.py — Order business logic
  - src/services/payment_service.py — Payment processing integration
  - src/services/notification_service.py — Email notification dispatch
  - src/routes/admin.py — Admin API route handlers
  - src/utils/csv_parser.py — CSV parsing utilities
  - tests/unit/ — Unit tests (mirrors src/ structure)
  - tests/integration/ — Integration tests
  - package: Python 3.11 + FastAPI + SQLAlchemy + pytest

  ## Design & Audit Docs
  - design_plan/index.md — system overview, architecture, cross-module interface contracts, integration risks (Must Read)
  - design_plan/<module>.md — one per module: responsibility, public interface, internal design, test strategy, dependencies (Must Read for the owning module task; other modules Read on Demand)
  - guardrails.md — baseline commit, scope whitelist, revision log, module-start SHA markers (Must Read for anti-hack subtasks)
  - error_report.md — execution error records; executors write on failure, only failure/fatal analysis task reads (P1)

  ## Key Commands
  - Install: pip install -e ".[dev]"
  - Unit tests: pytest tests/unit/
  - Integration tests: pytest tests/integration/
  - Full suite: pytest
  - Lint: ruff check src/ tests/
  - Type check: mypy src/

  ## Hard Constraints
  - Do NOT modify existing API endpoint schemas (request/response formats).
  - Do NOT remove, weaken, skip, or rewrite existing tests.
  - Do NOT change database migration files or existing model schemas.
  - Do NOT modify the payment gateway integration contract.
  - Do NOT change notification templates or delivery logic for existing flows.
  - Each module task's changes must be scoped to its own allowed-file list in
    guardrails.md §2.

  ## Rules
  - Fully autonomous: never ask the user questions.
  - Persist design to design_plan/index.md and design_plan/<module>.md;
    persist audit data (baseline, scope whitelist, revision log, module-start
    SHAs) to guardrails.md.
  - Split implementation into one scheduler-visible top-level task per module;
    dependencies and redispatch decisions belong in ai_orchestrator.strategy.
  - If a task is scheduled before prerequisites exist, it must report
    `❌ not completed: <reason>` rather than compensating by rewriting unrelated
    work; the scheduler will redispatch the missing producer task.
  - Every top-level task must be idempotent enough to run 0, 1, or many times.
  - Every module task must include unit tests for new code AND an anti-hack
    verification subtask.
  - Commit changes at each subtask completion.
  - Before starting any implementation subtask, run `git status`; if
    uncommitted changes exist from a previous retry, inspect and either
    continue from them or `git checkout .` to discard (see main guide §4.10).
  - Before editing a module, record the current `HEAD` in guardrails.md §3 as
    `module-start: <module> — <sha> — before task <id> edits`; anti-hack
    subtasks diff from this SHA.
  - guardrails.md §1 and §2 are immutable after Task 1; only §3 may be appended.
  - Any verification subtask that may run longer than one minute should be
    changed from `simple` to `long_running`, keeping `max_attempts: 1`.
  - The final integration task is scheduled only after module tasks succeed; it
    fixes cross-module bugs but must not rewrite module-internal logic.
  - design_plan/ may be edited only under the contract-bug-forces-update rules:
    a module task may edit its own <module>.md or append to index.md when
    implementation surfaces a real contract bug. Every design_plan change must
    be committed with the dependent code and recorded in guardrails.md §3 with
    a `contract-update:` or `gap-fill:` marker.
  - guardrails.md §2 may only grow via `scope-extend:` entries recorded in §3.
    §3 is append-only. §1 is immutable after Task 1.

  ## Reference Docs
  - P0 Must Read: docs/api_spec.md — API design patterns and admin endpoint conventions
  - P0 Must Read: docs/testing_guide.md — Test structure, fixtures, and mocking patterns
  - P1 Read Before Related Work: docs/payment_integration.md — Payment gateway contract
  - P1 Read Before Related Work: docs/database_schema.md — Current schema and migration rules

ai_orchestrator:
  strategy: |
    1. Bootstrap: run Task 1 (Baseline and design plan) first. If any later task
       reports missing design_plan/ or guardrails.md artifacts, redispatch Task 1.
    2. After Task 1 succeeds, run Tasks 2–5 in any order (they are independent
       module tasks).
    3. Run Task 6 only after Tasks 2–5 have all succeeded. If Task 6 reports
       missing or broken module artifacts, redispatch the owning module task.
    4. If the fatal_analysis task outputs `❌ not completed: <reason>`, stop
       scheduling and report the reason to the user.
    5. If a task fails for a code/test issue inside its own scope, rerun that same
       task up to its max_attempts. Prefer producer redispatch for prerequisite
       failures, not consumer retries.
    6. Stop when Task 6 succeeds, or after 5 consecutive scheduling rounds with
       no progress. Do not run tasks whose successful result is already current
       unless a downstream failure identifies that task as the owner.
  max_rounds: 30
  stop_condition: |
    Stop when Task 6 (Integration: end-to-end tests, full suite, global anti-hack)
    succeeds after all module tasks have succeeded. Otherwise stop after 5
    consecutive no-progress rounds and report the blocking task and reason.
  last_result:
    1:
      type: file
      path:
        - ${workspace}/guardrails.md
        - ${workspace}/design_plan/index.md
    2:
      type: response
    3:
      type: response
    4:
      type: response
    5:
      type: response
    6:
      type: response

tasks:
  # ── Fatal Analysis ─────────────────────────────────────────────────────────
  - id: fatal_analysis
    name: "Diagnose and resolve fatal prerequisite failures"
    description: |
      Handle hard prerequisites or global blockers that prevent any task from
      proceeding. Scheduler schedules this task when other tasks report
      `❌ not completed: <hard prerequisites or global blocker issues>`.
    type: simple
    max_attempts: 2
    completion_criteria: |
      1. The root cause of the fatal failure claimed by previous failed task is identified.
      2. If fixable within user-defined allowed scope, the correct fix is applied and verified.
      3. If not fixable within allowed scope, AutoAgent is stopped with a clear explanation.
    system_prompt_prefix: |
      You are a diagnostic engineer. You may inspect any file and fix failures
      claimed by previous failed task within the user-defined allowed scope.
    initial_hint: |
      Read error_report.md for the fatal error details.

      Allowed fixes:
        - Fix build or environment issues (install missing deps, fix config, etc.)
        - Fix code bugs within the allowed-file scope of the failing task
        - Revert changes from a previously failed task that left the workspace in a broken state

      Not allowed:
        - Modify files outside the failing task's allowed scope
        - Change design_plan/ or guardrails.md §1/§2 (only append to §3 if needed)

  # ── Task 1: Prerequisite Check + Design ────────────────────────────────────
  - id: 1
    name: "Verify prerequisites and write design_plan/ + guardrails.md"
    description: |
      Analyze the codebase, produce design_plan/ and guardrails.md, and commit
      the clean baseline consumed by all later module and integration tasks.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. <build command> exits 0. <!-- Remove if no existing code to build -->
      2. <test command> exits 0. <!-- Remove if no existing tests -->
      3. design_plan/index.md is produced with §1 Overview, §2 Architecture,
         §3 Cross-Module Interface Contracts, §4 Integration Risks,
         §5 Task-Module Assignment.
      4. One design_plan/<module>.md is produced for each top-level module task
         (tasks 2–5), each with §1 Responsibility, §2 Public Interface,
         §3 Internal Design, §4 Test Strategy (categories only), §5 Dependencies.
      5. design_plan/ is reviewed for completeness: every design decision that
         would be "freely invented" by implementation is explicitly complemented.
      6. guardrails.md is produced with §1 Baseline, §2 Scope Whitelist,
         §3 Revision Log.
      7. error_report.md exists with a header, initially empty.
      8. No source code modified.
    subtasks:
      - id: 1.1
        name: "Build and run tests without modifications"
        type: simple
        max_attempts: 1
        model: lite
        fatal: true
        completion_criteria: |
          1. <build command> exits 0.
          2. <test command> exits 0.
          3. git diff --name-only shows no changes.
        system_prompt_prefix: |
          You are a build engineer. Do NOT modify source code, tests, configs, or project files.
        initial_hint: |
          <hint on running build and test commands>

          If build or test fails, first retry the failing command once to rule out transient issues
          (e.g. resource busy, file locked, network flake).
          Only if the failure persists after retry, append an entry to error_report.md with the
          failure details, then output `❌ FATAL: <build/test failure reason>` so that a dedicated
          analysis task can handle it.

      <!-- If user has provided a design plan, replace subtask 1.2 with the variant
           defined in section 6.1 of this guide. -->
      - id: 1.2
        name: "Write design_plan/, guardrails.md, and error_report.md"
        type: simple
        completion_criteria: |
          1. design_plan/index.md produced with §1 Overview, §2 Architecture,
             §3 Cross-Module Interface Contracts, §4 Integration Risks,
             §5 Task-Module Assignment.
          2. One design_plan/<module>.md is produced per module in the project's
             own module decomposition.
             A single task may span multiple modules (and thus multiple .md files);
             a single module may also be shared by multiple tasks. The assignment
             of which task works on which module document is recorded in index.md
             §5 Task-Module Assignment and must be consistent.
          3. guardrails.md is produced with §1 Baseline, §2 Scope Whitelist
             (one entry per task), §3 Revision Log.
          4. error_report.md exists with a header, initially empty.
          5. No source files, tests, configs, or scripts are modified.
        system_prompt_prefix: |
          You are a global planner. Your role is to produce the master design plan
          that every subsequent task will execute against. You must think holistically
          across the entire project — every module, every cross-module interface,
          every error path — and ensure the design plan is complete, unambiguous,
          and internally consistent. No implementation detail should be left for
          later tasks to invent; the only thing excluded is pseudocode / line-level
          code. Do NOT modify source code, tests, or configs.
        initial_hint: |
          <Write the whole project description here. Since this task needs to write
          the whole design plan, this task must have all the information of this project.>

          CRITICAL: You are producing the master design plan that ALL subsequent
          tasks will execute against.

          ## Task decomposition is FIXED

          The tasks below have already been decomposed in the todo list. This
          decomposition is NOT negotiable — you MUST NOT change task boundaries,
          merge tasks, or create new tasks. The only thing you may adjust is which
          module document(s) each task is responsible for (recorded in index.md §5).

          ## Subsequent tasks and their work

          You MUST tell every later executor exactly what they are responsible for:

          | Task ID | Type   | Task Name | Work Description |
          |---------|--------|-----------|------------------|
          | 2       | nested | Module: <module_name_1> | <what task 2 implements> |
          | 3       | nested | Module: <module_name_2> | <what task 3 implements> |
          | ...     |        | ...       | ...              |
          | <N>     | nested | Module: <module_name_last> | <what task N implements> |
          | <last>  | nested | Integration: end-to-end tests, full suite, global anti-hack | <what the integration task does> |

          Replace the table above with the real task list from the actual todo.
          For each module a task is responsible for, create one
          design_plan/<module>.md (use the module name as the filename stem).
          If a task spans multiple modules, create one .md per module.

          ## Module decomposition follows the project design

          Modules are defined by the project's own architecture — NOT by a 1:1
          mapping to tasks. A task may own multiple module documents; a module
          document may be shared by multiple tasks.

          ## Design Plan Format

          1. Create design_plan/index.md exactly in this Markdown format:
             # Design Plan — Index

             ## §1 Overview
             One paragraph: goal, scope, non-goals.

             ## §2 Architecture
             - Components / layers and their responsibilities (high-level;
               details per module live in <module>.md)
             - Major control flows
             - ASCII diagram (optional)

             ## §3 Cross-Module Interface Contracts
             For every cross-module boundary, specify:
             - Signatures (function/method names, parameter types, return types)
             - Error codes / exceptions and their semantics
             - Atomicity guarantees and side-effect promises
             - Data exchange formats (DTOs, events, schemas)

             ## §4 Integration Risks
             - Transaction boundary issues
             - Call-order dependencies
             - Partial-failure semantics
             - Other cross-module risks

             ## §5 Task-Module Assignment
             Which task is responsible for which module document(s).
             | Module Document | Responsible Task(s) |
             | design_plan/<module_1>.md | <task id(s)> |
             | design_plan/<module_2>.md | <task id(s)> |

          2. Create one design_plan/<module>.md per module exactly in this format:
             # Design Plan — <Module Name>

             ## §1 Responsibility
             - What this module owns: <one sentence>
             - Explicitly NOT owned: <what callers must handle themselves>

             ## §2 Public Interface
             Signatures this module exposes with full semantics: parameters,
             return values, error conditions, side effects.

             ## §3 Internal Design
             - Key data structures: <what and why>
             - Key algorithms / control flow: <the non-obvious parts>
             - Design choices and reasoning: <alternatives considered, why this one>
             - Error handling protocol: <how each error type is detected,
               propagated, and recovered>
             - State management: <what state is held, lifecycle, invariants>
             - Validation rules: <input validation, preconditions, postconditions>

             ## §4 Test Strategy
             Test *categories* only (concrete cases are designed by the
             implementation task).
             - happy: <shape of happy-path cases>
             - edge: <specific edge conditions>
             - error: <failure modes to cover, expected error behavior>
             - regression (if any): <specific scenarios this module must
               not regress>

             ## §5 Dependencies
             - Calls into: <list of other modules>
             - Called from: <list of other modules>

          3. Create guardrails.md exactly in this Markdown format:
             # Guardrails

             <!-- RULES: §1 is immutable after Task 1. §2 may only grow via
             `scope-extend:` markers in §3. §3 is append-only. -->

             ## §1 Baseline
             - baseline commit SHA: <sha>
             - baseline timestamp: <ISO-8601>
             - <validation command 1> result: <result>
             - <validation command 2>: <result>

             ## §2 Scope Whitelist (Module → Allowed Files)
             Initial estimate. Replan subtasks may extend this via
             `scope-extend:` markers in §3.
             - module <id> (<module_name>): <file1>, <file2>, ...
             - ... (one line per module task)
             - integration: <file1>, <file2>, ...
             - design_plan/ and guardrails.md itself: <update rules of
               design_plan/ and guardrails.md>

             ## §3 Revision Log (Append-Only)
             Covers edits to **both** `design_plan/**` and `guardrails.md`.
             - baseline: task 1 — <sha> — scope whitelist written;
               design_plan/ authored

          4. Create error_report.md exactly in this Markdown format:
             # Error Report — <project name>

             (none yet)

          design_plan/ must be thorough: every design decision that the
          implementation AI would otherwise invent freely must be explicitly
          specified (error handling protocols, state transitions, validation
          rules, concurrency semantics, cross-module interface contracts,
          integration risks, etc.). The only thing excluded from design_plan/
          is pseudocode / line-level implementation details. guardrails is
          audit data, not documentation.

          Commit all of them together; that commit is the baseline for all
          later anti-hack subtasks. Do NOT modify source code in this task.

      - id: 1.3
        name: "Review design_plan/ for completeness"
        type: simple
        max_attempts: 5
        completion_criteria: |
          1. index.md §5 Task-Module Assignment lists all module docs and
             assignments are reasonable and applicable.
          2. index.md §3 Cross-Module Interface Contracts and §4 Integration
             Risks are complete and actionable.
          3. Every module doc has all five sections and no design point is
             ambiguous enough that two reasonable implementations would
             behave differently.
          4. If gaps are found, they are filled directly in design_plan/ and
             committed, then output `❌ not completed: task 1.3 should be
             retried to review once more` so that another reviewer can
             review it again.
          5. No source files, tests, configs, or scripts are modified.
        system_prompt_prefix: |
          You are a design reviewer. Your job is to find underspecified design
          points that would force the implementation AI to guess. Do NOT modify
          source code, tests, or configs.
        initial_hint: |
          Read every file in design_plan/ carefully. For each module, check:

          - Does index.md §5 Task-Module Assignment list all module docs?
          - Are index.md §3 Cross-Module Interface Contracts complete and
            actionable (signatures, error codes, atomicity, data formats)?
          - Are index.md §4 Integration Risks thorough (transaction boundaries,
            call order, partial-failure semantics)?
          - Does every module doc have all five sections?
          - Is any design point ambiguous enough that two reasonable
            implementations would behave differently?

          For every gap found, fill it directly in the relevant design_plan/
          file. Once complete:
          1. Record in guardrails.md §3:
             `gap-fill: <path> §<sec> — <what> — <why substantial>`
          2. commit every addition together;
          3. output `❌ not completed: task 1.3 should be retried to review
             once more` so that another reviewer can review it again.

  # ── Tasks 2–5: One top-level nested task per module ────────────────────────
  <!-- Repeat this pattern for each module. The example shows one module task. -->
  - id: 2
    name: "Module: <module_name>"
    description: |
      Implement and unit-test the <module_name> module, then verify scope and
      test integrity with an anti-hack subtask. Produces a concise final response for scheduler decisions.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. <module-specific implementation criteria>
      2. Unit tests for <module_name> pass.
      3. No files outside the <module_name> effective scope (original
         guardrails.md §2 entry + any `scope-extend:` additions) are modified,
         except design_plan/** updates justified by `contract-update:` markers
         and append-only guardrails.md §3 entries.
      4. <negative constraints for this module>
    subtasks:
      - id: 2.1
        name: "Replan <module_name>: review current state and update local plan"
        type: simple
        completion_criteria: |
          1. design_plan/<module_name>.md, design_plan/index.md, and
             guardrails.md have been read.
          2. Current codebase state has been inspected (git log, existing
             source files from earlier modules).
          3. If the original plan needs adjustments (new files needed,
             interface changes from earlier modules, scope changes, or
             issues from earlier tasks' work), design_plan/<module_name>.md
             is updated and guardrails.md §2 is extended with `scope-extend:`
             entries in §3.
          4. If earlier tasks left incorrect or incomplete design artifacts,
             they are fixed directly in design_plan/ (earlier tasks cannot
             be retried).
          5. Any updates are committed before implementation begins.
        initial_hint: |
          Read design_plan/<module_name>.md (your module) and
          design_plan/index.md (system architecture, cross-module interface
          contracts, and integration risks).
          Inspect the current codebase — earlier module tasks may have changed
          interfaces, added files, or updated contracts.

          Your job is to ensure design_plan/ is accurate and complete for this
          module BEFORE implementation starts. Earlier tasks cannot be retried —
          if they left issues in design_plan/, fix them here directly.

          1. Record the current `HEAD` in guardrails.md §3 as:
             `module-start: <module_name> — <sha> — before task 2 edits`
             This must be done before any edits.

          2. Specifically check and update:
             - If earlier modules changed interfaces that affect this module,
               update design_plan/<module_name>.md §2/§3 accordingly, and
               record in guardrails.md §3:
               `contract-update: <path> §<sec> — <old> → <new> — <why>`
             - If new files are needed (helpers, configs, migrations), extend
               guardrails.md §2 by appending the new files to the
               <module_name> row, and record in §3:
               `scope-extend: <module_name> — <new files> — <why needed>`

          3. If no changes needed, proceed without modifications.
          4. Commit any plan/scope updates before implementation begins.

      - id: 2.2
        name: "Implement <module_name> with unit tests"
        type: simple
        completion_criteria: |
          1. <module_name> implemented per the public interface in
             design_plan/<module_name>.md §2 (and, if it exposes cross-module
             edges, design_plan/index.md §3 and the interface contracts in §3).
          2. Unit tests in <test file path> cover **every category** listed in
             design_plan/<module_name>.md §4 (happy / edge / error). Concrete
             cases are designed by this task.
          3. <module test command> passes.
          4. Only files inside the <module_name> effective scope (original §2
             entry + `scope-extend:` additions) are modified, plus
             design_plan/** updates justified by `contract-update:` markers
             and append-only guardrails.md §3 entries.
          5. Changes committed.
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy should run this task only
          after its prerequisite tasks succeed. Verify prerequisite artifacts
          exist and pass. If missing or broken, output
          `❌ not completed: prerequisite artifact missing or broken: <artifact-or-test>`
          so the scheduler can redispatch the owning producer task.

          Read design_plan/<module_name>.md (your module) and
          design_plan/index.md (system architecture, cross-module interface
          contracts, and integration risks).
          Check guardrails.md §2 for the effective scope whitelist for
          <module_name> (including any `scope-extend:` additions from the
          replan subtask).
          Check git status first — discard residual changes from previous retry.
          Implement source code AND unit tests together.

          If you discover the contract is infeasible or wrong, you MAY update
          design_plan/ (<module_name>.md §2/§3 as appropriate, or index.md §3
          for cross-module changes) and append a guardrails.md §3 entry in the
          form `contract-update: <path> §<sec> — <old> → <new> — <why>`;
          commit the design_plan change alongside your code. NEVER widen
          guardrails.md §2 scope or delete a §4 test category just to pass.

          Run <module test command> before committing.

      - id: 2.3
        name: "Anti-hack verification for <module_name>"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are an anti-hack verifier. Your sole job is to detect constraint
          violations. Do NOT modify source code, tests, configs, scripts, or
          generated data.
        completion_criteria: |
          1. <module test command> exits with code 0.
          2. git diff --name-only <module_name-module-start-sha>..HEAD shows
             only files allowed by the <module_name> effective scope (original
             guardrails.md §2 entry + `scope-extend:` additions in §3 for this
             module), plus design_plan/** and guardrails.md §3 entries when
             justified by a matching `contract-update:` marker.
          3. No public contracts, tests, configs, scripts, generated outputs,
             or unrelated modules were modified.
          4. No removed/weakened assertions or @skip additions in the modified
             test file.
        initial_hint: |
          This is an execution-only verification subtask.
          1. Run: <module test command>
          2. Read the <module_name> `module-start:` SHA from guardrails.md §3.
             Run: git diff --name-only <module_name-module-start-sha>..HEAD
             Allowed files must be a subset of the <module_name> effective scope
             in guardrails.md §2 (plus design_plan/** and guardrails.md §3 only
             if a contract was updated with a matching `contract-update:` entry).
          3. Run: git diff <module_name-module-start-sha>..HEAD -- <test file path>
             and check for removed/weakened assertions or skipped-test
             annotations.
          4. <write all other anti-hack rules here based on global description
             and task-specific information>

          If verification result is 'FAIL', append an entry to error_report.md
          with the failure details, then output
          `❌ not completed: Anti-hack verification failed. Implementation task
          should be retried`
          so that the implementation task can be retried. Do not fix code by
          yourself.

  <!-- Repeat tasks 3–N for remaining modules following the same pattern as task 2. -->

  # ── Final Task: Integration + Global Anti-hack ─────────────────────────────
  - id: <last_id>
    name: "Integration: end-to-end tests, full suite, global anti-hack"
    description: |
      Add end-to-end coverage for the completed module set, run full validation,
      and perform global anti-hack verification before the scheduler stops.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Integration tests for the bulk order flow pass.
      2. Full `pytest` suite exits with code 0.
      3. ruff check and mypy pass with no errors.
      4. Module scope boundaries honored across all module tasks.
      5. No existing tests weakened anywhere in the repo.
    subtasks:
      - id: <last_id>.1
        name: "Write and pass integration tests"
        type: simple
        max_attempts: 3
        completion_criteria: |
          1. tests/integration/test_bulk_orders.py added, covering end-to-end
             CSV upload → DB commit → payment call → notification dispatch.
          2. pytest tests/integration/test_bulk_orders.py passes.
          3. If a cross-module bug is found, fix is scoped to the minimal
             module(s) responsible; module-internal logic refactors are not
             allowed — only bug fixes.
          4. Changes committed.
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy should run this task only
          after all module tasks (2–<N>) succeed. Verify these concrete
          artifacts exist and are non-trivial:
          <list all module source and test files>. Also run the module unit
          test commands. If any prerequisite artifact is missing or its module
          tests fail, output
          `❌ not completed: prerequisite module artifact missing or broken: <module>`
          so the scheduler can redispatch the owning module task.

          Write integration tests per cross-module interfaces documented in
          each design_plan/<module>.md §2 and §5, and any integration risks
          noted in design_plan/index.md §4. If a cross-module bug surfaces,
          fix it in the responsible module (keep fix minimal) and re-run the
          test. Do NOT rewrite module logic.

          Changes are committed once completed.

      - id: <last_id>.2
        name: "Global anti-hack and full-suite verification"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a test runner and code integrity verifier. Do NOT modify any
          files except for appending to error_report.md on failure.
        completion_criteria: |
          1. pytest (full suite including integration) exits with code 0.
          2. ruff check src/ tests/ exits with code 0.
          3. mypy src/ exits with code 0.
          4. git diff --name-only <guardrails-baseline-sha>..HEAD shows changes
             only in the effective scope (original guardrails.md §2 entries +
             `scope-extend:` additions in §3), plus design_plan/** and
             append-only guardrails.md §3 edits.
          5. No existing tests weakened: no removed assertions, no
             @pytest.mark.skip additions, no relaxed comparisons, no
             conditional test bypasses.
          6. No existing API schemas, migrations, or payment contracts modified.
          7. Every test category listed in any design_plan/<module>.md §4 has
             at least one concrete test function in the committed test files.
          8. **Contract integrity**: diff design_plan/** and guardrails.md
             (guardrails.md §1 baseline SHA vs current) and verify:
             a. every change in design_plan/** has a matching machine-readable
                `contract-update:` or `gap-fill:` entry in guardrails.md §3.
             b. no allowed-file list in guardrails.md §2 has been widened
                (§2 is immutable; any diff to §2 is `❌ not completed`).
             c. no §1 Baseline line in guardrails.md has been edited.
             d. no test category has been deleted from any
                design_plan/<module>.md §4.
        initial_hint: |
          This is an execution-only verification subtask. If the suite normally
          exceeds one minute, this subtask should be `type: long_running`.
          1. Run: pytest (full suite)
          2. Run: ruff check src/ tests/
          3. Run: mypy src/
          4. Read the baseline SHA from guardrails.md §1. Run:
             git diff --name-only <guardrails-baseline-sha>..HEAD
             Verify every changed source/test file appears in some module's
             allowed-file list in guardrails.md §2. design_plan/** and
             append-only guardrails.md §3 edits are allowed only with matching
             revision-log markers.
          5. Run: git diff <guardrails-baseline-sha>..HEAD -- tests/ across the
             whole repo — check for removed assertions, added
             @pytest.mark.skip / @xfail, relaxed comparisons, deleted tests.
          6. Verify each new source file has a corresponding test file.
          7. **Contract-hacking check**: run
               git show <guardrails-baseline-sha>:guardrails.md > /tmp/guard_v1.md
               diff /tmp/guard_v1.md guardrails.md
               git diff <guardrails-baseline-sha>..HEAD -- design_plan/
             Every diff chunk under design_plan/** must match a
             guardrails.md §3 `contract-update:` or `gap-fill:` entry. Any diff
             to guardrails.md §1 or §2 =
             `❌ not completed: contract-hacking guardrails §<sec>`. Any §4
             test-category deletion in design_plan/<module>.md =
             `❌ not completed: contract-hacking <module>.md §4`.

          If ANY check fails, output `❌ not completed: <reason>` with specific
          details. Do NOT fix code (see main guide §4.7 and §4.9).
```

---

## 6. Variants

### 6.1 When the user provides a design doc

When the user provides a `design_plan/` (see §4.5), Task 1.2 `completion_criteria` becomes:

```yaml
- id: 1.2
  name: "Write design_plan/, guardrails.md, and error_report.md"
  type: simple
  completion_criteria: |
    1. The assignment of which task works on which module document is recorded
       in index.md §5 Task-Module Assignment if missing.
    2. Any substantial gap in the user-provided design plan has been filled,
       with its own entry in guardrails.md §3 Revision Log.
    3. guardrails.md is produced with §1 Baseline, §2 Scope Whitelist
       (one entry per task), §3 Revision Log.
    4. error_report.md exists with a header, initially empty.
    5. No source files, tests, configs, or scripts are modified.
  system_prompt_prefix: |
    You are a global planner. Your role is to produce the master design plan
    that every subsequent task will execute against. You must think holistically
    across the entire project — every module, every cross-module interface,
    every error path — and ensure the design plan is complete, unambiguous,
    and internally consistent. No implementation detail should be left for
    later tasks to invent; the only thing excluded is pseudocode / line-level
    code. Do NOT modify source code, tests, or configs.
  initial_hint: |
    Read the user-provided design plan <path/to/design_plan> end-to-end.

    ## Task decomposition is FIXED

    The tasks below have already been decomposed in the todo list. This
    decomposition is NOT modifiable — you MUST NOT change task boundaries,
    merge tasks, or create new tasks. The only thing you may adjust is which
    module document(s) each task is responsible for.

    You should add a "Task-Module Assignment" section to index.md if missing:

    | Module Document | Responsible Task(s) |
    | design_plan/<module_1>.md | <task id(s)> |
    | design_plan/<module_2>.md | <task id(s)> |

    Modules are defined by the project's own architecture — NOT by a 1:1
    mapping to tasks. A task may own multiple module documents; a module
    document may be shared by multiple tasks.

    ## Subsequent tasks and their work

    You MUST tell every later executor exactly what they are responsible for:

    | Task ID | Type   | Task Name | Work Description |
    |---------|--------|-----------|------------------|
    | 2       | nested | Module: <module_name_1> | <what task 2 implements> |
    | 3       | nested | Module: <module_name_2> | <what task 3 implements> |
    | ...     |        | ...       | ...              |
    | <N>     | nested | Module: <module_name_last> | <what task N implements> |
    | <last>  | nested | Integration: end-to-end tests, full suite, global anti-hack | <what the integration task does> |

    Replace the table above with the real task list from the actual todo.

    ## guardrails.md Format

    Create guardrails.md exactly in this Markdown format:
      # Guardrails

      <!-- RULES: §1 is immutable after Task 1. §2 may only grow via
      `scope-extend:` markers in §3. §3 is append-only. -->

      ## §1 Baseline
      - baseline commit SHA: <sha>
      - baseline timestamp: <ISO-8601>
      - <validation command 1> result: <result> <!-- Delete this if no existing build / test exists. -->
      - <validation command 2>: <result> <!-- Delete this if no existing build / test exists. -->

      ## §2 Scope Whitelist (Module → Allowed Files)
      - module <id> (<module_name>): <file1>, <file2>, ...
      - ... (one line per module task)
      - integration: <file1>, <file2>, ...
      - design_plan/ and guardrails.md itself: <update rules of design_plan/ and guardrails.md>

      ## §3 Revision Log (Append-Only)
      - baseline: task 1 — <sha> — scope whitelist written; design_plan/ authored

    Your job is to fill any substantial gap (missing <module>.md for a module
    task, a contract needed by anti-hack that is entirely undefined, etc.) in
    the user-defined file. Cosmetic, stylistic, or reorganization edits are
    NOT performed.

    Any gap-fill edit should get its own entry in guardrails.md §3 Revision
    Log, in the form `gap-fill: <path> §<sec> — <what> — <why substantial>`.

    ## error_report.md Format

    Create error_report.md exactly in this Markdown format:
        # Error Report — <project name>

        (none yet)

    Commit all of them together; that commit is the baseline for all later
    anti-hack subtasks. Do NOT modify source code in this task.