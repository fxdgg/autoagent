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

# Directory containing the task design guide and its sub-guides.
_GUIDE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "task_design_guide")
)


def load_task_design_guide() -> str:
    """Load and cache the content of TASK_DESIGN_GUIDE.md.

    The file is located at ``autoagent/task_design_guide/TASK_DESIGN_GUIDE.md``.

    After loading, bare filenames that correspond to sibling ``.md`` files in
    the same directory (e.g. ``build_and_ship.md``) are replaced with their
    absolute paths so the consuming AI can read them directly without guessing.

    Returns:
        The full text of the guide, or a short fallback message if the file
        cannot be read.
    """
    global _task_design_guide_cache
    if _task_design_guide_cache is not None:
        return _task_design_guide_cache

    guide_path = os.path.join(_GUIDE_DIR, "TASK_DESIGN_GUIDE.md")
    try:
        with open(guide_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Replace bare .md filenames with absolute paths so the AI can read
        # them directly.  Only replace names that actually exist on disk.
        for fname in os.listdir(_GUIDE_DIR):
            if fname.endswith(".md") and fname != "TASK_DESIGN_GUIDE.md":
                abs_path = os.path.join(_GUIDE_DIR, fname)
                content = content.replace(f"`{fname}`", f"`{abs_path}`")
        _task_design_guide_cache = content
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
    """
    parts = []

    # For providers without native system-prompt support, add a heading
    # so the AI can distinguish instructions from the task description.
    if not supports_system_prompt:
        parts.append("<instructions>")

    # ── Core rules ────────────────────────────────────────────────
    rules = [
        "You are fully autonomous — make all decisions independently. "
        "NEVER ask the user questions or wait for confirmation.\n",
    ]

    if exec_script_path:
        rules.append(
            "For any command that may run longer than a few minutes "
            "(compilation, benchmarking, profiling, training, etc.), \n"
            "you MUST use autoagent-exec instead of running it directly in Bash:\n"
            f'  "{exec_script_path}" "<your entire command>"\n'
            "Always wrap the command in double quotes so that shell operators are passed correctly.\n"
            "autoagent-exec has three possible outcomes:\n"
            "  - \"TASK SUBMITTED\" → the command is running in the background. "
            "Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.\n"
            "  - \"[OK]\" → the command finished quickly with exit code 0. "
            "Continue working — treat it as a normal completed command.\n"
            "  - \"[FAST-FAIL]\" → the command failed quickly. "
            "Read the error output, fix the issue, and retry.\n"
            "NEVER run long commands directly in Bash — the session may be "
            "killed due to timeout, wasting time or leaving the project in broken state.\n"
        )

    rules.append(
        "When you are done, end your response with EXACTLY one of:\n"
        "  ✅ completed\n"
        "  ❌ not completed: <reason>\n"
        "  ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints \"TASK SUBMITTED\")"
    )

    if not supports_system_prompt:
        str_unindent = "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1))
        parts.append("\n".join("    " + line for line in str_unindent.splitlines()))
    else:
        parts.append("\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)))

    if not supports_system_prompt:
        parts.append("</instructions>")

    return "\n".join(parts)

ROLE_TASK_PLANNER = (
    "You are a task planner. Your job is to decompose a given idea into "
    "concrete, actionable TODO tasks in YAML format."
)

ROLE_TASK_REVIEWER = (
    "You are a task decomposition review expert. You evaluate TODO task "
    "YAML files for schema correctness, appropriate task type selection, "
    "completion criteria quality, and decomposition granularity. \n"
    "You focus on whether the tasks are actionable and verifiable by an "
    "autonomous AI coding agent."
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

def indent_block(text: str, spaces: int = 4) -> str:
    """Indent every non-empty line of *text* by *spaces* spaces.

    Leading/trailing whitespace is stripped from the whole block first.
    Empty lines within the text are preserved as-is (no trailing
    whitespace added).  This keeps the user's original relative
    indentation structure intact while shifting the whole block
    rightward.
    """
    if not text:
        return ""
    text = text.strip()
    if not text:
        return ""
    prefix = " " * spaces
    lines = text.split("\n")
    return "\n".join(prefix + line if line.strip() else line for line in lines)


def build_workflow_section(task: dict, parent_context: dict) -> str:
    """Build the sibling-subtask workflow orientation text.

    Returns the plain workflow lines (no wrapping tag — caller adds
    ``<workflow>``).  The current subtask is marked with ``→``.

    A reminder is appended telling the AI to focus only on the current
    step and not to perform work for later steps.

    Returns an empty string when there is no sibling information.
    """
    if not parent_context or not parent_context.get('subtasks'):
        return ""

    lines = []
    current_id = str(task['id'])
    for st in parent_context['subtasks']:
        st_id = str(st['id'])
        marker = "→" if st_id == current_id else " "
        lines.append(f"{marker} {st_id}. {st['name']}")
    lines.append("")
    lines.append(
        "IMPORTANT: Only work on the current step (→). "
        "Do NOT perform work that belongs to later steps."
    )
    return "\n".join(lines)


# Keep the old name as an alias so existing callers don't break during
# the transition.  Can be removed once all call-sites are updated.
build_sibling_context = build_workflow_section


def build_history_section(history: list, extract_summary_fn) -> str:
    """Build the previous-attempts history lines.

    Returns the formatted bullet list **without** a heading or wrapping
    tag — the caller wraps it in ``<attempt_history>``.

    Includes attempts that ended with ``error``, ``not_completed``, or
    ``interrupted``.  ``completed`` entries are omitted (they carry no
    actionable guidance).

    Args:
        history: Full history list from state.
        extract_summary_fn: Callable(ai_response) → str (unused but
            kept for API compatibility).
    """
    if not history:
        return ""

    recent = history[-3:]  # Last 3 attempts
    history_lines = []
    for h in recent:
        result_str = h.get('result', 'unknown')
        if result_str not in ('error', 'not_completed', 'interrupted'):
            continue
        history_lines.append(f"- Attempt {h.get('attempt', '?')}: {result_str}")
        if result_str == 'error':
            error_msg = h.get('error', '')
            if error_msg:
                history_lines.append(f"    Error: {error_msg[:limits.get('history_summary')]}")
        elif result_str == 'interrupted':
            history_lines.append(f"    Note: {h.get('summary', 'Interrupted by user')[:limits.get('history_summary')]}")
        elif result_str == 'not_completed':
            summary = h.get('summary', '')
            # Skip "no marker found" entries — they add noise, not guidance
            if summary and 'cannot find' not in summary.lower():
                history_lines.append(f"    Summary: {summary[:limits.get('history_summary')]}")
    if not history_lines:
        return ""
    return "\n".join(history_lines)


def build_suggested_fix_section(parent_context: dict, fallback_msg: str = None) -> str:
    """Build the AI-suggested-fix content for retry prompts.

    Returns the plain fix text (no wrapping tag — caller adds
    ``<guidance_from_previous_failure>``).

    Args:
        parent_context: May contain a ``suggested_fix`` key.
        fallback_msg: Message to use when no suggested fix is available.
            Defaults to a generic "try a different approach" message.
    """
    if parent_context and parent_context.get('suggested_fix'):
        fix_text = parent_context['suggested_fix']
        max_len = limits.get('max')
        if len(fix_text) > max_len:
            fix_text = f"(truncated, showing last {max_len} chars)\n..." + fix_text[-max_len:]
        return (
            f"{fix_text}\n\n"
            f"Please take this analysis into account and try a different approach."
        )

    if fallback_msg is None:
        fallback_msg = "Please analyze what went wrong and try a different approach."
    return fallback_msg


def build_previous_subtask_section(parent_context: dict) -> str:
    """Return the previous-subtask summary text and its tag name.

    Returns a ``(tag_name, content)`` tuple.  *tag_name* includes the
    previous subtask ID when available (e.g.
    ``"previous_step_result (1.2)"``).  *content* is the truncated
    summary text **without** any wrapping tag — the caller wraps it.

    Returns ``("", "")`` when there is no previous summary.
    """
    if not parent_context:
        return ("", "")
    summary = parent_context.get('previous_subtask_summary', '')
    if not summary:
        return ("", "")
    prev_id = parent_context.get('previous_subtask_id', '')
    tag_name = f"previous_step_result ({prev_id})" if prev_id else "previous_step_result"
    max_len = limits.get('previous_subtask_summary')
    if len(summary) > max_len:
        summary = "...(truncated)\n" + summary[-max_len:]
    return (tag_name, summary)


def build_previous_attempt_output_section(output: str) -> str:
    """Return the previous-attempt output text.

    Returns the truncated output **without** any wrapping tag — the
    caller wraps it in ``<previous_attempt_output>``.

    Returns an empty string when *output* is falsy.
    """
    if not output:
        return ""
    max_len = limits.get('previous_attempt_output')
    if len(output) > max_len:
        output = "...(truncated)\n" + output[-max_len:]
    return output


def build_timeout_guidance(
    exec_script_path: str,
    timeout_feedback: str,
    timeout_type: str = "bash",
) -> str:
    """Build the timeout-warning text.

    Returns plain text (no wrapping tag — caller adds ``<constraints>``).
    """
    if timeout_type == "session":
        return ""

    return (
        "⏰ TIMEOUT WARNING: The previous session was killed due to session timeout. \n"
        "If your task involves a long-running command, remember to use `autoagent-exec` (see system instructions)."
    )


def build_long_running_reminder(exec_script_path: str) -> str:
    """Build a short reminder for long-running tasks.

    Returns plain text (no wrapping tag — caller adds ``<constraints>``).
    """
    return (
        "⚠️ Long-Running Task: You MUST use autoagent-exec to run your command, Do NOT run it directly in Bash (see system instructions)."
    )