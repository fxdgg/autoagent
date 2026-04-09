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
    temp_tasks_path: str,
) -> str:
    """Build the prompt that asks a reviewer AI to evaluate generated tasks.

    Each review round uses a fresh session, so there is no need to include
    feedback from a previous reviewer round.

    Args:
        idea_content: Raw idea text.
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

<original_idea>
{idea_content[:limits.get('max')] + chr(10) + chr(10) + '(idea text truncated)' if len(idea_content) > limits.get('max') else idea_content}
</original_idea>

The generated tasks have been saved to the following file:
  {temp_tasks_path}

Please read this file to review the tasks.

The following guide describes how AutoAgent executes tasks at runtime. Use it as
the authoritative reference for task types, schema, hierarchy rules, and best
practices when reviewing the generated tasks.

<task_design_guide>
{task_design_guide}
</task_design_guide>

<review_criteria>
Evaluate the generated tasks against these criteria:

1. **Schema correctness**: Does every task have the required fields for its type?
   (e.g., nested/looping must have subtasks; looping must have repeat_count)
2. **ID consistency**: Are task IDs sequential integers and subtask IDs use correct
   dot notation (e.g., 2.1, 2.2)?
3. **Type appropriateness**: Are task types chosen correctly?
   - Multi-step ideas should use nested/looping, not a single simple task.
   - Iterative optimize-test cycles should use looping, not nested.
   - nested/looping CAN be used as subtask types (multi-level nesting is supported).
4. **Completion criteria quality**: Is every completion_criteria specific, measurable,
   and objectively verifiable by an AI agent?
   \u2705 Good: "All unit tests pass with 0 failures"
   \u274c Bad: "Code is optimized" or "Performance is improved"
5. **Decomposition granularity**: Does the decomposition fully cover the idea without
   over-decomposing into trivial subtasks or leaving gaps?
6. **YAML validity**: Is the YAML structure well-formed and parseable?
7. **Model field**: If present, the model field must be `"default"`, `"lite"`, or a direct
   model name string. Tasks requiring complex reasoning should use `"default"`;
   straightforward tasks can use `"lite"`. The `model` field is valid on ALL task types
   (including `long_running` and `long_running_once`).
8. **Root-level description**: Does the YAML include a meaningful `description` field at the
   root level that explains the project goal, key constraints, and technical context?
   An empty or missing `description` is a review failure.
9. **Hint quality**: When `initial_hint` is present, does it provide actionable context
   (file paths, commands, constraints) without duplicating `completion_criteria` or
   including step-by-step instructions that over-constrain the AI's approach?
10. **Retry strategy**: Are `max_attempts` values appropriate?
   - Execution-only subtasks (build, test, benchmark) should use `max_attempts: 1`.
   - Code-writing / reasoning tasks should allow multiple attempts (2–5).
</review_criteria>

<instructions>
If the tasks pass ALL criteria, respond with EXACTLY:
\u2705 completed

If the tasks need improvement:
1. DIRECTLY modify the YAML file at:
     {temp_tasks_path}
   Write the corrected full task list into that file.
   Do NOT include markdown code fences or any extra text in the file.
2. In your response, briefly list what you changed and why (1-2 sentences per change).
3. After listing your changes, respond with: \u274c not completed
</instructions>
"""


def build_revision_prompt(
    temp_tasks_path: str,
    human_feedback: str = "",
) -> str:
    """Build a revision prompt sent to the reviewer AI after human feedback.

    This prompt is sent to the **same reviewer** whose session context is
    preserved.  It optionally includes:
    - Human text feedback (if the human provided any)

    Args:
        temp_tasks_path: File path where revised YAML should be written.
        human_feedback: Free-form feedback text from the human user (may be empty).
    """
    parts: list[str] = []

    parts.append(f"""The current tasks are saved in the following file:
  {temp_tasks_path}

Please read this file to see the current tasks.""")

    if human_feedback:
        fb_display = human_feedback[:limits.get('max')]
        if len(human_feedback) > limits.get('max'):
            fb_display += '\n\n(feedback truncated)'
        parts.append(f"""<human_feedback>
{fb_display}
</human_feedback>""")

    parts.append(f"""<instructions>
Please revise the task decomposition based on the information above.
Remember to validate against all review criteria from the initial review
(schema correctness, type appropriateness, completion criteria quality,
decomposition granularity, root-level description, hint quality, retry strategy, etc.).

Write ONLY valid YAML (a dictionary containing a `description` string and a `tasks` list) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
</instructions>""")

    return '\n\n'.join(parts) + '\n'
