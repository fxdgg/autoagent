"""
Prompt builder for subtask failure analysis.

Covers both *nested* and *looping* task types.  Corresponds to
``NestedTaskExecutor._ai_analyze_failure()`` and
``LoopingTaskExecutor._ai_analyze_failure()`` in task_executor.py.
"""

from typing import List, Optional, Tuple

# Role definition for failure analysis prompts
ROLE_FAILURE_ANALYST = (
    "You are a failure analysis expert. Analyze the subtask failure below "
    "and decide the best retry strategy."
)


def build_failure_analysis_prompt(
    task: dict,
    failed_subtask: dict,
    all_subtasks: list,
    error_text: str,
    task_history_text: str,
    prev_decisions_text: str,
    loop_info: Optional[Tuple[int, int]] = None,
    previous_context: str = "",
    failed_subtask_history: str = "",
    previous_subtask_id: str = "",
) -> str:
    """Build the failure-analysis prompt for both *nested* and *looping* tasks.

    Args:
        task: Parent task configuration dict.
        failed_subtask: The subtask that failed.
        all_subtasks: All sibling subtasks (used for available IDs).
        error_text: The failed subtask's AI output (truncated).
        task_history_text: Pre-formatted subtask status block.
        prev_decisions_text: Pre-formatted previous AI decisions block
            (may be empty).
        loop_info: For looping tasks, a tuple of (loop_idx, repeat_count).
            None for nested tasks.
        previous_context: Summary from the previous (successful) subtask,
            providing context about the state of the project before the
            failure occurred.  May be empty.
        failed_subtask_history: Pre-formatted per-attempt history of the
            failed subtask, showing what was tried and why each attempt
            failed.  May be empty.
        previous_subtask_id: ID of the previous (successful) subtask whose
            summary is in *previous_context*.  May be empty.
    """
    failed_id = str(failed_subtask['id'])
    available_ids = [str(s['id']) for s in all_subtasks]

    parts = [ROLE_FAILURE_ANALYST]

    # -- ## Failed Subtask --
    failed_section = f"""<failed_subtask>
Main Task: {task['name']}
Completion Criteria: {task['completion_criteria']}"""

    if loop_info:
        loop_idx, repeat_count = loop_info
        failed_section += f"\nLoop Progress: iteration {loop_idx}/{repeat_count}"

    failed_section += f"""

Failed Subtask:
  ID: {failed_id}
  Name: {failed_subtask['name']}
  Type: {failed_subtask['type']}
  Completion Criteria: {failed_subtask.get('completion_criteria', 'N/A')}
</failed_subtask>"""

    parts.append(failed_section)

    # -- ## Previous Step Context (conditional) --
    if previous_context:
        prev_label = f"Previous Step ({previous_subtask_id}) Context" if previous_subtask_id else "Previous Step Context"
        parts.append(f"<{prev_label.replace(' ', '_').replace('(', '').replace(')', '').lower()}>\n{previous_context}\n</{prev_label.replace(' ', '_').replace('(', '').replace(')', '').lower()}>")

    # -- ## Failed Subtask Output --
    if error_text and error_text != "(no error output)":
        parts.append(f"<failed_subtask_output>\n{error_text}\n</failed_subtask_output>")

    # -- ## Failed Subtask Attempt History (conditional) --
    if failed_subtask_history:
        parts.append(f"<failed_subtask_attempt_history>\n{failed_subtask_history}\n</failed_subtask_attempt_history>")

    # -- ## All Subtasks Status --
    parts.append(f"<all_subtasks_status>\n{task_history_text}\n</all_subtasks_status>")

    # -- ## Previous Failure Analyses (conditional) --
    if prev_decisions_text:
        parts.append(f"<previous_failure_analyses>\n{prev_decisions_text}\n</previous_failure_analyses>")

    # -- ## Instructions --
    parts.append(f"""<instructions>
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
- Available subtask IDs: {available_ids}
</instructions>""")

    return "\n\n".join(parts)

