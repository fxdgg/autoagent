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

<original_idea>
{idea_content[:limits.get('max')] + chr(10) + chr(10) + '(idea text truncated)' if len(idea_content) > limits.get('max') else idea_content}
</original_idea>

The generated tasks have been saved to the following file:
  {temp_tasks_path}

Please read this file to review the tasks.

The following guide serves as the authoritative reference for task types, schema, hierarchy rules, 
and best practices when reviewing the generated tasks.

<task_design_guide>
{task_design_guide}
</task_design_guide>

<review_criteria>
Evaluate the generated tasks against these criteria. Refer to <task_design_guide> for
detailed rules and examples on each point.

1. **YAML & schema**: Well-formed YAML; correct IDs (integers + dot notation); all
   required fields present per type; `*_once` types only as subtasks.
2. **Type selection**: `nested` vs `looping` vs `simple` chosen correctly per §4.1;
   commands > 1 min use `long_running`; `*_once` used sparingly.
3. **Decomposition granularity**: No over-decomposition (merge steps that fail together)
   and no under-decomposition (split logically independent steps). See §4.2.
4. **Root-level `description`**: Present, meaningful, covers goal/architecture/key
   paths/commands/constraints as applicable. Missing = review failure. 
   Order of tasks and description fields doesn't matter. See §3.1.
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
10. **Looping discipline** (if applicable): Doc commits separated from code commits;
    failure pattern tracking; structured keep/discard rules; workspace cleanup. See §6.4.
</review_criteria>

<instructions>
If the tasks pass ALL criteria, respond with EXACTLY:
\u2705 completed

If the tasks need improvement:
DIRECTLY modify the YAML file at:
    {temp_tasks_path}
Do NOT include markdown code fences or any extra text in the file.
After modifying the file, respond with EXACTLY: 
\u274c not completed
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
