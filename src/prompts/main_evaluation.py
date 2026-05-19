"""
Prompt builder for main-task completion evaluation.

Corresponds to ``NestedTaskExecutor._ai_evaluate_main_task()`` in
task_executor.py.
"""

from prompts.shared import indent_block

# Role definition for main-task evaluation prompts
ROLE_MAIN_EVALUATOR = (
    "You are a task evaluation expert. Evaluate whether the main task's "
    "completion criteria have been fully met based on the execution results.\n"
    "DO NOT modifying source code, tests, configs, data, generated files, etc."
)


def _format_status(status: str) -> str:
    """Format workflow status labels the same way as documented prompts."""
    if status == "completed":
        return "✅ completed"
    if status == "failed":
        return "❌ not completed"
    return status or "unknown"


def _build_workflow_with_results(subtasks_with_status: list) -> str:
    """Build the workflow section for main-task evaluation."""
    lines = []
    for st in subtasks_with_status:
        st_id = str(st.get('display_subtask_id', st['subtask_id']))
        name = st['name']
        status = _format_status(st.get('status', 'unknown'))

        lines.append(f"  {st_id}. {name} ({status})")
        if st.get('completion_criteria'):
            lines.append("        Criteria:")
            lines.append(indent_block(st['completion_criteria'], 12))

    return "\n".join(lines)


def build_main_evaluation_prompt(
    task: dict,
    subtasks: list,
    prev_eval_section: str,
    subtasks_with_status: list = None,
    project_description: str = "",
) -> str:
    """Build the prompt that asks AI to evaluate main-task completion."""
    available_ids = [str(s.get('_display_id', s['id'])) for s in subtasks]
    I4 = 4
    I8 = 8

    parts = [ROLE_MAIN_EVALUATOR]

    # -- <context> --
    ctx_inner = []
    if project_description:
        ctx_inner.append(
            f"    <project_description>\n{indent_block(project_description, I8)}\n"
            f"    </project_description>"
        )
    ctx_inner.append(f"    <main_task>\n{indent_block(task['name'], I8)}\n    </main_task>")
    ctx_inner.append(
        f"    <completion_criteria>\n"
        f"{indent_block(task['completion_criteria'], I8)}\n"
        f"    </completion_criteria>"
    )
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
- `next_strategy`: Will be passed to the AI executing the next round - be specific and actionable.
- Available subtask IDs: {available_ids}"""

    parts.append(f"<instructions>\n{indent_block(instructions, I4)}\n</instructions>")

    return "\n\n".join(parts)
