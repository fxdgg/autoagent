# Best Practice: Build & Ship

## 1. Three Core Principles

Patterns for **implementing features, fixing bugs, and refactoring** — the most common software engineering task. These tasks typically involve **large codebases (10k+ lines)** where changes span multiple modules, so the three core principles below must be enforced:

1. **Module-based splitting at the top level** — Split by module/subsystem boundary into **independent top-level tasks**, not subtasks of one big nested task. In AI scheduling mode, top-level tasks are the scheduler's redispatch units: design each module task so it can run 0, 1, or many times without corrupting shared state.

2. **Anti-hack verification** — Every top-level module task must contain (as its last subtask) a dedicated `max_attempts: 1` verification subtask that re-runs the module's tests AND checks explicit diff evidence (`git diff --name-only <recorded-base>..HEAD` plus targeted `git diff` on tests/contracts) for scope violations, weakened assertions, `@skip` additions, and modified public schemas. Without this, the AI can silently "pass" by gaming the tests (see main guide §4.9).

3. **Unit test discipline** — Every implementation subtask that changes behavior must include unit tests for that behavior, written in the same subtask as the code (not a later subtask). Tests cover: happy path, edge cases, error cases, and any regression scenario that motivated the change.

---

## 2. Recommended Structure

| Task size | Structure |
|-----------|-----------|
| Single bug or small feature (< 3 files, < 1 module) | One top-level `simple` task |
| Feature or bug fix touching one module | One top-level `nested`: implement + test → anti-hack verify (`max_attempts: 1`) |
| Large feature / refactor spanning N modules, OR N independent bugs | **1 Analysis top-level task** + **N top-level `nested` tasks** + **1 top-level integration task** scheduled by `ai_orchestrator.strategy` (See §3) |
| Any of the above with build/test > 1 min | Use `long_running` for the verification subtask (see main guide rule 5 / §2.1) |

**Verifier type note**: the complete example below keeps verifier subtasks as `simple` for compactness. If any verifier command may exceed one minute (for example full `pytest`, `ruff`, `mypy`, integration tests, or large module tests), change that verifier's `type` to `long_running` while keeping `max_attempts: 1`, and the same `❌ not completed: <reason>` failure behavior.

---

## 3. Key Insights

1. **Why top-level splitting (not one big nested)?**

In AI scheduling mode, the scheduler selects one top-level task per round and can redispatch a failed or stale task according to `ai_orchestrator.strategy`. Splitting by module gives the scheduler small, independent recovery units: if the DB task fails, the scheduler can rerun that task without rerunning the CSV parser, service, route, or integration tasks.

Do not put all modules into one large `nested` task. The scheduler cannot partially select inner subtasks; once it selects a top-level `nested` task, its subtasks run through the normal sequential executor. A one-big-nested design therefore hides useful scheduling boundaries and makes recovery coarser.

2. **`looping` is generally not recommended for Build & Ship**, since the goal of implementation is typically "to reach a specific end state". Let the scheduler perform re-execution by redispatching top-level tasks.

3. **Details for task decomposition when module-based splitting is required**:
  - **Default flat at the top level**: prefer top-level `simple` / `long_running` / small `nested` tasks and let the scheduler handle ordering, dependency waits, and re-execution.
  - **Each Build & Ship module `nested` task generally has just two subtasks**: `implement + test` and `anti-hack verify`. This keeps enforced order local while leaving module-level scheduling to `ai_orchestrator.strategy`.
  - **A final top-level integration task is scheduled after module success**. It sees the full codebase, runs the whole test suite, and fixes cross-module bugs only now visible. Its workload is not large because each module has already been unit-tested in isolation.
  - **Put an analysis task in the graph** that designs an implementation plan (including per-module scope boundaries) and exposes scheduler-relevant artifacts via `last_result`.

4. **Prerequisite failures should be natural scheduler signals**: if a consumer task is dispatched before required artifacts exist, it should output `❌ not completed: <reason>`. The scheduler strategy can then rerun the missing producer task or wait for its successful `last_result`, instead of requiring the consumer task to compensate by rewriting unrelated work.

5. **Most Build & Ship `nested` module tasks can use `last_result: type: response`**. They usually have only two subtasks and the scheduler mainly needs the final success/failure summary. Use `last_result: type: file` only for producer tasks whose artifacts the scheduler must inspect across rounds (for example analysis, integration summary, benchmark/report files).

6. **Anti-hack subtask should explicitly output `❌ not completed: <reason>` when anti-hack check fails** for correct failure propagation (see main guide rule 18 / §4.7).

---

## 4. The Role of `design_plan/` and `guardrails.md`

The analysis task produces **two artifacts of different kinds**:

- **`design_plan/`** — a real design doc (architecture + per-submodule design). Long-lived intent. What the system *is*.
- **`guardrails.md`** — a short audit-data file (baseline, scope whitelist, revision log). Consumed only by anti-hack. What the build is *allowed* to touch.

