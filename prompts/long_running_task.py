"""
Prompt builders for long-running task execution and result analysis.

Corresponds to ``SubtaskExecutor._build_long_running_prompt()`` and
``SubtaskExecutor._ai_analyze_long_running_result()`` in task_executor.py.
"""

from prompts.shared import (
    indent_block,
    get_prompt_task_id,
    build_workflow_section,
    build_history_section,
    build_previous_subtask_section,
    build_suggested_fix_section,
    build_timeout_guidance,
    build_long_running_reminder,
)


def build_long_running_prompt(
    subtask: dict,
    exec_script_path: str,
    attempt: int,
    state: dict,
    extract_summary_fn,
    parent_context: dict = None,
    timeout_feedback: str = None,
    timeout_type: str = None,
    project_description: str = "",
) -> str:
    """Build the prompt that tells AI to use autoagent-exec for long-running tasks.

    Structure mirrors ``build_simple_task_prompt`` with these differences:

    - ``<previous_attempts>`` has no ``<previous_attempt_output>`` sub-tag.
    - ``<constraints>`` always present (long-running reminder or timeout warning).
    """
    parts = []
    I4 = 4
    I8 = 8

    # ── Section 1: Task ──────────────────────────────────────────────
    inner = [f"    Current task ID: {get_prompt_task_id(subtask)}"]
    inner.append(f"    <task_name>\n{indent_block(subtask['name'], I8)}\n    </task_name>")
    inner.append(f"    <completion_criteria>\n{indent_block(subtask['completion_criteria'], I8)}\n    </completion_criteria>")
    if subtask.get('initial_hint'):
        inner.append(f"    <initial_hint>\n{indent_block(subtask['initial_hint'], I8)}\n    </initial_hint>")
    parts.append("<task>\n" + "\n\n".join(inner) + "\n</task>")

    # ── Section 2: Context ───────────────────────────────────────────
    ctx_inner = []
    if project_description:
        ctx_inner.append(f"    <project_description>\n{indent_block(project_description, I8)}\n    </project_description>")

    if parent_context and parent_context.get('main_task_criteria'):
        ctx_inner.append(f"    <subtask_goal>\n{indent_block(parent_context['main_task_criteria'], I8)}\n    </subtask_goal>")

    workflow = build_workflow_section(subtask, parent_context)
    if workflow:
        ctx_inner.append(f"    <workflow>\n{indent_block(workflow, I8)}\n    </workflow>")

    prev_tag, prev_text = build_previous_subtask_section(parent_context)
    if prev_text:
        ctx_inner.append(f"    <{prev_tag}>\n{indent_block(prev_text, I8)}\n    </{prev_tag.split()[0]}>")

    if ctx_inner:
        parts.append("<context>\n" + "\n\n".join(ctx_inner) + "\n</context>")

    # ── Section 3: Previous Attempts (retry only) ────────────────────
    if attempt > 1:
        retry_inner = []

        history = state.get('history', [])
        history_text = build_history_section(history, extract_summary_fn)
        if history_text:
            retry_inner.append(f"    <attempt_history>\n{indent_block(history_text, I8)}\n    </attempt_history>")

        retry_inner.append(indent_block(
            "Please analyze what went wrong and try a different approach.", I4
        ))

        parts.append("<previous_attempts>\n" + "\n\n".join(retry_inner) + "\n</previous_attempts>")

    # ── Section 3b: Failure Guidance (always show when available) ──
    fix_section = build_suggested_fix_section(parent_context, fallback_msg="")
    if fix_section:
        parts.append(f"<guidance_from_previous_failure>\n{indent_block(fix_section, I4)}\n</guidance_from_previous_failure>")

    # ── Section 3c: Main Task Evaluator Guidance ──
    if parent_context and parent_context.get('next_strategy'):
        eval_text = (
            "The last round didn't match the subtask goal. "
            "Please take this analysis into account and try a different approach.\n\n"
            + parent_context['next_strategy']
        )
        parts.append(f"<guidance_from_main_task_evaluator>\n{indent_block(eval_text, I4)}\n</guidance_from_main_task_evaluator>")

    # ── Section 4: Constraints ───────────────────────────────────────
    constraint_text = ""
    if timeout_feedback:
        constraint_text = build_timeout_guidance(
            exec_script_path=exec_script_path,
            timeout_feedback=timeout_feedback,
            timeout_type=timeout_type or "bash",
        )
    if not constraint_text:
        constraint_text = build_long_running_reminder(exec_script_path)

    if constraint_text:
        parts.append(f"<constraints>\n{indent_block(constraint_text, I4)}\n</constraints>")

    return "\n\n".join(parts)


def build_long_running_analysis_prompt(
    output_log: str,
    command_info: str = "",
) -> str:
    """Build the prompt for AI to analyse a completed long-running task.

    The prompt is intentionally minimal because the AI conversation context
    is preserved — it already knows the task name, criteria, workflow, etc.

    Args:
        output_log: Path to the output log file (raw, will be normalised).
        command_info: Optional formatted string like ``"\\nCommand: ..."``
    """
    output_log_display = output_log.replace("\\", "/")

    # command_info typically looks like "\nCommand: ..." — strip leading newline
    command_line = command_info.strip()

    return f"""You previously launched this task using autoagent-exec:
    {command_line}
The task has now finished. Output has been saved to:
    {output_log_display}"""
