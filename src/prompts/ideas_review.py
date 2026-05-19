"""
Prompt builders for task-decomposition review and revision.

Corresponds to ``IdeasWatcher._review_tasks()`` and the revision block
inside ``IdeasWatcher._human_review_loop()`` in ideas_watcher.py.
"""

from util.truncation_limits import limits
from prompts.shared import (
    get_task_design_guide_path,
    get_adversarial_review_guide_path,
    indent_block,
    ROLE_TASK_REVIEWER,
    ROLE_ADVERSARIAL_REVIEWER,
    ROLE_ADVERSARIAL_WORKER,
)

# Indentation constants (same as other prompt builders)
I4 = 4


def build_ideas_review_prompt(
    idea_content: str,
    temp_tasks_path: str,
    next_id: int = 1,
    existing_todos_yaml: str = "",
    mode: str = "linear",
) -> str:
    """Build the prompt that asks a reviewer AI to evaluate generated tasks."""
    task_design_guide_path = get_task_design_guide_path(mode)

    # Reviewer role is fixed: do not use the user-configured
    # system_prompt_prefix here, because the reviewer must be independent.
    role_line = ROLE_TASK_REVIEWER

    # Truncate idea content if necessary.
    if len(idea_content) > limits.get('max'):
        idea_display = idea_content[:limits.get('max')] + '\n\n(idea text truncated)'
    else:
        idea_display = idea_content

    if next_id == 1:
        description_extra = (
            '    Additionally: Root-level `description` must be present, meaningful,\n'
            '    and cover goal/architecture/key paths/commands/constraints as applicable.\n'
            '    Missing = review failure.'
        )
    else:
        description_extra = (
            f'    Additionally: `description@{next_id}` is optional, used to override the existing `description` '
            f'for newly generated tasks.\n'
            f'    Existing `description` and `description@N` should not be modified.'
        )

    existing_todos_block = ""
    if existing_todos_yaml:
        truncated = existing_todos_yaml[:limits.get('max')]
        if len(existing_todos_yaml) > limits.get('max'):
            truncated += '\n\n(existing todos truncated)'
        existing_todos_block = f"""
The following are the existing tasks already defined in the project. They are provided
for reference only - the new tasks under review must not conflict with or duplicate them.

<existing_todos>
{indent_block(truncated, I4)}
</existing_todos>
"""

    return f"""{role_line}

<original_idea>
{indent_block(idea_display, I4)}
</original_idea>

The generated tasks have been saved to the following file:
    {temp_tasks_path}

<task_design_guide>
    Read this guide before reviewing `todos.yaml`:

    {task_design_guide_path}
</task_design_guide>
{existing_todos_block}
<id_context>
    New top-level task IDs must start from {next_id}.
    Subtask IDs use dot notation: {next_id}.1, {next_id}.2, etc.
    IDs below {next_id} are already in use by existing tasks.
</id_context>

<review_criteria>
    - Evaluate the generated tasks against the **Checklist** section of <task_design_guide>.
    - New top-level task IDs must start from {next_id}.

{description_extra}
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
    """Build a revision prompt sent to the reviewer AI after feedback."""
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

    if next_id == 1:
        desc_guidance = "a `description` string and a `tasks` list"
    else:
        desc_guidance = f"a `tasks` list (and optionally a `description@{next_id}` string)"

    parts.append(f"""<instructions>
    Please revise the task decomposition based on the information above.
    Remember to validate against every **Checklist** of the task design guide.

    Write ONLY valid YAML (a dictionary containing {desc_guidance}) into the following file:
        {temp_tasks_path}

    Do NOT include markdown code fences or any extra text in the file.
</instructions>""")

    return '\n\n'.join(parts) + '\n'


def build_adversarial_review_prompt(
    idea_content: str,
    temp_tasks_path: str,
    next_id: int = 1,
    mode: str = "linear",
    adversarial_feedback_path: str = "",
) -> str:
    """Build the prompt for an adversarial review of generated tasks."""
    adversarial_guide_path = get_adversarial_review_guide_path(mode)

    role_line = ROLE_ADVERSARIAL_REVIEWER

    if len(idea_content) > limits.get('max'):
        idea_display = idea_content[:limits.get('max')] + '\n\n(idea text truncated)'
    else:
        idea_display = idea_content

    feedback_path = adversarial_feedback_path or ".adversarial_review.md"

    return f"""{role_line}

<original_idea>
{indent_block(idea_display, I4)}
</original_idea>

The generated tasks have been saved to the following file:
    {temp_tasks_path}

<adversarial_review_guide>
    Read this guide before reviewing `todos.yaml`:

    {adversarial_guide_path}
</adversarial_review_guide>

<instructions>
    If the tasks are robust against all adversarial concerns in the guide, respond with EXACTLY:
    ✅ completed

    If you find loopholes or weaknesses, do NOT modify the YAML file.
    Instead, report structured findings that preserve your exploit reasoning into {feedback_path}.
    For each finding include:
    - severity: Critical | High | Medium | Low
    - location: task/subtask id and field name
    - vulnerable_text: the exact weak text or a concise description
    - exploit_path: how a careless or malicious agent could exploit it
    - impact: what bad outcome this permits
    - minimal_patch_intent: the smallest schema-safe hardening needed

    Then end your response with EXACTLY:
    ❌ not completed
</instructions>
"""


def build_adversarial_worker_prompt(
    temp_tasks_path: str,
    adversarial_feedback_path: str,
    next_id: int = 1,
    mode: str = "linear",
) -> str:
    """Build a prompt for revising tasks from adversarial findings."""
    task_design_guide_path = get_task_design_guide_path(mode)
    role_line = ROLE_ADVERSARIAL_WORKER

    if next_id == 1:
        desc_guidance = "a `description` string and a `tasks` list"
    else:
        desc_guidance = f"a `tasks` list (and optionally a `description@{next_id}` string)"

    return f"""{role_line}

The current tasks are saved in the following file:
    {temp_tasks_path}

<task_design_guide>
    Read this guide before revising `todos.yaml`:

    {task_design_guide_path}
</task_design_guide>

<adversarial_feedback>
    Read this file for adversarial reviewer's feedback:

    {adversarial_feedback_path}
</adversarial_feedback>

<instructions>
    Revise the task decomposition to fully address every adversarial finding above,
    while keeping the result compliant with every **Checklist** of the <task_design_guide>.

    Write ONLY the complete revised valid YAML (a dictionary containing {desc_guidance}) into the following file:
        {temp_tasks_path}

    Do NOT include markdown code fences or any extra text in the file.
</instructions>
"""
