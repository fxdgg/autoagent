# Best Practice: Iterative Optimization

## Recommended Structure

```
├── nested
|   ├── build the project                    (simple, model: lite)
|   └── establish baseline                   (simple, model: lite)
└── looping (repeat_count: N)
    ├── analyze + propose hypothesis (3 ideas at a time) (simple)
    └── looping (repeat_count: 3)
        ├── implement + build + test         (simple)
        ├── anti-hack check                  (simple, max_attempts: 1)
        ├── benchmark                        (simple or long_running, max_attempts: 1, model: lite)
        └── evaluate + keep/revert + report  (simple, max_attempts: 1)
```

- Use `looping` (not `nested`) because the goal is "run N rounds", not "reach a specific target".
- **Separate "thinking" from "doing"**: analysis in one subtask, implementation in another (see main guide §4.1).
- **finding fast-check profiling modes**: in implementation task, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor) when it is long-running to speed up self-correction (see main guide rule 8).
- **Explicitly tells the AI to output `not completed`** for anti-hack checks and benchmark subtasks (see main guide §4.6).
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

Idea generation may produce more than one candidate at a time. In linear mode, this can be represented with a `nested` structure, such as generating three ideas first in one subtask and then executing three implementation rounds via nested subtasks.

Pending ideas are candidates, not obligations: before the implementation subtask implements a pending idea, confirm that it is still valid after any earlier idea has been kept. If not, tell the AI to say `rejected`.

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

Below is a complete linear-mode `todos.yaml` demonstrating a fixed-count optimization workflow with batched idea generation, file-backed state, explicit failure propagation for execution-only subtasks, anti-hack verification, benchmark evaluation, and a rolling final report.

