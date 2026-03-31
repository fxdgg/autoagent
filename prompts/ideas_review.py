"""
Prompt builders for task-decomposition review and revision.

Corresponds to ``IdeasWatcher._review_tasks()`` and the revision block
inside ``IdeasWatcher._human_review_loop()`` in ideas_watcher.py.
"""

from truncation_limits import limits
from prompts.shared import (
    load_task_design_guide,
    ROLE_TASK_REVIEWER,
)


def build_ideas_review_prompt(
    idea_content: str,
    tasks_yaml: str,
    temp_tasks_path: str,
) -> str:
    """Build the prompt that asks a reviewer AI to evaluate generated tasks.

    Each review round uses a fresh session, so there is no need to include
    feedback from a previous reviewer round.

    Args:
        idea_content: Raw idea text.
        tasks_yaml: YAML-formatted task list string.
        temp_tasks_path: File path where corrected YAML should be written.
    """
    task_design_guide = load_task_design_guide()

    # Reviewer role is fixed — do NOT use the user-configured
    # system_prompt_prefix here, because the reviewer must be an
    # independent expert, not the same persona as the coding agent.
    role_line = ROLE_TASK_REVIEWER

    return f"""{role_line} Review the following TODO task decomposition
for quality, completeness, and correctness.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs.

## Original Idea

{idea_content[:limits.get('max')] + chr(10) + chr(10) + '(idea text truncated)' if len(idea_content) > limits.get('max') else idea_content}

## Generated Tasks (YAML)

```yaml
{tasks_yaml[:limits.get('max')] + chr(10) + '# (YAML truncated)' if len(tasks_yaml) > limits.get('max') else tasks_yaml}```

## Task Design Guide

The following guide describes how AutoAgent executes tasks at runtime. Use it as
the authoritative reference for task types, schema, hierarchy rules, and best
practices when reviewing the generated tasks.

<task_design_guide>
{task_design_guide}
</task_design_guide>

## Review Criteria

Evaluate the generated tasks against these criteria:

1. **Schema correctness**: Does every task have the required fields for its type?
   (e.g., nested/looping must have subtasks; looping must have repeat_count)
2. **ID consistency**: Are task IDs sequential integers and subtask IDs use correct
   dot notation (e.g., 2.1, 2.2)?
3. **Type appropriateness**: Are task types chosen correctly?
   - Multi-step ideas should use nested/looping, not a single simple task.
   - Iterative optimize-test cycles should use looping, not nested.
   - long_running is only used as a subtask, never top-level.
   - nested/looping are never used as subtask types.
4. **Completion criteria quality**: Is every completion_criteria specific, measurable,
   and objectively verifiable by an AI agent?
   \u2705 Good: "All unit tests pass with 0 failures"
   \u274c Bad: "Code is optimized" or "Performance is improved"
5. **Decomposition granularity**: Does the decomposition fully cover the idea without
   over-decomposing into trivial subtasks or leaving gaps?
6. **YAML validity**: Is the YAML structure well-formed and parseable?
7. **Model field**: If present, the model field must be either "default" or "simple".
   Tasks requiring complex reasoning should use "default"; straightforward tasks can use "simple".

## Instructions

If the tasks pass ALL criteria, respond with EXACTLY:
\u2705 completed

If the tasks need improvement:
1. Respond with: \u274c not completed
2. Briefly explain what needs to be fixed.
3. Then DIRECTLY modify the YAML file at:
     {temp_tasks_path}
   Write the corrected full task list into that file.
   Do NOT include markdown code fences or any extra text in the file.
"""


def build_revision_prompt(
    temp_tasks_path: str,
    human_feedback: str = "",
    current_tasks_yaml: str = "",
) -> str:
    """Build a revision prompt sent to the reviewer AI after human feedback.

    This prompt is sent to the **same reviewer** whose session context is
    preserved.  It optionally includes:
    - The latest YAML (if the human edited the temp file)
    - Human text feedback (if the human provided any)

    Args:
        temp_tasks_path: File path where revised YAML should be written.
        human_feedback: Free-form feedback text from the human user (may be empty).
        current_tasks_yaml: Updated YAML string if the human edited the file
            (empty string means no file edits).
    """
    parts: list[str] = []

    if current_tasks_yaml:
        yaml_display = current_tasks_yaml[:limits.get('max')]
        if len(current_tasks_yaml) > limits.get('max'):
            yaml_display += '\n# (YAML truncated)'
        parts.append(f"""## Updated Tasks (edited by human)

```yaml
{yaml_display}```""")

    if human_feedback:
        fb_display = human_feedback[:limits.get('max')]
        if len(human_feedback) > limits.get('max'):
            fb_display += '\n\n(feedback truncated)'
        parts.append(f"""## Human Feedback

{fb_display}""")

    parts.append(f"""Please revise the task decomposition based on the information above.
Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.""")

    return '\n\n'.join(parts) + '\n'
