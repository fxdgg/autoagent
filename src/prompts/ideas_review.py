"""
Prompt builders for task-decomposition review and revision.

Corresponds to ``IdeasWatcher._review_tasks()`` and the revision block
inside ``IdeasWatcher._human_review_loop()`` in ideas_watcher.py.
"""

from util.truncation_limits import limits
from prompts.shared import (
    load_task_design_guide,
    load_adversarial_review_guide,
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
    """Build the prompt that asks a reviewer AI to evaluate generated tasks.

    Each review round uses a fresh session, so there is no need to include
    feedback from a previous reviewer round.

    Args:
        idea_content: Raw idea text.
        temp_tasks_path: File path where corrected YAML should be written.
        next_id: Starting task ID for this batch (used for ID validation context).
        existing_todos_yaml: Serialized YAML of existing todos (read-only context).
        mode: Execution mode — ``"linear"`` or ``"ai"``.
    """
    task_design_guide = load_task_design_guide(mode)

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
        description_extra = (
            '    Additionally: Root-level `description` must be present, meaningful,\n'
            '    and cover goal/architecture/key paths/commands/constraints as applicable.\n'
            '    Missing = review failure. See §3.'
        )
    else:
        description_extra = (
            f'    Additionally: `description@{next_id}` is optional (which is used to override the existing `description`). If present, it must\n'
            f'    be meaningful and cover goal/architecture/key paths/commands/constraints.\n'
            f'    Root-level `description` must NOT be included (it belongs to the first batch). See §3.'
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
    Evaluate the generated tasks against **every rule in §1 (Rules)** of the <task_design_guide>.
    Check Schema Rules, Design Rules, and Anti-Hack Rules one by one.
    New top-level task IDs must start from {next_id}.

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
    Remember to validate against every rule in §1 (Rules) of the task design guide
    from the initial review, including Schema Rules, Design Rules, and Anti-Hack Rules.

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
) -> str:
    """Build the prompt for an adversarial (red-team) review of generated tasks.

    The adversarial reviewer looks for loopholes, ambiguities, and destructive
    potential — things a careless or malicious agent could exploit without
    technically violating any stated constraint.

    Unlike the positive review prompt, this does NOT include the full task
    design guide.  Instead it loads the mode-specific adversarial review guide
    that focuses on attack patterns and exploitability.

    Args:
        idea_content: Raw idea text.
        temp_tasks_path: File path where the YAML under review is saved.
        next_id: Starting task ID for this batch.
        mode: Execution mode — ``"linear"`` or ``"ai"``.
    """
    adversarial_guide = load_adversarial_review_guide(mode)

    role_line = ROLE_ADVERSARIAL_REVIEWER

    # Truncate idea content if necessary
    if len(idea_content) > limits.get('max'):
        idea_display = idea_content[:limits.get('max')] + '\n\n(idea text truncated)'
    else:
        idea_display = idea_content

    return f"""{role_line}

<original_idea>
{indent_block(idea_display, I4)}
</original_idea>

The generated tasks have been saved to the following file:
    {temp_tasks_path}

<adversarial_review_guide>
{indent_block(adversarial_guide, I4)}
</adversarial_review_guide>

<instructions>
    If the tasks are robust against all adversarial concerns in the guide, respond with EXACTLY:
    ✅ completed

    If you find loopholes or weaknesses, do NOT modify the YAML file.
    Instead, report structured findings that preserve your exploit reasoning.
    For each finding include:
    - severity: Critical | High | Medium | Low
    - location: task/subtask id and field name
    - vulnerable_text: the exact weak text or a concise description
    - exploit_path: how a careless or malicious agent could exploit it
    - impact: what bad outcome this permits
    - minimal_patch_intent: the smallest schema-safe hardening needed
    - do_not_change: task ids, task types, hierarchy, ordering, and unrelated scope unless explicitly necessary

    End your response with EXACTLY:
    ❌ not completed
</instructions>
"""


def build_adversarial_worker_prompt(
    temp_tasks_path: str,
    adversarial_feedback: str,
    next_id: int = 1,
    mode: str = "linear",
) -> str:
    """Build a prompt for revising tasks from adversarial findings.

    The adversarial worker receives the current YAML, the full task design
    guide, and the full red-team feedback, then writes a complete revised,
    schema-preserving YAML file.

    Args:
        temp_tasks_path: File path where revised YAML should be written.
        adversarial_feedback: Full feedback from the adversarial reviewer.
        next_id: Starting task ID for this batch (for description field guidance).
        mode: Execution mode — ``"linear"`` or ``"ai"``.
    """
    task_design_guide = load_task_design_guide(mode)
    role_line = ROLE_ADVERSARIAL_WORKER

    feedback_display = adversarial_feedback[:limits.get('max')]
    if len(adversarial_feedback) > limits.get('max'):
        feedback_display += '\n\n(feedback truncated)'

    if next_id == 1:
        desc_guidance = "a `description` string and a `tasks` list"
    else:
        desc_guidance = f"a `tasks` list (and optionally a `description@{next_id}` string)"

    return f"""{role_line}

The current tasks are saved in the following file:
    {temp_tasks_path}

<task_design_guide>
{indent_block(task_design_guide, I4)}
</task_design_guide>

<adversarial_feedback>
{indent_block(feedback_display, I4)}
</adversarial_feedback>

<instructions>
    Revise the task decomposition to fully address every adversarial finding above, 
    while keeping the result compliant with every rule in §1 (Rules) of the <task_design_guide>.

    Write ONLY the complete revised valid YAML (a dictionary containing {desc_guidance}) into the following file:
        {temp_tasks_path}

    Do NOT include markdown code fences or any extra text in the file.
</instructions>
"""
