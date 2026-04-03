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
    error_type: str,
    task_history_text: str,
    prev_decisions_text: str,
    loop_info: Optional[Tuple[int, int]] = None,
) -> str:
    """Build the failure-analysis prompt for both *nested* and *looping* tasks.

    Args:
        task: Parent task configuration dict.
        failed_subtask: The subtask that failed.
        all_subtasks: All sibling subtasks (used for available IDs).
        error_text: Truncated error output.
        error_type: Error classification string.
        task_history_text: Pre-formatted subtask status block.
        prev_decisions_text: Pre-formatted previous AI decisions block
            (may be empty).
        loop_info: For looping tasks, a tuple of (loop_idx, repeat_count).
            None for nested tasks.
    """
    failed_id = str(failed_subtask['id'])
    available_ids = [str(s['id']) for s in all_subtasks]

    parts = [ROLE_FAILURE_ANALYST]

    # -- ## Failed Subtask --
    failed_section = f"""## Failed Subtask

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
  Error Type: {error_type}"""

    parts.append(failed_section)

    # -- ## Error Output --
    parts.append(f"## Error Output\n\n{error_text}")

    # -- ## All Subtasks Status --
    parts.append(f"## All Subtasks Status\n\n{task_history_text}")

    # -- ## Previous Failure Analyses (conditional) --
    if prev_decisions_text:
        parts.append(f"## Previous Failure Analyses\n\n{prev_decisions_text}")

    # -- ## Instructions --
    parts.append(f"""## Instructions

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
- Available subtask IDs: {available_ids}""")

    return "\n\n".join(parts)

