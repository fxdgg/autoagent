"""
Prompt builder for the AI Orchestrator scheduler.

The scheduler prompt provides the AI with context about available tasks,
execution history, and scheduling strategy so it can decide which task
to execute next (or stop execution).
"""

import os
import logging

from prompts.shared import indent_block
from truncation_limits import limits

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scheduler system prompt
# ---------------------------------------------------------------------------

SCHEDULER_SYSTEM_PROMPT = (
    "You are an AI task scheduler. Your job is to decide which task to "
    "execute next, or whether to stop execution.\n\n"
    "You must respond with a JSON object in one of these formats:\n"
    '1. Execute a task: {"action": "execute", "task_id": <id>, "reasoning": "<why>"}\n'
    '2. Stop execution: {"action": "stop", "reasoning": "<why>"}\n\n'
    "You must choose exactly ONE task per round."
)


def build_scheduler_prompt(
    current_round: int,
    max_rounds: int,
    project_description: str,
    strategy: str,
    stop_condition: str,
    tasks: list,
    task_execution_counts: dict,
    schedule_history: list,
    last_result_config: dict,
    session_dir: str = "",
    scheduler_history_limit: int = 10,
) -> str:
    """Build the prompt sent to the AI scheduler for task selection.

    Args:
        current_round: Current scheduling round number.
        max_rounds: Maximum allowed scheduling rounds.
        project_description: Project-level description text.
        strategy: Scheduling strategy from ai_orchestrator.strategy.
        stop_condition: Stop condition from ai_orchestrator.stop_condition.
        tasks: List of task configuration dicts (each must have id, name,
            type, description).
        task_execution_counts: Dict mapping task_id (str) -> execution count.
        schedule_history: List of schedule history entries (dicts with
            round, task_id, task_name, result, reasoning).
        last_result_config: Dict mapping task_id (str) -> last_result config
            (type, path).
        session_dir: Session directory path (for resolving response result files).
        scheduler_history_limit: Max number of recent history entries to include.

    Returns:
        The formatted scheduler prompt string.
    """
    parts = []
    I4 = 4
    I8 = 8

    # ── Context wrapper ──────────────────────────────────────────────
    ctx_inner = []

    # Current round
    ctx_inner.append(f"    Current Round: {current_round} / {max_rounds}")

    # Project description
    if project_description:
        ctx_inner.append(
            f"    <project_description>\n"
            f"{indent_block(project_description, I8)}\n"
            f"    </project_description>"
        )

    # Scheduling strategy
    if strategy:
        ctx_inner.append(
            f"    <scheduling_strategy>\n"
            f"{indent_block(strategy, I8)}\n"
            f"    </scheduling_strategy>"
        )

    # Stop condition
    if stop_condition:
        ctx_inner.append(
            f"    <stop_condition>\n"
            f"{indent_block(stop_condition, I8)}\n"
            f"    </stop_condition>"
        )

    # Available tasks
    task_lines = []
    for task in tasks:
        tid = str(task['id'])
        tname = task.get('name', '')
        ttype = task.get('type', '')
        tdesc = task.get('description', '')
        exec_count = task_execution_counts.get(tid, 0)

        # Truncate description if too long
        max_desc = limits.get('max')
        if len(tdesc) > max_desc:
            tdesc = tdesc[:max_desc] + "...(truncated)"

        lines = []
        lines.append(f"        - Task {tid}: {tname}")
        lines.append(f"            Type: {ttype}")
        if tdesc:
            lines.append(f"            Description:")
            # Indent description lines
            for dline in tdesc.strip().split('\n'):
                lines.append(f"                {dline}")
        lines.append(f"            Executed: {exec_count} time(s)")

        # Last Result (only show if task has been executed at least once)
        if exec_count > 0:
            lr_line = _build_last_result_line(tid, last_result_config, session_dir)
            if lr_line:
                lines.append(f"            {lr_line}")

        task_lines.append("\n".join(lines))

    ctx_inner.append(
        f"    <available_tasks>\n"
        + "\n".join(task_lines) + "\n"
        f"    </available_tasks>"
    )

    # Schedule history (last N rounds)
    if schedule_history:
        recent = schedule_history[-scheduler_history_limit:]
        hist_lines = []
        for entry in recent:
            rnd = entry.get('round', '?')
            etid = entry.get('task_id', '?')
            ename = entry.get('task_name', '')
            result = entry.get('result', '')
            reasoning = entry.get('reasoning', '')

            if result == 'success':
                marker = '✅'
            elif result == 'failed':
                marker = '❌'
            else:
                marker = ''

            hist_lines.append(f"        - Round {rnd}: {marker}")
            hist_lines.append(f"            Task {etid} ({ename})")
            if reasoning:
                hist_lines.append(f"            Reasoning: {reasoning}")

        ctx_inner.append(
            f"    <schedule_history> (last {scheduler_history_limit} rounds)\n"
            + "\n".join(hist_lines) + "\n"
            f"    </schedule_history>"
        )

    parts.append("<context>\n" + "\n\n".join(ctx_inner) + "\n</context>")

    return "\n\n".join(parts)