```yaml
description: |
  # Project: Web API Performance Optimization

  ## Goal
  Run a fixed number of optimization rounds for the REST API server. Reduce p95
  latency while keeping all integration tests passing and preserving benchmark
  integrity. Every experiment must be traceable through the optimization state
  files under doc/.

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
  - Persist all inter-task handoffs in the optimization docs listed above.
  - Generate a small batch of candidate ideas, then implement pending ideas one at a time.
  - Before implementing a pending idea, confirm it is still valid after any earlier kept changes.
  - If an execution-only subtask finds broken prerequisites, output `not completed: <reason>`.

tasks:
  # ── Task 1: Establish Baseline ────────────────────────────────────────
  - id: 1
    name: "Build, test, benchmark, and initialize optimization state"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. cargo build --release exits 0.
      2. cargo test --all exits 0.
      3. k6 benchmark completes and writes results.json.
      4. doc/optimization_results.tsv exists with one baseline row using status=baseline.
      5. doc/optimization_log.md exists with baseline context and experiment numbering guidance.
      6. doc/optimization_report.md exists with project overview, baseline, empty experiment summary, cumulative improvement, and key changes sections.
      7. doc/failure_patterns.md exists with Proven Failure Patterns and Promising Directions sections.
      8. No source files, tests, configs, benchmark scripts, or hand-edited benchmark outputs are modified.
    subtasks:
      - id: 1.1
        name: "Build and run tests without modifications"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a build engineer. Do NOT modify source code, tests, configs, benchmark scripts, generated data, or documentation.
        completion_criteria: |
          1. cargo build --release exits 0.
          2. cargo test --all exits 0.
          3. git diff --name-only shows no changes.
        initial_hint: |
          Run:
          - docker compose up -d postgres redis
          - cargo build --release
          - cargo test --all

          This is an execution-only subtask. If dependencies are unavailable,
          the build fails, or tests fail because the repository is already
          broken, output `not completed: <reason>` and do not edit files.

      - id: 1.2
        name: "Run baseline benchmark and initialize state files"
        type: long_running
        max_attempts: 1
        model: lite
        completion_criteria: |
          1. k6 benchmark exits 0 and writes results.json.
          2. doc/optimization_results.tsv contains a baseline row with exp_id=BASELINE, date, module=all, changes=baseline, task-specific metric columns, status=baseline, reason, and commit_hash.
          3. doc/optimization_log.md contains baseline context and the next experiment ID format.
          4. doc/optimization_report.md summarizes project overview, baseline, current best, empty experiment table, cumulative improvement, and key changes.
          5. doc/failure_patterns.md contains Proven Failure Patterns and Promising Directions sections.
          6. Existing experiment rows, log entries, report history, and failure-pattern entries are preserved.
          7. Only doc/optimization_results.tsv, doc/optimization_log.md, doc/optimization_report.md, doc/failure_patterns.md, and results.json may change.
        initial_hint: |
          Run:
          - k6 run benchmarks/load_test.js --out json=results.json

          Parse results.json for the task-specific metrics, including p95 latency.
          Create the four optimization state files if missing. Use metric columns
          appropriate for this API optimization task, such as p50_ms, p95_ms,
          p99_ms, error_rate, and throughput_rps.

          results.json is a temporary benchmark artifact, not long-lived state.
          Preserve existing optimization history if the files already exist.
          If the benchmark cannot run because prerequisites are broken, output
          `not completed: <reason>` and do not edit source code, tests, configs,
          or benchmark scripts.

  # ── Task 2: Fixed Iterative Optimization Loop ─────────────────────────
  - id: 2
    name: "Run fixed optimization rounds"
    type: looping
    repeat_count: 4
    max_attempts_per_loop: 3
    completion_criteria: |
      Each outer round generates a small batch of candidate ideas, then attempts
      up to three pending ideas one by one. Every attempted idea is finalized as
      kept, reverted, or rejected in doc/optimization_results.tsv,
      doc/optimization_log.md, doc/optimization_report.md, and
      doc/failure_patterns.md. After the final round, doc/optimization_report.md
      is the final rolling summary.
    subtasks:
      - id: 2.1
        name: "Analyze evidence and propose candidate ideas"
        type: simple
        system_prompt_prefix: |
          You are a backend performance engineer specializing in Rust async services. Prefer focused, reversible experiments.
        completion_criteria: |
          1. doc/optimization_results.tsv, recent doc/optimization_log.md entries, doc/optimization_report.md, and doc/failure_patterns.md have been read.
          2. Up to three new pending experiments are appended to doc/optimization_log.md using the recommended experiment format.
          3. Matching pending rows are appended to doc/optimization_results.tsv with status=pending.
          4. Each idea identifies the module, proposed changes, expected outcome, and risk.
          5. No source code, tests, configs, benchmark scripts, benchmark outputs, or rolling summary files are modified.
          6. The hypothesis documentation is committed separately before implementation starts.
        initial_hint: |
          Read the required optimization state files first. Re-evaluate the
          current bottleneck instead of assuming it is unchanged. Use
          doc/failure_patterns.md to avoid repeated failed directions and
          doc/optimization_report.md to understand the current best result.

          Append at most three focused candidate ideas. Prefer diversity across
          plausible bottlenecks instead of three variants of the same idea. If
          fewer than three good ideas exist, write fewer. Keep each idea small
          enough to implement and revert independently.

          Commit only the documentation updates before implementation begins:
          git add doc/optimization_results.tsv doc/optimization_log.md
          git commit -m "doc: propose optimization ideas"

      - id: 2.2
        name: "Execute pending ideas one by one"
        type: looping
        repeat_count: 3
        max_attempts_per_loop: 3
        completion_criteria: |
          One pending idea is either implemented, benchmarked, and finalized, or
          rejected with a concrete reason. The standard optimization state files
          are updated after the decision.
        subtasks:
          - id: 2.2.1
            name: "Implement or reject the next pending idea"
            type: simple
            completion_criteria: |
              1. Exactly one pending experiment from doc/optimization_log.md is selected.
              2. If earlier kept changes make the idea obsolete, unsafe, or no longer meaningful, it is marked rejected in doc/optimization_results.tsv and doc/optimization_log.md with a reason.
              3. If implemented, the code change is focused on the selected module and cargo build --release exits 0.
              4. If a fast validation mode exists for the touched subsystem, it exits 0 before the full benchmark subtask runs.
              5. Public schemas, tests, configs, benchmark scripts, and unrelated modules are not modified.
              6. No code is committed; the evaluation subtask decides whether to keep or revert the change.
            initial_hint: |
              Read the next pending experiment from doc/optimization_log.md and
              compare it with the current best state in doc/optimization_report.md.
              If the idea is stale after earlier kept changes, reject it in the
              standard optimization state files and do not edit source code.

              Before editing, inspect git status and git diff for residual state
              from a failed retry. Implement only the selected idea. Search for a
              fast validation mode relevant to the touched subsystem before
              relying on the full benchmark step. Do not modify tests, public
              schemas, configs, or benchmark scripts.

          - id: 2.2.2
            name: "Anti-hack verification"
            type: simple
            max_attempts: 1
            system_prompt_prefix: |
              You are an anti-hack verifier. Your sole job is to detect constraint violations. Do NOT modify source code, tests, configs, benchmark scripts, generated data, or documentation.
            completion_criteria: |
              1. If no implementation is pending because the selected idea was rejected, verification reports that no code verification is required.
              2. If code was implemented, cargo test --all exits 0.
              3. git diff confirms no public schemas, tests, configs, benchmark scripts, generated benchmark outputs, or unrelated modules were modified.
              4. Tests are not weakened: no skipped assertions, relaxed tolerances, removed test cases, or conditional bypasses.
              5. Benchmark integrity is preserved: load shape, benchmark duration, thresholds, and result JSON are not changed to hide regressions.
            initial_hint: |
              This is an execution-only verification subtask. Inspect git diff
              and run cargo test --all when code changes are pending. If tests
              fail, forbidden files changed, or benchmark/test integrity is
              violated, output `not completed: <reason>` so the parent failure
              analysis can retry the correct implementation boundary. Do not fix
              code in this subtask.

          - id: 2.2.3
            name: "Run benchmark for the pending implementation"
            type: long_running
            max_attempts: 1
            model: lite
            system_prompt_prefix: |
              You are a benchmark runner. Do NOT modify source code, tests, configs, benchmark scripts, or documentation except for writing raw benchmark output produced by the benchmark command.
            completion_criteria: |
              1. If the selected idea was rejected before implementation, benchmark is skipped and no files are modified.
              2. If code was implemented, k6 benchmark exits 0 and writes results.json.
              3. The benchmark uses the checked-in benchmarks/load_test.js and checked-in config/server.yaml.
              4. No source code, tests, configs, benchmark scripts, or documentation are modified by this subtask.
            initial_hint: |
              If the selected experiment was already rejected, do nothing and
              report that no benchmark is required. Otherwise run:
              k6 run benchmarks/load_test.js --out json=results.json

              This is an execution-only subtask. If prerequisites are broken or
              the benchmark fails, output `not completed: <reason>` and do not
              edit files to compensate.

          - id: 2.2.4
            name: "Evaluate result, keep or revert, and update optimization state"
            type: simple
            max_attempts: 1
            system_prompt_prefix: |
              You are a strict experiment evaluator. Apply the decision rules consistently and preserve benchmark integrity.
            completion_criteria: |
              1. The selected experiment has final status=kept, status=reverted, or status=rejected in doc/optimization_results.tsv and doc/optimization_log.md.
              2. If rejected before implementation, no benchmark result is required and the rejection reason is recorded.
              3. If implemented, results.json is parsed and compared with the previous best kept result.
              4. If tests failed, benchmark failed, or p95_ms regressed by more than 5% versus the previous best kept row, only the latest implementation is reverted and status=reverted is recorded.
              5. If p95_ms improves by at least 5% and no secondary metric regresses by more than 3%, the change is kept and status=kept is recorded.
              6. If results are within noise or mixed outside the decision rules, the implementation is reverted and status=reverted is recorded.
              7. doc/optimization_report.md is updated as the rolling summary and final report for the current state.
              8. doc/failure_patterns.md is updated with proven failures or promising directions.
              9. Documentation updates and any kept code changes are committed; reverted code changes are not left in the workspace.
            initial_hint: |
              Read doc/optimization_results.tsv, the selected experiment entry in
              doc/optimization_log.md, doc/optimization_report.md, and
              doc/failure_patterns.md. If the experiment was rejected before
              implementation, record the rejection across the state files and
              commit the documentation updates.

              If code was implemented, parse results.json and compare against the
              previous best kept result. First identify the current primary
              bottleneck from the previous best kept row, not from the new
              experiment's metrics. Then apply this decision matrix:

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

              If the matrix says discard for an implemented change, revert only
              the latest implementation and record status=reverted. Do not remove
              the hypothesis documentation. If the matrix says keep, record
              status=kept.

              Update doc/optimization_report.md with current best vs baseline,
              experiment summary, cumulative improvement, and key changes.
              Update doc/failure_patterns.md: reverted/rejected experiments go
              under Proven Failure Patterns; kept experiments go under Promising
              Directions. Commit documentation updates and any kept code changes.
```