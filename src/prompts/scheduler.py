"""
Prompt builder for the AI Orchestrator scheduler.

The scheduler prompt provides the AI with context about available tasks,
execution history, and scheduling strategy so it can decide which task
to execute next (or stop execution).
"""

import os
import logging

from prompts.shared import indent_block
from util.truncation_limits import limits

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

    # Determine the task_id from the most recent scheduling round
    # so that only that task gets a full preview in its Last Result.
    last_scheduled_tid: str | None = None
    if schedule_history:
        last_scheduled_tid = str(schedule_history[-1].get('task_id', ''))

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
        lines.append(
            f"        - Task {tid}: {tname} | Type: {ttype} | Executed: {exec_count} time(s)"
        )
        if tdesc:
            lines.append(f"            Description:")
            # Indent description lines
            for dline in tdesc.strip().split('\n'):
                lines.append(f"                {dline}")

        # Last Result (only show if task has been executed at least once)
        # Only the most recently scheduled task gets a full preview;
        # other tasks show file paths only (no preview content).
        if exec_count > 0:
            show_preview = (tid == last_scheduled_tid)
            lr_lines = _build_last_result_lines(
                tid, last_result_config, session_dir,
                show_preview=show_preview,
            )
            if lr_lines:
                for lr_line in lr_lines:
                    lines.append(f"            {lr_line}")

        task_lines.append("\n".join(lines))

    ctx_inner.append(
        f"    <available_tasks>\n"
        + "\n".join(task_lines) + "\n\n"
        f"        IMPORTANT: If a result file is marked as NOTFOUND, it is probably\n"
        f"        due to task failures — the task may have crashed or errored out\n"
        f"        before it could write its result file. Consider re-running the\n"
        f"        task or running a diagnostic task to investigate.\n"
        f"    </available_tasks>"
    )

    # Schedule history (last N rounds)
    if schedule_history:
        recent = schedule_history[-scheduler_history_limit:]
        hist_lines = []
        for entry in recent:
            etid = entry.get('task_id', '?')
            ename = entry.get('task_name', '')
            result = entry.get('result', '')

            if result == 'success':
                status = 'COMPLETED'
            elif result == 'failed':
                status = 'FAILED'
            elif result == 'stopped':
                status = 'STOPPED'
            else:
                status = 'IN_PROGRESS'

            hist_lines.append(f"        Task {etid} | {ename} | {status}")

        ctx_inner.append(
            f"    <schedule_history> (last {scheduler_history_limit} rounds, most recent call last)\n"
            + "\n".join(hist_lines) + "\n"
            f"    </schedule_history>"
        )

    # Overtime warning (soft constraint when current_round > max_rounds)
    if current_round > max_rounds:
        ctx_inner.append(
            f"    WARNING: You have exceeded the planned number of scheduling rounds "
            f"({current_round}/{max_rounds}). Please finish any essential remaining "
            f"work (e.g. testing, validation) and then stop. Do NOT start new "
            f"feature tasks or optimizations."
        )

    parts.append("<context>\n" + "\n\n".join(ctx_inner) + "\n</context>")

    return "\n\n".join(parts)


def _build_last_result_lines(
    task_id: str,
    last_result_config: dict,
    session_dir: str,
    preview_lines: int = 5,
    show_preview: bool = True,
) -> list[str]:
    """Build the 'Last Result' display lines for a task.

    Both ``type=response`` and ``type=file`` produce file path(s).  When
    *show_preview* is ``True`` (the default), the last *preview_lines*
    lines of each file are included as an inline preview.  When ``False``,
    only the file path is shown (used for tasks that were NOT the most
    recently scheduled one, to keep the prompt concise).

    For ``type=response``, the response text is saved to a temporary file
    (via ``save_response_result``) and the path to that file is shown.

    Each file path is followed by ``(NOTFOUND)`` if the file does not
    exist at prompt-build time.

    Args:
        task_id: The task ID string.
        last_result_config: Dict mapping task_id -> {type, path}.
        session_dir: Session directory for resolving response result files.
        preview_lines: Number of trailing lines to include as preview.
        show_preview: Whether to include an inline content preview.

    Returns:
        A list of formatted lines for the Last Result block, or an
        empty list if type is 'none' or not configured.
    """
    config = last_result_config.get(task_id, {})
    lr_type = config.get('type', 'none')

    if lr_type == 'none':
        return []

    # Collect file paths to display
    file_paths: list[str] = []

    if lr_type == 'response':
        result_path = _get_response_result_path(task_id, session_dir)
        if result_path:
            file_paths.append(result_path)
        else:
            return ["Last Result: (NOTFOUND)"]

    elif lr_type == 'file':
        paths = config.get('path', '')
        if isinstance(paths, list):
            file_paths.extend(str(p) for p in paths)
        else:
            file_paths.append(str(paths))

    if not file_paths:
        return []

    # Build output lines
    lines: list[str] = ["Last Result:"]
    for idx, fpath in enumerate(file_paths, 1):
        display_path = fpath.replace("\\", "/")
        if not os.path.isfile(fpath):
            lines.append(f"    {idx}. {display_path} (NOTFOUND)")
            continue

        lines.append(f"    {idx}. {display_path}")

        # Only include inline preview for the most recently scheduled task
        if show_preview:
            preview = _read_tail(fpath, preview_lines)
            lines.append(f"    Preview:")
            if preview:
                for pline in preview:
                    lines.append(f"        {pline}")
            else:
                lines.append(f"        (empty)")

    return lines


def _read_tail(filepath: str, n: int = 5) -> list[str]:
    """Return the last *n* non-empty lines of a text file.

    Returns an empty list if the file is empty or unreadable.
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.read().splitlines()
        # Strip trailing blank lines
        while all_lines and not all_lines[-1].strip():
            all_lines.pop()
        return all_lines[-n:] if all_lines else []
    except Exception:
        return []


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
    max_length: int | None = None,
) -> str:
    """Save a task's AI response to the result file for scheduler consumption.

    The response is truncated to *max_length* characters.  When
    *max_length* is ``None`` (the default), the value is read from
    ``config.yaml`` → ``truncation_limits.previous_subtask_summary``.

    Args:
        task_id: Task ID string.
        response_text: The AI response text to save.
        session_dir: Session directory path.
        max_length: Maximum characters to save.  Defaults to the
            ``previous_subtask_summary`` truncation limit from config.

    Returns:
        The absolute path to the saved result file.
    """
    if max_length is None:
        max_length = limits.get('previous_subtask_summary')

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
