"""
Prompt builders for task-decomposition review and revision.

Corresponds to ``IdeasWatcher._review_tasks()`` and the revision block
inside ``IdeasWatcher._human_review_loop()`` in ideas_watcher.py.
"""

from truncation_limits import limits
from prompts.shared import (
    load_task_design_guide,
    indent_block,
    ROLE_TASK_REVIEWER,
)

# Indentation constants (same as other prompt builders)
I4 = 4


def build_ideas_review_prompt(
    idea_content: str,
    temp_tasks_path: str,
    next_id: int = 1,
    existing_todos_yaml: str = "",
) -> str:
    """Build the prompt that asks a reviewer AI to evaluate generated tasks.

    Each review round uses a fresh session, so there is no need to include
    feedback from a previous reviewer round.

    Args:
        idea_content: Raw idea text.
        temp_tasks_path: File path where corrected YAML should be written.
        next_id: Starting task ID for this batch (used for ID validation context).
        existing_todos_yaml: Serialized YAML of existing todos (read-only context).
    """
    task_design_guide = load_task_design_guide()

    # Reviewer role is fixed — do NOT use the user-configured
    # system_prompt_prefix here, because the reviewer must be an
    # independent expert, not the same persona as the coding agent.
    role_line = ROLE_TASK_REVIEWER

    # Truncate idea content if necessary
    if len(idea_content) > limits.get('max'):
        idea_display = idea_content[:limits.get('max')] + '\n\n(idea text truncated)'
    else:
        idea_display = idea_content

    # Description criterion varies by batch
    if next_id == 1:
        description_criterion = (
            '    4. **Description field**: Root-level `description` must be present, meaningful,\n'
            '       and cover goal/architecture/key paths/commands/constraints as applicable.\n'
            '       Missing = review failure. See §3.1.'
        )
    else:
        description_criterion = (
            f'    4. **Description field**: `description@{next_id}` is optional. If present, it must\n'
            f'       be meaningful and cover goal/architecture/key paths/commands/constraints.\n'
            f'       Root-level `description` must NOT be included (it belongs to the first batch). See §3.1.'
        )

    # Build the existing-todos context block (only when there are existing tasks)
    existing_todos_block = ""
    if existing_todos_yaml:
        truncated = existing_todos_yaml[:limits.get('max')]
        if len(existing_todos_yaml) > limits.get('max'):
            truncated += '\n\n(existing todos truncated)'
        existing_todos_block = f"""
The following are the existing tasks already defined in the project. They are provided
for reference only — the new tasks under review must not conflict with or duplicate them.

<existing_todos>
{indent_block(truncated, I4)}
</existing_todos>
"""

    return f"""{role_line} Review the following TODO task decomposition
for quality, completeness, and correctness.

<original_idea>
{indent_block(idea_display, I4)}
</original_idea>

The generated tasks have been saved to the following file:
    {temp_tasks_path}

Please read this file to review the tasks.

The following guide serves as the authoritative reference for task types, schema, hierarchy rules,
and best practices when reviewing the generated tasks.

<task_design_guide>
{indent_block(task_design_guide, I4)}
</task_design_guide>
{existing_todos_block}
<id_context>
    New top-level task IDs must start from {next_id}.
    Subtask IDs use dot notation: {next_id}.1, {next_id}.2, etc.
    IDs below {next_id} are already in use by existing tasks.
</id_context>

<review_criteria>
    Evaluate the generated tasks against these criteria. Refer to <task_design_guide> for
    detailed rules and examples on each point.

    1. **YAML & schema**: Well-formed YAML; correct IDs starting from {next_id}
       (integers + dot notation); all required fields present per type; `*_once` types only as subtasks.
    2. **Type selection**: `nested` vs `looping` vs `simple` chosen correctly per §4.1;
       commands > 1 min use `long_running`; `*_once` used sparingly.
    3. **Decomposition granularity**: No over-decomposition (merge steps that fail together)
       and no under-decomposition (split logically independent steps). See §4.2.
{description_criterion}
    5. **`completion_criteria`**: Specific, measurable, AI-verifiable. Top-level criteria
       describe end state; subtask criteria describe step output. No unverifiable or
       process-describing criteria. See §5.1.
    6. **`initial_hint`**: Provides context (paths, commands, constraints), not step-by-step
       playbooks. Subtasks use filesystem for state passing across sessions. See §5.2, §4.3.
    7. **`system_prompt_prefix`**: Used appropriately (persona, restrictions); NOT set on
       top-level `nested`/`looping`. See §5.3.
    8. **`model`**: `"default"` for reasoning, `"lite"` for execution. See §5.5.
    9. **Retry strategy**: `max_attempts: 1` for execution-only subtasks; 2–5 for code-writing
       tasks. Hints mention residual state cleanup when relevant. See §5.4, §6.
    10. **Task-type best practices**: Read the relevant guide listed in §7 for the task type
        (build & ship, testing, iterative optimization, data pipelines, setup, or research) and
        verify the generated tasks follow the recommended patterns and avoid the anti-patterns
        described there.
</review_criteria>

<instructions>
    If the tasks pass ALL criteria, respond with EXACTLY:
    ✅ completed

    If the tasks need improvement:
    DIRECTLY modify the YAML file at:
        {temp_tasks_path}
    Do NOT include markdown code fences or any extra text in the file.
    After modifying the file, respond with EXACTLY:
    ❌ not completed
</instructions>
"""


def build_revision_prompt(
    temp_tasks_path: str,
    human_feedback: str = "",
    next_id: int = 1,
) -> str:
    """Build a revision prompt sent to the reviewer AI after human feedback.

    This prompt is sent to the **same reviewer** whose session context is
    preserved.  It optionally includes:
    - Human text feedback (if the human provided any)

    Args:
        temp_tasks_path: File path where revised YAML should be written.
        human_feedback: Free-form feedback text from the human user (may be empty).
        next_id: Starting task ID for this batch (for description field guidance).
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
{indent_block(fb_display, I4)}
</human_feedback>""")

    # Description field guidance varies by batch
    if next_id == 1:
        desc_guidance = "a `description` string and a `tasks` list"
    else:
        desc_guidance = f"a `tasks` list (and optionally a `description@{next_id}` string)"

    parts.append(f"""<instructions>
    Please revise the task decomposition based on the information above.
    Remember to validate against all review criteria from the initial review
    (schema correctness, type appropriateness, completion criteria quality,
    decomposition granularity, description field, hint quality, retry strategy, etc.).

    Write ONLY valid YAML (a dictionary containing {desc_guidance}) into the following file:
        {temp_tasks_path}

    Do NOT include markdown code fences or any extra text in the file.
</instructions>""")

    return '\n\n'.join(parts) + '\n'
