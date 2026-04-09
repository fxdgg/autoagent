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

Understanding this following guide is essential for designing effective tasks. Read it carefully before generating your task decomposition.

<task_design_guide>
{task_design_guide}
</task_design_guide>

<output_instructions>
- Task IDs start from **{next_id}** (integer for top-level, dot notation for subtasks, e.g., {next_id}.1, {next_id}.2).
- Write ONLY valid YAML into the following file:
    {temp_tasks_path}
- Do NOT include markdown code fences or any extra text in the file.
- The file content must be a YAML dictionary containing a `description` string and a `tasks` list.
</output_instructions>
"""
