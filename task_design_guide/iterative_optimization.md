# Best Practice: Iterative Optimization

Patterns for **looping** tasks that run N rounds of experimentation (e.g., profiling → optimize → benchmark → evaluate). These patterns are proven in production and address the core challenge: **without shared context, the AI forgets what it tried and repeats failed strategies.**

---

## Recommended Structure

```
looping (repeat_count: N)
├── analyze + propose hypothesis     (simple)
├── implement + build + test         (simple)
├── benchmark                        (simple or long_running, max_attempts: 1, model: lite)
└── evaluate + keep/revert + report  (simple, max_attempts: 1, model: lite)
```

- Use `looping` (not `nested`) because the goal is "run N rounds", not "reach a specific target".
- **Separate "thinking" from "doing"**: analysis in one subtask, implementation in another (see main guide §4.2).
- Benchmark and evaluation subtasks should use `max_attempts: 1` and `model: lite` — they just execute, and failures should propagate to the parent for proper retry.
- Use `long_running` for benchmark if it takes more than a minute (e.g., GPU profiling, large simulation runs).

---

## Patterns

### Pattern 1: Separate documentation commits from code commits

Commit the hypothesis documentation *before* implementing code. If the code is rolled back on failure, the documentation survives and informs the next iteration.

```yaml
# In the "propose hypothesis" subtask:
initial_hint: |
  Commit documentation SEPARATELY before implementation begins:
    git add doc/ && git commit -m "doc: hypothesis for experiment 05"
  This ensures the idea description survives a code rollback.
```

### Pattern 2: Maintain a failure pattern database

Beyond a simple log, maintain a structured file that classifies *why* experiments failed. The AI should read this at the start of each iteration and update it at the end.

```yaml
# In the "propose hypothesis" subtask:
initial_hint: |
  Read failure_patterns.md FIRST to avoid repeating known failures.
  If the last 3+ experiments all failed in the same category,
  try a completely different direction.

# In the "evaluate results" subtask:
initial_hint: |
  Update failure_patterns.md:
  - If discarded: classify the failure (new pattern or existing?)
  - If kept: add to "Promising Directions" with what worked and why
```

### Pattern 3: Re-evaluate the bottleneck every iteration

Don't assume the bottleneck is the same as the previous round. Instruct the AI to compute a diagnostic metric at the start of each iteration to determine where to focus.

```yaml
initial_hint: |
  Identify the current bottleneck EVERY round (don't assume it's the same):
  - Compute ratio = E2E_error / baseline_error
  - ratio > 5× → focus on module A
  - ratio < 2× → focus on module B
```

### Pattern 4: Define a decision matrix for keep/discard

Don't let the AI make subjective keep/discard decisions. Provide a structured decision matrix in the evaluation subtask's `initial_hint` or `system_prompt_prefix`:

```yaml
system_prompt_prefix: |
  You are a strict experiment evaluator. Apply the decision matrix:
  - exe or validation failed → MUST revert
  - Primary metric improved ≥5% AND no other metric worsened >3% → keep
  - All metrics within ±1% → discard (no meaningful change)
  - Mixed results not covered above → discard
```

### Pattern 5: Reference on-demand deep docs

For complex projects, not all documentation needs to be read every iteration. List deep docs in `initial_hint` with conditions for when to read them:

```yaml
initial_hint: |
  On-demand docs (read ONLY if your idea involves these areas):
  - NN₁ architecture changes → read docs/design/00_overview.md
  - Loss function changes → read docs/design/05_training.md §8
```

### Pattern 6: Clean workspace at iteration start

Since subtasks share the filesystem, the start of each iteration may find uncommitted changes or stashed work from a previous failed attempt. Instruct the first subtask to handle this:

```yaml
initial_hint: |
  First: git status. If not clean:
  - Documentation changes → commit them
  - Code changes → git stash or git checkout
```

### Pattern 7: Consult history across branches or previous runs

