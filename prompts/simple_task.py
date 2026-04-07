"""
Prompt builder for simple task execution.

Corresponds to ``SimpleTaskExecutor._build_prompt()`` in task_executor.py.
"""

from prompts.shared import (
    indent_block,
    build_workflow_section,
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

    The prompt is organised into clearly separated XML sections with
    consistent indentation so the AI can parse them easily:

    1. **<task>** — core instructions (name, criteria, hint)
    2. **<context>** — background information (project, goal, workflow, prev step)
    3. **<previous_attempts>** — retry information (only when attempt > 1)
    4. **<guidance_from_previous_failure>** — suggested fix (when available)
    5. **<constraints>** — operational constraints (timeout warnings)
    """
    parts = []
    I4 = 4   # indent for content inside top-level tags
    I8 = 8   # indent for content inside nested tags

    # ── Section 1: Task ──────────────────────────────────────────────
    inner = []
    inner.append(f"    <task_name>\n{indent_block(task['name'], I8)}\n    </task_name>")
    inner.append(f"    <completion_criteria>\n{indent_block(task['completion_criteria'], I8)}\n    </completion_criteria>")
    if task.get('initial_hint'):
        inner.append(f"    <initial_hint>\n{indent_block(task['initial_hint'], I8)}\n    </initial_hint>")
    parts.append("<task>\n" + "\n\n".join(inner) + "\n</task>")

    # ── Section 2: Context ───────────────────────────────────────────
    ctx_inner = []
    if project_description:
        ctx_inner.append(f"    <project_description>\n{indent_block(project_description, I8)}\n    </project_description>")

    if parent_context and parent_context.get('main_task_criteria'):
        ctx_inner.append(f"    <subtask_goal>\n{indent_block(parent_context['main_task_criteria'], I8)}\n    </subtask_goal>")

    workflow = build_workflow_section(task, parent_context)
    if workflow:
        ctx_inner.append(f"    <workflow>\n{indent_block(workflow, I8)}\n    </workflow>")

    prev_tag, prev_text = build_previous_subtask_section(parent_context)
    if prev_text:
        ctx_inner.append(f"    <{prev_tag}>\n{indent_block(prev_text, I8)}\n    </{prev_tag.split()[0]}>")

    if ctx_inner:
        parts.append("<context>\n" + "\n\n".join(ctx_inner) + "\n</context>")

    # ── Section 3: Previous Attempts (retry only) ────────────────────
    if attempt > 1:
        retry_inner = []

        prev_output = build_previous_attempt_output_section(previous_attempt_output)
        if prev_output:
            retry_inner.append(f"    <previous_attempt_output>\n{indent_block(prev_output, I8)}\n    </previous_attempt_output>")

        history = state.get('history', [])
        history_text = build_history_section(history, extract_summary_fn)
        if history_text:
            retry_inner.append(f"    <attempt_history>\n{indent_block(history_text, I8)}\n    </attempt_history>")

        retry_inner.append(indent_block(
            "Please analyze what went wrong and try a different approach.", I4
        ))

        parts.append("<previous_attempts>\n" + "\n\n".join(retry_inner) + "\n</previous_attempts>")

    # ── Section 3b: Failure Guidance (always show when available) ──
    fix_section = build_suggested_fix_section(parent_context, fallback_msg="")
    if fix_section:
        parts.append(f"<guidance_from_previous_failure>\n{indent_block(fix_section, I4)}\n</guidance_from_previous_failure>")

    # ── Section 3c: Main Task Evaluator Guidance ──
    if parent_context and parent_context.get('next_strategy'):
        eval_text = (
            "The last round didn't match the subtask goal. "
            "Please take this analysis into account and try a different approach.\n\n"
            + parent_context['next_strategy']
        )
        parts.append(f"<guidance_from_main_task_evaluator>\n{indent_block(eval_text, I4)}\n</guidance_from_main_task_evaluator>")

    # ── Section 4: Constraints ───────────────────────────────────────
    if timeout_feedback:
        guidance = build_timeout_guidance(
            exec_script_path=exec_script_path,
            timeout_feedback=timeout_feedback,
            timeout_type=timeout_type or "bash",
        )
        if guidance:
            parts.append(f"<constraints>\n{indent_block(guidance, I4)}\n</constraints>")

    return "\n\n".join(parts)
