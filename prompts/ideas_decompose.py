"""
Prompt builder for idea-to-task decomposition.

Corresponds to ``IdeasWatcher._decompose_idea_to_tasks()``
in ideas_watcher.py.
"""

from truncation_limits import limits
from prompts.shared import load_task_design_guide


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
    task_design_guide = load_task_design_guide()

    return f"""You are a task planner. Your job is to decompose a given idea into concrete, actionable
TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

<idea>
{idea_content[:limits.get('max')] + chr(10) + chr(10) + '(idea text truncated)' if len(idea_content) > limits.get('max') else idea_content}
</idea>

The following guide describes how AutoAgent executes tasks at runtime. Understanding
this is essential for designing effective tasks. Read it carefully before generating
your task decomposition.

<task_design_guide>
{task_design_guide}
</task_design_guide>

<output_instructions>
- Task IDs start from **{next_id}** (integer for top-level, dot notation for subtasks,
  e.g., {next_id}.1, {next_id}.2).
- Write ONLY valid YAML into the following file:
    {temp_tasks_path}
- Do NOT include markdown code fences or any extra text in the file.
- The file content must be a YAML dictionary containing a `description` string and a `tasks` list.

### Output Examples

Below are minimal examples covering the main task types:

#### simple (top-level)

description: "Project description goes here"
tasks:
  - id: {next_id}
    name: "Refactor logging module"
    type: simple
    model: lite
    completion_criteria: |
      1. All log calls use the new structured format.
      2. No references to the old logging helper remain.
    initial_hint: |
      The old helper is in utils/legacy_logger.py.

#### nested (with simple and long_running subtasks)

description: "Project description goes here"
tasks:
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

#### looping

description: "Project description goes here"
tasks:
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
</output_instructions>
"""
