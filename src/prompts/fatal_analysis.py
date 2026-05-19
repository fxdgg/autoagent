"""Prompt builder for Fatal Analysis tasks."""

from prompts.shared import indent_block
from util.truncation_limits import limits



def _status_text(status: str, fatal_reason: str = "") -> str:
    if status == "completed":
        return "✅ completed"
    if status == "fatal":
        return f"❌ FATAL: {fatal_reason}" if fatal_reason else "❌ FATAL"
    if status == "failed":
        return "❌ not completed"
    if status == "in_progress":
        return "in progress"
    return ""


def _state_for_display_id(state_manager, display_id: str, top_level: bool = False) -> dict:
    """Find state by display ID, including schedule-prefixed AI-mode keys."""
    state = state_manager.get_task_state(display_id)
    if state.get("status") != "pending" or state.get("attempts", 0):
        return state

    suffix = "." + str(display_id)
    matches = []
    for key, candidate in state_manager.state.get("tasks", {}).items():
        base = str(key).split("@", 1)[0]
        if base == str(display_id):
            matches.append(candidate)
        elif base.endswith(suffix):
            if top_level and base.count(".") != 1:
                continue
            matches.append(candidate)
    return matches[-1] if matches else state


def build_fatal_workflow(
    tasks: list,
    current_task: dict,
    failed_task: dict,
    failed_task_id: str,
    fatal_reason: str,
    state_manager,
    include_subtasks: bool,
) -> str:
    """Build the workflow context shown to Fatal Analysis."""
    current_id = str(current_task.get('_display_id', current_task['id']))
    failed_display_id = str(failed_task.get('_display_id', failed_task['id']))
    lines = []

    for task in tasks:
        task_id = str(task.get('_display_id', task['id']))
        if task_id == "fatal_analysis":
            continue
        if not task_id.isdigit():
            continue
        if int(task_id) > int(current_id):
            break

        if task_id != current_id:
            state = _state_for_display_id(state_manager, task_id, top_level=True)
            status = _status_text(state.get("status", "pending"))
            suffix = f" ({status})" if status else ""
            lines.append(f"{task_id}. {task['name']}{suffix}")
            if task.get('completion_criteria'):
                lines.append("    Criteria:")
                lines.append(indent_block(task['completion_criteria'], 8))
            continue

        if include_subtasks:
            lines.append(f"{task_id}. {task['name']}")
            for subtask in current_task.get('subtasks', []):
                st_display_id = str(subtask.get('_display_id', subtask['id']))
                st_state = _state_for_display_id(state_manager, st_display_id)
                if st_display_id == failed_display_id:
                    status = _status_text("fatal", fatal_reason)
                else:
                    status = _status_text(st_state.get("status", "pending"))
                suffix = f" ({status})" if status else ""
                lines.append(f"    {st_display_id}. {subtask['name']}{suffix}")
                if subtask.get('completion_criteria'):
                    lines.append("        Criteria:")
                    lines.append(indent_block(subtask['completion_criteria'], 12))
        else:
            lines.append(f"{task_id}. {task['name']} ({_status_text('fatal', fatal_reason)})")
            if task.get('completion_criteria'):
                lines.append("    Criteria:")
                lines.append(indent_block(task['completion_criteria'], 8))
        break

    return "\n".join(lines)


def build_fatal_analysis_prompt(
    fatal_task: dict,
    project_description: str,
    workflow_text: str,
    failed_task_output: str,
    failed_task_id: str,
    available_retry_ids: list,
) -> str:
    """Build the Fatal Analysis prompt."""
    I4 = 4
    I8 = 8

    parts = []

    task_inner = []
    task_inner.append(
        f"    <task_name>\n{indent_block(fatal_task['name'], I8)}\n    </task_name>"
    )
    if fatal_task.get('description'):
        task_inner.append(
            f"    <task_description>\n{indent_block(fatal_task['description'], I8)}\n    </task_description>"
        )
    task_inner.append(
        "    <completion_criteria>\n"
        f"{indent_block(fatal_task['completion_criteria'], I8)}\n"
        "    </completion_criteria>"
    )
    if fatal_task.get('initial_hint'):
        task_inner.append(
            f"    <initial_hint>\n{indent_block(fatal_task['initial_hint'], I8)}\n    </initial_hint>"
        )
    parts.append("<task>\n" + "\n\n".join(task_inner) + "\n</task>")

    context_inner = []
    if project_description:
        context_inner.append(
            f"    <project_description>\n{indent_block(project_description, I8)}\n    </project_description>"
        )
    if workflow_text:
        context_inner.append(
            f"    <workflow>\n{indent_block(workflow_text, I8)}\n    </workflow>"
        )
    if context_inner:
        parts.append("<context>\n" + "\n\n".join(context_inner) + "\n</context>")

    output = failed_task_output or "(no failed task output)"
    max_len = limits.get('previous_subtask_summary')
    if len(output) > max_len:
        output = f"(truncated, showing last {max_len} chars)\n..." + output[-max_len:]
    parts.append(
        "<outputs>\n"
        f"    <failed_task_output ({failed_task_id})>\n{indent_block(output, I8)}\n    </failed_task_output>\n"
        "</outputs>"
    )

    instructions = f"""\
1. You should analyze the prerequisite failure, apply only fixes that are within this task's authority, and decide where AutoAgent should retry from.

2. Respond with a JSON object:
```json
{{
    "analysis": "Why the failure occurred and why retry from the chosen task",
    "retry_from": "<task_id>",
    "suggested_fix": "Specific, actionable fix for the retried task, or empty if retry_from is `stop`"
}}
```

- `retry_from`: The failed task itself, or an earlier one if the root cause is there.
  ⚠️ Choosing `stop` will end the whole AutoAgent system. Proceed with this choice
  ONLY if these failures are external blockers that cannot be resolved, or outside the user-allowed fix scope.
- `suggested_fix`: Will be shown to the AI executing the retry - be specific.
- Available `retry_from` IDs: {available_retry_ids}."""
    parts.append(f"<instructions>\n{indent_block(instructions, I4)}\n</instructions>")

    return "\n\n".join(parts)
