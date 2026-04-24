"""
Task Executors - Handle execution logic for different task types.

This module provides:
- SimpleTaskExecutor: Executes simple tasks with AI self-evaluation loop
- NestedTaskExecutor: Executes nested tasks with subtasks and AI decision points
- LoopingTaskExecutor: Executes looping tasks that repeat subtasks a fixed number of times
- SubtaskExecutor: Dispatches subtask execution based on type (supports nested subtasks)
"""

import os
import sys
import json
import time
import subprocess
import logging
from typing import Optional, Tuple

import yaml

from ai_client import AIClient, AICallError, BashTimeoutError, SessionTimeoutError, StreamTimeoutError
from state_manager import StateManager
from util.truncation_limits import limits
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)


_fast_fail_timeout_cache: int | None = None
_show_console_cache: bool | None = None


def _load_fast_fail_timeout() -> int:
    """Load fast_fail_timeout from config registry or config.yaml (cached after first call).

    Returns:
        The configured fast-fail timeout in seconds.
    """
    global _fast_fail_timeout_cache
    if _fast_fail_timeout_cache is not None:
        return _fast_fail_timeout_cache

    from util.config_registry import get_config, is_registered
    if is_registered():
        value = get_config().get("fast_fail_timeout", DEFAULTS["fast_fail_timeout"])
        _fast_fail_timeout_cache = int(value)
        return _fast_fail_timeout_cache

    # Fallback: load from disk
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            value = config.get("fast_fail_timeout", DEFAULTS["fast_fail_timeout"])
            _fast_fail_timeout_cache = int(value)
            return _fast_fail_timeout_cache
        except Exception:
            pass
    _fast_fail_timeout_cache = DEFAULTS["fast_fail_timeout"]
    return _fast_fail_timeout_cache


def _load_show_console() -> bool:
    """Load autoagent_exec_show_console from config registry or config.yaml (cached).

    Returns:
        True if the subprocess should get a visible console window (Windows).
    """
    global _show_console_cache
    if _show_console_cache is not None:
        return _show_console_cache

    from util.config_registry import get_config, is_registered
    if is_registered():
        _show_console_cache = bool(get_config().get("autoagent_exec_show_console", DEFAULTS["autoagent_exec_show_console"]))
        return _show_console_cache

    # Fallback: load from disk
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            _show_console_cache = bool(config.get("autoagent_exec_show_console", DEFAULTS["autoagent_exec_show_console"]))
            return _show_console_cache
        except Exception:
            pass
    _show_console_cache = DEFAULTS["autoagent_exec_show_console"]
    return _show_console_cache


