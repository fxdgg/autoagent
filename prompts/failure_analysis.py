"""
Prompt builders for subtask failure analysis.

Covers both *nested* and *looping* task types.  Corresponds to
``NestedTaskExecutor._ai_analyze_failure()`` and
``LoopingTaskExecutor._ai_analyze_failure()`` in task_executor.py.
"""

from typing import List


def build_nested_failure_analysis_prompt(
    task: dict,
    failed_subtask: dict,
    all_subtasks: list,
    error_text: str,
    error_type: str,
    task_history_text: str,
    prev_decisions_text: str,
) -> str:
    """Build the failure-analysis prompt for a *nested* task.

    Args:
        task: Parent task configuration dict.
        failed_subtask: The subtask that failed.
        all_subtasks: All sibling subtasks (used for available IDs).
        error_text: Truncated error output.
        error_type: Error classification string.
        task_history_text: Pre-formatted subtask status block
            (from ``_format_task_history``).
        prev_decisions_text: Pre-formatted previous AI decisions block
            (may be empty).
    """
    failed_id = str(failed_subtask['id'])
    available_ids = [str(s['id']) for s in all_subtasks]

    return f"""A subtask has failed. Please analyze the failure and decide the retry strategy.

Main Task: {task['name']}
Main Task Completion Criteria: {task['completion_criteria']}

Failed Subtask:
  ID: {failed_id}
  Name: {failed_subtask['name']}
  Type: {failed_subtask['type']}
  Completion Criteria: {failed_subtask.get('completion_criteria', 'N/A')}
  Error: {error_text}
  Error Type: {error_type}

All Subtasks Status:
{task_history_text}
{prev_decisions_text}

You MUST respond with a JSON object in the following format:
```json
{{
    "analysis": "Description of why the failure occurred",
    "retry_from": "<subtask_id to restart from>",
    "reasoning": "Why retry from this subtask",
    "suggested_fix": "Specific fix to try \u2014 this will be passed to the AI executing the retried subtask",
    "confidence": "high/medium/low"
}}
```

Important: 
- retry_from should be the ID of the subtask to restart from.
- It can be the failed subtask itself, or an earlier subtask if the root cause is there.
- The suggested_fix will be shown to the AI that retries the subtask, so be specific and actionable.
- Do NOT suggest the same fix that was already tried in previous rounds. Try a fundamentally different approach.
- Available subtask IDs: {available_ids}
"""


def build_looping_failure_analysis_prompt(
    task: dict,
    failed_subtask: dict,
    all_subtasks: list,
    error_text: str,
    error_type: str,
    loop_idx: int,
    history_text: str,
    prev_decisions_text: str,
) -> str:
    """Build the failure-analysis prompt for a *looping* task.

    Args:
        task: Parent task configuration dict.
        failed_subtask: The subtask that failed.
        all_subtasks: All sibling subtasks.
        error_text: Truncated error output.
        error_type: Error classification string.
        loop_idx: Current loop iteration (1-based).
        history_text: Pre-formatted subtask status block.
        prev_decisions_text: Pre-formatted previous AI decisions block.
    """
    failed_id = str(failed_subtask['id'])
    available_ids = [str(s['id']) for s in all_subtasks]
    repeat_count = task.get('repeat_count', 1)

    return f"""A subtask has failed during loop iteration {loop_idx}. Please analyze the failure and decide the retry strategy.

Main Task: {task['name']}
Task Type: looping (iteration {loop_idx}/{repeat_count})

Failed Subtask:
  ID: {failed_id}
  Name: {failed_subtask['name']}
  Type: {failed_subtask['type']}
  Completion Criteria: {failed_subtask.get('completion_criteria', 'N/A')}
  Error: {error_text}
  Error Type: {error_type}

All Subtasks Status:
{history_text}
{prev_decisions_text}

You MUST respond with a JSON object in the following format:
```json
{{
    "analysis": "Description of why the failure occurred",
    "retry_from": "<subtask_id to restart from>",
    "reasoning": "Why retry from this subtask",
    "suggested_fix": "Specific fix to try \u2014 this will be passed to the AI executing the retried subtask"
}}
```

Important:
- retry_from should be the ID of the subtask to restart from.
- The suggested_fix will be shown to the AI that retries the subtask, so be specific and actionable.
- Do NOT suggest the same fix that was already tried in previous rounds. Try a fundamentally different approach.
- Available subtask IDs: {available_ids}
"""