AutoAgent system does **not** enforce `design_plan/` or `guardrails.md` semantics automatically. They are file-backed conventions. Every task that depends on them must read them explicitly, and every verifier must check them explicitly.

### 4.1 What each artifact holds

| Artifact | Holds | Consumed by |
|----------|-------|-------------|
| `design_plan/index.md` | System overview, architecture, cross-module interface contracts, integration risks | Every module task (reads for neighbor contracts and system context) |
| `design_plan/<module>.md` | One per top-level module task: responsibility, public interface, internal design, test strategy, dependencies | The owning module task (authoritative); adjacent modules may peek |
| `guardrails.md` | Clean baseline commit (SHA + timestamp + pytest/lint/type state), scope whitelist (allowed files per module), append-only revision log, and module-start SHA markers | All anti-hack subtasks — the single oracle for "what changed", "what was allowed", and "was the change declared" |

### 4.2 Artifact structure

Three short skeletons. Keep each one lean — these are templates, not essays. The per-submodule file, in particular, documents *design intent and reasoning*; it is not an implementation spec with pseudocode.

**`design_plan/index.md`:**

```markdown
# Design Plan — Index

## §1 Overview
One paragraph: goal, scope, non-goals.

## §2 Architecture
- Components / layers and their responsibilities (high-level; details per module live in <module>.md)
- Major control flows (e.g. "CSV upload → parse → validate → bulk insert → payment → notify")
- ASCII diagram optional but encouraged

## §3 Cross-Module Interface Contracts
One line per cross-module edge.
- csv_parser.parse(file_bytes: bytes) -> list[OrderRow]; raises CsvFormatError on malformed input
- db.orders.bulk_insert(rows: list[OrderRow]) -> BulkInsertResult; atomic per-row (partial failure → per-row status, no full rollback)
- ... (one bullet per edge)

## §4 Integration Risks & Cross-Module Assumptions
- Transaction boundary: service layer owns the transaction; DB layer never commits.
- Call order: validate → parse → db insert → payment → notify; notify failures are logged, not fatal.
- ... (one bullet per non-obvious assumption)
```

**`design_plan/<module>.md`** (one per top-level module task; name it after the module, e.g. `csv_parser.md`):

```markdown
# Design Plan — <Module Name>

## §1 Responsibility
- What this module owns: <one sentence>
- Explicitly NOT owned: <what callers must handle themselves>

## §2 Public Interface
Signatures this module exposes. Either re-state from index.md §3 or point to it ("see index.md §3").

## §3 Internal Design
- Key data structures: <what and why>
- Key algorithms / control flow: <the non-obvious parts>
- Design choices and reasoning: <alternatives considered, why this one>

## §4 Test Strategy
Test *categories* only (concrete cases are designed by the implementation task).
- happy: <shape of happy-path cases>
- edge: <specific edge conditions, e.g. empty input, boundary sizes>
- error: <failure modes to cover>
- regression (if any): <specific scenarios this module must not regress>

## §5 Dependencies
- Calls into: <list of other modules>
- Called from: <list of other modules>
```

**`guardrails.md`:**