def _build_last_result_line(
    task_id: str,
    last_result_config: dict,
    session_dir: str,
) -> str:
    """Build the 'Last Result' display line for a task.

    Args:
        task_id: The task ID string.
        last_result_config: Dict mapping task_id -> {type, path}.
        session_dir: Session directory for resolving response result files.

    Returns:
        A formatted string like "Last Result: ✅ success (See /path/to/file)"
        or empty string if type is 'none' or not configured.
    """
    config = last_result_config.get(task_id, {})
    lr_type = config.get('type', 'none')

    if lr_type == 'none':
        return ""

    if lr_type == 'response':
        # Auto-generated response file
        result_path = _get_response_result_path(task_id, session_dir)
        if result_path and os.path.isfile(result_path):
            display_path = result_path.replace("\\", "/")
            return f"Last Result: See {display_path}"
        else:
            # File doesn't exist yet — shouldn't happen if exec_count > 0
            # but handle gracefully
            return "Last Result: (response file not yet generated)"

    if lr_type == 'file':
        paths = config.get('path', '')
        if isinstance(paths, list):
            # Multiple files
            result_parts = []
            for p in paths:
                display_p = str(p).replace("\\", "/")
                if os.path.isfile(p):
                    result_parts.append(f"See {display_p}")
                else:
                    result_parts.append(f"See {display_p} (Not found, probably due to task failures)")
            return "Last Result: " + "; ".join(result_parts)
        else:
            # Single file
            display_path = str(paths).replace("\\", "/")
            if os.path.isfile(paths):
                return f"Last Result: See {display_path}"
            else:
                return f"Last Result: See {display_path} (Not found, probably due to task failures)"

    return ""


def _get_response_result_path(task_id: str, session_dir: str) -> str:
    """Get the path to the auto-saved response result file.

    The file is stored at ``<session_dir>/task_results/result_<task_id>.txt``.

    Args:
        task_id: Task ID string.
        session_dir: Session directory path.

    Returns:
        Absolute path to the result file.
    """
    if not session_dir:
        return ""
    return os.path.join(session_dir, "task_results", f"result_{task_id}.txt")


def save_response_result(
    task_id: str,
    response_text: str,
    session_dir: str,
    max_length: int = 4000,
) -> str:
    """Save a task's AI response to the result file for scheduler consumption.

    The response is truncated to *max_length* characters (using the same
    strategy as ``previous_subtask_summary``).

    Args:
        task_id: Task ID string.
        response_text: The AI response text to save.
        session_dir: Session directory path.
        max_length: Maximum characters to save (default: 4000).

    Returns:
        The absolute path to the saved result file.
    """
    result_dir = os.path.join(session_dir, "task_results")
    os.makedirs(result_dir, exist_ok=True)

    result_path = os.path.join(result_dir, f"result_{task_id}.txt")

    # Truncate if needed
    text = response_text or ""
    if len(text) > max_length:
        text = "...(truncated)\n" + text[-max_length:]

    try:
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(text)
        logger.debug(f"Saved response result for task {task_id} to {result_path}")
    except Exception as e:
        logger.error(f"Failed to save response result for task {task_id}: {e}")

    return result_path
