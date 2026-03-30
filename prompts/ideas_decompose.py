"""
Prompt builder for idea-to-task decomposition.

Corresponds to ``IdeasWatcher._decompose_idea_to_tasks()``
in ideas_watcher.py.
"""

from truncation_limits import limits


def build_ideas_decompose_prompt(
    idea_content: str,
    next_id: int,
    temp_tasks_path: str,
) -> str:
    """Build the prompt that asks AI to decompose an idea into TODO tasks.

    Args:
        idea_content: Raw idea text from ``ideas.md``.
        next_id: The starting integer ID for new top-level tasks.
        temp_tasks_path: Path where the AI should write the YAML output.
    """
    return f"""You are a task planner. Your job is to decompose a given idea into concrete, actionable
TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

## Idea

{idea_content[:limits.get('idea_content')] + chr(10) + chr(10) + '(idea text truncated)' if len(idea_content) > limits.get('idea_content') else idea_content}

## Task Types

There are 6 task types. Choose the most appropriate one for each task:

1. **simple** \u2014 A single-step task the AI agent completes autonomously (code changes, running
   commands, analysis, etc.). Can be a top-level task or a subtask.
2. **nested** \u2014 A multi-step task containing ordered subtasks. After all subtasks finish, the
   AI evaluates whether the overall completion criteria are met. Top-level only.
3. **looping** \u2014 An iterative task that repeats all its subtasks for a fixed number of cycles
   (e.g., profile \u2192 optimize \u2192 benchmark \u2192 commit). No completion evaluation between cycles.
   Top-level only.
4. **long_running** \u2014 A task that runs in the background via nohup to avoid timeouts (e.g.,
   model training, large data processing). Subtask only (inside nested or looping).
5. **simple_once** \u2014 Same as simple, but executes only once within a nested/looping task.
   Once completed, it is never re-executed even if the parent task retries from an earlier
   subtask or a new loop iteration starts. Subtask only.
6. **long_running_once** \u2014 Same as long_running, but executes only once. Once completed,
   it is never re-executed. Subtask only.

**Hierarchy rules:**
- Top-level tasks can be: simple, nested, or looping.
- Subtasks (inside nested/looping) can be: simple, long_running, simple_once, or long_running_once.

**When to use which:**
- If the idea can be done in one step \u2192 use a single **simple** task.
- If the idea requires multiple ordered steps and the AI should evaluate overall success
  after all steps \u2192 use **nested**.
- If the idea involves repeating an optimize-test cycle N times \u2192 use **looping** with
  repeat_count.
- If a subtask runs a long-running process (training, heavy computation) \u2192 use **long_running**.
- If a subtask should only run once and not be repeated on retries or new loop iterations
  (e.g., one-time setup, data download, environment preparation) \u2192 use **simple_once** or
  **long_running_once**.

## Task Schema

Common fields (all types):
- id: integer for top-level tasks (starting from {next_id}), dot notation for subtasks (e.g., {next_id}.1)
- name: string \u2014 concise task name
- type: "simple" | "nested" | "looping" | "long_running" | "simple_once" | "long_running_once"
- completion_criteria: string \u2014 clear, specific, and measurable

Type-specific fields:
- simple / simple_once: initial_hint (optional \u2014 helpful context for the AI executor)
- nested: subtasks (list), max_attempts (optional, default 20)
- looping: subtasks (list), repeat_count (required, positive integer), max_attempts_per_loop (optional, default 20)
- long_running / long_running_once: command (optional), initial_hint (optional)

Optional field (all types):
- model: "default" | "simple" (optional, defaults to "default")
  Use "simple" for straightforward tasks that don't require complex reasoning
  (e.g., running a command, simple file edits, formatting).
  Use "default" (or omit) for tasks requiring deeper analysis or multi-step reasoning.

## Constraints

1. Do NOT over-decompose. If the idea is simple, a single "simple" task is perfectly fine.
   Prefer fewer, well-scoped tasks over many trivial ones.
2. Do NOT write vague completion_criteria. Each criterion must be objectively verifiable.
   \u2705 Good: "All unit tests pass with 0 failures"
   \u2705 Good: "Response time < 200ms on the /api/users endpoint"
   \u274c Bad: "Code is optimized"
   \u274c Bad: "Performance is improved"
3. Do NOT use "long_running" or "simple" as a top-level task type when the idea clearly
   requires multiple coordinated steps \u2014 use "nested" or "looping" instead.
4. Do NOT use "nested" or "looping" as subtask types.
5. Use "simple_once" or "long_running_once" ONLY for subtasks that genuinely need to run
   exactly once (e.g., one-time setup, data download). Do NOT overuse them.

## Output Format

Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
The file content must be a YAML list of task objects. Below are examples covering all task types:

### simple (top-level)

- id: {next_id}
  name: "Refactor logging module"
  type: simple
  model: simple
  completion_criteria: |
    1. All log calls use the new structured format.
    2. No references to the old logging helper remain.
  initial_hint: |
    The old helper is in utils/legacy_logger.py.

### nested (with simple and long_running subtasks)

- id: {next_id}
  name: "Add user authentication"
  type: nested
  max_attempts: 10
  completion_criteria: |
    1. Login and registration endpoints return correct status codes.
    2. All auth-related unit tests pass.
  subtasks:
    - id: {next_id}.1
      name: "Implement auth endpoints"
      type: simple
      completion_criteria: |
        POST /login and POST /register are functional.
    - id: {next_id}.2
      name: "Train fraud-detection model"
      type: long_running
      completion_criteria: |
        Model checkpoint saved to checkpoints/ with accuracy > 0.95.

### looping

- id: {next_id}
  name: "Iterative kernel optimization"
  type: looping
  repeat_count: 5
  max_attempts_per_loop: 10
  completion_criteria: |
    Kernel execution time reduced by at least 30%.
  subtasks:
    - id: {next_id}.1
      name: "Profile and optimize"
      type: simple
      completion_criteria: |
        At least one optimization applied and benchmarked.
    - id: {next_id}.2
      name: "Run full benchmark suite"
      type: long_running
      completion_criteria: |
        Benchmark results saved to results/bench_latest.json.
"""
