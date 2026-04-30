# Best Practice: Iterative Optimization

## Recommended Structure

```
├── nested
|   ├── build the project           (simple, model: lite)
|   └── establish baseline          (simple, model: lite)
├── analyze + propose hypothesis    (simple)
├── nested
|   ├── implement + build + test    (simple)
|   └── anti-hack check             (simple, max_attempts: 1)
├── benchmark                       (simple or long_running, max_attempts: 1, model: lite)
├── evaluate + keep/revert + report (simple, max_attempts: 1)
└── diagnose repeated failures      (simple)
```

- **Separate "thinking" from "doing"**: analysis in one subtask, implementation in another (see main guide §4.1).
- **finding fast-check profiling modes**: in implementation task, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor) when it is long-running to speed up self-correction (see main guide rule 10).
- **Explicitly tells the AI to output `not completed`** for anti-hack checks and benchmark tasks (see main guide §4.7).
- Anti-hack check, benchmark and evaluation subtasks should use `max_attempts: 1` —— failures should propagate to the parent for proper retry.
- Benchmark subtask should use `model: lite` —— they just execute.
- Use `long_running` for benchmark if it takes more than a minute (e.g. GPU profiling, large simulation runs).

---

## Patterns

### Pattern 1: Separate documentation commits from code commits

Commit the hypothesis documentation **before** implementing code. If the code is rolled back on failure/regression, the documentation survives and informs the next iteration.

### Pattern 2: Re-evaluate the bottleneck every iteration

Don't assume the bottleneck is the same as the previous round. Instruct the AI to compute a diagnostic metric at the start of each iteration to determine where to focus.

### Pattern 3: Define a decision matrix for keep/discard

Don't let the AI make subjective keep/discard decisions. Provide a structured decision matrix in the evaluation subtask's `initial_hint`:

```yaml
initial_hint: |
  ┌─────────────────────────────────────────────────────────────────┬──────────┐
  │ Condition                                                       │ Decision │
  ├─────────────────────────────────────────────────────────────────┼──────────┤
  │ Pure bug fix (no optimization intent)                           │ keep     │
  │ Primary bottleneck metric improved ≥5%                          │ keep     │
  │   AND no other metric group worsened >3%                        │          │
  │ Secondary bottleneck metric improved ≥5%                        │ keep     │
  │   AND primary not worsened >3%                                  │          │
  │ Multiple metrics improved (even if each <5%)                    │ keep     │
  │   AND none worsened >3%                                         │          │
  │ Primary bottleneck metric worsened >10%                         │ discard  │
  │ Any metric worsened >5% with no bottleneck compensation         │ discard  │
  │ All metrics within ±1% (no meaningful change)                   │ discard  │
  │ Mixed results not covered above                                 │ discard  │
  └─────────────────────────────────────────────────────────────────┴──────────┘
```

### Pattern 4: Clean workspace at iteration start

Since subtasks share the filesystem, the start of each iteration may find uncommitted changes or stashed work from a previous failed attempt. Instruct the first subtask to handle this.

---

## Recommended State Files

Use a small, stable set of files to preserve optimization state across isolated agent sessions. The files below assume they live under `doc/`, but the same names can be adapted to the target project's documentation directory.

### `optimization_results.tsv`

Records the baseline and every experiment result. This is a structured source of truth and **must be read by the AI agent** before deciding what to try, keep, revert, or reject.

Recommended columns:

```tsv
exp_id	date	module	changes	 <metric columns...>	status	reason	commit_hash
```

- `exp_id`: stable experiment ID, such as `EXP-001`.
- `date`: date when the experiment row was created or finalized.
- `module`: the module or subsystem changed by the experiment.
- `changes`: short summary of what changed.
- `<metric columns...>`: task-specific metric columns chosen by the todo-generating AI. Different projects need different metrics, so do not force a universal metric schema.
- `status`: one of `baseline`, `pending`, `kept`, `reverted`, or `rejected`.
- `reason`: compact explanation of the status or decision.
- `commit_hash`: commit that contains the kept/reverted implementation or relevant documentation update.

