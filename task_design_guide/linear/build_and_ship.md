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
├── fatal_analysis                                          (reserved, simple)
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

- Use `nested` (not `looping`) because the goal is "reach a specific end state", not "run N rounds".
- **Separate analysis from implementation**: design plan in one task, implementation in others (see main guide §4.2).
- The "review design_plan/ for completeness" task should have high `max_attempts` so that the design plan can be thoroughly reviewed multiple times.
- Anti-hack verification subtasks should use `max_attempts: 1` — failures should propagate to the parent for proper retry.
- Build/test subtask in the prerequisite task should use `fatal: true` — if the project cannot build or pass tests without any modification, this is a prerequisite failure that `fatal_analysis` should handle. It is fatal analysis task's responsibility to define the fix boundary. **Skip build/test subtask entirely if the project is built from scratch, or cannot be partially built / tested.**.
- Use `long_running` for build / test / verification a if they contain commands that may exceed one minute.
- Executors that output `❌ not completed` or `❌ FATAL` must append an entry to `error_report.md` before outputting the marker.

---

## 3. Key Insights

1. **Why top-level splitting (not one big nested)?**

When a `nested` task's subtask fails, the retry mechanism will rerun that subtask **and every subtask after it**. If you stuff N module implementations into one nested task and module 5 of 10 fails, modules 5–10 all rerun — wasting the already-correct work of modules 6–10. Instead, top-level tasks are isolated retry units: module 3 failing has no effect on modules 1–2 (already completed) and does not force modules 4..N to rerun. 

However, top-level tasks are isolated retry units, so issues left by one task cannot be fixed by retrying that task from a later task. That is why each module's replan subtask must fix issues left by earlier tasks and ensure design_plan/ is accurate before implementation starts.

2. **`looping` is generally not recommended for Build & Ship**, since the goal of implementation is typically "to reach a specific end state".

3. **Details for task decomposition when module-based splitting is required**:
  - **Each `nested` task generally has three subtasks**: `replan`, `implement + test`, and `anti-hack verify`.
  - **A final top-level integration task is added at the end**. This task sees the full codebase, runs the whole test suite, and fixes cross-module bugs only now visible. Its workload is not large because each module has already been unit-tested in isolation.

4. **Anti-hack subtask should explicitly output `❌ not completed: <reason>` when anti-hack check fails** for correct failure propagation (see main guide §2.3).

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

### 4.3 Plan vs reality: update policy

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

Use this example to understand the recommended linear-mode structure for Build & Ship. Replace every `<placeholder>` token with project-specific content; do not copy placeholder wording into real tasks. `<!-- xxx -->` are comments that explain this example in detail, so do not include them into real tasks either.

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

  ## Design & Audit Docs
  - design_plan/index.md —— system overview, architecture, document directory (Must Read)
  - design_plan/<module>.md —— one per module: responsibility, public interface, internal design, test strategy, dependencies (Must Read for the owning module task; other modules Read on Demand)
  - guardrails.md —— baseline commit, scope whitelist, revision log, module-start SHA markers (Must Read for anti-hack subtasks)
  - error_report.md —— execution error records; executors write on failure, only failure/fatal analysis task reads (P1)

  ## Environments
  <environments>

  ## Key Commands
  - <command 1>: <command>
  - <command 2>: <command>
  ...

  ## Hard Constraints
  - Each module task's changes must be scoped to its own allowed-file list in guardrails.md §2.
  - <project-specific constraints on what should not be modified>
  - <project-specific constraints on not weakening existing tests, if any exist>
  - <other project-specific constraints>

  ## Reference Docs
  ### P0 Must Read
    - <document path 1>: <its responsibility>
    - <document path 2>: <its responsibility>
    ...
  ### P1 Read Before Related Work
    - <document path 1>: <its responsibility>
    - <document path 2>: <its responsibility>
    ...
  ### P2 On Demand
    - <document path 1>: <its responsibility>
    - <document path 2>: <its responsibility>
    ...

  ## Rules
  - Persist design to design_plan/index.md and design_plan/<module>.md; persist audit data (baseline, scope whitelist, revision log, module-start SHAs) to guardrails.md.
  - Before any implementation work on a module, the replan subtask must record the current HEAD
    in guardrails.md §3 as `module-start: <module> — <sha> — before task <id> edits`.
    Anti-hack subtasks diff from this SHA.
  - A module task may edit its own design_plan/<module>.md or append to design_plan/index.md
    when implementation surfaces a real contract bug. Every design_plan change must be committed
    with the dependent code and recorded in guardrails.md §3 with a `contract-update:` or
    `gap-fill:` marker.
  - guardrails.md §1 is immutable after Task 1; §2 may only grow via `scope-extend:` entries
    in §3; §3 is append-only.
  - Before starting any implementation subtask, run `git status`; if uncommitted changes exist
    from a previous retry, inspect and either continue from them or `git checkout .` to discard.
  - <other project-specific rules>

