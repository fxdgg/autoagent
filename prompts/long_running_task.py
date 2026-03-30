"""
Prompt builders for long-running task execution and result analysis.

Corresponds to ``SubtaskExecutor._build_long_running_prompt()`` and
``SubtaskExecutor._ai_analyze_long_running_result()`` in task_executor.py.
"""

from prompts.shared import (
    SYSTEM_PROMPT_CODING_AGENT,
    STATUS_MARKER_INSTRUCTION,
    apply_system_prompt_prefix,
    build_sibling_context,
    build_history_section,
    build_suggested_fix_section,
)


def build_long_running_prompt(
    subtask: dict,
    exec_script_path: str,
    attempt: int,
    state: dict,
    extract_summary_fn,
    parent_context: dict = None,
) -> str:
    """Build the prompt that tells AI to use autoagent-exec for long-running tasks.

    Args:
        subtask: Subtask configuration dict.
        exec_script_path: Absolute path to the generated ``autoagent-exec``
            convenience script (forward-slash normalised).
        attempt: Current attempt number (1-based).
        state: Current subtask state from state_manager.
        extract_summary_fn: Callable(ai_response: str) -> str.
        parent_context: Optional context from the parent task.
    """
    parts = [
        SYSTEM_PROMPT_CODING_AGENT,
        f"Task: {subtask['name']}",
        f"Type: long_running (\u26a0\ufe0f This task may take a long time)",
        f"Completion Criteria: {subtask['completion_criteria']}",
    ]
    apply_system_prompt_prefix(parts)

    # Show main task goal if this is a subtask
    if parent_context and parent_context.get('main_task_criteria'):
        parts.append(f"Main Task Goal: {parent_context['main_task_criteria']}")

    if subtask.get('initial_hint') and attempt == 1:
        parts.append(f"Initial Hint: {subtask['initial_hint']}")

    # Sibling subtask orientation
    sibling = build_sibling_context(subtask, parent_context)
    if sibling:
        parts.append(sibling)

    # Retry context
    if attempt > 1:
        history = state.get('history', [])
        history_section = build_history_section(history, extract_summary_fn)
        if history_section:
            parts.append(history_section)

        fallback = (
            "The previous attempt failed. Please analyze what went wrong "
            "and adjust your command or approach."
        )
        parts.append(build_suggested_fix_section(parent_context, fallback_msg=fallback))

    parts.append(f"""\n**Long-Running Task Instructions**

You MUST use the `autoagent-exec` launcher to run your command:

"{exec_script_path}" <your command here>

- If the command fails within 10s, the error is shown immediately — fix and retry with autoagent-exec.
- If the command is still running after 10s, it will be detached and you will see "TASK SUBMITTED".
- When you see "TASK SUBMITTED", output: ⏳ LONG_RUNNING_IN_PROGRESS
  AutoAgent will call you back with the results.
- If the task cannot be done, output: ❌ not completed: <reason>

**⚠️ CRITICAL: You MUST always use autoagent-exec to run the command. NEVER run it directly in Bash.
Running commands directly will cause the session to hang and be killed.
Even if autoagent-exec reports errors, debug and fix the command arguments, then retry with autoagent-exec.
Do NOT attempt to bypass autoagent-exec under any circumstances.**""")
    return "\n\n".join(parts)


def build_long_running_analysis_prompt(
    subtask: dict,
    status: str,
    output_log: str,
    command_info: str = "",
    exit_code_info: str = "",
    parent_context: dict = None,
) -> str:
    """Build the prompt for AI to analyse a completed long-running task.

    Args:
        subtask: Subtask configuration dict.
        status: Task status string (e.g. "completed", "failed").
        output_log: Path to the output log file (raw, will be normalised).
        command_info: Optional formatted string like ``"\\nCommand: ..."``
        exit_code_info: Optional formatted string like ``"\\nExit Code: 0"``
        parent_context: Optional context from the parent task.
    """
    output_log_display = output_log.replace("\\", "/")

    # Build sibling subtask list for orientation
    sibling_info = ""
    if parent_context and parent_context.get('subtasks'):
        sibling_info = "\n\n" + build_sibling_context(subtask, parent_context)

    prefix = ""
    _parts = []
    apply_system_prompt_prefix(_parts)
    if _parts:
        prefix = _parts[0] + "\n\n"

    return f"""{prefix}You previously launched this task using autoagent-exec.{command_info}
The task has now finished.

Subtask: {subtask['name']}
Completion Criteria: {subtask['completion_criteria']}
Task Status: {status}{exit_code_info}{sibling_info}

The task output has been saved to:
  {output_log_display}

Please:
1. Read the output log file above to understand what happened
2. Evaluate whether the task completed successfully
3. Check if the results meet the completion criteria
4. If the task produced output files, you may examine them as needed

{STATUS_MARKER_INSTRUCTION}"""