If the project has a history of previous optimization attempts (e.g., on other branches), instruct the AI to check those records to avoid re-trying known failures:

```yaml
initial_hint: |
  Check if previous branch reports exist (e.g., optimization_report_1.md).
  Reverted experiments = that direction didn't work. Don't retry unless
  you have a fundamentally different approach.
```

---

## Complete YAML Example

A realistic iterative optimization project. Note how:
- The `description` provides comprehensive project context (goal, architecture, constraints, naming rules, historical references).
- Each subtask explicitly states what files it reads and writes, ensuring information flows correctly across context-isolated sessions.
- Documentation commits are separated from code commits (Pattern 1), so hypothesis docs survive code rollbacks.
- A failure pattern database is maintained across iterations (Pattern 2).

```yaml
description: |
  ## Project: GPU Compute Shader Performance Optimization

  ### Goal
  Iteratively optimize DX12 GPU compute shaders for minimum latency
  while maintaining numerical correctness.

  ### Architecture
  - src/shaders/ — HLSL compute shaders (optimization targets)
  - src/frame_processor.cpp — GPU dispatch logic
  - src/test_reference.cpp — CPU reference implementation for correctness checks
  - doc/compute_shader_specs.md — documentation for per-stage specifications

  ### Key File Paths
  All paths are relative to the project root, the shell working directory.
  - Results log: doc/optimization_results_N.tsv (N = branch number from opt_<N>)
  - Experiment log: doc/optimization_log_N.md
  - Failure patterns: doc/failure_patterns.md

  ### Key Commands
  - Build: cmake --build build --config Release
  - Correctness test: build/Release/Simulator.exe (exit code 0 = GPU matches CPU reference)

  ### Naming Conventions
  - Optimization docs are named by branch number N (from branch name opt_<N>)
  - optimization_results_N.tsv — performance data table
  - optimization_log_N.md — experiment log
  - optimization_report_N.md — optimization report

  ### Historical Branch References
  - doc/ may contain optimization reports from previous branches (e.g., optimization_report_1.md)
  - These document all previously attempted optimizations (both kept and reverted)
  - New branches MUST reference these to avoid repeating reverted failures

  ### Hard Constraints
  - Do NOT modify CPU-side post-processing logic in main.cpp
  - Do NOT modify resource/ binary data files
  - One optimization per experiment, keep changes minimal

  ### Architecture Notes
  - Shaders share a constant buffer register with stage-dependent semantics
  - When modifying shader thread group size, sync Dispatch() call in frame_processor.cpp
  - When modifying GPU buffers, sync resource_manager.cpp and shader register declarations
  - When changing shader algorithms, sync CPU reference in test_reference.cpp

  ### Reference Docs (read only when needed)
  - doc/pipeline_architecture.md — full pipeline overview
  - doc/optimization_report_*.md — previous optimization branch reports

  ### Rules
  - Fully autonomous — never ask the user questions
  - One optimization per experiment, keep changes minimal
  - If you discover a bug, fix ONLY the bug in that round (no optimization)

tasks:
  # ── Task 1: Establish Baseline (one-time setup) ──────────────────────
  - id: 1
    name: "Build, validate, and record baseline performance"
    type: nested
    max_attempts: 3
    completion_criteria: |
      1. Simulator.exe exit code 0 (correctness test passes)
      2. doc/optimization_results_N.tsv exists with baseline row
    subtasks:
      - id: 1.1
        name: "Create optimization branch"
        type: simple_once
        model: lite
        system_prompt_prefix: |
          You are a build engineer. Do NOT modify any source code.
        completion_criteria: |
          1. On a new opt_<N> branch (N = next available number)
          2. git branch confirms current branch
        initial_hint: |
          git branch -a | grep opt_ to determine next number.
          git checkout -b opt_<N> main

      - id: 1.2
        name: "Build, run correctness tests, and record baseline"
        type: simple
        completion_criteria: |
          1. cmake build succeeds
          2. Simulator.exe exit code 0
          3. doc/optimization_results_N.tsv created with header + baseline row
          4. doc/optimization_log_N.md created with baseline profiling data
          5. doc/failure_patterns.md created (from template if missing)
          6. Changes committed
        initial_hint: |
          Build: cmake --build build --config Release
          Test: build/Release/Simulator.exe
          Extract N from branch name. Create results TSV and log MD.
          If doc/failure_patterns.md doesn't exist, create it with template:
            # Failure Patterns & Insights
            ## Proven Failure Patterns
            (none yet)
            ## Promising Directions
            (none yet)

  # ── Task 2: Iterative Optimization Loop ──────────────────────────────
  - id: 2
    name: "Iterative shader optimization"
    type: looping
    repeat_count: 20
    max_attempts_per_loop: 5
    completion_criteria: |
      One complete cycle of: analyze → implement → benchmark → evaluate.
    subtasks:
      - id: 2.1
        name: "Analyze bottleneck and propose optimization hypothesis"
        type: simple
        system_prompt_prefix: |
          You are a senior GPU performance engineer.
          Be fully autonomous. Only read files relevant to the current bottleneck.
        completion_criteria: |
          1. Current bottleneck identified from profiling data
          2. Hypothesis appended to optimization_log_N.md
          3. Hypothesis doc committed SEPARATELY before implementation
        initial_hint: |
          Read optimization_results_N.tsv and optimization_log_N.md for history.
          Read failure_patterns.md to avoid repeating known failures.
          Check doc/optimization_report_*.md for previous branch history.
          Propose one specific optimization hypothesis.
          Commit documentation SEPARATELY before implementation:
            git add doc/ && git commit -m "doc: hypothesis for exp <id>"
          This ensures the hypothesis survives a code rollback.

      - id: 2.2
        name: "Implement optimization, build, and verify correctness"
        type: simple
        completion_criteria: |
          1. Code changes implement the latest hypothesis
          2. cmake build succeeds
          3. Simulator.exe exit code 0 (correctness preserved)
          4. Changes committed: "opt: exp <id> - <description>"
        initial_hint: |
          Read optimization_log_N.md for the latest hypothesis.
          Read only the source files you need to modify.
          Implement, build, and test. If tests fail, fix before committing.

      - id: 2.3
        name: "Run benchmark"
        type: simple
        max_attempts: 1
        model: lite
        system_prompt_prefix: |
          You are a benchmark runner. Do NOT modify any source code.
        completion_criteria: |
          1. Benchmark completed, full performance profile captured
        initial_hint: |
          Run: build/Release/Simulator.exe
          If failed, add --verbose and rerun for diagnostics.

      - id: 2.4
        name: "Evaluate results, keep/revert, and update failure patterns"
        type: simple
        model: lite
        max_attempts: 1
        system_prompt_prefix: |
          You are a performance analyst. Apply the decision rules strictly.
          Correctness failure → MUST revert. No subjective judgments.
        completion_criteria: |
          1. New row appended to optimization_results_N.tsv
          2. If revert: git revert of the code commit (doc commit preserved)
          3. optimization_log_N.md updated with results and decision
          4. failure_patterns.md updated with learnings from this round
          5. All changes committed
        initial_hint: |
          Compare benchmark results against the SOTA row in optimization_results_N.tsv.
          Decision rules:
          - Correctness test failed → revert
          - Performance improved → keep, update SOTA
          - No improvement or regression → revert
          If revert: git revert <code_commit> --no-edit
            (The doc commit from 2.1 is preserved automatically.)
          Append results to TSV regardless of decision.
          Update failure_patterns.md:
          - If reverted: classify the failure (new or existing pattern?)
          - If kept: add to "Promising Directions" with what worked and why
          Update optimization_report_N.md with current summary.
          Commit: git add doc/ && git commit -m "doc: results for exp <id>"
```