### `optimization_log.md`

Records **detailed** experiment hypotheses, target areas, risks, profiling results, and decision reasons. The AI agent should **always read the tail/recent entries** and may read older entries on demand when investigating history or avoiding repeated work.

Idea generation may produce more than one candidate at a time. In AI scheduling mode, the scheduler can manage this more naturally by running one idea generation task and multiple implementation / benchmark / report tasks.

Pending ideas are candidates, not obligations: before the implementation task implements a pending idea, confirm that it is still valid after any earlier idea has been kept. If not, tell the AI to say `rejected`.

Recommended entry format:

```md
## Exp xxx: xxx
Date: xxx
Module: xxx
Status: xxx

### Hypothesis

xxx

### Proposed Changes

xxx

### Expected Outcome

xxx

### Risk

xxx

### Profiling Results

xxx

### Decision

xxx
```

The idea generation stage writes the header, `Hypothesis`, `Proposed Changes`, `Expected Outcome`, and `Risk`. The benchmark stage writes `Profiling Results`. The reporting/evaluation stage writes `Decision` and updates the status.

### `optimization_report.md`

A rolling summary updated after every round. It summarizes `optimization_log.md`. It **must be read by the AI agent** before proposing or implementing further optimization work.

Recommended structure:

```md
## Project Overview

xxx

## Current Best vs Baseline

xxx

## Experiment Summary

| Exp | Date | Module | Changes | Module Delta | Total Delta | Status | Reason |
|-----|------|--------|---------|--------------|-------------|--------|--------|

## Cumulative Improvement

| Experiment | Value |
|------------|-------|
| Baseline | 615.1 us |
| After EXP-001 | 585.8 us (-4.8%) |
| After EXP-003 | 426.4 us (-30.7%) |
| After EXP-004 | 414.6 us (-32.6%) |

## Key Changes

1. **EXP-001 (KEEP)**: short summary.
2. **EXP-002 (REVERT)**: short summary.
```

Keep summaries concise. The report should make the current state easy to understand without forcing the agent to reread the full `optimization_log` every round.

### `failure_patterns.md`

Records proven failure patterns and promising directions to prevent repeated attempts. This file **must be read by the AI agent** before proposing new ideas.

Recommended structure:

```md
## Proven Failure Patterns

### Pattern xxx: xxx
Experiment: EXP-xxx — xxx
Result: xxx time 122.7 -> 133.2ms (+8.6%)
Root Cause: xxx
Lesson: xxx

## Promising Directions

### Direction xxx: xxx
Experiment: EXP-xxx — xxx
Result: xxx time 120.4 -> 92.2ms (-23.4%)
Why it worked: xxx
Lesson: xxx
```

Keep `Root Cause`, `Why it worked`, and `Lesson` short. This file should be a compact knowledge base, not a long-form report.

---

## Complete Example

Below is a complete AI-scheduler-mode `todos.yaml` demonstrating scheduler-managed optimization with batched idea generation, file-backed scheduler state, explicit failure propagation for execution-only subtasks, anti-hack verification, benchmark evaluation, failure-pattern tracking, and a rolling final report.

