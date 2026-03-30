"""
Shared constants and helper functions for prompt construction.

These building blocks are used across multiple prompt modules to ensure
consistency in role definitions, status marker instructions, and common
formatting utilities.
"""

import os
import logging

from truncation_limits import limits

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Task Design Guide loader (cached)
# ---------------------------------------------------------------------------

_task_design_guide_cache: str | None = None


def load_task_design_guide() -> str:
    """Load and cache the content of TASK_DESIGN_GUIDE.md.

    The file is located at ``autoagent/TASK_DESIGN_GUIDE.md`` (one level up
    from the ``prompts/`` package directory).

    Returns:
        The full text of the guide, or a short fallback message if the file
        cannot be read.
    """
    global _task_design_guide_cache
    if _task_design_guide_cache is not None:
        return _task_design_guide_cache

    guide_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "TASK_DESIGN_GUIDE.md"
    )
    try:
        with open(guide_path, "r", encoding="utf-8") as f:
            _task_design_guide_cache = f.read()
    except OSError as e:
        logger.warning(f"Failed to load TASK_DESIGN_GUIDE.md: {e}")
        _task_design_guide_cache = (
            "(Task Design Guide not available — refer to the task schema "
            "documentation for task types, fields, and best practices.)"
        )
    return _task_design_guide_cache


# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLE_CODING_AGENT = (
    "You are an AI coding agent. You can read/write files, run shell "
    "commands, and analyze outputs. Complete the following task."
)

SYSTEM_PROMPT_CODING_AGENT = (
    "You are an AI coding agent. You can read/write files, run shell "
    "commands, and analyze outputs.\n\n"
    "## Status Markers\n"
    "When you finish a task, you MUST end your response with EXACTLY one of "
    "these status lines (on its own line):\n"
    "  ✅ completed\n"
    "  ❌ not completed: <reason>\n\n"
    "If a task requires a long-running command (e.g. compilation, benchmarking), "
    "use the `autoagent-exec` launcher instead of running it directly in Bash. "
    "When the launcher prints \"TASK SUBMITTED\", output:\n"
    "  ⏳ LONG_RUNNING_IN_PROGRESS\n\n"
    "These markers are MANDATORY. Your response MUST end with one of them."
)

ROLE_TASK_PLANNER = (
    "You are a task planner. Your job is to decompose a given idea into "
    "concrete, actionable TODO tasks in YAML format."
)

ROLE_TASK_REVIEWER = (
    "You are a task review expert. Review the following TODO task "
    "decomposition for quality, completeness, and correctness."
)


# ---------------------------------------------------------------------------
# Status marker instructions
# ---------------------------------------------------------------------------

