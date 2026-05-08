# Best Practice: Build & Ship

## 1. Three Core Principles

Patterns for **implementing features, fixing bugs, and refactoring** — the most common software engineering task. These tasks typically involve **large codebases (10k+ lines)** where changes span multiple modules, so the three core principles below must be enforced:

1. **Module-based splitting at the top level** — Split by module/subsystem boundary into **independent top-level tasks**, not subtasks of one big nested task. Each top-level task owns one module's changes end-to-end (implement + anti-hack). Top-level tasks are the unit of independent retry (see §3).

2. **Anti-hack verification** — Every top-level module task must contain (as its last subtask) a dedicated `max_attempts: 1` verification subtask that re-runs the module's tests AND checks `git diff` for scope violations, weakened assertions, `@skip` additions, and modified public schemas. Without this, the AI can silently "pass" by gaming the tests (see main guide §4.8).

3. **Unit test discipline** — Every implementation subtask that changes behavior must include unit tests for that behavior, written in the same subtask as the code (not a later subtask). Tests cover: happy path, edge cases, error cases, and any regression scenario that motivated the change.

---

## 2. Recommended Structure

| Task size | Structure |
|-----------|-----------|
| Single bug or small feature (< 3 files, < 1 module) | One top-level `simple` task |
| Feature or bug fix touching one module | One top-level `nested`: implement + test → anti-hack verify (`max_attempts: 1`) |
| Large feature / refactor spanning N modules, OR N independent bugs | **1 Analysis top-level task** + **N top-level `nested` tasks** + **1 top-level integration task** at the end (See §3) |
| Any of the above with build/test > 1 min | Use `long_running` for the verification subtask (see main guide rule 5) |

---

## 3. Key Insights

1. **Why top-level splitting (not one big nested)?**

When a `nested` task's subtask fails, the retry machanism will rerun that subtask **and every subtask after it**. If you stuff N module implementations into one nested task and module 5 of 10 fails, modules 5–10 all rerun — wasting the already-correct work of modules 6–10.

Instead, top-level tasks are isolated from each other: module 3 failing has no effect on modules 1–2 (already completed) or on modules 4..N (run independently in their own sessions).

2. **`looping` is generally not recommended for Build & Ship**, since the goal of implementation is typically "to reach a specific end state".

3. **Details for task decomposition when module-based splitting is required**:
  - **Each `nested` task generally has just two subtasks**: `implement + test` and `anti-hack verify`.
  - **A final top-level integration task is added at the end**. This task sees the full codebase, runs the whole test suite, and fixes cross-module bugs only now visible. Its workload is not large because each module has already been unit-tested in isolation.
  - **Put an analysis task at the front** that designs an implementation plan (including per-module scope boundaries).

4. **Anti-hack subtask should explicitly output `not completed: <reason>` when anti-hack check fails** for correct failure propagation (see main guide rule 16).

---

## 4. The Role of `design_plan/` and `guardrails.md`

The analysis task produces **two artifacts of different kinds**:

- **`design_plan/`** — a real design doc (architecture + per-submodule design). Long-lived intent. What the system *is*.
- **`guardrails.md`** — a short audit-data file (baseline, scope whitelist, revision log). Consumed only by anti-hack. What the build is *allowed* to touch.

### 4.1 What each artifact holds

| Artifact | Holds | Consumed by |
|----------|-------|-------------|
| `design_plan/index.md` | System overview, architecture, cross-module interface contracts, integration risks | Every module task (reads for neighbor contracts and system context) |
| `design_plan/<module>.md` | One per top-level module task: responsibility, public interface, internal design, test strategy, dependencies | The owning module task (authoritative); adjacent modules may peek |
| `guardrails.md` | Baseline (SHA + pytest/lint state), scope whitelist (allowed files per module), revision log (append-only, covers edits to both this file and `design_plan/**`) | All anti-hack subtasks — the single oracle for "what changed" and "was the change declared" |

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
- baseline commit SHA: <sha>   (this is the commit of the analysis task itself; all anti-hack diffs against it)
- pytest result: <e.g. 842 passed, 0 failed>
- ruff check: clean / <count> warnings
- mypy: clean / <count> errors

