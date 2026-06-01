# Best Practice: Iterative Optimization

## 1. Recommended Structure

```
├── build the project and establish baseline  (simple or long_running, model: lite)
├── analyze + propose hypothesis              (simple)
├── nested
|   ├── implement + build + test              (simple)
|   └── anti-hack check                       (simple, max_attempts: 1)
├── benchmark                                 (simple or long_running, max_attempts: 1, model: lite)
├── evaluate + keep/revert + report           (simple, max_attempts: 1)
└── diagnose execution anomalies              (simple, max_attempts: 1)
```

Key Considerations:

- **Default flat**: prefer single `simple` / `long_running` top-level tasks (see main guide rule 7).
- **Separate "thinking" from "doing"**: analysis in one subtask, implementation in another (see main guide §4.1).
- Anti-hack check, benchmark and evaluation subtasks should use `max_attempts: 1` —— failures should propagate to the parent for proper retry.
- Benchmark subtask should use `model: lite` —— they just execute.
- Use `long_running` for benchmark if it takes more than a minute (e.g. GPU profiling, large simulation runs).
- Prefer `last_result: type: response`: optimization files are durable task-internal state; scheduler decisions should rely on concise final response summaries unless a truly complex strategy must inspect files directly.
- Task 6 diagnoses repeated execution anomalies only. It must not be triggered by consecutive `reverted` experiments, because `reverted` means an idea failed evaluation rather than execution failed.

---

## 2. Recommended State Files

Use a small, stable set of files to preserve optimization state across isolated agent sessions.

These files are task-internal durable state by default; expose concise scheduler-facing outcomes through final responses unless the scheduler truly needs direct file inspection for complex scheduling strategy.

### 2.1 `optimization_results.tsv`

Records the baseline benchmark history and every experiment result. This is the compact source of truth and **must be read before deciding what to try, keep, revert, or reject**.

Required columns:

```tsv
exp_id  date  module  changes <metric columns...> status  reason  commit_hash
```
- `exp_id`: `BASELINE-001`, `BASELINE-002`, ... for baseline benchmark rows; `EXP-001`, `EXP-002`, ... for experiments. When rerunning baseline, append the next sequential `BASELINE-00N` row instead of overwriting previous baseline rows.
- `date`: date when the row is created.
- `module`: the touched module or subsystem for experiments (`all` for baseline benchmark rows).
- `changes`: short summary for experiments (`baseline` for baseline benchmark rows).
- `<metric columns...>`: task-specific metric columns chosen by the todo-generating AI. Different projects need different metrics, so do not force a universal metric schema.
Pending rows should use `NA` for metric values that do not exist yet. Benchmark task replaces `NA` with measured values.
- `status`: one of `baseline`, `pending`, `kept`, `reverted`, or `rejected`.
- `reason`: compact explanation of the current status or final decision.
- `commit_hash`: use hypothesis commit hash for each experiment. `commit_hash` is `pending` until final evaluation is performed; final evaluator fills the hypothesis commit hash. For baseline benchmark rows, use the baseline documentation commit hash after the baseline docs are committed.

Status lifecycle:

- `baseline`: created for each baseline benchmark row before optimization starts or when baseline is rerun; baseline reruns use the next sequential `BASELINE-00N` id and preserve previous baseline rows.
- `pending`: created by the analysis subtask before implementation starts.
- `rejected`: used when the pending idea is not implemented because it is stale, unsafe, duplicate, or not meaningful.
- `kept`: used when the implementation is accepted by evidence-based evaluation using the defined metrics, metric priorities, and hard failure conditions.
- `reverted`: used when the implementation is discarded after evaluation. 

When one experiment is `reverted`, only the code change is reverted —— the hypothesis remains.

### 2.2 `optimization_log.md`

Records detailed hypotheses, target areas, risks, profiling results, and decision reasons. The AI agent should **always read recent entries first** and may read older entries on demand when investigating history or avoiding repeated work.

Required head:

```md
# Optimization Log —— <project name>

## Project Overview

<project overview>

## Environments

<environments>
Latest baseline commit: <baseline commit>
Latest baseline branch: <baseline branch>

## Baseline

### Baseline-00N
<baseline metrics and relevant context for run N>

## Experiment Index

Next experiment id: EXP-001
```

Required format for each experiment:

```md
## Exp EXP-xxx: <short title>
Date: <date>
Module: <module>
Status: pending | kept | reverted | rejected
Hypothesis commit: <hypothesis commit hash>

### Hypothesis

<hypothesis>

### Proposed Changes

<proposed changes>

### Expected Outcome

<expected outcome>

### Risk

<risk>

### Profiling Results

<benchmark or profiling results, or NA before benchmark>

### Decision

<decision and reason, or pending before evaluation>
```

