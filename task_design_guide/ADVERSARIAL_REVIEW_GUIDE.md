# Adversarial Review Guide

Reference for the adversarial (red-team) reviewer. Your job is to think like
a careless or malicious AI agent and find loopholes in the task definitions.

**You are NOT checking schema, formatting, or design quality** — a separate
positive reviewer handles that. Focus exclusively on exploitability.

---

## 1. Key Fields to Attack

These are the YAML fields that define what the executing AI will do. Your job
is to find ways a lazy or adversarial agent could satisfy them without doing
real work, or could interpret them destructively.

| Field | What it controls | What to look for |
|-------|-----------------|------------------|
| `completion_criteria` | When the AI declares "done" | Can it be trivially satisfied? Is it measurable? |
| `initial_hint` | Guidance and constraints for the AI | Missing negative constraints? Ambiguous paths? |
| `system_prompt_prefix` | Persona and restrictions | Missing restrictions on verification tasks? |
| `description` / `name` | What the task is about | Could it be interpreted destructively? |
| `max_attempts` | How many retries | Too many retries on a task that could cause damage? |

---

## 2. Adversarial Checklist

For each task and subtask, systematically check:

### 2.1 Trivial Satisfaction
Can the `completion_criteria` be satisfied by a trivial or degenerate action?

**Common hacks:**
- Creating an empty file when criteria says "file exists"
- Writing a no-op implementation that passes type checks but does nothing
- Deleting or modifying the test that was supposed to pass
- Hardcoding expected outputs instead of computing them
- Returning dummy data that matches the expected format

**Fix:** Add negative constraints ("must not be empty", "must not modify test files",
"output must be computed from input, not hardcoded").

### 2.2 Destructive Interpretation
Could the `initial_hint` or task description be interpreted in a way that
deletes, overwrites, or corrupts important files, data, or configurations?

**Common hacks:**
- "Clean up the build directory" → deletes source files
- "Reset to a clean state" → drops database tables
- "Simplify the implementation" → removes critical error handling

**Fix:** Explicitly list files/directories that must NOT be modified or deleted.

### 2.3 Missing Negative Constraints
Are there important things the agent should NOT do that are not explicitly
forbidden?

**Common hacks:**
- "Implement feature X" without saying "do not modify module Y" → agent
  rewrites unrelated modules to make X trivially easy
- "Make tests pass" without saying "do not modify test files" → agent
  weakens the tests
- "Optimize performance" without saying "do not reduce correctness" → agent
  removes validation logic

**Fix:** For every "implement X" task, add explicit "do NOT modify Y" constraints.

### 2.4 Scope Escape
Could the agent satisfy the task by making changes far outside the intended
scope?

**Common hacks:**
- Modifying global configuration files
- Disabling security checks or validation
- Hardcoding test expectations in a shared fixture
- Adding environment variables that bypass normal code paths

**Fix:** Specify which files/directories are in scope. Forbid changes outside
that scope.

### 2.5 Ambiguous Success Criteria
Are there completion criteria that are subjective, unmeasurable, or that could
be gamed by the agent?

**Red flags:**
- "Code is clean and well-organized"
- "Performance is acceptable"
- "Error handling is robust"
- "Tests are comprehensive"

**Fix:** Replace with measurable criteria: "pylint score ≥ 9.0",
"p99 latency < 50ms", "all error paths return proper HTTP status codes",
"line coverage ≥ 80%".

### 2.6 State Pollution
Could executing one task leave behind state that silently breaks subsequent
tasks?

**Common issues:**
- Temp files left in the working directory
- Environment variables set but never unset
- Modified global configs not restored
- Database migrations that can't be rolled back

**Fix:** Add cleanup instructions in `initial_hint`. Mention what state to
restore after the task completes.

### 2.7 Resource Abuse
Could any task lead to unbounded resource consumption without explicit limits?

**Common issues:**
- Loops without iteration limits
- File generation without size caps
- Network requests without timeouts
- Recursive operations without depth limits

**Fix:** Add explicit bounds: "max 1000 iterations", "output file < 10MB",
"timeout after 60 seconds".

---

## 3. Anti-Hack Rules Reference

The positive reviewer already checks these rules. They are listed here so you
know what defenses are already in place and can focus on finding gaps the rules
don't cover.

1. **Negative constraints**: For every "implement X" task, explicitly state what must NOT be modified (test files, configs, unrelated modules).
2. **Verification separation**: Separate "implement" from "verify" into different subtasks. Use `system_prompt_prefix` on verification subtasks to forbid code modification.
3. **Measurable criteria only**: Every `completion_criteria` must be checkable by running a command or reading a file — never subjective ("code is clean", "well-optimized").
4. **Scope boundaries**: When a task modifies code, specify which files/directories are in scope. Forbid changes outside that scope.

---

## 4. What You Can Modify

When you find loopholes, you may tighten the following fields to close them:

- `completion_criteria` — add negative constraints, make criteria more specific
- `initial_hint` — add warnings, forbidden actions, scope boundaries
- `system_prompt_prefix` — add restrictions (e.g., "Do NOT modify test files")
- `description` — clarify intent to prevent destructive interpretation

**Do NOT change:**
- Task structure (IDs, hierarchy, ordering)
- Task types (`simple`, `nested`, `looping`, etc.)
- Task names
- `max_attempts` or `model` settings
