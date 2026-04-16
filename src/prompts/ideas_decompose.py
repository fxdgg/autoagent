"""
Prompt builder for idea-to-task decomposition.

Corresponds to ``IdeasWatcher._decompose_idea_to_tasks()``
in ideas_watcher.py.
"""

from util.truncation_limits import limits
from prompts.shared import load_task_design_guide, indent_block

# Indentation constants (same as other prompt builders)
I4 = 4


def build_ideas_decompose_prompt(
    idea_content: str,
    next_id: int,
    temp_tasks_path: str,
    existing_todos_yaml: str = "",
) -> str:
    """Build the prompt that asks AI to decompose an idea into TODO tasks.

    Args:
        idea_content: Raw idea text from ``ideas.md``.
        next_id: The starting integer ID for new top-level tasks.
        temp_tasks_path: Path where the AI should write the YAML output.
        existing_todos_yaml: Serialized YAML of existing todos (read-only context).
    """
    task_design_guide = load_task_design_guide()

    # Truncate idea content if necessary
    if len(idea_content) > limits.get('max'):
        idea_display = idea_content[:limits.get('max')] + '\n\n(idea text truncated)'
    else:
        idea_display = idea_content

    # Build the existing-todos context block (only when there are existing tasks)
    existing_todos_block = ""
    if existing_todos_yaml:
        truncated = existing_todos_yaml[:limits.get('max')]
        if len(existing_todos_yaml) > limits.get('max'):
            truncated += '\n\n(existing todos truncated)'
        existing_todos_block = f"""
The following are the existing tasks already defined in the project. They are provided
for reference only — do NOT modify, duplicate, or regenerate them.
Ensure new tasks do not conflict with or duplicate existing tasks.

<existing_todos>
{indent_block(truncated, I4)}
</existing_todos>
"""

    # Description instruction varies by whether this is the first batch
    if next_id == 1:
        description_instruction = (
            "- The file content must be a YAML dictionary containing a `description` string and a `tasks` list."
        )
    else:
        description_instruction = (
            f"- The file content must be a YAML dictionary containing a `tasks` list.\n"
            f"    - You may optionally include a `description@{next_id}` field (string) to describe the purpose of this new batch of tasks.\n"
            f"    - Do NOT include a root-level `description` field — the existing one will be preserved."
        )

    return f"""You are a task planner. Your job is to decompose a given idea into concrete, actionable
TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

<idea>
{indent_block(idea_display, I4)}
</idea>

Understanding this following guide is essential for designing effective tasks. Read it carefully before generating your task decomposition.

<task_design_guide>
{indent_block(task_design_guide, I4)}
</task_design_guide>
{existing_todos_block}
<instructions>
    - Task IDs start from **{next_id}** (integer for top-level, dot notation for subtasks, e.g., {next_id}.1, {next_id}.2).
    - Write ONLY valid YAML into the following file:
        {temp_tasks_path}
    - Do NOT include markdown code fences or any extra text in the file.
    {description_instruction}
</instructions>
"""
