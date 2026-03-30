"""
Prompt builder for simple task execution.

Corresponds to ``SimpleTaskExecutor._build_prompt()`` in task_executor.py.
"""

import os
from typing import Optional

from prompts.shared import (
    ROLE_CODING_AGENT,
    STATUS_MARKER_INSTRUCTION,
    build_sibling_context,
    build_history_section,
    build_suggested_fix_section,
    build_autoagent_exec_note,
    build_timeout_guidance,
)


def build_simple_task_prompt(
    task: dict,
    attempt: int,
    state: dict,
    extract_summary_fn,
    parent_context: dict = None,
    timeout_feedback: str = None,
    exec_path: str = None,
    log_session_dir: str = "",
) -> str:
    """Build the prompt sent to AI for a simple task execution.

    Args:
        task: Task configuration dict (must contain 'id', 'name',
            'completion_criteria'; may contain 'initial_hint').
        attempt: Current attempt number (1-based).
        state: Current task state from state_manager.
        extract_summary_fn: Callable(ai_response: str) -> str used to
            extract a summary from a previous AI response.
        parent_context: Optional context from the parent task, containing:
            - subtasks: list of all sibling subtasks (for orientation)
            - suggested_fix: AI's suggested fix from failure analysis
            - main_task_criteria: completion criteria of the parent task
        timeout_feedback: If set, the previous AI call timed out.  This
            string contains the error message.
        exec_path: Absolute path to ``autoagent_exec.py`` (forward-slash
            normalised).  Required when *timeout_feedback* is set and on
            the first attempt for the long-running-command note.
        log_session_dir: Log session directory (forward-slash normalised).
    """
    parts = [
        ROLE_CODING_AGENT,
        f"Task: {task['name']}",
        f"Completion Criteria: {task['completion_criteria']}",
    ]

    # Show main task goal if this is a subtask
    if parent_context and parent_context.get('main_task_criteria'):
        parts.append(f"Main Task Goal: {parent_context['main_task_criteria']}")

    if task.get('initial_hint') and attempt == 1:
        parts.append(f"Initial Hint: {task['initial_hint']}")

    # Sibling subtask orientation
    sibling = build_sibling_context(task, parent_context)
    if sibling:
        parts.append(sibling)

    # Retry context
    if attempt > 1:
        history = state.get('history', [])
        history_section = build_history_section(history, extract_summary_fn)
        if history_section:
            parts.append(history_section)

        parts.append(build_suggested_fix_section(parent_context))

    # Timeout feedback with autoagent-exec guidance
    if timeout_feedback:
        if exec_path is None:
            exec_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "autoagent_exec.py"
            ).replace("\\", "/")
        parts.append(
            build_timeout_guidance(
                task_id=str(task['id']),
                exec_path=exec_path,
                log_session_dir=log_session_dir,
                timeout_feedback=timeout_feedback,
            )
        )

    # Mandatory status marker
    parts.append(STATUS_MARKER_INSTRUCTION)

    # First-attempt note about autoagent-exec
    if attempt == 1:
        if exec_path is None:
            exec_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "autoagent_exec.py"
            ).replace("\\", "/")
        parts.append(
            build_autoagent_exec_note(
                task_id=str(task['id']),
                exec_path=exec_path,
            )
        )

    return "\n\n".join(parts)
