"""
Prompt builder for main-task completion evaluation.

Corresponds to ``NestedTaskExecutor._ai_evaluate_main_task()``
in task_executor.py.
"""

from typing import List

from prompts.shared import indent_block
from truncation_limits import limits

# Role definition for main-task evaluation prompts
ROLE_MAIN_EVALUATOR = (
    "You are a task evaluation expert. Evaluate whether the main task's "
    "completion criteria have been fully met based on the execution results."
)


def _build_workflow_with_results(subtasks_with_status: list) -> str:
    """Build the workflow section for main-task evaluation.

    All subtasks are expected to be completed at this point, so each
    entry shows ``(COMPLETED)`` with its criteria and result summary.

    Args:
        subtasks_with_status: List of dicts with keys: subtask_id, name,
            status, completion_criteria, ai_reasoning.
    """
    lines = []
    for st in subtasks_with_status:
        st_id = str(st['subtask_id'])
        name = st['name']
        status = st.get('status', 'unknown')

        tag = "COMPLETED" if status == "completed" else status.upper()
        lines.append(f"  {st_id}. {name} ({tag})")
        if st.get('completion_criteria'):
            lines.append("        Criteria:")
            lines.append(indent_block(st['completion_criteria'], 12))
        if st.get('ai_reasoning'):
            lines.append("        Result:")
            lines.append(indent_block(
                st['ai_reasoning'][:limits.get('history_summary')], 12
            ))

    return "\n".join(lines)


def build_main_evaluation_prompt(
    task: dict,
    subtasks: list,
    prev_eval_section: str,
    subtasks_with_status: list = None,
) -> str:
    """Build the prompt that asks AI to evaluate main-task completion.

    Args:
        task: Parent task configuration dict.
        subtasks: All subtask dicts (used for available IDs).
        prev_eval_section: Pre-formatted previous evaluations section
            (may be empty).
        subtasks_with_status: List of dicts with keys: subtask_id, name,
            status, completion_criteria, ai_reasoning.  When provided,
            a ``<workflow>`` section is built.
    """
    available_ids = [str(s['id']) for s in subtasks]
    I4 = 4
    I8 = 8

    parts = [ROLE_MAIN_EVALUATOR]

    # -- <context> --
    ctx_inner = []
    ctx_inner.append(f"    <main_task>\n{indent_block(task['name'], I8)}\n    </main_task>")
    ctx_inner.append(f"    <completion_criteria>\n{indent_block(task['completion_criteria'], I8)}\n    </completion_criteria>")
    parts.append("<context>\n" + "\n\n".join(ctx_inner) + "\n</context>")

    # -- <workflow> --
    if subtasks_with_status:
        workflow_text = _build_workflow_with_results(subtasks_with_status)
        parts.append(f"<workflow>\n{indent_block(workflow_text, I4)}\n</workflow>")

    # -- <previous_evaluations> (conditional) --
    if prev_eval_section:
        parts.append(f"<previous_evaluations>\n{indent_block(prev_eval_section, I4)}\n</previous_evaluations>")

    # -- <instructions> --
    instructions = f"""\
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
- Available subtask IDs: {available_ids}"""

    parts.append(f"<instructions>\n{indent_block(instructions, I4)}\n</instructions>")

    return "\n\n".join(parts)