tasks:
  # ── Fatal Analysis ─────────────────────────────────────────────────────────
  - id: fatal_analysis
    name: "Diagnose and resolve fatal prerequisite failures"
    type: simple
    max_attempts: 2
    completion_criteria: |
      1. The root cause of the fatal failure claimed by previous failed task is identified.
      2. If fixable within user-defined allowed scope, the correct fix is applied and verified.
      3. If not fixable within allowed scope, AutoAgent is stopped with a clear explanation.
    system_prompt_prefix: |
      You are a diagnostic engineer. You may inspect any file and fix failures claimed by previous failed task within the user-defined allowed scope.
    initial_hint: |
      Read error_report.md for the fatal error details.

      Allowed fixes:
        <project-specific allowed fixes>

      Not allowed:
        <project-specific restrictions>

  # ── Task 1: Prerequisite Check + Design ────────────────────────────────────
  <!-- If the project is built from scratch, remove subtask 1.1 and its corresponding completion_criteria items. -->
  - id: 1
    name: "Verify prerequisites and write design_plan/ + guardrails.md"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. <build command> exits 0. <!-- Remove if no existing code to build -->
      2. <test command> exits 0. <!-- Remove if no existing tests -->
      3. design_plan/index.md is produced with §1 Overview, §2 Architecture, §3 Document Directory.
      4. One design_plan/<module>.md is produced for each top-level module task, each with §1 Responsibility, §2 Public Interface, §3 Internal Design, §4 Test Strategy, §5 Dependencies.
      5. design_plan/ is reviewed for completeness: every design decision that would be "freely invented" by implementation is explicitly complemented.
      6. guardrails.md is produced with §1 Baseline, §2 Scope Whitelist, §3 Revision Log.
      7. error_report.md exists with a header, initially empty.
      8. No source files, tests, configs, or scripts are modified.
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

          If build or test fails, first retry the failing command once to rule out transient issues  (e.g. resource busy, file locked, network flake). 
          Only if the failure persists after retry, append an entry to error_report.md with the failure details, then output `❌ FATAL: <build/test failure reason>` so that a dedicated analysis task can handle it.

      <!-- If user has provided a design plan, replace the whole subtask 1.2 with the variant defined in section 6.1 of this guide. -->
      - id: 1.2
        name: "Write design_plan/, guardrails.md, and error_report.md"
        type: simple
        completion_criteria: |
          1. design_plan/index.md produced with §1 Overview, §2 Architecture, §3 Document Directory, §4 Task-Module Assignment.
          2. One design_plan/<module>.md is produced per module in the project's own module decomposition.
             A single task may span multiple modules (and thus multiple .md files); a single module may also
             be shared by multiple tasks. The assignment of which task works on which module document is
             recorded in index.md §4 Task-Module Assignment and must be consistent.
          3. guardrails.md is produced with §1 Baseline, §2 Scope Whitelist (one entry per task), §3 Revision Log.
          4. error_report.md exists with a header, initially empty.
          5. No source files, tests, configs, or scripts are modified.
        system_prompt_prefix: |
          You are a global planner. Your role is to produce the master design plan that every
          subsequent task will execute against. You must think holistically across the entire
          project — every module, every cross-module interface, every error path — and ensure
          the design plan is complete, unambiguous, and internally consistent. No implementation
          detail should be left for later tasks to invent; the only thing excluded is
          pseudocode / line-level code. Do NOT modify source code, tests, or configs.
        initial_hint: |
          ## Project Detail

          <Write all project details that this plan task needs here. Do NOT duplicate things that has been written in root description. Since this task needs to write the whole design plan, this task must have all the information of this project.>

          ## Task decomposition is FIXED

          The tasks below have already been decomposed in the todo list. This decomposition is NOT
          modifiable — you MUST NOT change task boundaries, merge tasks, or create new tasks.
          The only thing you may adjust is which module document(s) each task is responsible for
          (recorded in index.md §4).

          Modules are defined by the project's own architecture — NOT by a 1:1 mapping to tasks.
          A task may own multiple module documents; a module document may be shared by multiple tasks.

          ## Subsequent Task Decomposition

          Here are the subsequent task's decomposition details:
           
          | Task ID | Task Name | Work Description |
          |---------|-----------|------------------|
          | 2       | <task 2's name> | <what task 2 implements> |
          | 3       | <task 3's name> | <what task 3 implements> |
          ...
          | <last_id> | Integration | End-to-end tests, full suite, global anti-hack |

          ## Design Plan Format

          1. Create design_plan/index.md exactly in this Markdown format:
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

          2. Create one design_plan/<module>.md per module in the project decomposition exactly in this Markdown format:
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

          3. Create guardrails.md exactly in this Markdown format:
              # Guardrails
              
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

          4. Create error_report.md exactly in this Markdown format:
             # Error Report —— <project name>

             (none yet)

          design_plan/ must be thorough: every design decision that the implementation AI
          would otherwise invent freely must be explicitly specified (error handling protocols,
          state transitions, validation rules, concurrency semantics, etc.).
          The only thing excluded is pseudocode / line-level implementation.
          guardrails is audit data, not documentation.

          Commit all of them together; that commit is the baseline for all later anti-hack subtasks.
          Do NOT modify source code in this task.

      - id: 1.3
        name: "Review design_plan/ for completeness"
        type: simple
        max_attempts: 5
        completion_criteria: |
          1. index.md §3 Document Directory list all module docs, and §4 Task-Module Assignment are reasonable and applicable.
          2. <write project-specific completion_criteria here>
          3. No design point is left ambiguous enough that two reasonable implementations would behave differently.
          4. If gaps are found, they are filled directly in design_plan/ and committed, then output `❌ not completed: task 1.3 should be retried to review once more` so that another reviewer can review it again.
          5. No source files, tests, configs, or scripts are modified.
        system_prompt_prefix: |
          You are a design reviewer. Your job is to find underspecified design points that would force the implementation AI to guess. Do NOT modify source code, tests, or configs.
        initial_hint: |
          Read every file in design_plan/ carefully. For each module, check:

          - Does index.md §3 Document Directory list all module docs?
          - Are index.md §4 Task-Module Assignment reasonable and applicable?
          <write other project-specific review rules here>

          For every gap found, fill it directly in the relevant design_plan/ file. Once complete:
          1. Record in guardrails.md §3: `gap-fill: <path> §<sec> — <what> — <why substantial>`
          2. commit every additions together;
          3. output `❌ not completed: task 1.3 should be retried to review once more` so that another reviewer can review it again.

  # ── Tasks 2..N: One top-level nested task per module ───────────────────────
  <!-- Repeat this pattern for each module. The example shows one module task. -->
  - id: 2
    name: "Module: <module_name>"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. <module-specific implementation criteria>
      2. Unit tests for <module_name> pass.
      3. No files outside the <module_name> effective scope (original guardrails.md §2 entry + any `scope-extend:` additions) are modified, except design_plan/** updates justified by `contract-update:` markers and append-only guardrails.md §3 entries.
      4. <negative constraints for this module>
    subtasks:
      - id: 2.1
        name: "Replan <module_name>: review current state and update local plan"
        type: simple
        completion_criteria: |
          1. design_plan/<module_name>.md, design_plan/index.md, and guardrails.md have been read.
          2. Current codebase state has been inspected (git log, existing source files from earlier modules).
          3. If the original plan needs adjustments (new files needed, interface changes from earlier modules, scope changes, or issues from earlier tasks' work), design_plan/<module_name>.md is updated and guardrails.md §2 is extended with `scope-extend:` entries in §3.
          4. If earlier tasks left incorrect or incomplete design artifacts, they are fixed directly in design_plan/ (earlier tasks cannot be retried).
          5. Any updates are committed before implementation begins.
        initial_hint: |
          Read design_plan/<module_name>.md (your module) and design_plan/index.md (system architecture and cross-module context).
          Inspect the current codebase — earlier module tasks may have changed interfaces, added files, or updated contracts.

          Your job is to ensure design_plan/ is accurate and complete for this module BEFORE implementation starts. Earlier tasks cannot be retried — if they left issues in design_plan/, fix them here directly.

          1. Record the current `HEAD` in guardrails.md §3 as:
             `module-start: <module_name> — <sha> — before task 2 edits`
             This must be done before any edits.

          2. Specifically check and update:
             - If earlier modules changed interfaces that affect this module, update design_plan/<module_name>.md §2/§3 accordingly, and record in guardrails.md §3:
               `contract-update: <path> §<sec> — <old> → <new> — <why>`
             - If new files are needed (helpers, configs, migrations), extend guardrails.md §2 by appending the new files to the <module_name> row, and record in §3:
               `scope-extend: <module_name> — <new files> — <why needed>`

          3. If no changes needed, proceed without modifications.
          4. Commit any plan/scope updates before implementation begins.

      - id: 2.2
        name: "Implement <module_name> with unit tests"
        type: simple
        completion_criteria: |
          1. <module_name> implemented per the public interface in design_plan/<module_name>.md §2 (and cross-module edges in adjacent design_plan/<other_module>.md §2/§5).
          2. Unit tests in <test file path> cover **every category** listed in design_plan/<module_name>.md §4 (happy / edge / error). Concrete cases are designed by this task.
          3. <module test command> passes.
          4. Only files inside the <module_name> effective scope (original §2 entry + `scope-extend:` additions) are modified, plus design_plan/** updates justified by `contract-update:` markers and append-only guardrails.md §3 entries.
          5. Changes inside this task are committed.
        initial_hint: |
          Read design_plan/<module_name>.md (your module) and design_plan/index.md (system architecture and cross-module context).
          Check guardrails.md §2 for the effective scope whitelist for <module_name> (including any `scope-extend:` additions from the replan subtask).
          Check git status first — discard residual changes from previous retry.
          Implement source code AND unit tests together.

          If you discover the contract is infeasible or wrong, you MAY update design_plan/ (<module_name>.md §2/§3 as appropriate) and append a guardrails.md §3 entry in the form
          `contract-update: <path> §<sec> — <old> → <new> — <why>`; commit the design_plan change alongside your code.
          If earlier tasks left bugs in the code, fix them directly —— earlier tasks cannot be retried.
          
          Run <module test command> before committing changes. NEVER delete a §4 test category just to pass.

      - id: 2.3
        name: "Anti-hack verification for <module_name>"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are an anti-hack verifier. Your sole job is to detect constraint violations. Do NOT modify source code, tests, configs, scripts, or generated data.
        completion_criteria: |
          1. <module test command> exits with code 0.
          2. If verification result is 'FAIL', output `❌ not completed: Anti-hack verification failed. Implementation task should be retried` so that the implementation task can be retried.
          3. No public contracts, tests, configs, scripts, generated outputs, or unrelated modules were modified.
        initial_hint: |
          Run: <module test command>

          Inspect git to find implementation code changes corresponding to this module.
          
          1. Read the <module_name> `module-start:` SHA from guardrails.md §3.
             Run: git diff --name-only <module_name-module-start-sha>..HEAD
             Allowed files must be within the <module_name> effective scope: the original §2 row PLUS any files added via `scope-extend:` entries in §3 for this module.
             design_plan/** and guardrails.md §3 are allowed only if a contract was updated with a matching marker.

          2. Run: git diff <module_name-module-start-sha>..HEAD -- <test file path>
             and check for removed/weakened assertions or skipped-test annotations.

          3. <write all other anti-hack rules here based on global description and task-specific informations>

          If verification result is 'FAIL', append an entry to error_report.md with the failure details, then output `❌ not completed: Anti-hack verification failed. Implementation task should be retried`
          so that the implementation task can be retried. Do not fix code by yourself.

  <!-- Repeat tasks 3..N for remaining modules following the same pattern as task 2. -->

  # ── Final Task: Integration + Global Anti-hack ─────────────────────────────
  - id: <last_id>
    name: "Integration: end-to-end tests, full suite, global anti-hack"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Integration tests for the end-to-end flow pass.
      2. Full <test command> suite exits with code 0.
      3. No existing tests weakened in the repo.
    subtasks:
      - id: <last_id>.1
        name: "Write and pass integration tests"
        type: simple
        max_attempts: 3
        completion_criteria: |
          1. <integration test file path> added, covering the end-to-end flow.
          2. <integration test command> passes.
          3. If a cross-module bug is found, fix is scoped to the minimal module(s) responsible; module-internal logic refactors are not allowed — only bug fixes.
        initial_hint: |
          Verify source and test files for each module exist and their unit tests pass.
          If a module left issues (failing tests, missing integration points), fix them here — earlier tasks cannot be retried.

          Write integration tests per cross-module interfaces documented in each design_plan/<module>.md §2 and §5, and any integration risks noted in design_plan/index.md §2 Architecture.
          If a cross-module bug surfaces, fix it in the responsible module (keep fix minimal) and re-run the test.
          Do NOT rewrite module logic.

          Changes are commited once completed.

      - id: <last_id>.2
        name: "Global anti-hack and full-suite verification"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are a test runner and code integrity verifier. Do NOT modify any files except for appending to error_report.md on failure.
        completion_criteria: |
          1. <test command> (full suite) exits with code 0.
          2. git diff --name-only <guardrails-baseline-sha>..HEAD shows changes only in the effective scope (original guardrails.md §2 entries + `scope-extend:` additions in §3), plus design_plan/** and append-only guardrails.md §3 edits.
          3. No existing tests weakened: no removed assertions, no skipped-test annotations, no relaxed comparisons, no conditional test bypasses.
          4. If verification result is 'FAIL', output `❌ not completed: Anti-hack verification failed. Implementation task should be retried` so that the implementation task can be retried.
          5. No public contracts, tests, configs, scripts, generated outputs, or unrelated modules were modified.
        initial_hint: |
          Run: <test command> (full suite)

          Inspect git to find implementation code changes of all modules.

          1. Read the baseline SHA from guardrails.md §1. Run:
             git diff --name-only <guardrails-baseline-sha>..HEAD
             Verify every changed source/test file appears in some module's effective scope (original §2 entry + `scope-extend:` additions in §3).
             design_plan/** and append-only guardrails.md §3 edits are allowed only with matching revision-log markers.

          2. Run: git diff <guardrails-baseline-sha>..HEAD -- <test directories>
             Check for removed assertions, added skip/xfail annotations, relaxed comparisons, deleted tests.

          3. <write all other anti-hack rules here based on global description and task-specific informations>

          If verification result is 'FAIL', append an entry to error_report.md with the failure details, then output `❌ not completed: Anti-hack verification failed. Integration task should be retried`
          so that the integration task can be retried. Do not fix code by yourself.
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
    1. The assignment of which task works on which module document is recorded in index.md "Task-Module Assignment" session if missing.
    2. Any substantial gap in the user-provided design plan has been filled, with its own entry in guardrails.md §3 Revision Log.
    3. guardrails.md is produced with §1 Baseline, §2 Scope Whitelist (one entry per task), §3 Revision Log.
    4. error_report.md exists with a header, initially empty.
    5. No source files, tests, configs, or scripts are modified.
  system_prompt_prefix: |
    You are a global planner. Your role is to produce the master design plan that every
    subsequent task will execute against. You must think holistically across the entire
    project — every module, every cross-module interface, every error path — and ensure
    the design plan is complete, unambiguous, and internally consistent. No implementation
    detail should be left for later tasks to invent; the only thing excluded is
    pseudocode / line-level code. Do NOT modify source code, tests, or configs.
  initial_hint: |
    Read the user-provided design plan <path/to/design_plan> end-to-end.

    ## Task decomposition is FIXED

    The tasks below have already been decomposed in the todo list. This decomposition is NOT
    modifiable — you MUST NOT change task boundaries, merge tasks, or create new tasks.
    The only thing you may adjust is which module document(s) each task is responsible for.

    You should add a "Task-Module Assignment" section to index.md if missing:

    | Module Document | Responsible Task(s) |
    | design_plan/<module_1>.md | <task id(s)> |
    | design_plan/<module_2>.md | <task id(s)> |

    Modules are defined by the project's own architecture — NOT by a 1:1 mapping to tasks.
    A task may own multiple module documents; a module document may be shared by multiple tasks.

    ## Subsequent Task Decomposition

    Here are the subsequent task's decomposition details:
      
    | Task ID | Task Name | Work Description |
    |---------|-----------|------------------|
    | 2       | <task 2's name> | <what task 2 implements> |
    | 3       | <task 3's name> | <what task 3 implements> |
    ...
    | <last_id> | Integration | End-to-end tests, full suite, global anti-hack |

    ## guardrails.md Format

    Create guardrails.md exactly in this Markdown format:
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

    Your job is to fill any substantial gap (missing <module>.md for a module task, a contract needed by anti-hack that is entirely undefined, etc.) in the user-defined file. 
    Cosmetic, stylistic, or reorganization edits are NOT performed.

    Any gap-fill edit should get its own entry in guardrails.md §3 Revision Log, in the form
    `gap-fill: <path> §<sec> — <what> — <why substantial>`.

    ## error_report.md Format

    Create error_report.md exactly in this Markdown format:
        # Error Report —— <project name>

        (none yet)

    Commit all of them together; that commit is the baseline for all later anti-hack subtasks.
    Do NOT modify source code in this task.
```