```markdown
# Guardrails

## §1 Baseline
- baseline commit SHA: <sha>   (Task 1 clean baseline commit)
- baseline timestamp: <ISO-8601>
- working tree clean at baseline: yes
- pytest result: <e.g. 842 passed, 0 failed>
- ruff check: clean / <count> warnings
- mypy: clean / <count> errors

## §2 Scope Whitelist (Module → Allowed Files)
Exhaustive. No wildcards the anti-hack cannot mechanically diff against.
- module 2 (csv_parser): src/utils/csv_parser.py, tests/unit/test_csv_parser.py
- module 3 (db.orders): src/db/orders.py, tests/unit/db/test_orders.py
- ... (one line per module task)
- integration task (6): tests/integration/test_bulk_orders.py
- design_plan/ and guardrails.md itself: module tasks may update design_plan/** only under §4.3 policy and may append guardrails.md §3; never edit §1 or §2

## §3 Revision Log (Append-Only)
Covers edits to **both** `design_plan/**` and `guardrails.md`.
- baseline: task 1 — <sha> — clean baseline + scope whitelist written; design_plan/ authored
- module-start: csv_parser — <sha> — before task 2.1 edits
- contract-update: design_plan/db_orders.md §2 — <old> → <new> — rationale: partial-failure reporting required by index.md §4 assumption
- gap-fill: design_plan/<module>.md §<sec> — <what> — <why substantial>
- ... (append-only; never rewrite earlier entries)
```

### 4.3 Plan vs reality: update policy

Reality often diverges during large implementations. The rule: **let design_plan evolve, keep guardrails §1/§2 immutable**.

| Action | `design_plan/**` | `guardrails.md` |
|--------|------------------|-----------------|
| **Allowed mid-flight edit** | A module task may edit its own `<module>.md`, or append to `index.md` §3/§4, when implementation surfaces a real contract bug. Change committed **with** the dependent code. | Only `§3 Revision Log` is editable (append-only). Add `module-start`, `contract-update`, or `gap-fill` markers as needed. `§1` and `§2` are immutable in content. |
| **Forbidden (hacking)** | Deleting a §4 test category; rewriting §3 contracts in a way the revision log does not explain | Widening `§2` scope; rewriting `§3` non-append; any edit to `§1` or `§2` |
| **Consumer behavior** | Module tasks read the **latest committed** design_plan at session start; other modules' updates are visible because all tasks share the filesystem and committed state | Anti-hack subtasks read guardrails for every check |

Revision-log entries should use machine-readable marker prefixes so anti-hack can match diffs mechanically:

- `module-start: <module> — <sha> — before task <id> edits`
- `contract-update: <path> §<sec> — <old> → <new> — <why>`
- `gap-fill: <path> §<sec> — <what> — <why substantial>`
- `contract-hack-detected: <path> §<sec> — <reason>` (only used by verifiers when reporting a failure; do not commit this as a fix)

### 4.4 Prerequisite, module-start, and diff baseline policy

In AI scheduling mode, prerequisite handling has two layers:

- **Primary control**: encode dependencies and recovery in `ai_orchestrator.strategy`. If a consumer reports `❌ not completed: prerequisite artifact missing`, the scheduler can naturally redispatch the missing producer task or wait for its successful `last_result`.
- **Executor fallback**: every consumer task still verifies required artifacts before editing, because it may be scheduled from stale history, after a failed predecessor, or after partial filesystem changes.

Required policy:

1. **Prerequisite checks**: verify required source files, test files, design_plan sections, and guardrails baseline/scope entries exist before starting work. If a prerequisite is missing or clearly incomplete, output `❌ not completed: prerequisite artifact missing: <path-or-condition>` and do not compensate by rewriting unrelated work.
2. **Module-start SHA**: each module implementation subtask records the current `HEAD` as `module-start: <module> — <sha> — before task <id> edits` in `guardrails.md §3` before making implementation changes. The module anti-hack subtask diffs from that SHA, not from an implicit "previous task completion commit".
3. **Diff commands**: use `git diff --name-only <recorded-sha>..HEAD` for scope checks, and targeted `git diff <recorded-sha>..HEAD -- tests/ design_plan/ guardrails.md <schema/api paths>` for integrity checks. `git diff --stat` is useful as a summary, but is not sufficient evidence by itself.
4. **Global baseline**: final global anti-hack diffs from `guardrails.md §1` baseline SHA. `guardrails.md §1` and `§2` must not change after Task 1.
5. **Scheduler visibility**: configure `last_result` for every top-level task whose outcome is referenced by `strategy`. For typical two-subtask Build & Ship module tasks, `type: response` is enough; use `type: file` for analysis or integration artifacts that the scheduler must inspect.

### 4.5 When the user provides a design doc themselves

**Key insight**: User-provided design docs are **NOT authoritative** either. But the main difference is that user-provided design docs typically have **higher quality** since they have undergone multiple optimizations. In this case, what the analysis task (Task 1) should do is **not re-authoring, but gap-filling**:

- Read the user's design plan end-to-end.
- **Only if a section is materially missing** (e.g. a module has no `<module>.md`, `index.md` has no Architecture section, or a contract needed by anti-hack is entirely undefined) may Task 1 edit the design_plan directly to fill the gap. "Could be clearer" / stylistic / reorganization do NOT qualify.
- Always produce `guardrails.md` from scratch (baseline + scope whitelist + initial revision log entry — including a `gap-fill:` log entry for any substantial gap-fill performed in step 2).
- The commit at the end of Task 1 **is** the baseline; `guardrails.md §1` records its SHA.

**Module tasks (2–5) in this mode** behave exactly as in default mode: they may edit `design_plan/**` under the same "contract-bug-forces-update" rules. The fact that the user originally provided the doc grants no special immunity — but the default tendency remains "edit minimally".

**Global anti-hack (task 6.2)** is identical to default mode: diff every file under `design_plan/**` and `guardrails.md` against the Task-1 baseline commit. Every diff chunk must have a matching machine-readable `guardrails.md §3` marker. No separate two-baseline tracking is needed because Task 1's commit already absorbs any user-design-doc gap-fills.

### 4.6 State persistence patterns (Optional)

For richer history tracking, keep small, stable state files that every later task can read from disk without relying on conversation context. For Build & Ship, `design_plan/` and `guardrails.md` are usually enough; larger projects may add a compact `build_state.md` when operational facts become too noisy for `guardrails.md §3`.

Use `build_state.md` only for factual task-state snapshots such as:

- per-module `module-start` SHA table
- prerequisite check status per task
- integration findings and owner module
- deferred cross-module issues that still need resolution

`build_state.md` must not override `guardrails.md §1/§2`, widen scope, or replace the `guardrails.md §3` revision log required by anti-hack checks.

---

## 5. Complete Example

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

  ## Reference Docs
  - P0 Must Read: docs/api_spec.md — API design patterns and admin endpoint conventions
  - P0 Must Read: docs/testing_guide.md — Test structure, fixtures, and mocking patterns
  - P1 Read Before Related Work: docs/payment_integration.md — Payment gateway contract
  - P1 Read Before Related Work: docs/database_schema.md — Current schema and migration rules

ai_orchestrator:
  strategy: |
    1. Bootstrap: run Task 1 (Baseline and design plan) first. If any later task
       reports missing design_plan/ or guardrails.md artifacts, redispatch Task 1.
    2. After Task 1 succeeds, run Tasks 2 and 3 when useful. They are independent
       module tasks and may be scheduled in any order.
    3. Run Task 4 only after Tasks 2 and 3 have succeeded. If Task 4 reports
       missing or broken csv_parser/db artifacts, redispatch the missing or
       failing producer task instead of repeatedly running Task 4.
    4. Run Task 5 only after Task 4 succeeds. If Task 5 reports missing or broken
       service artifacts, redispatch Task 4.
    5. Run Task 6 only after Tasks 2-5 have all succeeded. If Task 6 reports a
       missing module artifact or failing module unit test, redispatch the owning
       module task.
    6. If a task fails for a code/test issue inside its own scope, rerun that same
       task up to its max_attempts. Prefer producer redispatch for prerequisite
       failures, not consumer retries.
    7. Stop when Task 6 succeeds, or after 5 consecutive scheduling rounds with
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
  # -------------------------------------------------------------------------
  # Task 1 — Analyze codebase and plan module-level implementation.
  # Single simple task (no retry needed beyond AI self-correction).
  # -------------------------------------------------------------------------
  - id: 1
    name: "Establish baseline and write design_plan/ + guardrails.md"
    description: |
      Analyze the codebase, produce design_plan/ and guardrails.md, and commit
      the clean baseline consumed by all later module and integration tasks.
    type: simple
    completion_criteria: |
      1. design_plan/index.md is produced per guide §"Artifact structure":
         §1 Overview, §2 Architecture, §3 Cross-Module Interface Contracts,
         §4 Integration Risks. Architecture section covers the major control
         flows, not just a file list.
      2. One design_plan/<module>.md is produced for each top-level module
         task (tasks 2–5), each with §1 Responsibility, §2 Public Interface,
         §3 Internal Design, §4 Test Strategy (categories only), §5 Dependencies.
         Internal Design explains design choices and reasoning, not code.
      3. guardrails.md is produced with three sections:
         §1 Baseline (clean commit SHA, ISO-8601 timestamp, clean working-tree
         confirmation, pytest result, ruff/mypy state),
         §2 Scope Whitelist (exhaustive allowed-file list for every module
         task 2–5 and the integration task 6; no "etc." / no wildcards),
         §3 Revision Log (initial `baseline:` entry recording the authoring of
         this baseline and the scope whitelist).
      4. All test strategies in <module>.md §4 list test *categories* only
         (happy / edge / error / regression), NOT concrete test cases.
      5. design_plan/ and guardrails.md are committed from a clean working tree.
         That commit IS the baseline referenced in guardrails.md §1.
      6. No source code modified.
    initial_hint: |
      Read docs/api_spec.md and docs/testing_guide.md first.
      Run `git status` before baseline capture. If the working tree is not clean,
      output `❌ not completed: baseline working tree is dirty` and do not mix
      unrelated changes into the baseline.
      Run `pytest`, `ruff check`, `mypy` to confirm a green baseline.
      Record the baseline SHA, ISO-8601 timestamp, clean working-tree status,
      and tool results in guardrails.md §1.

      The module breakdown is already fixed by this todos.yaml — do NOT
      re-invent it. Your job:
        - design_plan/index.md: architecture (control flows, layer
          boundaries), cross-module interface contracts (signatures, error
          codes, atomicity / side-effect promises), integration risks.
        - design_plan/<module>.md (one per top-level module task): what
          this module is responsible for, its public interface, key
          internal design choices and reasoning, test categories, and
          module dependencies.
        - guardrails.md: baseline facts, per-module allowed-file list
          (exhaustive — anti-hack mechanically diffs against this), and an
          initial revision-log entry.

      Keep each file lean. design_plan is design intent, not pseudocode.
      guardrails is audit data, not documentation. Commit all of them
      together; that commit is the baseline for all later anti-hack
      subtasks. Do NOT modify source code in this task.

  # -------------------------------------------------------------------------
  # Tasks 2–5 — One top-level nested task per module.
  # Each has two subtasks: implement+test, then anti-hack verify.
  # -------------------------------------------------------------------------
  - id: 2
    name: "Module: CSV parser utility"
    description: |
      Implement and unit-test the CSV parser module, then verify scope and test
      integrity with an anti-hack subtask. Produces a concise final response for scheduler decisions.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. src/utils/csv_parser.py implements CSV parsing for order data
      2. Unit tests for csv_parser pass
      3. No files outside the csv_parser row in guardrails.md §2 are modified,
         except design_plan/** updates justified by `contract-update:` markers
         and append-only guardrails.md §3 entries
    subtasks:
      - id: 2.1
        name: "Implement CSV parser with unit tests"
        type: simple
        completion_criteria: |
          1. src/utils/csv_parser.py implements the parser per the public
             interface in design_plan/csv_parser.md §2 (and, if it exposes
             cross-module edges, design_plan/index.md §3)
          2. Unit tests in tests/unit/test_csv_parser.py cover **every
             category** listed in design_plan/csv_parser.md §4
             (happy / edge / error). Concrete cases are designed by this task.
          3. pytest tests/unit/test_csv_parser.py passes
          4. Only files inside the csv_parser allowed-file list in
             guardrails.md §2 are modified, plus design_plan/** updates
             justified by `contract-update:` markers and append-only
             guardrails.md §3 entries
          5. Changes committed
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy should run Task 1 before
          this task. Verify design_plan/index.md, design_plan/csv_parser.md,
          and guardrails.md exist; guardrails.md §1 has a baseline SHA;
          guardrails.md §2 has a csv_parser row. If missing, output
          `❌ not completed: prerequisite artifact missing: design_plan/ or guardrails.md`
          so the scheduler can redispatch Task 1.

          Read design_plan/csv_parser.md (your module) and design_plan/index.md
          (cross-module contracts and integration risks). Check guardrails.md §2
          for the scope whitelist for csv_parser.
          Check git status first — discard residual changes from previous retry.
          Record the current `HEAD` in guardrails.md §3 as
          `module-start: csv_parser — <sha> — before task 2.1 edits` before
          implementation edits. Implement parser AND unit tests together.

          If you discover the contract is infeasible or wrong, you MAY update
          design_plan/ (csv_parser.md §2/§3 or index.md §3 as appropriate) and
          append a guardrails.md §3 entry in the form
          `contract-update: <path> §<sec> — <old> → <new> — <why>`; commit the
          design_plan change alongside your code. NEVER widen guardrails.md §2
          scope or delete a §4 test category just to pass.

          Run pytest tests/unit/test_csv_parser.py before committing.
      - id: 2.2
        name: "Anti-hack verification for CSV parser"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/test_csv_parser.py exits with code 0
          2. git diff --name-only <csv_parser-module-start-sha>..HEAD shows
             only files allowed by the csv_parser row in guardrails.md §2, plus
             design_plan/** and guardrails.md §3 entries when justified by a
             matching `contract-update:` marker
          3. No removed assertions, no @pytest.mark.skip additions,
             no relaxed comparisons in the modified test file
        initial_hint: |
          This is an execution-only verification subtask.
          1. Run: pytest tests/unit/test_csv_parser.py
          2. Read the csv_parser `module-start:` SHA from guardrails.md §3.
             Run: git diff --name-only <csv_parser-module-start-sha>..HEAD.
             Allowed files must be a subset of the csv_parser row in
             guardrails.md §2 (plus design_plan/** and guardrails.md §3 only
             if a contract was updated with a matching `contract-update:` entry).
          3. Run: git diff <csv_parser-module-start-sha>..HEAD -- tests/unit/test_csv_parser.py
             and check for removed/weakened assertions or @skip additions.
          If ANY check fails, output `❌ not completed: <reason>` with specific
          details. Do NOT fix code (see main guide §4.7 and §4.9).

  - id: 3
    name: "Module: Order database layer"
    description: |
      Implement and unit-test bulk order database operations without schema or
      migration changes, then run anti-hack scope and integrity verification.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Bulk order creation queries implemented in src/db/orders.py
      2. Unit tests for the DB layer pass
      3. No files outside the db.orders row in guardrails.md §2 are modified,
         except design_plan/** updates justified by `contract-update:` markers
         and append-only guardrails.md §3 entries
      4. No existing model schemas or migrations changed
    subtasks:
      - id: 3.1
        name: "Implement DB layer with unit tests"
        type: simple
        completion_criteria: |
          1. Bulk order queries implemented per design_plan/db_orders.md §2
             and the atomicity contract in design_plan/index.md §3
          2. Unit tests in tests/unit/db/test_orders.py cover **every
             category** listed in design_plan/db_orders.md §4
             (happy / edge / error). Concrete cases designed by this task.
          3. pytest tests/unit/db/ passes
          4. Only files in db.orders' allowed-file list (guardrails.md §2)
             modified, plus design_plan/** updates justified by
             `contract-update:` markers and append-only guardrails.md §3 entries
          5. No existing model schemas or migrations changed
          6. Changes committed
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy may run this task after
          Task 1, independent of Task 2. Verify design_plan/db_orders.md,
          design_plan/index.md, and guardrails.md exist before editing. If any
          planning artifact is missing, output `❌ not completed: prerequisite artifact missing: design_plan/ or guardrails.md`
          so the scheduler can redispatch Task 1.

          Read design_plan/db_orders.md and design_plan/index.md §3/§4.
          Check guardrails.md §2 for the scope whitelist.
          Check git status first — discard residual changes from previous retry.
          Record the current `HEAD` in guardrails.md §3 as
          `module-start: db_orders — <sha> — before task 3.1 edits` before
          implementation edits. Implement queries AND unit tests together; use
          fixtures from docs/testing_guide.md.

          If a contract is infeasible, update the relevant design_plan file
          (db_orders.md §2/§3 or index.md §3), append a guardrails.md §3 entry
          in the form `contract-update: <path> §<sec> — <old> → <new> — <why>`,
          and commit the design_plan change with your code. NEVER widen
          guardrails.md §2 scope or delete a §4 category. Migration files and
          existing model schemas remain untouchable.

          Run pytest tests/unit/db/ before committing.
      - id: 3.2
        name: "Anti-hack verification for DB layer"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/db/ exits with code 0
          2. git diff --name-only <db_orders-module-start-sha>..HEAD shows
             only files allowed by the db.orders row in guardrails.md §2, plus
             design_plan/** and guardrails.md §3 entries when justified by a
             matching `contract-update:` marker
          3. No migration files or existing model schemas modified
          4. No removed/weakened assertions or @skip additions
        initial_hint: |
          Execution-only. Run the DB unit tests. Read the db_orders
          `module-start:` SHA from guardrails.md §3 and run
          git diff --name-only <db_orders-module-start-sha>..HEAD; allowed files
          must match the db.orders row in guardrails.md §2 (plus design_plan/**
          and guardrails.md §3 only if a contract was updated with a matching
          `contract-update:` entry). Run targeted diffs on tests/unit/db/ and
          migration/schema paths to check test weakening and forbidden schema
          changes. If ANY check fails, output `❌ not completed: <reason>`. Do
          NOT fix code.

  - id: 4
    name: "Module: Order service"
    description: |
      Implement and unit-test bulk order service logic that consumes the parser
      and database contracts, then verify scope and test integrity.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Bulk processing logic implemented in src/services/order_service.py
      2. Unit tests for the service pass with mocked dependencies
      3. No files outside the order_service row in guardrails.md §2 are modified,
         except design_plan/** updates justified by `contract-update:` markers
         and append-only guardrails.md §3 entries
    subtasks:
      - id: 4.1
        name: "Implement service with unit tests"
        type: simple
        completion_criteria: |
          1. Service logic implemented per design_plan/order_service.md §2/§3,
             consuming the csv_parser and db.orders contracts from
             design_plan/index.md §3 verbatim
          2. Unit tests in tests/unit/services/test_order_service.py cover
             **every category** listed in design_plan/order_service.md §4
             (happy / edge / error). Concrete cases designed by this task.
          3. pytest tests/unit/services/ passes
          4. Only files in order_service's allowed-file list (guardrails.md §2)
             modified, plus design_plan/** updates justified by
             `contract-update:` markers and append-only guardrails.md §3 entries
          5. Database and payment dependencies mocked in tests
          6. Changes committed
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy should run this task only
          after Tasks 2 and 3 succeed. Verify the csv_parser and db.orders
          source/test files exist and their unit tests pass. If missing or
          broken, output `❌ not completed: prerequisite artifact missing or broken: <artifact-or-test>`
          so the scheduler can redispatch the owning producer task.

          Read design_plan/order_service.md and design_plan/index.md.
          Check guardrails.md §2 for the scope whitelist.
          Consume csv_parser and db.orders contracts verbatim from
          design_plan/index.md §3.
          Record the current `HEAD` in guardrails.md §3 as
          `module-start: order_service — <sha> — before task 4.1 edits` before
          implementation edits. Mock dependencies in unit tests.

          If consuming a neighbor's contract surfaces a bug, update the
          relevant design_plan file (index.md §3 for cross-module changes,
          or a neighbor's <module>.md §2 if the neighbor's interface spec
          was wrong), append a guardrails.md §3 entry in the form
          `contract-update: <path> §<sec> — <old> → <new> — <why>`, and commit
          the design_plan change with your code. NEVER widen guardrails.md §2
          scope or delete a §4 category.

          Run pytest tests/unit/services/ before committing.
      - id: 4.2
        name: "Anti-hack verification for service"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/services/ exits with code 0
          2. git diff --name-only <order_service-module-start-sha>..HEAD shows
             only files allowed by the order_service row in guardrails.md §2,
             plus design_plan/** and guardrails.md §3 entries when justified by
             a matching `contract-update:` marker
          3. No removed/weakened assertions or @skip additions
        initial_hint: |
          Execution-only. Verify tests pass. Read the order_service
          `module-start:` SHA from guardrails.md §3 and run
          git diff --name-only <order_service-module-start-sha>..HEAD; allowed
          files must match the order_service row in guardrails.md §2 (plus
          design_plan/** and guardrails.md §3 only if a contract was updated
          with a matching `contract-update:` entry). Run targeted diffs on
          tests/unit/services/ to check tests were not weakened. If ANY check
          fails, output `❌ not completed: <reason>`. Do NOT fix code.

  - id: 5
    name: "Module: Admin API route"
    description: |
      Implement and unit-test the admin bulk-order API route against the service
      contract, then verify API/schema boundaries and test integrity.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. POST /api/admin/orders/bulk route implemented in src/routes/admin.py
      2. Unit tests for the route pass with mocked service
      3. No files outside the admin_route row in guardrails.md §2 are modified,
         except design_plan/** updates justified by `contract-update:` markers
         and append-only guardrails.md §3 entries
      4. No existing route handlers or response schemas changed
    subtasks:
      - id: 5.1
        name: "Implement route with unit tests"
        type: simple
        completion_criteria: |
          1. Route handler implemented per design_plan/admin_route.md §2/§3,
             consuming the order_service contract from
             design_plan/index.md §3 verbatim
          2. Unit tests in tests/unit/routes/test_admin.py cover **every
             category** listed in design_plan/admin_route.md §4 (happy /
             auth-failure / validation-failure / partial-success).
             Concrete cases designed by this task.
          3. pytest tests/unit/routes/ passes
          4. Only files in the admin route's allowed-file list (guardrails.md §2)
             modified, plus design_plan/** updates justified by
             `contract-update:` markers and append-only guardrails.md §3 entries
          5. No existing route handlers or response schemas changed
          6. Changes committed
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy should run this task only
          after Task 4 succeeds. Verify src/services/order_service.py and
          tests/unit/services/test_order_service.py exist, and pytest
          tests/unit/services/ passes. If missing or broken, output
          `❌ not completed: prerequisite artifact missing or broken: order_service`
          so the scheduler can redispatch Task 4.

          Read design_plan/admin_route.md and design_plan/index.md.
          Check guardrails.md §2 for the scope whitelist.
          Consume the order_service contract verbatim from design_plan/index.md §3.
          Record the current `HEAD` in guardrails.md §3 as
          `module-start: admin_route — <sha> — before task 5.1 edits` before
          implementation edits. Use FastAPI TestClient and
          `app.dependency_overrides` for mocking (per design_plan/index.md §4
          integration risks).

          If a contract surfaces an incompatibility, update the relevant
          design_plan file, append a guardrails.md §3 entry in the form
          `contract-update: <path> §<sec> — <old> → <new> — <why>`, and commit
          the design_plan change with your code. NEVER widen guardrails.md §2
          scope or delete a §4 category.

          Run pytest tests/unit/routes/ before committing.
      - id: 5.2
        name: "Anti-hack verification for route"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/routes/ exits with code 0
          2. git diff --name-only <admin_route-module-start-sha>..HEAD shows
             only files allowed by the admin_route row in guardrails.md §2,
             plus design_plan/** and guardrails.md §3 entries when justified by
             a matching `contract-update:` marker
          3. No existing route handlers or response schemas modified
          4. No removed/weakened assertions or @skip additions
        initial_hint: |
          Execution-only. Verify tests pass. Read the admin_route
          `module-start:` SHA from guardrails.md §3 and run
          git diff --name-only <admin_route-module-start-sha>..HEAD; allowed
          files must match the admin_route row in guardrails.md §2 (plus
          design_plan/** and guardrails.md §3 only if a contract was updated
          with a matching `contract-update:` entry). Run targeted diffs on
          tests/unit/routes/ and route schema/API paths. Existing route handlers
          and response schemas must be untouched. If ANY check fails, output
          `❌ not completed: <reason>`. Do NOT fix code.

  # -------------------------------------------------------------------------
  # Task 6 — Integration + global anti-hack.
  # Runs once all module tasks are complete; sees the full codebase.
  # Workload is small because each module was unit-tested in isolation.
  # -------------------------------------------------------------------------
  - id: 6
    name: "Integration: end-to-end tests, full suite, global anti-hack"
    description: |
      Add end-to-end coverage for the completed module set, run full validation,
      and perform global anti-hack verification before the scheduler stops.
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Integration tests for the bulk order flow pass
      2. Full `pytest` suite exits with code 0
      3. ruff check and mypy pass with no errors
      4. Module scope boundaries honored across all module tasks
      5. No existing tests weakened anywhere in the repo
    subtasks:
      - id: 6.1
        name: "Write and pass integration tests"
        type: simple
        max_attempts: 3
        completion_criteria: |
          1. tests/integration/test_bulk_orders.py added, covering end-to-end
             CSV upload → DB commit → payment call → notification dispatch
          2. pytest tests/integration/test_bulk_orders.py passes
          3. If a cross-module bug is found, fix is scoped to the minimal
             module(s) responsible; module-internal logic refactors are not
             allowed — only bug fixes
          4. Changes committed
        initial_hint: |
          PREREQUISITE FALLBACK: Scheduler strategy should run this task only
          after Tasks 2–5 succeed. Verify these concrete artifacts exist and
          are non-trivial:
          src/utils/csv_parser.py, tests/unit/test_csv_parser.py,
          src/db/orders.py, tests/unit/db/test_orders.py,
          src/services/order_service.py, tests/unit/services/test_order_service.py,
          src/routes/admin.py, tests/unit/routes/test_admin.py. Also run the
          module unit test commands. If any prerequisite artifact is missing or
          its module tests fail, output `❌ not completed: prerequisite module artifact missing or broken: <module>`
          so the scheduler can redispatch the owning module task.

          Write integration tests per design_plan/index.md §4 integration risks
          (transaction boundary, call order, partial-failure semantics). If a
          cross-module bug surfaces, fix it in the responsible module (keep fix
          minimal) and re-run the test. Do NOT rewrite module logic.
      - id: 6.2
        name: "Global anti-hack and full-suite verification"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a test runner and code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest (full suite including integration) exits with code 0
          2. ruff check src/ tests/ exits with code 0
          3. mypy src/ exits with code 0
          4. git diff --name-only <guardrails-baseline-sha>..HEAD shows changes
             only in the allowed-file lists documented in guardrails.md §2, plus
             design_plan/** and append-only guardrails.md §3 edits
          5. No existing tests weakened: no removed assertions, no
             @pytest.mark.skip additions, no relaxed comparisons, no
             conditional test bypasses
          6. No existing API schemas, migrations, or payment contracts modified
          7. Every test category listed in any design_plan/<module>.md §4
             has at least one concrete test function in the committed test files
          8. **Contract integrity**: diff design_plan/** and guardrails.md
             (guardrails.md §1 baseline SHA vs current) and verify:
             a. every change in design_plan/** has a matching machine-readable
                `contract-update:` or `gap-fill:` entry in guardrails.md §3
             b. no allowed-file list in guardrails.md §2 has been widened
                (§2 is immutable; any diff to §2 is `❌ not completed`)
             c. no §1 Baseline line in guardrails.md has been edited
             d. no test category has been deleted from any
                design_plan/<module>.md §4
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

**How this example maps to the three core principles:**

- **Module-based splitting at the top level**: tasks 2–5 each own one module (utils / db / service / route) as independent top-level `nested` tasks. The scheduler can redispatch the failed or stale module task without rerunning unrelated module tasks, and prerequisite failures become signals to redispatch the missing producer.
- **Scheduler visibility**: Task 1 exposes durable planning artifacts with `last_result: type: file`; the two-subtask module tasks and integration task use `last_result: type: response` because their final responses are enough for scheduler decisions in this example.
- **Anti-hack verification**: subtasks 2.2, 3.2, 4.2, 5.2, 6.2 are all dedicated `max_attempts: 1`, `model: lite` verifiers with `system_prompt_prefix` forbidding edits; each checks tests + recorded-SHA diff scope + test-integrity heuristics. If a verifier command may exceed one minute, switch that verifier from `simple` to `long_running`.
- **Unit test discipline**: each implementation subtask (2.1, 3.1, 4.1, 5.1) lists the exact unit test categories it must cover, written in the same subtask as the code. Integration tests are deferred to task 6.1, intentionally — they only become tractable once all modules exist.

### 5.1 Variants in design-doc mode

When the user provides a `design_plan/` (see §4.5), the scheduler graph stays identical and only these fields change:

1. `description.Reference Docs` gains `design_plan/` as a P0 Must Read entry.
2. `description.Rules` gains one line: "design_plan/ was user-provided; edit only on substantial gaps (missing <module>.md, missing Architecture section, undefined contract needed by anti-hack); every edit recorded in guardrails.md §3 with marker `gap-fill: <path> §<sec> — <what> — <why substantial>`."
3. **Task 1** switches from authoring design_plan/ to inspect-and-gap-fill; guardrails.md is always authored from scratch.
4. `ai_orchestrator.strategy` still treats Task 1 as the bootstrap producer, and `last_result.1` should still expose `guardrails.md` plus `design_plan/index.md` so the scheduler can see the baseline and design availability.

Task 1 `completion_criteria` becomes:

```yaml
      1. design_plan/ (user-provided) has been read end-to-end. Any
         substantial gap (missing <module>.md for a module task 2–5;
         missing §2 Architecture or §3/§4 sections in index.md; a contract
         needed by anti-hack that is entirely undefined) has been filled
         directly in the relevant file. Cosmetic, stylistic, or
         reorganization edits are NOT performed.
      2. guardrails.md is produced from scratch with §1 Baseline
         (clean commit SHA after step 1's edits, ISO-8601 timestamp,
         clean working-tree status, plus pytest/ruff/mypy state),
         §2 Scope Whitelist (exhaustive), and §3 Revision Log. The log's
         initial entry records the baseline; any gap-fill edit performed
         in step 1 gets its own entry in the form
         `gap-fill: <path> §<sec> — <what> — <why substantial>`.
      3. design_plan/ and guardrails.md are committed together from a clean
         working tree; that commit is the baseline referenced in guardrails.md §1.
      4. No source code modified.
```

Each module task's `initial_hint` also gains one line: "design_plan/ was user-provided; prefer working around design quirks in code over editing design_plan/. Edit only on real contract bugs, and always pair the edit with a guardrails.md §3 `contract-update:` entry."