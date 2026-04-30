# Best Practice: Academic Experiments

Patterns for **multi-branch comparison experiments** common in academic research — controlled-variable studies, ablation experiments, baseline reproduction, and cross-condition result aggregation. Each experimental condition runs on its own git branch; a final aggregation step merges results into a comparison table.

> **Complements `iterative_optimization.md`**, which covers single-branch iterative optimize→benchmark→evaluate loops. Use *this* guide when you need to compare multiple conditions side-by-side.

---

## Recommended Structures

| Scenario | Structure | Why |
|----------|-----------|-----|
| Single-factor comparison (e.g., 3 models on 1 dataset) | Baseline task → N experiment tasks → aggregation task | Each condition is independent; aggregation needs all results. |
| Multi-factor controlled-variable study | Sequential experiment tasks, one factor changed per task | Ensures each factor's effect is isolated. |
| Ablation study (remove components one at a time) | Baseline task → N ablation tasks → aggregation task | Same as single-factor, but each task *removes* one component. |
| Baseline reproduction before experiments | Baseline task (first) → experiment tasks | Establishes the reference point all experiments compare against. |

---

## Patterns

### Pattern 1: Branch-per-condition

Each experimental condition runs on its own git branch. Results are recorded to a per-branch file. A final aggregation task reads all branch results and produces a comparison table.

```yaml
# In root description:
description: |
  ### Branch Naming Convention
  - Baseline: exp/baseline
  - Experiments: exp/<condition_name> (e.g., exp/model_A, exp/no_attention)

  ### Result File Convention
  Each branch writes results to results/metrics.tsv with columns:
  condition | accuracy | latency_ms | memory_mb | notes
```

```yaml
# Experiment task:
initial_hint: |
  1. Create and checkout branch exp/<condition_name>
  2. Apply the experimental changes
  3. Run the full evaluation pipeline
  4. Record results to results/metrics.tsv (append, don't overwrite)
  5. Commit all changes including results
```

### Pattern 2: Controlled-variable discipline

Each experiment changes **exactly one variable**. The task's `initial_hint` explicitly states which variable is changed and which are held constant. `completion_criteria` requires documenting this.

```yaml
initial_hint: |
  This experiment tests: <variable> = <new_value>
  Hold constant:
  - learning_rate = 0.001
  - batch_size = 32
  - epochs = 100
  - dataset = CIFAR-10
  - seed = 42

  If you need to change anything else to make this work,
  STOP and report — do not silently change controlled variables.

completion_criteria: |
  1. Only the specified variable was changed
  2. results/metrics.tsv contains a row for this condition
  3. results/experiment_log.md documents:
     - Changed variable and its value
     - All held-constant variables confirmed unchanged
     - Any anomalies observed during the run
```

### Pattern 3: Standardized data recording format

Define the result schema **once** in the root `description`. Every experiment writes results in the same format so aggregation is mechanical.

```yaml
description: |
  ### Result Schema (TSV)
  All experiment tasks MUST write results to results/metrics.tsv
  using this exact schema:

  condition | accuracy | precision | recall | f1 | latency_ms | memory_mb | notes

  - condition: branch name (e.g., "baseline", "model_A")
  - All numeric fields: report mean ± std over 3 runs
  - notes: any anomalies or observations

  ### Experiment Log Schema
  Each experiment also appends to results/experiment_log.md:
  - Experiment ID and condition name
  - Changed variable(s) and values
  - Held-constant variables
  - Raw output snippets (first/last 10 lines of training log)
  - Pass/fail status and reason
```

### Pattern 4: Baseline-first workflow

Always reproduce the baseline **before** running any experiments. The baseline task produces a reference result that all subsequent tasks compare against.

```yaml
# Baseline task (must run first):
- id: 1
  name: "Reproduce baseline"
  type: simple
  max_attempts: 3
  completion_criteria: |
    1. Branch exp/baseline created and checked out
    2. Training + evaluation completed successfully
    3. results/metrics.tsv contains the baseline row
    4. Baseline metrics are within expected range:
       - accuracy: 92% ± 2%  (from paper Table 1)
    5. If metrics are outside expected range, document the discrepancy
       but do NOT tune hyperparameters to match — report as-is
  initial_hint: |
    This is the baseline reproduction step. Do NOT modify the model
    or training pipeline. Run the code as-is and record results.
    The baseline result is the reference point for all experiments.
```

