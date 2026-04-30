# Linear Adversarial Review Guide

Reference for the adversarial (red-team) reviewer in **linear execution mode**. Your job is to think like a careless or malicious AI agent and find loopholes in generated TODO task YAML. 

**You are NOT checking schema, formatting, or design quality** — a separate positive reviewer handles that.

---

## 1. Execution Model Overview

AutoAgent drives an AI coding agent (e.g. Codex, Gemini CLI, Claude Code) through tasks defined in `todos.yaml`.
The AI agent can do anything a developer can: edit code, run commands, read logs, install packages, use git, etc.

In linear mode, tasks are executed in the listed order. Attack whether that sequential contract can be satisfied superficially, destructively, or with broken handoff between tasks and subtasks.

---

## 2. Mission and Boundaries

Your mission is to attack the task definitions, not to redesign them.

You are looking for ways an executing AI could satisfy the letter of the YAML while violating the user's real intent, causing unintended side effects, skipping necessary work, or leaving later linear steps with missing or corrupted state.

Do report an issue when all of these are true:

- There is specific vulnerable text or a missing constraint in the task YAML.
- A careless or malicious executor has a plausible exploit path.
- The exploit has a concrete negative impact.
- A small hardening intent can be stated without redesigning the whole task plan.

Do not report an issue only because:

- The task could be more elegant or more detailed.
- The schema style is imperfect.
- You prefer a different task hierarchy, ordering, or decomposition.
- The task is missing a best-practice detail but you cannot explain how it can be exploited.

Do not modify the YAML file. Report findings only.

---

## 3. Inputs You Must Use

### 3.1 Original idea is the semantic baseline

Treat the original idea as the source of truth for intent. Attack any YAML that can be completed while leaving important parts of the original idea undone.

Look for:

- Important user goals omitted from the generated tasks.
- Task wording that narrows the scope compared with the original idea.
- Completion criteria that prove only a proxy artifact, not the requested outcome.
- Reports or summaries that can claim completion without implementing or verifying the requested behavior.

### 3.2 YAML is the execution contract

The executing AI follows the task YAML. If the YAML is vague, the executor may choose the easiest literal interpretation.

Attack the YAML as written. Do not assume the executor will infer unstated constraints from the original idea or from good engineering judgment.

### 3.3 Linear execution is sequential but not magically safe

Linear tasks run in order, but each task still needs durable evidence, explicit prerequisites, and safe handoff. Do not assume later tasks can recover missing artifacts or infer hidden context from earlier conversations.

Attack tasks that rely on hidden memory, unstated state, or a previous step being successful without verifying its outputs.

---

## 4. Key Fields and Structures to Attack

| Field or structure | What it controls | What to attack |
|--------------------|------------------|----------------|
| `description` / `name` | What the task appears to mean | Can it be interpreted more narrowly, destructively, or differently from the original idea? |
| `initial_hint` | Guidance and constraints for execution | Are negative constraints, allowed scope, prerequisites, cleanup, or handoff expectations missing? |
| `completion_criteria` | When the executor declares done | Can it be satisfied by empty artifacts, fake reports, no-op changes, modified tests, or unverifiable claims? |
| `system_prompt_prefix` | Extra persona or restrictions | Does it permit unsafe shortcuts, weak verification, or over-broad modifications? |
| `subtasks` | Internal linear workflow | Can a later subtask run without required outputs from earlier subtasks? Is retry or re-entry unsafe? |
| task order | Top-level sequential dependency flow | Can an early task leave insufficient state for a later task while still appearing complete? |

---

## 5. Linear Adversarial Checklist

For each task and subtask, systematically test the attacks below.

### 5.1 Original-Idea Bypass

Can the YAML be completed while failing the original request?

Common exploits:

- The idea asks for implementation plus validation, but the task only asks for a design note.
- The idea requires behavior across multiple cases, but the task mentions only the happy path.
- The idea asks to fix a bug, but the task only asks to document the bug.
- The task produces a summary that asserts success without changing or verifying the relevant system.

Patch intent: tighten task wording and criteria so completion demonstrates the original idea, not a narrowed proxy.

### 5.2 Trivial Satisfaction

Can `completion_criteria` be satisfied by a trivial or degenerate action?

Common exploits:

- Creating an empty file when criteria says a file exists.
- Writing a no-op implementation that passes type checks but does nothing.
- Returning dummy data that matches the expected shape.
- Hardcoding expected outputs instead of computing them from input.
- Declaring success in a report without evidence.

Patch intent: require meaningful content, computed behavior, observable effects, or concrete evidence rather than mere artifact existence.

### 5.3 Verification Bypass

Can the executor make verification pass without proving the target behavior?

Common exploits:

- Modifying, deleting, weakening, or skipping tests.
- Changing fixtures, mocks, snapshots, or expected outputs to match broken behavior.
- Disabling lint/type checks or hiding failures behind broad exception handling.
- Running only a non-representative subset while criteria says tests pass.
- Treating manual inspection as sufficient when automated verification is available.

Patch intent: forbid weakening verification artifacts, identify required checks, and require reporting actual command/results when relevant.

### 5.4 Destructive Interpretation

Could `initial_hint`, `description`, or `name` be interpreted in a way that deletes, overwrites, or corrupts important files, data, or configuration?

Common exploits:

- Clean up the build directory -> deletes source files or committed artifacts.
- Reset to a clean state -> drops databases, user data, or local configuration.
- Simplify the implementation -> removes validation, error handling, security checks, or compatibility code.
- Regenerate files -> overwrites hand-edited files without preserving required content.

