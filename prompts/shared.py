"""
Shared constants and helper functions for prompt construction.

These building blocks are used across multiple prompt modules to ensure
consistency in role definitions, status marker instructions, and common
formatting utilities.
"""

import os
import logging
import yaml

from truncation_limits import limits

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt prefix loader (cached)
# ---------------------------------------------------------------------------

_system_prompt_prefix_cache: str | None = None


def load_system_prompt_prefix() -> str:
    """Load and cache the system_prompt_prefix from config.yaml.

    Returns:
        The prefix string, or empty string if not configured.
    """
    global _system_prompt_prefix_cache
    if _system_prompt_prefix_cache is not None:
        return _system_prompt_prefix_cache

    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"
    )
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        _system_prompt_prefix_cache = config.get("system_prompt_prefix", "") or ""
    except OSError as e:
        logger.warning(f"Failed to load config.yaml for system_prompt_prefix: {e}")
        _system_prompt_prefix_cache = ""
    return _system_prompt_prefix_cache


def get_system_prompt_prefix(task: dict = None) -> str:
    """Return the effective system prompt prefix for a task.

    If the *task* dict contains a ``system_prompt_prefix`` key, that
    value takes precedence.  Otherwise the global value from
    config.yaml is used.

    Args:
        task: Optional task configuration dict.  When provided, its
            ``system_prompt_prefix`` field (if any) overrides the
            global setting.

    Returns:
        The prefix string, or empty string if not configured.
    """
    if task and task.get('system_prompt_prefix'):
        return task['system_prompt_prefix']
    return load_system_prompt_prefix()


def apply_system_prompt_prefix(parts: list, task: dict = None) -> None:
    """Prepend the user-configured system prompt prefix to a parts list.

    If ``system_prompt_prefix`` is configured (non-empty) — either at the
    task level or globally in config.yaml — it is inserted at position 0
    of *parts*.  Otherwise *parts* is left unchanged.

    Args:
        parts: Mutable list of prompt sections.
        task: Optional task configuration dict.  When provided, its
            ``system_prompt_prefix`` field (if any) overrides the
            global setting.
    """
    prefix = get_system_prompt_prefix(task)
    if prefix:
        parts.insert(0, prefix)


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

def build_system_prompt_coding_agent(
    exec_script_path: str = "",
    supports_system_prompt: bool = True,
    task: dict = None,
) -> str:
    """Build the system prompt for coding-agent tasks.

    Includes status-marker instructions and — when *exec_script_path*
    is provided — the autoagent-exec usage note so the AI knows how to
    handle long-running commands.

    For providers that do **not** support a dedicated system-prompt
    channel (``supports_system_prompt=False``), the returned text is
    meant to be **appended** after the user prompt so the AI sees the
    task description first and the operational instructions second.

    The user-configured ``system_prompt_prefix`` (from the *task* dict
    or from config.yaml) is placed before the ``# Instructions``
    heading (or at the end for providers with native system-prompt
    support).

    Args:
        exec_script_path: Absolute path to the generated ``autoagent-exec``
            convenience script.  When empty, the long-running-command
            section is omitted.
        supports_system_prompt: Whether the AI provider supports a
            dedicated ``--append-system-prompt`` CLI parameter.  When
            *False*, the returned text is appended (not prepended) to
            the user prompt, with section headings for clarity.
        task: Optional task configuration dict.  When provided, its
            ``system_prompt_prefix`` field (if any) overrides the
            global setting from config.yaml.
    """
    parts = []

    # Append user-configured system_prompt_prefix first
    # (task-level overrides global)
    prefix = get_system_prompt_prefix(task)
    if prefix:
        parts.append(prefix)

    # For providers without native system-prompt support, add a heading
    # so the AI can distinguish instructions from the task description.
    if not supports_system_prompt:
        parts.append("# Instructions")

    parts.append(
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

    if exec_script_path:
        parts.append(
            "## Note on long-running commands\n"
            "If a Bash command may take more than a few minutes "
            "(e.g. compilation, benchmarking, profiling), do "
            "NOT run it directly in Bash. Instead use the `autoagent-exec` launcher:\n"
            f'  "{exec_script_path}" <your command>\n'
            "The launcher will auto-detach after 10s and print \"TASK SUBMITTED\". "
            "When you see that, output: ⏳ LONG_RUNNING_IN_PROGRESS"
        )
        parts.append(
            "## ⚠️ IMPORTANT\n"
            "You MUST always use autoagent-exec for long-running "
            "commands. Running them directly in Bash will cause the session to hang "
            "and be killed. Even if autoagent-exec fails, fix the command arguments "
            "and retry with autoagent-exec — NEVER fall back to running directly in Bash."
        )

    return "\n\n".join(parts)

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


# Keep build_autoagent_exec_note as a thin wrapper for backward compatibility.
# The canonical long-running note now lives inside build_system_prompt_coding_agent.
def build_autoagent_exec_note(exec_script_path: str) -> str:
    """Build a brief first-attempt note about autoagent-exec.

    .. deprecated::
        The autoagent-exec note is now included in the system prompt
        returned by :func:`build_system_prompt_coding_agent`.  This
        function is kept only for backward compatibility.
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
