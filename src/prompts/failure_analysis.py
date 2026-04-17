"""
Prompt builder for subtask failure analysis.

Covers both *nested* and *looping* task types.  Corresponds to
``NestedTaskExecutor._ai_analyze_failure()`` and
``LoopingTaskExecutor._ai_analyze_failure()`` in task_executor.py.
"""

from typing import List, Optional, Tuple

from prompts.shared import indent_block
from util.truncation_limits import limits

# Role definition for failure analysis prompts
ROLE_FAILURE_ANALYST = (
    "You are a failure analysis expert. Analyze the subtask failure below "
    "and decide the best retry strategy."
)


def _build_workflow_with_status(
    failed_id: str,
    subtasks_with_status: list,
) -> str:
    """Build the workflow section with status annotations.

    Each subtask is shown with its status (COMPLETED / FAILED / pending).
    The failed subtask is marked with ``→``.  Completed subtasks include
    their criteria and summary.

    Args:
        failed_id: ID of the failed subtask.
        subtasks_with_status: List of dicts with keys: subtask_id, name,
            status, completion_criteria, ai_reasoning.
    """
    lines = []
    for st in subtasks_with_status:
        st_id = str(st.get('display_subtask_id', st['subtask_id']))
        name = st['name']
        status = st.get('status', 'pending')

        if st_id == failed_id:
            lines.append(f"→ {st_id}. {name} (FAILED)")
            if st.get('completion_criteria'):
                lines.append(f"        Criteria:")
                lines.append(indent_block(st['completion_criteria'], 12))
        elif status == 'completed':
            lines.append(f"  {st_id}. {name} (COMPLETED)")
            if st.get('completion_criteria'):
                lines.append(f"        Criteria:")
                lines.append(indent_block(st['completion_criteria'], 12))
            if st.get('ai_reasoning'):
                lines.append(f"        Summary:")
                lines.append(indent_block(
                    st['ai_reasoning'][:limits.get('history_summary')], 12
                ))
        else:
            # pending / in_progress — just show name
            lines.append(f"  {st_id}. {name}")

    return "\n".join(lines)


def build_failure_analysis_prompt(
    task: dict,
    failed_subtask: dict,
    all_subtasks: list,
    error_text: str,
    prev_decisions_text: str,
    previous_context: str = "",
    failed_subtask_history: str = "",
    previous_subtask_id: str = "",
    subtasks_with_status: list = None,
) -> str:
    """Build the failure-analysis prompt for both *nested* and *looping* tasks.

    Args:
        task: Parent task configuration dict.
        failed_subtask: The subtask that failed.
        all_subtasks: All sibling subtasks (used for available IDs).
        error_text: The failed subtask's AI output (truncated).
        prev_decisions_text: Pre-formatted previous AI decisions block
            (may be empty).
        previous_context: Summary from the previous (successful) subtask.
        failed_subtask_history: Pre-formatted per-attempt history.
        previous_subtask_id: ID of the previous subtask.
        subtasks_with_status: List of dicts with keys: subtask_id, name,
            status, completion_criteria, ai_reasoning.  When provided,
            a ``<workflow>`` section is built from this list.  When
            ``None``, the workflow section is omitted.
    """
    failed_id = str(failed_subtask.get('_display_id', failed_subtask['id']))
    available_ids = [str(s.get('_display_id', s['id'])) for s in all_subtasks]
    I4 = 4
    I8 = 8

    parts = [ROLE_FAILURE_ANALYST]

    # -- <failed_subtask> --
    fs_inner = []
    fs_inner.append(f"    <task_name>\n{indent_block(task['name'], I8)}\n    </task_name>")
    fs_inner.append(f"    <main_task_completion_criteria>\n{indent_block(task['completion_criteria'], I8)}\n    </main_task_completion_criteria>")

    if subtasks_with_status:
        workflow_text = _build_workflow_with_status(failed_id, subtasks_with_status)
        fs_inner.append(f"    <workflow>\n{indent_block(workflow_text, I8)}\n    </workflow>")

    parts.append("<failed_subtask>\n" + "\n\n".join(fs_inner) + "\n</failed_subtask>")

    # -- <outputs> --
    outputs_inner = []

    if previous_context:
        tag = f"previous_step_context ({previous_subtask_id})" if previous_subtask_id else "previous_step_context"
        outputs_inner.append(f"    <{tag}>\n{indent_block(previous_context, I8)}\n    </{tag.split()[0]}>")

    if error_text and error_text != "(no error output)":
        tag = f"failed_subtask_output ({failed_id})"
        outputs_inner.append(f"    <{tag}>\n{indent_block(error_text, I8)}\n    </{tag.split()[0]}>")

    if failed_subtask_history:
        tag = f"failed_subtask_attempt_history ({failed_id})"
        outputs_inner.append(f"    <{tag}>\n{indent_block(failed_subtask_history, I8)}\n    </{tag.split()[0]}>")

    if outputs_inner:
        parts.append("<outputs>\n" + "\n\n".join(outputs_inner) + "\n</outputs>")

    # -- <previous_failure_analyses> (conditional) --
    if prev_decisions_text:
        parts.append(f"<previous_failure_analyses>\n{indent_block(prev_decisions_text, I4)}\n</previous_failure_analyses>")

    # -- <instructions> --
    instructions = f"""\
⚠️ Do NOT suggest the same fix that was already tried. Try a fundamentally different approach.

Respond with a JSON object:
```json
{{
    "analysis": "Why the failure occurred and why retry from the chosen subtask",
    "retry_from": "<subtask_id>",
    "suggested_fix": "Specific, actionable fix for the retried subtask"
}}
```

- `retry_from`: The failed subtask itself, or an earlier one if the root cause is there.
- `suggested_fix`: Will be shown to the AI executing the retry — be specific.
- Available subtask IDs: {available_ids}"""

    parts.append(f"<instructions>\n{indent_block(instructions, I4)}\n</instructions>")

    return "\n\n".join(parts)
