"""
Prompt builders for task-decomposition review, revision, and human-feedback revision.

Corresponds to ``IdeasWatcher._review_tasks()``, ``IdeasWatcher._revise_tasks()``,
and the human-feedback revision block inside ``IdeasWatcher._human_review_loop()``
in ideas_watcher.py.
"""

from truncation_limits import limits
from prompts.shared import load_task_design_guide, load_system_prompt_prefix


def build_ideas_review_prompt(
    idea_content: str,
    tasks_yaml: str,
    temp_tasks_path: str,
    last_feedback_section: str = "",
) -> str:
    """Build the prompt that asks a reviewer AI to evaluate generated tasks.

    Args:
        idea_content: Raw idea text.
        tasks_yaml: YAML-formatted task list string.
        temp_tasks_path: File path where corrected YAML should be written.
        last_feedback_section: Optional pre-formatted section containing
            the previous reviewer's feedback (may be empty string).
    """
    task_design_guide = load_task_design_guide()

    prefix = load_system_prompt_prefix()
    role_line = prefix if prefix else "You are a task review expert."

    return f"""{role_line} Review the following TODO task decomposition
for quality, completeness, and correctness.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs.

## Original Idea

{idea_content[:limits.get('idea_content')] + chr(10) + chr(10) + '(idea text truncated)' if len(idea_content) > limits.get('idea_content') else idea_content}

## Generated Tasks (YAML)

```yaml
{tasks_yaml[:limits.get('tasks_yaml')] + chr(10) + '# (YAML truncated)' if len(tasks_yaml) > limits.get('tasks_yaml') else tasks_yaml}```

{last_feedback_section}## Task Design Guide

The following guide describes how AutoAgent executes tasks at runtime. Use it as
the authoritative reference for task types, schema, hierarchy rules, and best
practices when reviewing the generated tasks.

<task_design_guide>
{task_design_guide}
</task_design_guide>

## Review Criteria

Evaluate the generated tasks against these criteria:

1. **Schema correctness**: Does every task have the required fields for its type?
   (e.g., nested/looping must have subtasks; looping must have repeat_count)
2. **ID consistency**: Are task IDs sequential integers and subtask IDs use correct
   dot notation (e.g., 2.1, 2.2)?
3. **Type appropriateness**: Are task types chosen correctly?
   - Multi-step ideas should use nested/looping, not a single simple task.
   - Iterative optimize-test cycles should use looping, not nested.
   - long_running is only used as a subtask, never top-level.
   - nested/looping are never used as subtask types.
4. **Completion criteria quality**: Is every completion_criteria specific, measurable,
   and objectively verifiable by an AI agent?
   \u2705 Good: "All unit tests pass with 0 failures"
   \u274c Bad: "Code is optimized" or "Performance is improved"
5. **Decomposition granularity**: Does the decomposition fully cover the idea without
   over-decomposing into trivial subtasks or leaving gaps?
6. **YAML validity**: Is the YAML structure well-formed and parseable?
7. **Model field**: If present, the model field must be either "default" or "simple".
   Tasks requiring complex reasoning should use "default"; straightforward tasks can use "simple".

## Instructions

If the tasks pass ALL criteria, respond with EXACTLY:
\u2705 completed

If the tasks need improvement:
1. Respond with: \u274c not completed
2. Briefly explain what needs to be fixed.
3. Then DIRECTLY modify the YAML file at:
     {temp_tasks_path}
   Write the corrected full task list into that file.
   Do NOT include markdown code fences or any extra text in the file.
"""


def build_ideas_revision_prompt(
    review_feedback: str,
    temp_tasks_path: str,
) -> str:
    """Build the prompt that asks the planner AI to revise tasks after review.

    Args:
        review_feedback: Feedback text from the reviewer AI.
        temp_tasks_path: File path where revised YAML should be written.
    """
    prefix = load_system_prompt_prefix()
    prefix_block = prefix + "\n\n" if prefix else ""

    return f"""{prefix_block}Your previous task decomposition was reviewed and needs revision.

## Reviewer Feedback

{review_feedback[:limits.get('review_feedback')] + chr(10) + chr(10) + '(feedback truncated)' if len(review_feedback) > limits.get('review_feedback') else review_feedback}

## Instructions

Please revise the task decomposition based on the feedback above.
Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
"""


def build_human_feedback_revision_prompt(
    current_tasks_yaml: str,
    human_feedback: str,
    temp_tasks_path: str,
) -> str:
    """Build the prompt for revising tasks based on human feedback.

    Args:
        current_tasks_yaml: Current tasks serialised as YAML.
        human_feedback: Free-form feedback text from the human user.
        temp_tasks_path: File path where revised YAML should be written.
    """
    prefix = load_system_prompt_prefix()
    prefix_block = prefix + "\n\n" if prefix else ""

    return f"""{prefix_block}Your task decomposition needs revision based on human feedback.

## Current Tasks

```yaml
{current_tasks_yaml[:limits.get('tasks_yaml')] + chr(10) + '# (YAML truncated)' if len(current_tasks_yaml) > limits.get('tasks_yaml') else current_tasks_yaml}
```

## Human Feedback

{human_feedback[:limits.get('human_feedback')] + chr(10) + chr(10) + '(feedback truncated)' if len(human_feedback) > limits.get('human_feedback') else human_feedback}

## Instructions

Please revise the task decomposition based on the feedback above.
Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
"""