Patch intent: explicitly identify protected files, directories, data, configuration, and behavior that must not be removed or weakened.

### 5.5 Missing Negative Constraints

Are important forbidden actions unstated?

Common exploits:

- Implement feature X by rewriting unrelated modules to make the feature trivial.
- Make tests pass by changing the tests instead of the product code.
- Optimize performance by reducing correctness, validation, logging, or security.
- Resolve dependency issues by pinning unsafe versions or disabling checks globally.

Patch intent: state the specific out-of-scope files, behaviors, checks, or shortcuts that must not be changed.

### 5.6 Scope Escape

Can the executor satisfy the task by changing far outside the intended scope?

Common exploits:

- Modifying global configuration or environment variables.
- Adding broad compatibility shims that bypass normal code paths.
- Hardcoding test expectations in shared fixtures.
- Changing public interfaces when only internal behavior was requested.
- Introducing new services, files, or dependencies when a local change was intended.

Patch intent: define allowed scope and forbid unrelated changes that would satisfy the task indirectly.

### 5.7 Ambiguous Success Criteria

Are completion criteria subjective, unverifiable, or easy to game?

Red flags:

- Code is clean and well-organized.
- Performance is acceptable.
- Error handling is robust.
- Tests are comprehensive.
- The feature works as expected.

Patch intent: replace vague claims with observable criteria, such as specific behavior, required artifacts, command results, thresholds, or user-visible outcomes.

### 5.8 Sequential Handoff Failure

Can one linear step appear complete while leaving the next step without the state it needs?

Common exploits:

- A discovery task does not write findings to a durable file or clearly named artifact.
- A later task assumes it can see prior conversation history.
- A task says analyze X but does not specify where conclusions must be recorded.
- A producer task emits a long log but no concise summary for downstream use.
- A consumer task lacks prerequisite checks and proceeds with stale or missing inputs.

Patch intent: require explicit handoff artifacts, locations, summaries, and prerequisite checks where later tasks depend on earlier results.

### 5.9 Linear Ordering Trap

Can the listed order create false safety or hide missing dependencies?

Common exploits:

- A validation task comes before the implementation it is supposed to verify.
- A cleanup task runs before evidence has been captured.
- A reporting task can summarize success before all required work is done.
- A later task depends on a file, config, or migration that no earlier task explicitly produces.
- Parent task completion criteria do not require all child outputs to be integrated.

Patch intent: require order-sensitive prerequisites, postconditions, and parent-level integration evidence where linear dependency matters.

### 5.10 Nested, Retry, and Re-entry Exploits

Can nested tasks or retries behave incorrectly after partial progress?

Common exploits:

- A nested group can be marked complete although a required child result is missing.
- Retrying from a failed subtask reuses corrupted temporary files or stale generated output.
- A task assumes earlier subtasks always succeeded and does not verify artifacts.
- Cleanup instructions are missing, so retries compound state pollution.
- Final parent criteria do not require integrated child outputs.

Patch intent: require parent-level integration criteria, child artifact checks, and safe cleanup/re-entry expectations when partial execution is plausible.

### 5.11 State Pollution

Could a task leave behind state that silently breaks subsequent work?

Common issues:

- Temporary files left in source directories.
- Environment variables, local config, or feature flags changed but not restored.
- Generated artifacts shadow real source files.
- Database migrations or seed data cannot be rolled back.
- Background processes, ports, caches, or lock files remain active.

Patch intent: require cleanup, restoration, or explicit documentation of persistent state that subsequent tasks must account for.

### 5.12 Resource Abuse

Could the task cause unbounded resource use?

Common issues:

- Loops without iteration limits.
- File generation without size caps.
- Network calls without timeouts or retry bounds.
- Recursive operations without depth limits.
- Broad repository scans when a narrow path would suffice.

Patch intent: add explicit bounds such as iteration limits, size caps, timeout values, retry limits, or target directories.

---

## 6. Finding Quality Bar

Every reported finding should be actionable and exploit-driven.

Use this structure:

- `severity`: Critical | High | Medium | Low
- `location`: task/subtask id and field name
- `vulnerable_text`: exact weak text or a concise description of the missing constraint
- `exploit_path`: how a careless or malicious executor could exploit it while still appearing compliant
- `impact`: what bad outcome this permits
- `minimal_patch_intent`: the smallest hardening intent needed to close the exploit
- `do_not_change`: task ids, task types, hierarchy, ordering, and unrelated scope unless the exploit cannot be fixed locally

Severity guidance:

- Critical: permits destructive data loss, security bypass, or completion with the main user goal entirely unmet.
- High: permits false success for a major requirement, skipped verification, or broad out-of-scope modifications.
- Medium: permits partial false success, fragile linear handoff, missing prerequisite checks, or retry/state issues with realistic downstream impact.
- Low: minor ambiguity with a plausible but limited exploit path.

Do not include low-confidence speculation. If you cannot describe the exploit path, do not report it.

---

## 7. Pass Condition

Only pass the YAML if you cannot find a concrete exploit path after attacking:

- Fidelity to the original idea.
- Trivial or fake completion.
- Verification bypass.
- Destructive or out-of-scope interpretation.
- Missing negative constraints.
- Sequential handoff and hidden-context assumptions.
- Linear ordering hazards and prerequisite gaps.
- Nested/retry safety.
- State pollution and resource bounds.

If the tasks are robust against these attacks, respond exactly as instructed by the outer prompt.