### 2.3 `optimization_report.md`

A rolling summary updated after every round. It summarizes the current state from `optimization_log.md` and `optimization_results.tsv`. It **must be read before proposing or implementing further optimization work**.

Required structure:

```md
# Optimization Report —— <project name>

## Project Overview

<project overview>

## Current Best vs Baseline

<current best result, baseline result, and overall delta using the project-specific primary metric>

## Experiment Summary

| Exp | Date | Module | Changes | Module Delta | Total Delta | Status | Reason |
|-----|------|--------|---------|--------------|-------------|--------|--------|
| BASELINE-00N | <date> | all | baseline | 0 | 0 | baseline | baseline or new baseline |

## Cumulative Improvement

| Experiment | Value |
|------------|-------|
| BASELINE-001 | <baseline primary metric value> |
| After EXP-001 | <primary metric value and delta vs baseline-001> |
| After EXP-002 | <primary metric value and delta vs baseline-001> |
| BASELINE-002 | <baseline primary metric value> |
| After EXP-003 | <primary metric value and delta vs baseline-002> |
| After EXP-004 | <primary metric value and delta vs baseline-002> |
...
| BASELINE-00M | <baseline primary metric value> |
| After EXP-00N | <primary metric value and delta vs baseline-00M> |


## Key Changes

(none yet)
```

`Key Changes` should stay concise; it is a navigable summary, not a duplicate of the full log.

### 2.4 `failure_patterns.md`

Records proven failure patterns and promising directions to prevent repeated attempts. This file **must be read before proposing new ideas**.

Required structure:

```md
# Failure Patterns —— <project name>

## Proven Failure Patterns

(none yet)

## Promising Directions

(none yet)
```

Required entry format:

```md
### Pattern 00N: <short name>
Experiment: EXP-xxx — <short title>
Result: <metric summary>
Root Cause: <root cause>
Lesson: <lesson>

### Direction 00N: <short name>
Experiment: EXP-xxx — <short title>
Result: <metric summary>
Why it worked: <reason>
Lesson: <lesson>
```

Keep `Root Cause`, `Why it worked`, and `Lesson` short. This file should be a compact knowledge base, not a long-form report.

### 2.5 `error_report.md`

Records execution errors that caused tasks to output `❌ not completed`. This file **must not be modified during clean optimization rounds**.

Use it when Task 1, Task 3, Task 4, or Task 5 reports `❌ not completed`. The failing task should append a concise entry to this file before returning `❌ not completed`. Task 6 reads this file and reports its diagnosis through the final response; it does not need to update this file.

Required structure:

```md
# Error Report —— <project name>

## Execution Errors

(none yet)
```

Required entry format:

```md
### Error 00N: <short title>
Task: <task id/name>
Experiment: EXP-xxx | none
Status: not completed
Reason: <short reason>
Observed command/output: <short evidence or file reference>
```

Keep entries concise. Do not use this file for reverted experiments, normal evaluation decisions, proven failure patterns, or promising directions.

## 3. Macro Workflow

### Task 1: Build, test, benchmark, and initialize optimization state

#### Subtask 1.1: Build and run tests without modifications

Build and test without modifying the repository. If build or tests fail, append a concise entry to `error_report.md`, then output `❌ not completed`.

#### Subtask 1.2: Run baseline benchmark and initialize state files

1. Run the baseline benchmark.
2. If the baseline benchmark fails, append a concise entry to `error_report.md`, then output `❌ not completed`.
3. Create or update the optimization state files, and `error_report.md`:
   - `optimization_results.tsv`
   - `optimization_log.md`
   - `optimization_report.md`
   - `failure_patterns.md`
   - `error_report.md`

### Task 2: Analyze and propose one hypothesis

1. read all optimization state files, re-evaluate the current bottleneck, and avoid repeated failed directions.
2. Append one `pending` row to `optimization_results.tsv`.
3. Writes `Hypothesis`, `Proposed Changes`, `Expected Outcome`, and `Risk` to `optimization_log.md`.

### Task 3: Implement and verify the proposed experiment

#### Subtask 3.1: Implement or reject the proposed experiment

1. implement only the selected pending experiment, or mark it `rejected` if it is stale, unsafe, or no longer meaningful.
2. If the idea is not implemented, change status to `rejected` in both `optimization_results.tsv` and `optimization_log.md` and record the reason.

#### Subtask 3.2: Anti-hack verification

