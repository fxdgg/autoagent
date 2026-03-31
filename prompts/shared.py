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


def prepend_system_prompt_prefix(prompt: str, task: dict = None) -> str:
    """Prepend the user-configured system prompt prefix to a prompt string.

    The prefix is always placed at the very beginning of the user prompt
    so that the AI sees the role/persona instruction first, regardless of
    whether the provider supports a native system-prompt channel.

    Args:
        prompt: The original user prompt string.
        task: Optional task configuration dict.  When provided, its
            ``system_prompt_prefix`` field (if any) overrides the
            global setting.

    Returns:
        The prompt with the prefix prepended (separated by two newlines),
        or the original prompt unchanged if no prefix is configured.
    """
    prefix = get_system_prompt_prefix(task)
    if prefix:
        return prefix + "\n\n" + prompt
    return prompt


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

    .. note::

        The user-configured ``system_prompt_prefix`` is **not** included
        here.  It is always prepended to the *user prompt* by the caller
        (see :func:`prepend_system_prompt_prefix`) so that it appears at
        the very beginning of the prompt regardless of whether the
        provider supports a native system-prompt channel.

    Args:
        exec_script_path: Absolute path to the generated ``autoagent-exec``
            convenience script.  When empty, the long-running-command
            section is omitted.
        supports_system_prompt: Whether the AI provider supports a
            dedicated ``--append-system-prompt`` CLI parameter.  When
            *False*, the returned text is appended (not prepended) to
            the user prompt, with section headings for clarity.
        task: Optional task configuration dict.  Currently unused but
            kept for API compatibility.
    """
    parts = []

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
            f'  "{exec_script_path}" "<your entire command>"\n'
            "Always wrap your command in double quotes so that shell operators "
            "(&&, |, ;, etc.) are passed correctly. For example:\n"
            f'  "{exec_script_path}" "cd build && cmake .. && make -j8"\n'
            "The launcher will auto-detach after the fast-run window and print \"TASK SUBMITTED\". "
            "When you see that, output: \u23f3 LONG_RUNNING_IN_PROGRESS"
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

    Includes attempts that ended with an error (e.g. timeout, AI call
    failure) or ``not_completed`` — both carry useful diagnostic
    information for the next attempt.  ``completed`` entries are omitted
    because they indicate success and provide no actionable guidance.

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
        # Include error and not_completed entries; skip completed
        if result_str not in ('error', 'not_completed'):
            continue
        history_lines.append(f"  - Attempt {h.get('attempt', '?')}: {result_str}")
        if result_str == 'error':
            error_msg = h.get('error', '')
            if error_msg:
                history_lines.append(f"    Error: {error_msg[:limits.get('history_summary')]}")
        elif result_str == 'not_completed':
            summary = h.get('summary', '')
            if summary:
                history_lines.append(f"    Summary: {summary[:limits.get('history_summary')]}")
    if not history_lines:
        return ""
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
        max_len = limits.get('max')
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
        f'  "{exec_script_path}" "<your entire command>"\n'
        "Always wrap your command in double quotes so that shell operators "
        "(&&, |, ;, etc.) are passed correctly.\n"
        "The launcher will auto-detach after the fast-run window and print \"TASK SUBMITTED\". "
        "When you see that, output: \u23f3 LONG_RUNNING_IN_PROGRESS\n\n"
        "**\u26a0\ufe0f IMPORTANT: You MUST always use autoagent-exec for long-running "
        "commands. Running them directly in Bash will cause the session to hang "
        "and be killed. Even if autoagent-exec fails, fix the command arguments "
        "and retry with autoagent-exec \u2014 NEVER fall back to running directly in Bash.**"
    )

def build_previous_subtask_section(parent_context: dict) -> str:
    """Build the previous-subtask summary section for context-isolated prompts.

    When context isolation is enabled, each subtask starts a fresh AI session.
    This section injects a truncated summary of the previous subtask's AI
    response so the new session has essential context.

    Returns an empty string when there is no previous summary to inject.
    """
    if not parent_context:
        return ""
    summary = parent_context.get('previous_subtask_summary', '')
    if not summary:
        return ""
    max_len = limits.get('previous_subtask_summary')
    if len(summary) > max_len:
        summary = "...(truncated)\n" + summary[-max_len:]
    return f"=== Previous Step Result ===\n{summary}\n============================"


def build_timeout_guidance(
    exec_script_path: str,
    timeout_feedback: str,
    timeout_type: str = "bash",
) -> str:
    """Build the timeout-warning section.

    Args:
        exec_script_path: Path to the autoagent-exec wrapper script.
        timeout_feedback: Human-readable description of the timeout event.
        timeout_type: Either ``"bash"`` (no output for N seconds — remind
            the AI to use autoagent-exec) or ``"session"`` (total session
            time exceeded — tell the AI it was interrupted by the user).
    """
    if timeout_type == "session":
        # Session timeout: not included in the prompt per design.
        # Return empty — session timeout is handled via history entries.
        return ""

    # bash timeout: short reminder — the system prompt already contains
    # full autoagent-exec usage instructions.
    return (
        f"**⏰ TIMEOUT WARNING:** The previous session was terminated because "
        f"no new output was produced for an extended period. "
        f"If your task involves a long-running command, remember to use "
        f"`autoagent-exec` (see system instructions)."
    )


def build_long_running_reminder(exec_script_path: str) -> str:
    """Build a short reminder for long-running tasks.

    This is a concise reminder that the AI must use autoagent-exec.
    The full usage instructions are already in the system prompt.

    Args:
        exec_script_path: Path to the autoagent-exec wrapper script.
    """
    return (
        f"**⚠️ Long-Running Task:** You MUST use `autoagent-exec` to run your command. "
        f"Do NOT run it directly in Bash. Example:\n"
        f'  "{exec_script_path}" "cd build && cmake .. && make -j8"\n'
        f"See system instructions for full details."
    )