```yaml
description: |
  # Project: Web API Performance Optimization

  ## Goal
  Optimize the REST API server until p95 latency is below 50ms, or until the
  scheduler determines that no safe optimization remains. Keep all integration
  tests passing, preserve benchmark integrity, and make every scheduler decision
  traceable through the optimization state files under doc/.

  ## Architecture
  - src/handlers/users.rs —— user-facing HTTP handlers and request validation
  - src/handlers/orders.rs —— order APIs and response assembly
  - src/db/pool.rs —— PostgreSQL connection pool and transaction helpers
  - src/db/queries.rs —— hot-path SQL query functions
  - src/cache/redis.rs —— Redis client wrapper and cache key construction
  - src/middleware/auth.rs —— authentication middleware used by all routes
  - tests/integration/ —— end-to-end API behavior tests
  - benchmarks/load_test.js —— k6 load test for latency measurements
  - config/server.yaml —— runtime configuration for local benchmark runs

  ## Optimization Docs
  - doc/optimization_results.tsv —— structured baseline and experiment results; must read
  - doc/optimization_log.md —— detailed experiment log; read recent entries first, older entries on demand
  - doc/optimization_report.md —— rolling summary and final report; must read
  - doc/failure_patterns.md —— proven failures and promising directions; must read

  ## Environment
  - Run commands from the repository root.
  - PostgreSQL and Redis must be available through the local development compose stack.
  - Benchmark runs must use the checked-in benchmark script and checked-in server config.

  ## Key Commands
  - Start dependencies: docker compose up -d postgres redis
  - Build: cargo build --release
  - Test: cargo test --all
  - Benchmark: k6 run benchmarks/load_test.js --out json=results.json

  ## Hard Constraints
  - Do NOT modify public request/response schemas.
  - Do NOT remove, weaken, skip, or rewrite tests to hide failures.
  - Do NOT change benchmark scripts, load shape, benchmark thresholds, or server config to hide regressions.
  - Do NOT edit generated benchmark output by hand; summarize it in docs instead.
  - Keep each implementation focused and reversible.

  ## Reference Docs
  - P0 Must Read: doc/architecture.md —— request flow, service boundaries, and public API contracts
  - P1 Read Before Related Work: doc/database_indexes.md —— read before changing src/db/
  - P1 Read Before Related Work: doc/cache_semantics.md —— read before changing src/cache/
  - P1 Read Before Related Work: doc/benchmark_methodology.md —— read before interpreting benchmark results
  - P2 On Demand: doc/runtime_tuning.md —— read only when investigating runtime or pooling behavior

  ## Rules
  - Fully autonomous: never ask the user questions.
  - Persist scheduler-relevant outcomes in the optimization docs listed above.
  - Generate a small batch of candidate ideas, then let the scheduler execute pending ideas one at a time.
  - Before implementing a pending idea, confirm it is still valid after any earlier kept changes.
  - If an execution-only subtask finds broken prerequisites, output `not completed: <reason>`.

ai_orchestrator:
  max_rounds: 20
  strategy: |
    Scheduling rules:
    1. If Task 1 (Build, test, benchmark, and initialize optimization state) has never succeeded, run Task 1.
    2. After Task 1 succeeds, run Task 2 (Analyze evidence and propose candidate ideas).
    3. After Task 2 succeeds and doc/optimization_log.md contains pending experiments, run Task 3 (Implement and anti-hack verify the next pending idea).
    4. If Task 3 rejects the selected idea, run Task 5 (Evaluate result and update optimization state) to record the rejection in the rolling report, then return to Task 2 if no pending ideas remain.
    5. If Task 3 implements and verifies a change, run Task 4 (Run benchmark for the verified implementation).
    6. After Task 4 succeeds, run Task 5 to apply the decision matrix, keep or revert the implementation, and update optimization state.
    7. After Task 5 finalizes an experiment, run Task 3 again if pending ideas remain and are still valid; otherwise run Task 2.
    8. Stop when doc/optimization_report.md shows the latest kept result has tests=pass and p95_ms < 50.
    9. If execution-only verification in Task 3 or benchmark Task 4 fails twice consecutively with `not completed`, run Task 6 (Diagnose repeated failures in core state files).
    10. If Task 6 records stop_no_safe_optimization or stop_external_blocker in doc/optimization_report.md, stop.
  stop_condition: |
    Stop after doc/optimization_report.md shows either:
    - target_reached with latest kept tests=pass and p95_ms < 50, or
    - stop_no_safe_optimization, or
    - stop_external_blocker, or
    - five consecutive reverted or rejected experiments with no p95 improvement.
  last_result:
    1:
      type: file
      path:
        - ${workspace}/doc/optimization_results.tsv
        - ${workspace}/doc/optimization_log.md
        - ${workspace}/doc/optimization_report.md
        - ${workspace}/doc/failure_patterns.md
    2:
      type: file
      path:
        - ${workspace}/doc/optimization_log.md
        - ${workspace}/doc/optimization_report.md
    3:
      type: file
      path:
        - ${workspace}/doc/optimization_log.md
        - ${workspace}/doc/optimization_report.md
    4:
      type: file
      path: ${workspace}/results.json
    5:
      type: file
      path:
        - ${workspace}/doc/optimization_log.md
        - ${workspace}/doc/optimization_report.md
    6:
      type: file
      path:
        - ${workspace}/doc/optimization_report.md
        - ${workspace}/doc/failure_patterns.md

tasks:
  - id: 1
    name: "Build, test, benchmark, and initialize optimization state"
    type: long_running
    description: |
      Build the project, run tests, establish the baseline benchmark, and create
      the four core optimization state files that the scheduler observes.
    completion_criteria: |
      1. cargo build --release exits 0.
      2. cargo test --all exits 0.
      3. k6 benchmark completes and writes results.json.
      4. doc/optimization_results.tsv exists with one baseline row using status=baseline.
      5. doc/optimization_log.md exists with baseline context and experiment numbering guidance.
      6. doc/optimization_report.md exists with project overview, baseline, empty experiment summary, cumulative improvement, and key changes sections.
      7. doc/failure_patterns.md exists with Proven Failure Patterns and Promising Directions sections.
      8. No source files, tests, configs, benchmark scripts, or hand-edited benchmark outputs are modified.
    initial_hint: |
      Run:
      - docker compose up -d postgres redis
      - cargo build --release
      - cargo test --all
      - k6 run benchmarks/load_test.js --out json=results.json

      Parse results.json for the task-specific metrics, including p95 latency.
      Create the four optimization state files if missing. Use metric columns
      appropriate for this API optimization task, such as p50_ms, p95_ms,
      p99_ms, error_rate, and throughput_rps.

      results.json is a temporary benchmark artifact, not long-lived state.
      Preserve existing optimization history if the files already exist. If the
      build, tests, or benchmark cannot run because prerequisites are broken,
      output `not completed: <reason>` and do not edit source code, tests,
      configs, or benchmark scripts.

  - id: 2
    name: "Analyze evidence and propose candidate ideas"
    type: simple
    description: |
      Read the current optimization state, re-evaluate the bottleneck, and append
      up to three pending candidate experiments for scheduler-managed execution.
    completion_criteria: |
      1. doc/optimization_results.tsv, recent doc/optimization_log.md entries, doc/optimization_report.md, and doc/failure_patterns.md have been read.
      2. Up to three new pending experiments are appended to doc/optimization_log.md using the recommended experiment format.
      3. Matching pending rows are appended to doc/optimization_results.tsv with status=pending.
      4. Each idea identifies the module, proposed changes, expected outcome, and risk.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, or rolling summary files are modified.
      6. The hypothesis documentation is committed separately before implementation starts.
    initial_hint: |
      Read the required optimization state files first. Re-evaluate the current
      bottleneck instead of assuming it is unchanged. Use doc/failure_patterns.md
      to avoid repeated failed directions and doc/optimization_report.md to
      understand the current best result.

      Append at most three focused candidate ideas. Prefer diversity across
      plausible bottlenecks instead of three variants of the same idea. If fewer
      than three good ideas exist, write fewer. Keep each idea small enough to
      implement and revert independently.

      Commit only the documentation updates before implementation begins:
      git add doc/optimization_results.tsv doc/optimization_log.md
      git commit -m "doc: propose optimization ideas"

  - id: 3
    name: "Implement and anti-hack verify the next pending idea"
    type: nested
    description: |
      Select exactly one pending experiment, reject it if it is stale or unsafe,
      or implement it as a focused reversible change and verify constraint compliance.
    completion_criteria: |
      1. Exactly one pending experiment from doc/optimization_log.md is selected.
      2. If rejected, doc/optimization_results.tsv and doc/optimization_log.md record status=rejected with a concrete reason.
      3. If implemented, cargo build --release exits 0 and any available fast validation mode for the touched subsystem exits 0.
      4. If implemented, anti-hack verification passes with no public schemas, tests, configs, benchmark scripts, generated benchmark outputs, or unrelated modules modified.
      5. No code is committed; Task 5 decides whether to keep or revert the change.
    subtasks:
      - id: 3.1
        name: "Implement or reject the next pending idea"
        type: simple
        completion_criteria: |
          1. Exactly one pending experiment from doc/optimization_log.md is selected.
          2. If earlier kept changes make the idea obsolete, unsafe, or no longer meaningful, it is marked rejected in doc/optimization_results.tsv and doc/optimization_log.md with a reason.
          3. If implemented, the code change is focused on the selected module and cargo build --release exits 0.
          4. If a fast validation mode exists for the touched subsystem, it exits 0 before the benchmark task runs.
          5. Public schemas, tests, configs, benchmark scripts, and unrelated modules are not modified.
          6. No code is committed; Task 5 decides whether to keep or revert the change.
        initial_hint: |
          Read the next pending experiment from doc/optimization_log.md and
          compare it with the current best state in doc/optimization_report.md.
          If the idea is stale after earlier kept changes, reject it in
          doc/optimization_results.tsv and doc/optimization_log.md and do not
          edit source code.

          Before editing, inspect git status and git diff for residual state from
          a failed retry. Implement only the selected idea. Search for a fast
          validation mode relevant to the touched subsystem before relying on the
          full benchmark step. Do not modify tests, public schemas, configs, or
          benchmark scripts.

      - id: 3.2
        name: "Anti-hack verification"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are an anti-hack verifier. Your sole job is to detect constraint violations. Do NOT modify source code, tests, configs, benchmark scripts, generated data, or documentation.
        completion_criteria: |
          1. If the selected idea was rejected before implementation, verification reports that no code verification is required.
          2. If code was implemented, cargo test --all exits 0.
          3. git diff confirms no public schemas, tests, configs, benchmark scripts, generated benchmark outputs, or unrelated modules were modified.
          4. Tests are not weakened: no skipped assertions, relaxed tolerances, removed test cases, or conditional bypasses.
          5. Benchmark integrity is preserved: load shape, benchmark duration, thresholds, and result JSON are not changed to hide regressions.
        initial_hint: |
          This is an execution-only verification subtask. Inspect git diff and
          run cargo test --all when code changes are pending. If tests fail,
          forbidden files changed, or benchmark/test integrity is violated,
          output `not completed: <reason>` so nested-task failure analysis can
          retry the correct implementation boundary. Do not fix code in this
          subtask.

  - id: 4
    name: "Run benchmark for the verified implementation"
    type: long_running
    max_attempts: 1
    model: lite
    description: |
      Run the checked-in benchmark for the latest implementation that already
      passed anti-hack verification, producing raw benchmark output for evaluation.
    system_prompt_prefix: |
      You are a benchmark runner. Do NOT modify source code, tests, configs, benchmark scripts, or documentation except for writing raw benchmark output produced by the benchmark command.
    completion_criteria: |
      1. If the selected idea was rejected before implementation, benchmark is skipped and no files are modified.
      2. If code was implemented and verified, k6 benchmark exits 0 and writes results.json.
      3. The benchmark uses the checked-in benchmarks/load_test.js and checked-in config/server.yaml.
      4. No source code, tests, configs, benchmark scripts, or documentation are modified by this task.
    initial_hint: |
      If the selected experiment was already rejected, do nothing and report that
      no benchmark is required. Otherwise run:
      k6 run benchmarks/load_test.js --out json=results.json

      This is an execution-only task. If prerequisites are broken or the
      benchmark fails, output `not completed: <reason>` and do not edit files to
      compensate.

  - id: 5
    name: "Evaluate result, keep or revert, and update optimization state"
    type: simple
    max_attempts: 1
    description: |
      Apply the decision matrix to the selected experiment, keep or revert the
      implementation, and update the scheduler-visible optimization state files.
    system_prompt_prefix: |
      You are a strict experiment evaluator. Apply the decision matrix consistently and preserve benchmark integrity.
    completion_criteria: |
      1. The selected experiment has final status=kept, status=reverted, or status=rejected in doc/optimization_results.tsv and doc/optimization_log.md.
      2. If rejected before implementation, no benchmark result is required and the rejection reason is recorded.
      3. If implemented, results.json is parsed and compared with the previous best kept result.
      4. The decision matrix is applied; keep maps to status=kept, while discard of an implemented change maps to status=reverted.
      5. Reverted code changes are not left in the workspace.
      6. doc/optimization_report.md is updated as the rolling summary and final report for the current state.
      7. doc/failure_patterns.md is updated with proven failures or promising directions.
      8. Documentation updates and any kept code changes are committed.
    initial_hint: |
      Read doc/optimization_results.tsv, the selected experiment entry in
      doc/optimization_log.md, doc/optimization_report.md, and
      doc/failure_patterns.md. If the experiment was rejected before
      implementation, record the rejection across the state files and commit the
      documentation updates.

      If code was implemented, parse results.json and compare against the
      previous best kept result. First identify the current primary bottleneck
      from the previous best kept row, not from the new experiment's metrics.
      Then apply this decision matrix:

      ┌─────────────────────────────────────────────────────────────────┬──────────┐
      │ Condition                                                       │ Decision │
      ├─────────────────────────────────────────────────────────────────┼──────────┤
      │ Pure bug fix (no optimization intent)                           │ keep     │
      │ Primary bottleneck metric improved ≥5%                          │ keep     │
      │   AND no other metric group worsened >3%                        │          │
      │ Secondary bottleneck metric improved ≥5%                        │ keep     │
      │   AND primary not worsened >3%                                  │          │
      │ Multiple metrics improved (even if each <5%)                    │ keep     │
      │   AND none worsened >3%                                         │          │
      │ Primary bottleneck metric worsened >10%                         │ discard  │
      │ Any metric worsened >5% with no bottleneck compensation         │ discard  │
      │ All metrics within ±1% (no meaningful change)                   │ discard  │
      │ Mixed results not covered above                                 │ discard  │
      └─────────────────────────────────────────────────────────────────┴──────────┘

      If the matrix says discard for an implemented change, revert only the
      latest implementation and record status=reverted. Do not remove the
      hypothesis documentation. If the matrix says keep, record status=kept.

      Update doc/optimization_report.md with current best vs baseline,
      experiment summary, cumulative improvement, key changes, and any stop
      marker such as target_reached, stop_no_safe_optimization, or
      stop_external_blocker. Update doc/failure_patterns.md: reverted/rejected
      experiments go under Proven Failure Patterns; kept experiments go under
      Promising Directions. Commit documentation updates and any kept code changes.

  - id: 6
    name: "Diagnose repeated failures in core state files"
    type: simple
    max_attempts: 1
    description: |
      Diagnose repeated execution failures using the scheduler-visible state
      files, and record whether the scheduler should continue or stop.
    completion_criteria: |
      1. doc/optimization_results.tsv, doc/optimization_log.md, doc/optimization_report.md, and doc/failure_patterns.md have been read.
      2. doc/optimization_report.md records a concise diagnosis and exactly one scheduler action: continue, stop_no_safe_optimization, or stop_external_blocker.
      3. doc/failure_patterns.md is updated if the repeated failure reveals a reusable proven failure pattern.
      4. No source code, tests, configs, benchmark scripts, benchmark outputs, or result tables are modified.
    initial_hint: |
      Read the four core optimization state files and recent command outputs if
      available. Do not edit code. Diagnose whether failures are caused by a
      retryable implementation issue, a repeated unsafe optimization direction,
      or an external blocker such as unavailable services.

      Record the diagnosis and scheduler action in doc/optimization_report.md.
      Use scheduler_action=continue only when a concrete safe next direction
      exists. Use scheduler_action=stop_no_safe_optimization when the remaining
      ideas repeat proven failures. Use scheduler_action=stop_external_blocker
      when progress is blocked by environment or missing prerequisites.
```