def _save_previous_subtask_summary(session_dir: str, summary: str) -> None:
    """Persist the latest previous_subtask_summary to disk.

    The file is written to ``<session_dir>/previous_subtask_summary.txt``
    and is overwritten each time so that only the most recent summary is
    kept.  On resume the orchestrator reads this file to restore context
    that would otherwise be lost when completed subtasks are skipped.
    """
    if not session_dir:
        return
    path = os.path.join(session_dir, "previous_subtask_summary.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(summary or "")
        logger.debug(f"Saved previous_subtask_summary ({len(summary or '')} chars)")
    except OSError as e:
        logger.warning(f"Failed to save previous_subtask_summary: {e}")


def _load_previous_subtask_summary(session_dir: str) -> str:
    """Load the persisted previous_subtask_summary from disk.

    Returns the stored text, or an empty string if the file does not
    exist or is empty.
    """
    if not session_dir:
        return ""
    path = os.path.join(session_dir, "previous_subtask_summary.txt")
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if content:
            logger.debug(f"Loaded previous_subtask_summary ({len(content)} chars)")
        return content
    except OSError as e:
        logger.warning(f"Failed to load previous_subtask_summary: {e}")
        return ""


def _read_log_file_smart(path: str) -> str:
    """Read a log file with smart encoding detection.

    The log file may be written in binary mode (raw bytes from the subprocess),
    so we try multiple encodings:
      1. UTF-8 (strict)
      2. System console encoding (e.g. GBK on Chinese Windows)
      3. latin-1 (never fails)
    """
    with open(path, "rb") as f:
        raw = f.read()
    # Try UTF-8 first
    try:
        return raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        pass
    # Try system console encoding
    import locale
    console_enc = locale.getpreferredencoding(False)
    if console_enc and console_enc.lower() not in ("utf-8", "utf8"):
        try:
            return raw.decode(console_enc)
        except (UnicodeDecodeError, ValueError, LookupError):
            pass
    # Last resort
    return raw.decode("latin-1")


def _state_key(subtask: dict, round_label: str | None) -> str:
    """Build the state key for a subtask in a given round.

    ``*_once`` subtasks always use their plain id (they are shared
    across rounds).  All other subtasks use ``id@round_label``.
    """
    st_id = str(subtask['id'])
    if subtask.get('type', '').endswith('_once'):
        return st_id
    return StateManager.round_key(st_id, round_label)


def _display_id(task_or_subtask: dict) -> str:
    """Return the human-readable ID for a task or subtask.

    In AI scheduling mode, ``_build_scheduled_task`` stores the original
    (pre-prefix) ID in ``_display_id``.  This helper returns that value
    when present, falling back to the plain ``id`` field.
    """
    return str(task_or_subtask.get('_display_id', task_or_subtask['id']))


def _find_display_id(internal_id: str, subtasks: list) -> str:
    """Look up the display ID for an internal (possibly 3-level) subtask ID.

    Searches *subtasks* for a dict whose ``id`` matches *internal_id*
    and returns its ``_display_id``.  Falls back to *internal_id* itself
    when no match is found (e.g. in Linear mode where IDs are unchanged).
    """
    for st in subtasks:
        if str(st['id']) == str(internal_id):
            return str(st.get('_display_id', st['id']))
    return str(internal_id)


def _build_failed_subtask_history(
    failed_id: str, state_manager, round_label: str | None,
) -> str:
    """Build a human-readable per-attempt history for a failed subtask.

    Extracts the ``history`` list from the subtask's state and formats
    each entry so the failure-analysis AI can see what was tried and
    why each attempt failed.  Returns an empty string when no history
    is available.
    """
    sk = StateManager.round_key(failed_id, round_label) if round_label else failed_id
    st_state = state_manager.get_task_state(sk)
    history = st_state.get('history', [])
    if not history:
        return ""
    lines = []
    for idx, entry in enumerate(history, 1):
        result = entry.get('result', 'unknown')
        summary = entry.get('summary', '')
        error = entry.get('error', '')
        line = f"- Attempt {idx}: {result}"
        detail = summary or error
        if detail:
            # Truncate long summaries to keep the prompt manageable
            detail_text = detail[:limits.get('history_summary')]
            if len(detail) > limits.get('history_summary'):
                detail_text += "..."
            line += f"\n    Detail: {detail_text}"
        lines.append(line)
    return "\n".join(lines)


def _write_autoagent_exec_script(
    session_dir: str,
    task_id: str,
    fast_fail_timeout: int = 30,
    show_console: bool = False,
) -> str:
    """Write (or overwrite) the ``autoagent-exec`` convenience script.

    The script is placed in ``<session_dir>/scripts/`` so the AI can invoke
    it by its absolute path without knowing the full
    ``python … --log-dir … --task-id …`` incantation.

    On Windows a ``.bat`` file is generated; on other platforms a ``.sh``
    file is generated.  Both accept arbitrary trailing arguments which are
    forwarded to ``autoagent_exec.py`` as the command to run.

    The script is regenerated every time a new (sub)task starts so that
    ``--task-id`` always matches the current task.

    Args:
        session_dir: Absolute path to the log session directory.
        task_id: Current task / subtask ID (e.g. ``"1"`` or ``"2.1"``).
        fast_fail_timeout: Seconds to wait before treating the command as
        long-running (default 30, from config.yaml ``fast_fail_timeout``).
        show_console: If True, pass ``--show-console`` to autoagent_exec.py
            so the subprocess gets a visible console window on Windows.
            (from config.yaml ``autoagent_exec_show_console``).

    Returns:
        The absolute path to the generated script.
    """
    exec_py = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "util", "autoagent_exec.py"
    ).replace("\\", "/")
    log_dir = session_dir.replace("\\", "/")
    python_exe = sys.executable.replace("\\", "/")

    scripts_dir = os.path.join(session_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    show_console_flag = " --show-console" if show_console else ""

    if os.name == "nt":
        script_name = "autoagent-exec.bat"
        # %* forwards all arguments.  The AI is instructed to wrap the
        # entire command in quotes so that shell operators (&&, |, ;)
        # are preserved as a single argument.  Optional --stdout/--stderr
        # flags are placed before the command and parsed by argparse.
        content = (
            "@echo off\r\n"
            f'"{ python_exe}" "{exec_py}" --log-dir "{log_dir}" --task-id {task_id}'
            f' --fast-fail-timeout {fast_fail_timeout}{show_console_flag} %*\r\n'
        )
    else:
        script_name = "autoagent-exec.sh"
        # "$@" preserves each positional parameter as a separate quoted
        # argument, so optional flags like --stdout/--stderr are forwarded
        # correctly to argparse.  (Using "$*" would merge all parameters
        # into a single string, breaking flag parsing.)
        content = (
            "#!/usr/bin/env bash\n"
            f'"{ python_exe}" "{exec_py}" --log-dir "{log_dir}" --task-id {task_id}'
            f' --fast-fail-timeout {fast_fail_timeout}{show_console_flag} "$@"\n'
        )
    script_path = os.path.join(scripts_dir, script_name)
    try:
        with open(script_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        # Make executable on Unix
        if os.name != "nt":
            os.chmod(script_path, 0o755)
        logger.debug(f"Wrote {script_path} (task_id={task_id})")
    except OSError as e:
        logger.warning(f"Failed to write {script_path}: {e}")

    return script_path.replace("\\", "/")


class ConfigError(Exception):
    """Configuration file error (YAML syntax, missing fields, etc.)"""
    pass


class ExecutionError(Exception):
    """Task execution error (command failure, timeout, etc.)"""
    pass


class SubtaskResult:
    """Result of a subtask execution."""
    
    def __init__(self, success: bool, output: str = "", logs: str = "", error_type: str = None, response_text: str = ""):
        self.success = success
        self.output = output
        self.logs = logs
        self.error_type = error_type
        self.response_text = response_text


def _resolve_retry_from(retry_from: str, subtasks: list) -> str:
    """Resolve a retry_from ID to an actual subtask ID.

    In AI scheduling mode, subtask IDs are prefixed with
    ``{schedule_round}.{task_id}.`` (e.g. ``1.2.2`` becomes ``1.1.2.2``).
    The AI's failure analysis may return the *original* (un-prefixed)
    subtask ID.  This helper tries an exact match first, then falls
    back to suffix matching so that ``retry_from="1.2.2"`` correctly
    resolves to subtask ``1.1.2.2``.
    """
    retry_from = str(retry_from)
    subtask_ids = [str(st['id']) for st in subtasks]

    # Exact match
    if retry_from in subtask_ids:
        return retry_from

    # Suffix match: find a subtask whose ID ends with ".{retry_from}"
    suffix = "." + retry_from
    candidates = [sid for sid in subtask_ids if sid.endswith(suffix)]
    if len(candidates) == 1:
        logger.info(
            f"Resolved retry_from '{retry_from}' → '{candidates[0]}' "
            f"(suffix match)"
        )
        return candidates[0]
    if len(candidates) > 1:
        # Multiple matches — pick the first (should be rare)
        logger.warning(
            f"Multiple suffix matches for retry_from '{retry_from}': "
            f"{candidates}; using first match '{candidates[0]}'"
        )
        return candidates[0]

    # No match — return as-is (will be handled gracefully downstream)
    logger.warning(
        f"retry_from '{retry_from}' does not match any subtask ID "
        f"in {subtask_ids}"
    )
    return retry_from






