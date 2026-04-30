# Best Practice: Build & Ship

Patterns for **implementing features, fixing bugs, and refactoring** — the most common type of software engineering task.

---

## Recommended Structures

| Scenario | Structure | Why |
|----------|-----------|-----|
| Single bug fix or small feature | `simple` (top-level) | One logical unit, no need to decompose. |
| Feature with build + test verification | `nested` with 2–3 subtasks | Separate implementation from verification so verification failures trigger targeted retry. |
| Feature with long-running build (> 1 min) | Same as above, but use `long_running` for the build/test step | Prevents session timeout during compilation or test execution. |
| Fix multiple independent bugs | `nested` with per-bug subtasks + final validation | Each bug is an independent failure mode; isolating them lets the AI focus on one at a time. |
| New feature with new tests | `nested`: analyze → implement + write tests → run full suite | Separate analysis from implementation; keep code and test writing together so they stay consistent. |
| Large refactoring across many files | `nested`: analyze → implement → verify | Separate analysis from implementation to prevent the AI from rushing. |

### Key Principle: Use `nested` when the goal is "reach a specific end state"

`nested` evaluates `completion_criteria` after each round of subtasks and can retry intelligently. This makes it ideal for "all tests pass", "feature works end-to-end", etc.

---

## Patterns

### Pattern 1: Analyze before implementing

For non-trivial changes, separate "understand the problem" from "write the code". When combined, the AI tends to rush analysis to start coding, or takes shortcuts in implementation because it spent too much context on analysis.

```yaml
subtasks:
  - id: 1.1
    name: "Analyze codebase and design implementation approach"
    type: simple
    completion_criteria: |
      1. Key files and functions identified
      2. Implementation approach documented in implementation_plan.md
      3. Edge cases and potential risks listed
    initial_hint: |
      Key entry points: src/api/routes.py, src/models/user.py
      Write your analysis to implementation_plan.md so the next step can read it.

  - id: 1.2
    name: "Implement changes, build, and run tests"
    type: simple
    completion_criteria: |
      1. Changes implemented per implementation_plan.md
      2. All existing tests pass: pytest tests/
      3. Changes committed
    initial_hint: |
      Read implementation_plan.md for the approach.
      Run existing tests before AND after changes to catch regressions.
```

### Pattern 2: Multi-bug fixing with isolated subtasks

When fixing multiple bugs, each bug should be its own subtask. This prevents the AI from getting overwhelmed and ensures each fix is independently retryable.

```yaml
- id: 1
  name: "Fix authentication bugs"
  type: nested
  completion_criteria: |
    1. All auth bugs are fixed
    2. pytest tests/auth/ passes with 0 failures
  subtasks:
    - id: 1.1
      name: "Fix session expiry not triggering logout"
      type: simple
      completion_criteria: |
        1. Session expiry triggers logout redirect
        2. Unit test added for expiry behavior
        3. Changes committed
      initial_hint: |
        Bug: sessions expire but users stay logged in.
        Key file: src/auth/session.py

    - id: 1.2
      name: "Fix password reset token reuse"
      type: simple
      completion_criteria: |
        1. Reset tokens are invalidated after use
        2. Test added for token reuse rejection
        3. Changes committed

    - id: 1.3
      name: "Run full auth test suite"
      type: simple
      max_attempts: 1
      model: lite
      system_prompt_prefix: |
        You are a test runner. Do NOT modify any source code.
      completion_criteria: |
        1. pytest tests/auth/ exits with code 0
```

### Pattern 3: Feature with build verification

Always keep "implement + build" together — if the build fails, the AI can fix it immediately without a costly failure analysis round-trip. Separate the final validation as a fail-fast step. If the build takes more than a minute, use `long_running` for the build/test subtask.

```yaml
subtasks:
  - id: 1.1
    name: "Implement feature and ensure it builds"
    type: simple
    completion_criteria: |
      1. Feature implemented per spec
      2. Project builds without errors: npm run build
      3. Changes committed
    initial_hint: |
      Spec: Add a /api/export endpoint that returns CSV.
      Key files: src/routes/api.ts, src/services/export.ts

  - id: 1.2
    name: "Run tests and lint"
    type: simple
    max_attempts: 1
    model: lite
    system_prompt_prefix: |
      You are a test runner. Do NOT modify any source code.
    completion_criteria: |
      1. npm test exits with code 0
      2. npm run lint exits with code 0
```

### Pattern 4: Refactoring with safety nets

For refactoring tasks, use git to create safety checkpoints and validate behavior preservation at each step.

```yaml
- id: 1
  name: "Refactor payment module to use strategy pattern"
  type: nested
  completion_criteria: |
    1. Payment module uses strategy pattern
    2. All payment tests pass: pytest tests/payment/
    3. No functional changes (tests are the proof)
  subtasks:
    - id: 1.1
      name: "Analyze current payment module and plan refactoring"
      type: simple
      completion_criteria: |
        1. Current architecture documented in refactor_plan.md
        2. Step-by-step refactoring plan with safety checkpoints
      initial_hint: |
        Key files: src/payment/*.py
        Run tests FIRST to establish a green baseline: pytest tests/payment/
        Document which functions to extract and how they map to strategies.

    - id: 1.2
      name: "Refactor and verify tests pass"
      type: simple
      completion_criteria: |
        1. Strategy pattern implemented per refactor_plan.md
        2. All tests pass: pytest tests/payment/
        3. Changes committed
      initial_hint: |
        Read refactor_plan.md for the approach.
        After each significant change, run pytest tests/payment/ to verify.
        If tests break, fix immediately before proceeding.
```

### Pattern 5: Feature with new tests

When implementing a new feature that requires new tests, keep implementation and test writing in the same subtask — the AI writes better tests when it just wrote the code, and better code when it knows it needs to write tests for it.

```yaml
- id: 1
  name: "Add CSV export endpoint with tests"
  type: nested
  completion_criteria: |
    1. GET /api/export returns valid CSV
    2. All new and existing tests pass: pytest tests/
  subtasks:
    - id: 1.1
      name: "Analyze existing API patterns and plan implementation"
      type: simple
      completion_criteria: |
        1. Implementation approach documented in implementation_plan.md
        2. Test cases listed (happy path, edge cases, error cases)
      initial_hint: |
        Key files: src/routes/api.py, tests/test_api.py
        Document: what endpoint to add, request/response format,
        error handling, and what test cases to write.

    - id: 1.2
      name: "Implement feature, write tests, and ensure build passes"
      type: simple
      completion_criteria: |
        1. Endpoint implemented per implementation_plan.md
        2. Tests written covering all planned test cases
        3. pytest tests/ exits with code 0
        4. Changes committed
      initial_hint: |
        Read implementation_plan.md for the approach.
        Write the implementation and tests together.
        Run the full test suite before committing.
```

---

## Anti-Patterns

| Anti-pattern | Problem | Better |
|--------------|---------|--------|
| Putting all bugs in one `simple` task | AI gets overwhelmed, fixes some but not others, or takes shortcuts | Use `nested` with per-bug subtasks |
| Separate "implement" and "build" into different subtasks | Build failure triggers expensive failure analysis instead of immediate fix | Keep "implement + build" together |
| No final validation subtask | Parent can't tell if everything actually works | Add a `max_attempts: 1` test-runner subtask at the end |
| `completion_criteria` says "code is clean" | AI will always claim success | Use verifiable criteria: "linter passes", "tests pass", "builds without warnings" |