### Pattern 5: Cross-branch aggregation

A dedicated final task collects results from all experiment branches and produces the comparison table. This task should be read-only (no code changes).

```yaml
- id: 5
  name: "Aggregate results and produce comparison table"
  type: simple
  max_attempts: 2
  system_prompt_prefix: |
    You are a data analyst. Do NOT modify any source code or rerun experiments.
    Your job is to collect, organize, and present results.
  completion_criteria: |
    1. results/comparison_table.md contains a formatted table with all conditions
    2. Each row shows: condition, all metrics, delta vs. baseline
    3. Statistical significance noted where applicable
    4. results/summary.md contains a 1-paragraph executive summary
  initial_hint: |
    For each experiment branch (exp/*):
      git checkout <branch> -- results/metrics.tsv
      Read the metrics row and record it
      git checkout main  (return to main before next branch)

    Produce:
    1. results/comparison_table.md — full comparison with deltas vs. baseline
    2. results/summary.md — which condition performed best and why

    Sort the table by the primary metric (descending).
    Highlight the best result in each column.
```

### Pattern 6: Ablation study

N experiments, each removing one component. The aggregation task produces an ablation table showing each component's contribution.

```yaml
description: |
  ### Ablation Study Design
  Components to ablate:
  1. Attention mechanism → branch exp/no_attention
  2. Skip connections → branch exp/no_skip
  3. Data augmentation → branch exp/no_augment
  4. Learning rate scheduler → branch exp/no_lr_sched

  Each ablation branch starts from the baseline code and removes
  exactly one component. Do NOT change anything else.

# One task per ablation (repeat this pattern for each component):
- id: 3
  name: "Ablation: remove attention mechanism"
  type: simple
  max_attempts: 3
  completion_criteria: |
    1. Branch exp/no_attention created from exp/baseline
    2. Attention mechanism removed, nothing else changed
    3. Training + evaluation completed
    4. results/metrics.tsv contains the "no_attention" row
  initial_hint: |
    git checkout -b exp/no_attention exp/baseline
    Remove ONLY the attention mechanism. Keep everything else identical.
    If removing attention requires structural changes (e.g., tensor shape),
    make the minimal adjustment and document it in experiment_log.md.
```

### Pattern 7: Experiment registry

Maintain a registry file that tracks all planned experiments, their status, and key results. Each experiment task updates it at start and end.

```yaml
initial_hint: |
  At the START of this experiment:
  - Read results/experiment_registry.md
  - Update your experiment's status to "running"
  - Commit: git add results/experiment_registry.md && git commit -m "registry: start <exp_name>"

  At the END of this experiment:
  - Update status to "done" (or "failed") with key metric
  - Commit: git add results/ && git commit -m "registry: complete <exp_name>"
```

Registry format:
```markdown
# Experiment Registry

| ID | Condition | Branch | Status | Key Metric | Notes |
|----|-----------|--------|--------|------------|-------|
| 1  | baseline  | exp/baseline | done | acc=92.1% | Reference |
| 2  | model_A   | exp/model_A  | done | acc=94.3% | +2.2% vs baseline |
| 3  | no_attention | exp/no_attention | running | — | Ablation |
| 4  | no_skip   | exp/no_skip  | pending | — | Ablation |
```

---

## Anti-Patterns

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| All experiments on the same branch | Merge conflicts, can't isolate failures, can't revert one experiment without affecting others | Branch-per-condition (Pattern 1) |
| No standardized result format | Aggregation becomes manual and error-prone | Define schema in root `description` (Pattern 3) |
| Skipping baseline reproduction | No reference point — can't compute deltas or validate setup | Always run baseline first (Pattern 4) |
| Changing multiple variables at once | Can't attribute improvements to any single factor | One variable per experiment (Pattern 2) |
| Results only in conversation/logs | Lost between sessions, can't aggregate | Write to files in standardized format |
| No experiment registry | Lose track of what's been tried, risk re-running experiments | Maintain registry (Pattern 7) |
| Aggregation task modifies code | Mixes analysis with implementation, risks breaking experiments | Aggregation is read-only (Pattern 5) |