"""
Prompt builders for long-running task execution and result analysis.

Corresponds to ``SubtaskExecutor._build_long_running_prompt()`` and
``SubtaskExecutor._ai_analyze_long_running_result()`` in task_executor.py.
"""

from prompts.shared import (
    build_sibling_context,
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

    The prompt is organised into clearly separated sections:

    1. **Task** — core instructions (name, criteria, hint on every attempt)
    2. **Context** — background information (main goal, workflow, prev step)
    3. **Previous Attempts** — retry information (only when attempt > 1)
    4. **Constraints** — long-running reminder + timeout warnings

    Args:
        subtask: Subtask configuration dict.
        exec_script_path: Absolute path to the generated ``autoagent-exec``
            convenience script (forward-slash normalised).
        attempt: Current attempt number (1-based).
        state: Current subtask state from state_manager.
        extract_summary_fn: Callable(ai_response: str) -> str.
        parent_context: Optional context from the parent task.
        timeout_feedback: If set, the previous AI call timed out.
        timeout_type: Either ``"bash"`` or ``"session"``.
        project_description: Optional root-level description from
            ``todos.yaml`` providing project-wide context.
    """
    parts = []

    # ── Section 1: Task ──────────────────────────────────────────────
    task_lines = [
        "## Task",
        f"Task: {subtask['name']}",
        f"Completion Criteria: {subtask['completion_criteria']}",
    ]
    if subtask.get('initial_hint'):
        task_lines.append(f"Initial Hint: {subtask['initial_hint']}")
    parts.append("\n".join(task_lines))

    # ── Section 2: Context ───────────────────────────────────────────
    context_lines = []
    if project_description:
        context_lines.append(f"Project Description: {project_description}")

    if parent_context and parent_context.get('main_task_criteria'):
        context_lines.append(f"Subtask Goal: {parent_context['main_task_criteria']}")

    sibling = build_sibling_context(subtask, parent_context)
    if sibling:
        context_lines.append(sibling)

    prev_section = build_previous_subtask_section(parent_context)
    if prev_section:
        context_lines.append(prev_section)

    if context_lines:
        parts.append("## Context\n" + "\n\n".join(context_lines))

    # ── Section 3: Previous Attempts (retry only) ────────────────────
    if attempt > 1:
        retry_lines = []

        history = state.get('history', [])
        history_section = build_history_section(history, extract_summary_fn)
        if history_section:
            retry_lines.append(history_section)

        retry_lines.append(
            "The previous attempt failed. Please analyze what went wrong "
            "and adjust your command or approach."
        )

        parts.append("## Previous Attempts\n" + "\n\n".join(retry_lines))

    # ── Section 3b: Failure Guidance (always show when available) ──
    fix_section = build_suggested_fix_section(parent_context, fallback_msg="")
    if fix_section:
        parts.append("## Guidance from Previous Failure\n" + fix_section)

    # ── Section 4: Constraints ───────────────────────────────────────
    constraint_lines = []

    # Timeout guidance takes priority; if present, skip the generic reminder
    has_timeout_guidance = False
    if timeout_feedback:
        guidance = build_timeout_guidance(
            exec_script_path=exec_script_path,
            timeout_feedback=timeout_feedback,
            timeout_type=timeout_type or "bash",
        )
        if guidance:
            constraint_lines.append(guidance)
            has_timeout_guidance = True

    # Long-running reminder (only if no timeout guidance already present)
    if not has_timeout_guidance:
        constraint_lines.append(build_long_running_reminder(exec_script_path))

    if constraint_lines:
        parts.append("## Constraints\n" + "\n\n".join(constraint_lines))

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
