"""
Prompt builder for main-task completion evaluation.

Corresponds to ``NestedTaskExecutor._ai_evaluate_main_task()``
in task_executor.py.
"""

from typing import List

from prompts.shared import apply_system_prompt_prefix


def build_main_evaluation_prompt(
    task: dict,
    subtasks: list,
    execution_results_text: str,
    log_section: str,
    prev_eval_section: str,
) -> str:
    """Build the prompt that asks AI to evaluate main-task completion.

    Args:
        task: Parent task configuration dict.
        subtasks: All subtask dicts (used for available IDs).
        execution_results_text: Pre-formatted execution results block
            (from ``_format_execution_results``).
        log_section: Pre-formatted log-file contents section (may be empty).
        prev_eval_section: Pre-formatted previous evaluations section
            (may be empty).
    """
    available_ids = [str(s['id']) for s in subtasks]

    prefix = ""
    _parts = []
    apply_system_prompt_prefix(_parts)
    if _parts:
        prefix = _parts[0] + "\n\n"

    return f"""{prefix}All subtasks are completed. Please evaluate whether the main task is finished.

Main Task: {task['name']}
Completion Criteria: {task['completion_criteria']}

Execution Results:
{execution_results_text}
{log_section}
{prev_eval_section}

Please respond in the following JSON format:
```json
{{
    "main_task_completed": true/false,
    "analysis": "Detailed analysis of results vs criteria",
    "retry_from": "<subtask_id to restart from>",
    "next_strategy": "Strategy for next round if not completed",
    "suggested_improvements": ["improvement 1", "improvement 2"],
    "confidence": "high/medium/low"
}}
```

Important: 
- Set main_task_completed to true ONLY if ALL completion criteria are met.
- If not completed, retry_from should be the subtask ID to restart from.
- If not completed, next_strategy and suggested_improvements will be passed to the AI executing the next round, so be specific.
- Available subtask IDs: {available_ids}
"""
