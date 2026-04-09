# Best Practice: Testing & Verification

Patterns for **running tests, fixing failures, and ensuring quality** — test-driven repair loops and CI-style verification workflows.

---

## Recommended Structures

| Scenario | Structure | Why |
|----------|-----------|-----|
| Run tests and report results | Single `simple` task | Just execute and report. |
| Run tests → fix failures → re-verify | `nested` with 3 subtasks | Separate diagnosis from fixing; fail-fast on re-verification. |
| Slow test suite (> 1 min) | Use `long_running` for the test execution step | Prevents session timeout from killing a slow test run. |
| Fix multiple test categories | `nested` with per-category fix subtasks | Independent failure modes benefit from isolated retry. |

---

## Patterns

### Pattern 1: Test → Fix → Verify cycle

The canonical pattern for "make all tests pass". The key insight: **separate diagnosis from repair**, and make the final verification a fail-fast step that triggers the parent's failure analysis on failure.

```yaml
- id: 1
  name: "Fix all failing tests"
  type: nested
  completion_criteria: |
    1. pytest tests/ exits with code 0
    2. No skipped tests (all tests run and pass)
  subtasks:
    - id: 1.1
      name: "Run tests and catalog failures"
      type: simple
      model: lite
      completion_criteria: |
        1. Full test suite executed: pytest tests/ --tb=short -q
        2. Failing test names and error summaries written to test_failures.txt
      initial_hint: |
        Run the full suite and capture output.
        Write a structured list to test_failures.txt:
          - test name
          - error type (assertion, import, timeout, etc.)
          - one-line summary of the failure

    - id: 1.2
      name: "Apply fixes for cataloged failures"
      type: simple
      completion_criteria: |
        1. All issues from test_failures.txt addressed
        2. Changes committed
      initial_hint: |
        Read test_failures.txt for the list of failures.
        Fix each failing test. Group related fixes into logical commits.
        Do NOT skip or delete tests — fix the underlying code or the test itself.

    - id: 1.3
      name: "Re-run full test suite"
      type: simple
      max_attempts: 1
      model: lite
      system_prompt_prefix: |
        You are a test runner. Do NOT modify any source code or tests.
      completion_criteria: |
        1. pytest tests/ exits with code 0
```

### Pattern 2: Long-running test suites

When the test suite takes more than a minute, use `long_running` to prevent session timeout.

```yaml
- id: 1.1
  name: "Run integration test suite"
  type: long_running
  model: lite
  system_prompt_prefix: |
    You are a test runner. Do NOT modify any source code.
  completion_criteria: |
    1. Integration tests completed
    2. Exit code 0 (all tests passed)
  initial_hint: |
    Run: pytest tests/integration/ -v --timeout=300
    This suite takes several minutes.
```

### Pattern 3: Category-based test fixing

When failures span multiple independent areas, fix them category by category. This prevents the AI from being overwhelmed and allows targeted retry.

```yaml
- id: 1
  name: "Fix all test failures"
  type: nested
  completion_criteria: |
    1. pytest tests/ exits with code 0
  subtasks:
    - id: 1.1
      name: "Run tests and categorize failures"
      type: simple
      model: lite
      completion_criteria: |
        1. Failures categorized by module in test_failures.txt
      initial_hint: |
        Run: pytest tests/ --tb=line -q
        Group failures by module/directory in test_failures.txt.

    - id: 1.2
      name: "Fix API test failures"
      type: simple
      completion_criteria: |
        1. All API test failures from test_failures.txt resolved
        2. pytest tests/api/ passes
      initial_hint: |
        Focus ONLY on API tests. Read test_failures.txt for the list.
        Run pytest tests/api/ to verify before committing.

    - id: 1.3
      name: "Fix model test failures"
      type: simple
      completion_criteria: |
        1. All model test failures from test_failures.txt resolved
        2. pytest tests/models/ passes

    - id: 1.4
      name: "Run full test suite"
      type: simple
      max_attempts: 1
      model: lite
      system_prompt_prefix: |
        You are a test runner. Do NOT modify any source code.
      completion_criteria: |
        1. pytest tests/ exits with code 0
```

### Pattern 4: Adding tests for existing code

When the task is to improve test coverage, separate "identify what to test" from "write the tests" to ensure thorough coverage analysis.

```yaml
subtasks:
  - id: 1.1
    name: "Analyze coverage and identify gaps"
    type: simple
    completion_criteria: |
      1. Coverage report generated: pytest --cov=src/ --cov-report=term-missing
      2. Uncovered functions listed in coverage_gaps.txt with priority
    initial_hint: |
      Run coverage and identify functions with 0% or low coverage.
      Prioritize: public API functions > internal helpers > edge cases.

  - id: 1.2
    name: "Write tests for uncovered code"
    type: simple
    completion_criteria: |
      1. Tests written for all high-priority gaps in coverage_gaps.txt
      2. All new tests pass: pytest tests/ -v
      3. Coverage improved (check with pytest --cov)
```

---

## Anti-Patterns

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| Running slow tests in a `simple` task | Session timeout kills the test mid-run | Use `long_running` for any test suite > 1 minute |
| Fixing tests without running them first | AI doesn't know which tests actually fail | Always run + catalog failures first |
| Combining test writing and bug fixing | Two different goals compete for attention | Separate: write tests in one task, fix bugs in another |
| Deleting failing tests as a "fix" | Tests exist for a reason | `completion_criteria` should require 0 skipped/deleted tests |
