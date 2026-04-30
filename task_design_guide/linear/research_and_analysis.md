# Best Practice: Research & Analysis

Patterns for **reading code, analyzing systems, writing reports, and exploratory tasks** where the primary output is documentation or understanding, not code changes.

---

## Recommended Structures

| Scenario | Structure | Why |
|----------|-----------|-----|
| Read code and write a report | Single `simple` task | One session can read files and produce analysis. |
| Multi-part analysis (architecture + performance + security) | `nested` with per-area subtasks | Each analysis area benefits from focused attention. |
| Analysis that requires running diagnostics first | `nested`: run diagnostics → analyze results | Separate data collection from interpretation. |
| Analysis of large codebase (many files) | `nested`: survey structure → deep dive per module → synthesize | Prevents context overflow from trying to read everything at once. |
| Analysis requiring long-running tools (static analysis, large profiling) | `nested` with `long_running` diagnostic step → `simple` analysis | Prevents session timeout during data collection. |

---

## Patterns

### Pattern 1: Persist analysis to files

Analysis tasks must write results to files — the next subtask (or the human reader) can't access the AI's conversation. Be explicit about output file paths.

```yaml
- id: 1
  name: "Analyze API architecture and write report"
  type: simple
  completion_criteria: |
    1. doc/api_analysis.md exists
    2. Report covers: endpoint inventory, auth flow, error handling patterns
    3. Each section includes specific file:line references
  initial_hint: |
    Key directories:
    - src/api/ — route handlers
    - src/middleware/ — auth and validation
    - src/models/ — data models

    Write your analysis to doc/api_analysis.md.
    Include specific file paths and line numbers for every claim.
```

### Pattern 2: Large codebase analysis with progressive focus

For large codebases, don't try to read everything in one session. Survey first, then deep-dive into each area. For very large codebases (10+ modules), consider splitting the deep-dive into multiple subtasks — one per module group — to avoid context overflow in a single session.

```yaml
- id: 1
  name: "Codebase architecture analysis"
  type: nested
  completion_criteria: |
    1. doc/architecture_report.md is complete
    2. Report covers all major modules with dependency diagram
  subtasks:
    - id: 1.1
      name: "Survey project structure and identify modules"
      type: simple
      completion_criteria: |
        1. doc/module_inventory.md lists all top-level modules
        2. Each module has: purpose, key files, approximate size
        3. Inter-module dependencies identified
      initial_hint: |
        Start with directory listing and README files.
        Read entry points (main.py, index.ts, etc.) to understand the top-level flow.
        Write inventory to doc/module_inventory.md.
        Do NOT deep-dive into any single module yet.

    - id: 1.2
      name: "Deep-dive analysis of each module"
      type: simple
      completion_criteria: |
        1. doc/module_details.md contains detailed analysis per module
        2. Each module section covers: public API, internal patterns, tech debt
      initial_hint: |
        Read doc/module_inventory.md for the module list.
        For each module, read the key files identified in the inventory.
        Write detailed analysis to doc/module_details.md.

    - id: 1.3
      name: "Synthesize final architecture report"
      type: simple
      completion_criteria: |
        1. doc/architecture_report.md is the final deliverable
        2. Includes: overview, module descriptions, dependency diagram (text-based), recommendations
      initial_hint: |
        Read doc/module_inventory.md and doc/module_details.md.
        Synthesize into a single cohesive report at doc/architecture_report.md.
        Include a text-based dependency diagram (ASCII or Mermaid).
```

### Pattern 3: Diagnostic data collection before analysis

When the analysis requires running commands (profiling, benchmarking, log analysis), separate data collection from interpretation. This lets the AI focus on one cognitive task at a time.

```yaml
subtasks:
  - id: 1.1
    name: "Collect diagnostic data"
    type: simple
    model: lite
    system_prompt_prefix: |
      You are a diagnostics runner. Collect data only — do NOT analyze or modify code.
    completion_criteria: |
      1. Profiling output saved to diagnostics/profile.txt
      2. Memory usage saved to diagnostics/memory.txt
      3. Log summary saved to diagnostics/log_summary.txt
    initial_hint: |
      Run these commands and save outputs:
      - python -m cProfile -o diagnostics/profile.txt src/main.py
      - python scripts/memory_check.py > diagnostics/memory.txt
      - grep -c ERROR logs/*.log > diagnostics/log_summary.txt

  - id: 1.2
    name: "Analyze diagnostics and write recommendations"
    type: simple
    completion_criteria: |
      1. doc/performance_analysis.md written with findings and recommendations
      2. Top 3 bottlenecks identified with specific file:line references
      3. Each recommendation includes estimated impact and difficulty
    initial_hint: |
      Read all files in diagnostics/ directory.
      Focus on: what's slow, what uses too much memory, what errors are common.
      Write actionable recommendations to doc/performance_analysis.md.
```

### Pattern 4: Long-running diagnostic tools

When analysis requires running tools that take more than a minute (static analyzers on large codebases, comprehensive profiling, security scanners), use `long_running` for the data collection step.

```yaml
subtasks:
  - id: 1.1
    name: "Run static analysis on full codebase"
    type: long_running
    model: lite
    system_prompt_prefix: |
      You are a diagnostics runner. Collect data only — do NOT analyze or modify code.
    completion_criteria: |
      1. Static analysis completed with exit code 0
      2. Report saved to diagnostics/static_analysis.json
    initial_hint: |
      Run: python -m pylint src/ --output-format=json > diagnostics/static_analysis.json
      This may take several minutes on a large codebase.

  - id: 1.2
    name: "Analyze results and write recommendations"
    type: simple
    completion_criteria: |
      1. doc/code_quality_report.md written with categorized findings
      2. Top issues prioritized by severity and frequency
    initial_hint: |
      Read diagnostics/static_analysis.json.
      Categorize findings by type (complexity, duplication, style, bugs).
      Write actionable recommendations to doc/code_quality_report.md.
```

### Pattern 5: Use `system_prompt_prefix` for analysis-mode persona

For pure analysis tasks, use `system_prompt_prefix` to set the right persona and prevent the AI from making code changes.

```yaml
system_prompt_prefix: |
  You are a senior software architect conducting a code review.
  Your job is to READ and ANALYZE — do NOT modify any source code.
  Write all findings to the specified output files.
```

---

## Anti-Patterns

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| Analysis without specific output file | AI produces analysis in conversation, lost between sessions | Always specify output file path in `completion_criteria` |
| Reading entire large codebase in one task | Context overflow, shallow analysis | Progressive focus: survey → deep-dive → synthesize |
| Mixing analysis and code changes | AI rushes through analysis to start coding | Separate analysis tasks from implementation tasks |
| Vague `completion_criteria` ("analyze the code") | AI produces superficial report and claims success | Require specific sections, file references, and concrete deliverables |