1. Skip this step if the idea is marked as `rejected`.
2. Run anti-hack checks without modifying files.
3. If anti-hack result is 'FAIL', append a concise entry to `error_report.md`, then explicitly output `❌ not completed` so that Task 3 can be retried.

#### Task 4: Run benchmark for the implementation

1. Skip this step if the idea is marked as `rejected` (Guarded by scheduler).
2. Run the project-specific benchmark only for implemented experiments, and on benchmark failure append a concise entry to `error_report.md`, then immediately output `❌ not completed` so that Task 4 can be retried.
3. Write measured metric values into the selected `optimization_results.tsv` row, and `Profiling Results` section in `optimization_log.md`.

### Task 5: Evaluate result, keep or revert, and update optimization state

1. Read the benchmark results already written to `optimization_results.tsv`. if required benchmark evidence is missing or incomplete for an implemented experiment, append a concise entry to `error_report.md`, then output `❌ not completed` so that Task 4 can be retried.
2. Compare against the previous best kept result, use the project-specific metric definitions, metric priorities, and hard failure conditions, and choose `kept` or `reverted`. `rejected` can only be chosen by implementation task.
3. Update `Decision` and `Status` in `optimization_log.md`.
4. Update `optimization_report.md` and failure/promising-pattern notes in `failure_patterns.md`.

### Task 6: Diagnose repeated execution failures

1. Read all optimization state files, and `error_report.md`.
2. Diagnose only repeated execution anomalies; do not treat consecutive `reverted` experiments as execution failures.
3. If progress is blocked by unavailable external prerequisites, output `❌ not completed: external blocker - <reason>` without modifying regular optimization state files.
4. Report the concise diagnosis and next retry focus in the final response.

## 4. Patterns

### Pattern 1: Separate hypothesis, implementation, and decision commits

Commit the hypothesis documentation **before** implementing code. Commit the implementation separately before benchmarking. Finalize the experiment with one decision commit.

Use exactly these commit message formats:

```text
xxx_opt(EXP-xxx): hypothesis —— <hypothesis>
xxx_opt(EXP-xxx): implementation —— <implementation>
xxx_opt(EXP-xxx): kept/reverted/rejected —— <reason>
```

If the final decision is `reverted`, use `git reset` to remove the implementation commit, then commit only the final state documentation.

### Pattern 2: Re-evaluate the bottleneck every iteration

Don't assume the bottleneck is the same as the previous round. Instruct the AI to compute a diagnostic metric at the start of each iteration to determine where to focus.

### Pattern 3: Finding fast-check training/profiling modes

In implementation task, search for fast validation mode in training/profiling framework (e.g. --validate, --doctor) when it is long-running to speed up self-correction (see main guide rule 8).
If tests are not long-running, this pattern should not be applied —— use full test mode.

### Pattern 4: Define metrics, priorities, and hard failure conditions

Don't encode numeric keep/revert thresholds in generated todos unless they are true project requirements. Instead, the evaluation subtask's `initial_hint` should define what the metrics mean, how they are prioritized, which benchmark evidence is required before a decision can be made, and which failures make a result impossible to keep.

---

## 5. Complete Example

Use this example to understand the recommended AI-scheduler-mode structure for iterative optimization. Replace every `<placeholder>` token with project-specific content; do not copy placeholder wording into real tasks. `<!-- xxx -->` are comments that explain this example in detail, so do not include them into real tasks either.

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

  ## Optimization Docs
  - <path/to/optimization_results.tsv> —— baseline and experiment results (Must Read)
  - <path/to/optimization_log.md> —— detailed experiment log (Read recent entries first; read older entries on demand)
  - <path/to/optimization_report.md> —— rolling summary and final report (Must Read)
  - <path/to/failure_patterns.md> —— proven failures and promising directions (Must Read)
  - <path/to/error_report.md> —— pre-created execution-error record (Read only by task 6 (Diagnose repeated execution failures); append only when reporting `❌ not completed`)

  ## Environments
  <environments>

  ## Key Commands
  - <command 1>: <command>
  - <command 2>: <command>
  ...

  ## Hard Constraints
  - Keep each experiment small, focused, and reversible.
  - <rules on what should not be modified>
  - <rules on not weakening tests>
  - <rules on preserving benchmark integrity>
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
  - One optimization experiment per iteration.
  - Record every experiment faithfully in the optimization docs. Preserve   optimization history even when code is reverted. 
  Optimization histories from previous experiments should not be modified.
  - Do not create or modify error_report.md during clean optimization rounds.
  - <other project-specific rules>