## §2 Scope Whitelist (Module → Allowed Files)
Exhaustive. No wildcards the anti-hack cannot mechanically diff against.
- module 2 (csv_parser): src/utils/csv_parser.py, tests/unit/test_csv_parser.py
- module 3 (db.orders): src/db/orders.py, tests/unit/db/test_orders.py
- ... (one line per module task)
- integration task (6): tests/integration/test_bulk_orders.py
- design_plan/ and guardrails.md itself: any module task may append to design_plan/**, never widen §2 of guardrails.md

## §3 Revision Log (Append-Only)
Covers edits to **both** `design_plan/**` and `guardrails.md`.
- (task 1, <date>) baseline + scope whitelist written; design_plan/ authored
- (task 3, <date>) design_plan/db_orders.md §2: changed bulk_insert signature to return per-row status list instead of single success bool — rationale: partial-failure reporting required by index.md §4 assumption
- ... (append-only; never rewrite earlier entries)
```

### 4.3 Plan vs reality: update policy

Reality often diverges during large implementations. The rule: **let design_plan evolve, keep guardrails immutable**.

| Action | `design_plan/**` | `guardrails.md` |
|--------|------------------|-----------------|
| **Allowed mid-flight edit** | A module task may edit its own `<module>.md`, or append to `index.md` §3/§4, when implementation surfaces a real contract bug. Change committed **with** the dependent code. | Only `§3 Revision Log` is editable (append-only). `§1` is immutable. `§2` is immutable in content. |
| **Forbidden (hacking)** | Deleting a §4 test category; rewriting §3 contracts in a way the revision log does not explain | Widening `§2` scope; rewriting `§3` non-append; any edit to `§1` |
| **Consumer behavior** | Module tasks read the **latest committed** design_plan at session start; earlier modules' updates are visible to later modules via linear execution order | Anti-hack subtasks read guardrails for every check |

### 4.4 When the user provides a design doc themselves

**Key insight**: User-provided design docs are **NOT authoritative** either. But the main difference is that user-provided design docs typically have **higher quality** since they have undergone multiple optimizations. In this case, what the analysis task (Task 1) should do is **not re-authoring, but gap-filling**:

- Read the user's design plan end-to-end.
- **Only if a section is materially missing** (e.g. a module has no `<module>.md`, `index.md` has no Architecture section, or a contract needed by anti-hack is entirely undefined) may Task 1 edit the design_plan directly to fill the gap. "Could be clearer" / stylistic / reorganization do NOT qualify.
- Always produce `guardrails.md` from scratch (baseline + scope whitelist + initial revision log entry — including a log entry for any substantial gap-fill performed in step 2).
- The commit at the end of Task 1 **is** the baseline; `guardrails.md §1` records its SHA.

**Module tasks (2–5) in this mode** behave exactly as in default mode: they may edit `design_plan/**` under the same "contract-bug-forces-update" rules. The fact that the user originally provided the doc grants no special immunity — but the default tendency remains "edit minimally".

**Global anti-hack (task 6.2)** is identical to default mode: diff every file under `design_plan/**` and `guardrails.md` against the Task-1 baseline commit. Every diff chunk must have a matching `guardrails.md §3` entry. No separate two-baseline tracking is needed because Task 1's commit already absorbs any user-design-doc gap-fills.

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
    persist audit data (baseline, scope whitelist, revision log) to
    guardrails.md.
  - Split implementation into one top-level task per module (linear mode
    executes them in ID order, and each retries independently).
  - Every module task must include unit tests for new code AND an anti-hack
    verification subtask.
  - Commit changes at each subtask completion.
  - Before starting any implementation subtask, run `git status`; if
    uncommitted changes exist from a previous retry, inspect and either
    continue from them or `git checkout .` to discard (see main guide §4.9).
  - The final integration task must only run after all module tasks have
    completed successfully; it fixes cross-module bugs but must not rewrite
    module-internal logic.

  ## Reference Docs
  - P0 Must Read: docs/api_spec.md — API design patterns and admin endpoint conventions
  - P0 Must Read: docs/testing_guide.md — Test structure, fixtures, and mocking patterns
  - P1 Read Before Related Work: docs/payment_integration.md — Payment gateway contract
  - P1 Read Before Related Work: docs/database_schema.md — Current schema and migration rules

tasks:
  # -------------------------------------------------------------------------
  # Task 1 — Analyze codebase and plan module-level implementation.
  # Single simple task (no retry needed beyond AI self-correction).
  # -------------------------------------------------------------------------
  - id: 1
    name: "Establish baseline and write design_plan/ + guardrails.md"
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
         §1 Baseline (commit SHA, pytest result, ruff/mypy state),
         §2 Scope Whitelist (exhaustive allowed-file list for every module
         task 2–5 and the integration task 6; no "etc." / no wildcards),
         §3 Revision Log (initial entry recording the authoring of this
         baseline).
      4. All test strategies in <module>.md §4 list test *categories* only
         (happy / edge / error / regression), NOT concrete test cases.
      5. design_plan/ and guardrails.md are committed. That commit IS the
         baseline referenced in guardrails.md §1.
      6. No source code modified.
    initial_hint: |
      Read docs/api_spec.md and docs/testing_guide.md first.
      Run `pytest`, `ruff check`, `mypy` to confirm a green baseline.
      Record the baseline SHA and tool results in guardrails.md §1.

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
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. src/utils/csv_parser.py implements CSV parsing for order data
      2. Unit tests for csv_parser pass
      3. No files outside src/utils/ and tests/unit/test_csv_parser.py modified
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
             guardrails.md §2 are modified (plus design_plan/ entries if
             a contract update was needed)
          5. Changes committed
        initial_hint: |
          Read design_plan/csv_parser.md (your module) and design_plan/index.md
          (cross-module contracts and integration risks). Check guardrails.md §2
          for the scope whitelist for csv_parser. Design concrete test cases
          covering every category in design_plan/csv_parser.md §4.
          Check git status first — discard residual changes from previous retry.
          Implement parser AND unit tests together.

          If you discover the contract is infeasible or wrong, you MAY update
          design_plan/ (csv_parser.md §2/§3 or index.md §3 as appropriate) and
          append a guardrails.md §3 revision-log entry describing the change
          and rationale; commit the design_plan change alongside your code.
          NEVER widen guardrails.md §2 scope or delete a §4 test category
          just to pass.

          Run pytest tests/unit/test_csv_parser.py before committing.
      - id: 2.2
        name: "Anti-hack verification for CSV parser"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/test_csv_parser.py exits with code 0
          2. git diff --stat shows only src/utils/csv_parser.py and
             tests/unit/test_csv_parser.py changed since task 1
          3. No removed assertions, no @pytest.mark.skip additions,
             no relaxed comparisons in the modified test file
        initial_hint: |
          This is an execution-only verification subtask.
          1. Run: pytest tests/unit/test_csv_parser.py
          2. Run: git diff --stat against the commit at the end of task 1.
             Allowed files must be a subset of the csv_parser row in
             guardrails.md §2 (plus design_plan/** if a contract was updated
             with a matching guardrails.md §3 entry).
          3. Run: git diff -- tests/unit/test_csv_parser.py and check for
             removed/weakened assertions or @skip additions
          If ANY check fails, output `not completed: <reason>` with specific
          details. Do NOT fix code (see main guide §4.6).

  - id: 3
    name: "Module: Order database layer"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Bulk order creation queries implemented in src/db/orders.py
      2. Unit tests for the DB layer pass
      3. No files outside src/db/ and tests/unit/db/ modified
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
             modified (plus design_plan/ entries if a contract update was
             needed)
          5. No existing model schemas or migrations changed
          6. Changes committed
        initial_hint: |
          Read design_plan/db_orders.md and design_plan/index.md §3/§4.
          Check guardrails.md §2 for the scope whitelist.
          Check git status first — discard residual changes from previous retry.
          Implement queries AND unit tests together; design concrete test cases
          for every category in §4. Use fixtures from docs/testing_guide.md.

          If a contract is infeasible, update the relevant design_plan file
          (db_orders.md §2/§3 or index.md §3), append a guardrails.md §3
          revision-log entry, and commit the design_plan change with your
          code. NEVER widen guardrails.md §2 scope or delete a §4 category.
          Migration files and existing model schemas remain untouchable.

          Run pytest tests/unit/db/ before committing.
      - id: 3.2
        name: "Anti-hack verification for DB layer"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/db/ exits with code 0
          2. git diff --stat (since task 2 completion) shows only src/db/
             and tests/unit/db/ changed
          3. No migration files or existing model schemas modified
          4. No removed/weakened assertions or @skip additions
        initial_hint: |
          Execution-only. Run the DB unit tests, inspect git diff --stat
          against task 2's completion commit; allowed files must match the
          db.orders row in guardrails.md §2 (plus design_plan/** if a
          contract was updated with a matching guardrails.md §3 entry).
          If ANY check fails, output `not completed: <reason>`. Do NOT fix code.

  - id: 4
    name: "Module: Order service"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Bulk processing logic implemented in src/services/order_service.py
      2. Unit tests for the service pass with mocked dependencies
      3. No files outside src/services/ and tests/unit/services/ modified
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
             modified (plus design_plan/ entries if a contract update was
             needed)
          5. Database and payment dependencies mocked in tests
          6. Changes committed
        initial_hint: |
          Read design_plan/order_service.md and design_plan/index.md.
          Check guardrails.md §2 for the scope whitelist.
          csv_parser (task 2) and db.orders (task 3) contracts are already
          committed; consume them verbatim from design_plan/index.md §3.
          Mock their implementations in unit tests.

          If consuming a neighbor's contract surfaces a bug, update the
          relevant design_plan file (index.md §3 for cross-module changes,
          or a neighbor's <module>.md §2 if the neighbor's interface spec
          was wrong), append a guardrails.md §3 revision-log entry, and
          commit the design_plan change with your code. NEVER widen
          guardrails.md §2 scope or delete a §4 category.

          Run pytest tests/unit/services/ before committing.
      - id: 4.2
        name: "Anti-hack verification for service"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/services/ exits with code 0
          2. git diff --stat (since task 3 completion) shows only src/services/
             and tests/unit/services/ changed
          3. No removed/weakened assertions or @skip additions
        initial_hint: |
          Execution-only. Verify tests pass. Check git diff --stat against
          task 3's completion commit; allowed files must match the
          order_service row in guardrails.md §2 (plus design_plan/** if a
          contract was updated with a matching guardrails.md §3 entry).
          Check tests were not weakened. If ANY check fails, output
          `not completed: <reason>`. Do NOT fix code.

  - id: 5
    name: "Module: Admin API route"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. POST /api/admin/orders/bulk route implemented in src/routes/admin.py
      2. Unit tests for the route pass with mocked service
      3. No files outside src/routes/ and tests/unit/routes/ modified
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
             modified (plus design_plan/ entries if a contract update was
             needed)
          5. No existing route handlers or response schemas changed
          6. Changes committed
        initial_hint: |
          Read design_plan/admin_route.md and design_plan/index.md.
          Check guardrails.md §2 for the scope whitelist.
          order_service (task 4) contract is already committed in
          design_plan/index.md §3; consume it verbatim. Use FastAPI TestClient
          and `app.dependency_overrides` for mocking (per design_plan/index.md §4
          integration risks).

          If a contract surfaces an incompatibility, update the relevant
          design_plan file, append a guardrails.md §3 revision-log entry,
          and commit the design_plan change with your code. NEVER widen
          guardrails.md §2 scope or delete a §4 category.

          Run pytest tests/unit/routes/ before committing.
      - id: 5.2
        name: "Anti-hack verification for route"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest tests/unit/routes/ exits with code 0
          2. git diff --stat (since task 4 completion) shows only src/routes/
             and tests/unit/routes/ changed
          3. No existing route handlers or response schemas modified
          4. No removed/weakened assertions or @skip additions
        initial_hint: |
          Execution-only. Verify tests pass. Check git diff --stat against
          task 4's completion commit; allowed files must match the
          admin_route row in guardrails.md §2 (plus design_plan/** if a
          contract was updated with a matching guardrails.md §3 entry).
          Existing route handlers and response schemas must be untouched.
          If ANY check fails, output `not completed: <reason>`. Do NOT fix code.

  # -------------------------------------------------------------------------
  # Task 6 — Integration + global anti-hack.
  # Runs once all module tasks are complete; sees the full codebase.
  # Workload is small because each module was unit-tested in isolation.
  # -------------------------------------------------------------------------
  - id: 6
    name: "Integration: end-to-end tests, full suite, global anti-hack"
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
          All four module tasks (2–5) should be complete. Check git log to
          confirm; if any module task's expected files are missing, output
          `not completed: prerequisite module <id> incomplete`.
          Write integration tests per design_plan/index.md §4 integration
          risks (transaction boundary, call order, partial-failure semantics).
          If a cross-module bug surfaces, fix it in the responsible module
          (keep fix minimal) and re-run the test. Do NOT rewrite module logic.
      - id: 6.2
        name: "Global anti-hack and full-suite verification"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a test runner and code integrity verifier. Do NOT modify any files.
        completion_criteria: |
          1. pytest (full suite including integration) exits with code 0
          2. ruff check src/ tests/ exits with code 0
          3. mypy src/ exits with code 0
          4. git diff --stat against the baseline (end of task 1) shows
             changes only in the allowed-file lists documented in the
             CURRENT version of guardrails.md §2 (plus edits to design_plan/**
             or guardrails.md §3 itself)
          5. No existing tests weakened: no removed assertions, no
             @pytest.mark.skip additions, no relaxed comparisons, no
             conditional test bypasses
          6. No existing API schemas, migrations, or payment contracts modified
          7. Every test category listed in any design_plan/<module>.md §4
             has at least one concrete test function in the committed test files
          8. **Contract integrity**: diff design_plan/** and guardrails.md
             (task-1 baseline vs current) and verify:
             a. every change in design_plan/** has a matching revision-log
                entry in guardrails.md §3
             b. no allowed-file list in guardrails.md §2 has been widened
                (§2 is immutable; any diff to §2 is `not completed`)
             c. no §1 Baseline line in guardrails.md has been edited
             d. no test category has been deleted from any
                design_plan/<module>.md §4
        initial_hint: |
          This is an execution-only verification subtask.
          1. Run: pytest (full suite)
          2. Run: ruff check src/ tests/
          3. Run: mypy src/
          4. Run: git diff --stat <baseline-commit>..HEAD — verify every
             changed source/test file appears in some module's allowed-file
             list in the CURRENT guardrails.md §2 (design_plan/** and
             guardrails.md §3 edits are allowed in addition to source/test)
          5. Run: git diff -- tests/ across the whole repo — check for
             removed assertions, added @pytest.mark.skip / @xfail, relaxed
             comparisons, deleted tests
          6. Verify each new source file has a corresponding test file
          7. **Contract-hacking check**: run
               git show <baseline-commit>:guardrails.md > /tmp/guard_v1.md
               diff /tmp/guard_v1.md guardrails.md
               git diff <baseline-commit>..HEAD -- design_plan/
             Every diff chunk under design_plan/** must match a
             guardrails.md §3 entry. Any diff to guardrails.md §1 or §2 =
             `not completed: contract-hacking guardrails §<sec>`. Any
             §4 test-category deletion in design_plan/<module>.md =
             `not completed: contract-hacking <module>.md §4`.

          If ANY check fails, output `not completed: <reason>` with specific
          details. Do NOT fix code (see main guide §4.6).
```

**How this example maps to the three core principles:**

- **Module-based splitting at the top level**: tasks 2–5 each own one module (utils / db / service / route) as independent top-level `nested` tasks. When module 3 fails in linear mode, only task 3 retries; tasks 2 (done) and 4, 5 (not yet run) are unaffected.
- **Anti-hack verification**: subtasks 2.2, 3.2, 4.2, 5.2, 6.2 are all dedicated `max_attempts: 1` verifiers with `system_prompt_prefix` forbidding edits; each checks the module's tests + `git diff` scope + test-integrity heuristics. Task 6.2 is the global anti-hack that repeats these checks across the full repo.
- **Unit test discipline**: each implementation subtask (2.1, 3.1, 4.1, 5.1) lists the exact unit test cases it must deliver, written in the same subtask as the code. Integration tests are deferred to task 6.1, intentionally — they only become tractable once all modules exist.

### 5.1 Variants in design-doc mode

When the user provides a `design_plan/` (see §4.4), only three things change — the task graph stays identical:

1. `description.Reference Docs` gains `design_plan/` as a P0 Must Read entry.
2. `description.Rules` gains one line: "design_plan/ was user-provided; edit only on substantial gaps (missing <module>.md, missing Architecture section, undefined contract needed by anti-hack); every edit recorded in guardrails.md §3 with marker `gap-fill: <path> §<sec> — <what> — <why substantial>`."
3. **Task 1** switches from authoring design_plan/ to inspect-and-gap-fill; guardrails.md is always authored from scratch.

Task 1 `completion_criteria` becomes:

```yaml
      1. design_plan/ (user-provided) has been read end-to-end. Any
         substantial gap (missing <module>.md for a module task 2–5;
         missing §2 Architecture or §3/§4 sections in index.md; a contract
         needed by anti-hack that is entirely undefined) has been filled
         directly in the relevant file. Cosmetic, stylistic, or
         reorganization edits are NOT performed.
      2. guardrails.md is produced from scratch with §1 Baseline
         (commit SHA after step 1's edits, plus pytest/ruff/mypy state),
         §2 Scope Whitelist (exhaustive), and §3 Revision Log. The log's
         initial entry records the baseline; any gap-fill edit performed
         in step 1 gets its own entry in the form
         `gap-fill: <path> §<sec> — <what> — <why substantial>`.
      3. design_plan/ and guardrails.md are committed together; that
         commit is the baseline referenced in guardrails.md §1.
      4. No source code modified.
```

Each module task's `initial_hint` also gains one line: "design_plan/ was user-provided; prefer working around design quirks in code over editing design_plan/. Edit only on real contract bugs, and always pair the edit with a guardrails.md §3 entry."