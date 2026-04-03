"""
Prompt builder for simple task execution.

Corresponds to ``SimpleTaskExecutor._build_prompt()`` in task_executor.py.
"""

from prompts.shared import (
    build_sibling_context,
    build_history_section,
    build_previous_subtask_section,
    build_previous_attempt_output_section,
    build_suggested_fix_section,
    build_timeout_guidance,
)


def build_simple_task_prompt(
    task: dict,
    attempt: int,
    state: dict,
    extract_summary_fn,
    parent_context: dict = None,
    timeout_feedback: str = None,
    timeout_type: str = None,
    exec_script_path: str = "",
    project_description: str = "",
    previous_attempt_output: str = None,
) -> str:
    """Build the prompt sent to AI for a simple task execution.

    The prompt is organised into clearly separated sections:

    1. **Task** — core instructions (name, criteria, hint on every attempt)
    2. **Context** — background information (main goal, workflow, prev step)
    3. **Previous Attempts** — retry information (only when attempt > 1)
    4. **Constraints** — operational constraints (timeout warnings)

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
        timeout_type: Either ``"bash"`` (no output for N seconds) or
            ``"session"`` (total session time exceeded).  Determines
            the style of timeout guidance injected into the prompt.
        exec_script_path: Absolute path to the generated ``autoagent-exec``
            convenience script (forward-slash normalised).
        project_description: Optional root-level description from
            ``todos.yaml`` providing project-wide context.
        previous_attempt_output: Full AI output from the previous attempt
            (truncated).  Injected when the session was reset so the AI
            can see what it already did.
    """
    parts = []

    # ── Section 1: Task ──────────────────────────────────────────────
    task_lines = [
        "## Task",
        f"Task: {task['name']}",
        f"Completion Criteria: {task['completion_criteria']}",
    ]
    if task.get('initial_hint'):
        task_lines.append(f"Initial Hint: {task['initial_hint']}")
    parts.append("\n".join(task_lines))

    # ── Section 2: Context ───────────────────────────────────────────
    context_lines = []
    if project_description:
        context_lines.append(f"Project Description: {project_description}")

    if parent_context and parent_context.get('main_task_criteria'):
        context_lines.append(f"Subtask Goal: {parent_context['main_task_criteria']}")

    sibling = build_sibling_context(task, parent_context)
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

        # Full output from the previous attempt (when session was reset)
        prev_output = build_previous_attempt_output_section(previous_attempt_output)
        if prev_output:
            retry_lines.append(prev_output)

        history = state.get('history', [])
        history_section = build_history_section(history, extract_summary_fn)
        if history_section:
            retry_lines.append(history_section)

        retry_lines.append(build_suggested_fix_section(parent_context))

        parts.append("## Previous Attempts\n" + "\n\n".join(retry_lines))

    # ── Section 4: Constraints ───────────────────────────────────────
    constraint_lines = []
    if timeout_feedback:
        guidance = build_timeout_guidance(
            exec_script_path=exec_script_path,
            timeout_feedback=timeout_feedback,
            timeout_type=timeout_type or "bash",
        )
        if guidance:
            constraint_lines.append(guidance)

    if constraint_lines:
        parts.append("## Constraints\n" + "\n\n".join(constraint_lines))

    return "\n\n".join(parts)