ai_orchestrator:
  max_rounds: 20
  strategy: |
    Scheduling rules:

    I. Workflow

    1. If Task 1 has never succeeded, run Task 1.
    2. After Task 1 succeeds, run the optimization loop Task 2 (Analyze and propose ideas) -> Task 3 (Implement and anti-hack verify) -> Task 4 (Benchmark) -> Task 5 (Evaluate result).
    3. If Task 5 reports 'Optimization target: reached' in its final response, stop. <!-- If the project explicitly mentions an optimization goal, add this. If the project runs a fixed number of schedule rounds, do not add this --> If not, run Task 2 to start a new optimization loop.
    4. If Task 3 reports 'Implementation: rejected' in its final response, skip Task 4 and run Task 5 (Do not run Task 4 for rejected ideas).

    II. Error Handling
    
    4. If Task 1 reports `❌ not completed: <reason>` but not 'external blocker', run Task 6 for detailed diagnosis.
    5. If Task 3 reports `❌ not completed: Anti-hack verification failed. Implementation task should be retried`, retry Task 3.
    6. If Task 4 reports `❌ not completed: Benchmark failed. Implementation task should be retried`, retry Task 3. If Task 4 reports `❌ not completed: <other reason>` but not 'external blocker', run Task 6 for detailed diagnosis.
    7. If Task 5 reports `❌ not completed: benchmark incomplete`, retry Task 4.
    8. Do not run Task 6 because of consecutive `reverted` experiments; revert means the idea was evaluated and rejected, not that execution is broken.

  stop_condition: |
    Stop when:
    1. Any task reports `❌ not completed: external blocker - <reason>` —— external prerequisites must be fixed outside this optimization loop.
    2. No required work is left when maximum schedule rounds reached.
    3. Task 5 reports 'optimization target reached' in its final response. <!-- If the project explicitly mentions an optimization goal, add this. If the project runs a fixed number of schedule rounds, do not add this -->
    
  last_result:
    1:
      type: response
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
  - id: 1
    name: "Build, test, benchmark, and initialize optimization state"
    type: long_running
    max_attempts: 1
    model: lite
    description: |
      Build the project, run tests, establish the baseline benchmark, and 
      create the optimization state files used by later optimization tasks.
    completion_criteria: |
      If not completed:
      1. a concise entry is appended to error_report.md, and outputs `❌ not completed: <reason>`.
      
      If completed:
      1. <build command> exits 0.
      2. <test command> exits 0.
      3. <benchmark command> exits 0 and baseline measurements are recorded.
      4. optimization_results.tsv exists with columns: exp_id, date, module, changes, task-specific metric columns, status, reason, commit_hash; it contains at least one baseline row whose exp_id follows BASELINE-00N, latest baseline row uses module=all, changes=baseline, status=baseline, and reason=baseline or new baseline.
      5. optimization_log.md exists with Project Overview, Environments, Baseline, and Experiment Index sections, including Next experiment id: EXP-001.
      6. optimization_report.md exists with Project Overview, Current Best vs Baseline, Experiment Summary, Cumulative Improvement, and Key Changes sections; the latest BASELINE-00N row is the current best before optimization experiments.
      7. failure_patterns.md exists with Proven Failure Patterns and Promising Directions sections, both initially empty unless history already exists.
      8. error_report.md exists with the required empty Error Report structure.
      9. No source files, tests, configs, or benchmark scripts are modified.
    system_prompt_prefix: |
      You are a build & benchmark engineer and documenter. Do NOT modify source code, tests, configs, benchmark scripts, generated data.
    initial_hint: |
      1. <hint on running build and test commands>
      2. <hints on how to run benchmark commands>
      3. If the build, tests, or benchmark cannot run or fails, append a concise entry to
      error_report.md in this Markdown format and output `❌ not completed: <reason>`:
        # Error Report —— <project name>

        ## Execution Errors

        ### Error 001: <short title>
        Task: Task 1
        Experiment: EXP-xxx / BASELINE-xxx
        Status: not completed
        Reason: <short reason>
        Observed command/output: <short evidence or file reference>

      4. Otherwise:

      (1) Create or update optimization_results.tsv exactly in this TSV format:
        exp_id	  date	  module	changes	  <metric columns...>	status	  reason	  commit_hash
        BASELINE-00N	<date>	all	    baseline	<metric values...>	baseline	baseline or new baseline  <commit_hash>

      Use `BASELINE-001` when no prior baseline rows exist. If baseline rows already exist, use the next sequential baseline id, such as `BASELINE-002`.

      (2) Create or update optimization_log.md exactly in this Markdown format:
      # Optimization Log —— <project name>

      ## Project Overview

      <project overview>

      ## Environments

      <environments>
      Latest baseline commit: <baseline commit hash>
      Latest baseline branch: <baseline branch>

      ## Baseline

      ### Baseline-00N
      <baseline metrics and relevant context for run N>

      ## Experiment Index

      Next experiment id: EXP-001

      (3) Create or update optimization_report.md exactly in this Markdown format:
      # Optimization Report —— <project name>

      ## Project Overview

      <project overview>

      ## Current Best vs Baseline

      <current best result, baseline result, and overall delta using the project-specific primary metric>

      ## Experiment Summary

      | Exp | Date | Module | Changes | Module Delta | Total Delta | Status | Reason |
      |-----|------|--------|---------|--------------|-------------|--------|--------|
      | BASELINE-00N | <date> | all | baseline | 0 | 0 | baseline | baseline or new baseline |
      <!-- Always append it to the end if there are existing baselines. DO NOT override previous ones. -->

      ## Cumulative Improvement

      | Experiment | Value |
      |------------|-------|
      | BASELINE-00N | <baseline primary metric> | 
      <!-- Always append it to the end if there are existing baselines. DO NOT override previous ones. -->

      ## Key Changes

      (none yet)

      (4) Create or update failure_patterns.md exactly in this Markdown format:
      # Failure Patterns —— <project name>

      ## Proven Failure Patterns

      (none yet)

      ## Promising Directions

      (none yet)

      (5) Create or update error_report.md exactly in this Markdown format: 
      # Error Report —— <project name>

      ## Execution Errors

      (none yet)

      Notes: 
      1. Preserve existing optimization history if these files already exist, and adapt the formats mentioned above accordingly. 
      2. You must re-benchmark if these files already exist, and append a new baseline row to optimization_results.tsv using the next sequential baseline id, such as BASELINE-002, with reason="new baseline".
        DO NOT skip this step since the code/data may have changed outside optimization loops.
      3. Split into two commits since baseline commit hash is not available before actually committed. Use these commit messages below:
        xxx_opt(BASELINE-00N): baseline (or new baseline) profiling
        xxx_opt(BASELINE-00N): update baseline (or new baseline) commit hash

  - id: 2
    name: "Analyze and propose one hypothesis"
    type: simple
    description: |
      Read the current optimization state, re-evaluate the bottleneck, and propose one hypothesis for the next experiment.
    system_prompt_prefix: |
      <system prompts for a <domain> performance analyst, including the primary metric, bottleneck signals, and project-specific optimization constraints>
    completion_criteria: |
      1. optimization_results.tsv, recent optimization_log.md entries, optimization_report.md, and failure_patterns.md have been read.
      2. Exactly one new pending experiment entry is appended to optimization_log.md with Date, Module, Status: pending, Hypothesis commit: pending, Hypothesis, Proposed Changes, Expected Outcome, Risk, Profiling Results, and Decision sections.
      3. The 'Next experiment id' in 'Experiment Index' section in optimization_log.md is updated for the next round.
      4. Exactly one pending row is appended to optimization_results.tsv with exp_id=EXP-xxx, status=pending, metric values set to NA, reason explaining the hypothesis, and commit_hash=pending.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, rolling summary files, or failure-pattern files are modified.
      6. The hypothesis documentation is committed with "xxx_opt(EXP-xxx): hypothesis —— <hypothesis>" separately before implementation starts.
    initial_hint: |
      Read optimization_results.tsv, recent optimization_log.md entries, optimization_report.md, and failure_patterns.md first.
      Re-evaluate the current bottleneck instead of assuming it is unchanged, and use failure_patterns.md to avoid repeated failed directions.

      After proposing one hypothesis:

      1. Append exactly one pending row to optimization_results.tsv in this TSV format:
      exp_id  date  module  changes <metric columns...> status  reason  commit_hash
      EXP-xxx <date>  <module>  <short changes summary> NA  pending <hypothesis reason> pending

      Use the next experiment id from optimization_log.md.

      2. Append exactly one matching experiment entry to optimization_log.md in this Markdown format:
      ## Exp EXP-xxx: <short title>
      Date: <date>
      Module: <module>
      Status: pending
      Hypothesis commit: pending

      ### Hypothesis

      <hypothesis>

      ### Proposed Changes

      <proposed changes>

      ### Expected Outcome

      <expected outcome>

      ### Risk

      <risk>

      ### Profiling Results

      NA

      ### Decision

      pending

      3. Update the Experiment Index / Next experiment id in optimization_log.md for the next round. Do not update optimization_report.md or failure_patterns.md in this task.

      4. Commit only the documentation updates before implementation begins:
        git commit -m "xxx_opt(EXP-xxx): hypothesis —— <hypothesis>"

  - id: 3
    name: "Implement and anti-hack verify the next pending idea"
    type: nested
    description: |
      Select the pending experiment, reject it if it is stale or unsafe,
      or implement it as a focused reversible change and verify constraint compliance.
    completion_criteria: |
      Finish the implement -> anti-hack verify workflow of the next pending idea.
    subtasks:
      - id: 3.1
        name: "Implement or reject the proposed experiment"
        type: simple
        completion_criteria: |
          1. Exactly one pending experiment from optimization_log.md is selected.
          2. If current state makes the idea obsolete, unsafe, or no longer meaningful, it is marked `rejected` in optimization_results.tsv and optimization_log.md with a reason.
          3. If implemented, the code change is focused on the selected module, <build command> and <test command> exits 0.
          4. <completion_criteria on what should not be changed>
          5. If implemented, the implementation is committed with: xxx_opt(EXP-xxx): implementation —— <implementation>.
        system_prompt_prefix: |
          <system prompts for a <domain> optimization engineer, including implementation boundaries, performance goals, and constraints that must not be weakened>
        initial_hint: |
          Read the pending experiment from optimization_log.md and compare it with the current best state in optimization_report.md.
          
          If the idea is stale after earlier kept changes, unsafe under current constraints, duplicate, or no longer meaningful, do not edit source code. Instead, reject the selected experiment this way:
          - In optimization_results.tsv, update the selected EXP-xxx row in place: status=rejected, reason=<rejection reason>, commit_hash=<hypothesis commit hash>. Keep metric values as NA.
          - In optimization_log.md, update the selected EXP-xxx entry with "Status: rejected and Decision: rejected: <rejection reason>"
          - Do not create an implementation commit. The evaluation task will create the final documentation commit.

          If the idea is still valid:
          
          1. inspect git status first: if a previous commit exists from a failed retry, use git reset --soft and amend fix on residual state.
          
          2. Implement only the selected idea. 

          3. <rules on what should not be changed>

          4. <rules on how to build and test. Search fast validation mode by yourself (todo-generating AI) and provide deterministic commands, instead of writing 'search for fast validation mode' and let this task's AI search by itself>

          5. Commit the implementation with:
            git commit -m "xxx_opt(EXP-xxx): implementation —— <implementation>"

      - id: 3.2
        name: "Anti-hack verification"
        type: simple
        max_attempts: 1
        system_prompt_prefix: |
          You are an anti-hack verifier. Your sole job is to detect constraint violations. Do NOT modify source code, tests, configs, benchmark scripts, generated data, or documentation.
        completion_criteria: |
          1. If the selected idea was marked as 'rejected', outputs 'Implementation: rejected' in the second-to-last line 
          to inform the scheduler, and output '✅ completed' in the last line to proceed.
          2. If verification result is 'FAIL', output `❌ not completed: Anti-hack verification failed. Implementation task should be retried` so that the implementation task can be retried.
          3. No public contracts, tests, configs, benchmark scripts, generated benchmark outputs, or unrelated modules were modified.
        initial_hint: |
          Read the current experiment from optimization_log.md and inspect git to find implementation code changes.
          If the selected idea was marked as 'rejected', skip this anti-hack step, outputs 'Implementation: rejected' in the second-to-last line to inform the scheduler, 
          and output '✅ completed' in the last line to proceed. If not:

          1. Check if the implementation code matches the experiment idea;
          2. <write all other anti-hack rules here based on global description and task-specific informations>
          3. If verification result is 'FAIL', output `❌ not completed: Anti-hack verification failed. Implementation task should be retried`
          so that the implementation task can be retried. Do not fix code by yourself.

  - id: 4
    name: "Run benchmark for the implementation"
    type: long_running
    max_attempts: 1
    model: lite
    description: |
      Run the benchmark for the latest implementation that already
      passed anti-hack verification, producing raw benchmark output for evaluation.
    system_prompt_prefix: |
      You are a benchmark runner. Do NOT modify source code, tests, configs, benchmark scripts, or documentation except for writing raw benchmark output produced by the benchmark command.
    completion_criteria: |
      1. If the selected idea was marked as 'rejected', skip this step.
      2. If code was implemented, <benchmark command> exits 0; optimization_results.tsv has the selected EXP-xxx row updated in place with the measured metric values while keeping status=pending and commit_hash=pending; the 'Profiling Results' section in optimization_log.md records the observed metric values, metric notes, and benchmark reliability notes.
      3. If the benchmark fails because of external issues (e.g. missing environments), immediately output `❌ not completed: <external issues>` to inform the scheduler.
      4. If the benchmark fails because of implementation error, immediately output `❌ not completed: Benchmark failed. Implementation task should be retried` so that the implementation task can be retried.
    initial_hint: |
      If the selected idea was marked as 'rejected', skip this benchmark step and directly output ✅ completed to proceed to the next task.

      Otherwise run:
      <benchmark command>

      If the benchmark command fails, its output is incomplete, or the expected raw benchmark output is missing:
        - If because of external issues (e.g. missing environments), immediately output `❌ not completed: <external issues>` to inform the scheduler.
        - If because of implementation error, immediately output `❌ not completed: Benchmark failed. Implementation task should be retried` so that the implementation task can be retried.
      Do not update optimization_results.tsv or optimization_log.md on benchmark failure.

      After a successful benchmark, update the selected EXP-xxx row in optimization_results.tsv in place: 
      replace the metric columns' NA values with the measured metric values, and keep status=pending, commit_hash=pending.
      Do not finalize the decision in this task.

      Then update only 'Profiling Results' section in the selected EXP-xxx entry in optimization_log.md:

      Metrics: <observed metric values>
      Metric notes: <units, directionality, and any relevant interpretation notes>
      Benchmark reliability: <known noise, repeated-run count if applicable, missing reliability information, or other caveats produced by the benchmark task>

  - id: 5
    name: "Evaluate result, keep or revert, and update optimization state"
    type: simple
    max_attempts: 1
    description: |
      Make an evidence-based decision for the selected experiment, keep or
      revert the implementation, update optimization state files, and report the
      decision in the final response summary.
    system_prompt_prefix: |
      You are a strict experiment evaluator. Apply the decision rules consistently and use the benchmark results already recorded by the benchmark subtask.
    completion_criteria: |
      1. If required benchmark evidence is missing, incomplete, or internally inconsistent for an implemented experiment, 
      output `❌ not completed: benchmark incomplete` so that the benchmark task can be retried.
      2. Otherwise, exactly one final decision is applied as status=kept/reverted in both optimization_results.tsv and optimization_log.md according to initial_hint, 
      and the implementation commit is kept or removed with git reset, or absent because of 'rejected'.
      3. The selected experiment row in optimization_results.tsv is finalized with measured metric values already written by the benchmark subtask, 
      final reason and hypothesis commit hash.
      4. optimization_log.md updates the selected experiment's Status, Decision, and Hypothesis commit fields according to the final outcome.
      5. optimization_report.md is updated with Current Best vs Baseline, Experiment Summary, Cumulative Improvement, and Key Changes.
      6. failure_patterns.md is updated with a Pattern entry for useful reverted/rejected lessons or a Direction entry for useful kept lessons.
      7. Final documentation is committed with: xxx_opt(EXP-xxx): kept/reverted/rejected —— <reason>.
    initial_hint: |
      Read optimization_results.tsv, recent optimization_log.md entries, optimization_report.md, and failure_patterns.md first.
      Then make an evidence-based 'kept' / 'reverted' decision using the metric definitions, metric priorities, benchmark reliability notes, and observed tradeoffs. 
      DO NOT make 'rejected' decision by yourself: this decision can only be made by the implementation task.

      1. Required benchmark evidence before decision (Skip if the experiment was marked as 'rejected')
        - optimization_results.tsv contains the required metric values for EXP-xxx.
        - The selected experiment's Profiling Results contains observed metrics, metric notes, and benchmark reliability notes.
        - If required benchmark evidence is missing, incomplete, or internally inconsistent, output `❌ not completed: benchmark incomplete` 
          so that the benchmark task can be retried.

      2. Decision rules (Skip if the experiment was marked as 'rejected')
        - Metrics: <project-specific metric names, units, directionality, and where each value is recorded in optimization_results.tsv>
        - Metric priorities: <primary metric, secondary metrics, and how to reason about tradeoffs without fixed numeric keep/revert thresholds>
        - <project-specific decision rules. Write only when user specifies —— DO NOT invent thresholds by yourself (todo generating AI), let AI itself decide>
        
      3. If the decision is 'reverted', use git reset to remove the implementation commit. Do not remove the hypothesis documentation commit.

      4. Finalize state exactly as follows:
      
        (1) optimization_results.tsv
          exp_id  date  module  changes <metric columns...> status  reason  commit_hash
          EXP-xxx <date>  <module>  <short changes summary> <measured metric values, or NA if rejected> kept/reverted/rejected  <decision reason> <hypothesis commit hash>

        (2) optimization_log.md

          Keep this Markdown shape and replace <final status> with exactly one of kept, reverted, or rejected:
          ## Exp EXP-xxx: <short title>
          Date: <date>
          Module: <module>
          Status: <final status>
          Hypothesis commit: <hypothesis commit hash>

          ### Hypothesis

          <existing hypothesis>

          ### Proposed Changes

          <existing proposed changes>

          ### Expected Outcome

          <existing expected outcome>

          ### Risk

          <existing risk>

          ### Profiling Results

          <preserve the benchmark subtask's raw evidence; NA if rejected>

          ### Decision

          <final status>: <decision reason>

        (3) optimization_report.md
        
          Keep this Markdown shape and replace <final status> with exactly one of kept, reverted, or rejected:
          # Optimization Report —— <project name>

          ## Project Overview

          <existing project overview>

          ## Current Best vs Baseline

          <current best result, baseline result, and overall delta using the project-specific primary metric>

          ## Experiment Summary

          | Exp | Date | Module | Changes | Module Delta | Total Delta | Status | Reason |
          |-----|------|--------|---------|--------------|-------------|--------|--------|
          | <BASELINE-00N> | <date> | all | baseline | 0 | 0 | baseline | baseline or new baseline |
          | EXP-xxx | <date> | <module> | <short changes summary> | <module delta or NA> | <total delta or NA> | <final status> | <decision reason> |

          ## Cumulative Improvement

          | Experiment | Value |
          |------------|-------|
          | <BASELINE-00N> | <baseline primary metric value> |
          | After EXP-xxx | <primary metric value and delta vs baseline. Only added if decision is kept> |

          ## Key Changes

          1. **EXP-xxx (<FINAL STATUS>)**: <short summary>.

        (4) Update failure_patterns.md only when there is a reusable lesson. Keep this Markdown shape:
          # Failure Patterns —— <project name>

          ## Proven Failure Patterns

          (existing entries)

          ## Promising Directions

          (existing entries)

        If the experiment was reverted or rejected and has a useful lesson, append only this entry under Proven Failure Patterns:
          ### Pattern 00N: <short name>
          Experiment: EXP-xxx — <short title>
          Result: <metric summary or rejection summary>
          Root Cause: <root cause>
          Lesson: <lesson>

        If the experiment was kept and has a reusable lesson, append only this entry under Promising Directions:
          ### Direction 00N: <short name>
          Experiment: EXP-xxx — <short title>
          Result: <metric summary>
          Why it worked: <reason>
          Lesson: <lesson>

      5. Commit the final state documentation with:
        git commit -m "xxx_opt(EXP-xxx): <final status> —— <reason>"

  - id: 6
    name: "Diagnose repeated execution failures"
    type: simple
    max_attempts: 1
    description: |
      Diagnose repeated execution failures. This task is for execution
      anomalies only, not for ideas that were cleanly evaluated and reverted.
    completion_criteria: |
      1. optimization_results.tsv, optimization_log.md, optimization_report.md, failure_patterns.md and error_report.md have been read.
      2. If the failure is caused by missing external prerequisites, output exactly `❌ not completed: external blocker - <reason>` and do not modify regular optimization state files.
      3. The concise diagnosis and next retry focus are reported in the final response.
      4. error_report.md is not created or modified.
      5. No source code, tests, configs, benchmark scripts, benchmark outputs, result tables, optimization logs, or rolling reports are modified.
    initial_hint: |
      Read the optimization_results.tsv, optimization_log.md, optimization_report.md, failure_patterns.md and error_report.md. Do not edit code.

      Diagnose only repeated execution anomalies, such as baseline setup failures,
      build/test failures caused by the current implementation, anti-hack failures,
      benchmark command failures, missing benchmark evidence, or retryable broken
      workspace state.

      Do not treat consecutive `reverted` experiments as repeated execution failures. 
      A reverted experiment means the idea was implemented, benchmarked, and evaluated 
      but was not worth keeping.

      If progress is blocked by unavailable external prerequisites, missing
      services, unavailable credentials, or other environment issues that cannot
      be fixed inside the optimization loop, output exactly
      `❌ not completed: external blocker - <reason>` and stop without editing
      regular optimization state files.

      Otherwise, report the concise diagnosis and next retry focus in the final
      response. Do not create or modify optimization_results.tsv, optimization_log.md, optimization_report.md, failure_patterns.md and error_report.md.

      End the final response with a concise summary in the last 5 lines to inform the scheduler:
      - Diagnosis: <short issue> | external blocker | none
      - Action: continue | stop
      - External blocker: yes | no
```