STATUS_MARKER_INSTRUCTION = (
    "\nWhen finished, end your response with EXACTLY one of these status "
    "lines (on its own line):\n"
    "  \u2705 completed\n"
    "  \u274c not completed: <reason>\n"
    "This status line is MANDATORY and must be the LAST line of your response."
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def build_sibling_context(task: dict, parent_context: dict) -> str:
    """Build the sibling-subtask orientation section.

    Returns an empty string when there is no sibling information to show.
    """
    if not parent_context or not parent_context.get('subtasks'):
        return ""

    subtask_lines = []
    current_id = str(task['id'])
    for st in parent_context['subtasks']:
        st_id = str(st['id'])
        marker = "\u2192" if st_id == current_id else " "
        subtask_lines.append(f"  {marker} {st_id}. {st['name']}")
    return f"This task is part of a larger workflow:\n" + "\n".join(subtask_lines)


def build_history_section(history: list, extract_summary_fn) -> str:
    """Build the previous-attempts history section.

    Args:
        history: Full history list from state.
        extract_summary_fn: A callable that takes an ai_response string and
            returns a short summary.

    Returns the formatted string (may be empty).
    """
    if not history:
        return ""

    recent = history[-3:]  # Last 3 attempts
    history_lines = []
    for h in recent:
        result_str = h.get('result', 'unknown')
        summary = h.get('summary', '')
        if not summary:
            summary = extract_summary_fn(h.get('ai_response', ''))
        history_lines.append(f"  - Attempt {h.get('attempt', '?')}: {result_str}")
        if summary:
            history_lines.append(f"    Summary: {summary[:limits.get('history_summary')]}")
    return f"Previous Attempts:\n" + "\n".join(history_lines)


def build_suggested_fix_section(parent_context: dict, fallback_msg: str = None) -> str:
    """Build the AI-suggested-fix section for retry prompts.

    Args:
        parent_context: May contain a ``suggested_fix`` key.
        fallback_msg: Message to use when no suggested fix is available.
            Defaults to a generic "try a different approach" message.

    Returns the formatted string.
    """
    if parent_context and parent_context.get('suggested_fix'):
        fix_text = parent_context['suggested_fix']
        max_len = limits.get('suggested_fix')
        if len(fix_text) > max_len:
            fix_text = f"(truncated, showing last {max_len} chars)\n..." + fix_text[-max_len:]
        return (
            f"**AI Analysis from previous failure:**\n"
            f"{fix_text}\n\n"
            f"Please take this analysis into account and try a different approach."
        )

    if fallback_msg is None:
        fallback_msg = "Please analyze what went wrong and try a different approach."
    return fallback_msg


def build_autoagent_exec_note(exec_script_path: str) -> str:
    """Build a brief first-attempt note about autoagent-exec.

    This is appended to simple-task prompts on the first attempt so the AI
    knows how to handle long-running commands *before* hitting a timeout.
    """
    return (
        "**Note on long-running commands:** If a Bash command may take more "
        "than a few minutes (e.g. compilation, benchmarking, profiling), do "
        "NOT run it directly in Bash. Instead use the `autoagent-exec` launcher:\n"
        f'  "{exec_script_path}" <your command>\n'
        "The launcher will auto-detach after 10s and print \"TASK SUBMITTED\". "
        "When you see that, output: \u23f3 LONG_RUNNING_IN_PROGRESS\n\n"
        "**\u26a0\ufe0f IMPORTANT: You MUST always use autoagent-exec for long-running "
        "commands. Running them directly in Bash will cause the session to hang "
        "and be killed. Even if autoagent-exec fails, fix the command arguments "
        "and retry with autoagent-exec — NEVER fall back to running directly in Bash.**"
    )


def build_timeout_guidance(
    exec_script_path: str,
    timeout_feedback: str,
) -> str:
    """Build the detailed timeout-warning section.

    Injected when the previous AI call timed out so the AI learns to use
    ``autoagent-exec`` for long-running commands.
    """
    return (
        f"**\u23f0 TIMEOUT WARNING:** The previous session timed out "
        f"({timeout_feedback}). The session was terminated before completion.\n\n"
        f"If your task requires running a command that takes more than a few "
        f"minutes (e.g. compilation, benchmarking, data processing), you MUST "
        f"use the `autoagent-exec` launcher to run it as a background task:\n\n"
        f'"{exec_script_path}" <your command here>\n\n'
        f"- If the command fails within 10s, the error is shown immediately \u2014 fix and retry.\n"
        f"- If the command is still running after 10s, it will be detached and you will see "
        f"\"TASK SUBMITTED\".\n"
        f"- When you see \"TASK SUBMITTED\", output: \u23f3 LONG_RUNNING_IN_PROGRESS\n"
        f"  AutoAgent will call you back with the results.\n\n"
        f"**\u26a0\ufe0f CRITICAL: You MUST always use autoagent-exec for long-running "
        f"commands. Running them directly in Bash will cause the session to hang "
        f"and be killed. Even if autoagent-exec fails, fix the command arguments "
        f"and retry with autoagent-exec — NEVER fall back to running directly in Bash.**"
    )
