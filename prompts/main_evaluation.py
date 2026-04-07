"""
Prompt builder for main-task completion evaluation.

Corresponds to ``NestedTaskExecutor._ai_evaluate_main_task()``
in task_executor.py.
"""

from typing import List

# Role definition for main-task evaluation prompts
ROLE_MAIN_EVALUATOR = (
    "You are a task evaluation expert. Evaluate whether the main task's "
    "completion criteria have been fully met based on the execution results."
)


def build_main_evaluation_prompt(
    task: dict,
    subtasks: list,
    execution_results_text: str,
    prev_eval_section: str,
) -> str:
    """Build the prompt that asks AI to evaluate main-task completion.

    Args:
        task: Parent task configuration dict.
        subtasks: All subtask dicts (used for available IDs).
        execution_results_text: Pre-formatted execution results block
            (from ``_format_execution_results``).
        prev_eval_section: Pre-formatted previous evaluations section
            (may be empty).
    """
    available_ids = [str(s['id']) for s in subtasks]

    parts = [ROLE_MAIN_EVALUATOR]

    # -- ## Evaluation Context --
    parts.append(f"""<evaluation_context>
Main Task: {task['name']}
Completion Criteria: {task['completion_criteria']}
</evaluation_context>""")

    # -- ## Execution Results --
    parts.append(f"<execution_results>\n{execution_results_text}\n</execution_results>")

    # -- ## Previous Evaluations (conditional) --
    if prev_eval_section:
        parts.append(f"<previous_evaluations>\n{prev_eval_section}\n</previous_evaluations>")

    # -- ## Instructions --
    parts.append(f"""<instructions>
Evaluate whether ALL completion criteria are met based on the execution results above.

Respond with a JSON object:
```json
{{
    "main_task_completed": true/false,
    "analysis": "Detailed analysis of results vs each criterion",
    "retry_from": "<subtask_id>",
    "next_strategy": "What to do differently in the next round"
}}
```

- `retry_from` and `next_strategy`: Only required when `main_task_completed` is false.
- `next_strategy`: Will be passed to the AI executing the next round — be specific and actionable.
- Available subtask IDs: {available_ids}
</instructions>""")

    return "\n\n".join(parts)
