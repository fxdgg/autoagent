"""
Prompt templates for AutoAgent task orchestration.

This package contains all prompt construction logic, extracted from
task_executor.py and ideas_watcher.py for better maintainability.

Modules:
    shared              - Shared constants and helper functions
    simple_task         - Simple task execution prompts
    long_running_task   - Long-running task prompts (launch + analysis)
    failure_analysis    - Subtask failure analysis prompts (nested + looping)
    main_evaluation     - Main task completion evaluation prompts
    scheduler           - AI scheduler prompts (scheduling decisions)
    marker_nudge        - Marker nudge prompts (completion status reminders)
    timeout_continuation - Timeout continuation prompts (in-session follow-ups)
    ideas_decompose     - Idea-to-task decomposition prompts
    ideas_review        - Task review and revision prompts
"""

from prompts.simple_task import build_simple_task_prompt
from prompts.long_running_task import (
    build_long_running_prompt,
    build_long_running_analysis_prompt,
)
from prompts.failure_analysis import build_failure_analysis_prompt
from prompts.fatal_analysis import build_fatal_analysis_prompt
from prompts.main_evaluation import build_main_evaluation_prompt
from prompts.ideas_decompose import build_ideas_decompose_prompt
from prompts.ideas_review import (
    build_ideas_review_prompt,
    build_revision_prompt,
)
from prompts.scheduler import (
    build_scheduler_prompt,
    save_response_result,
    SCHEDULER_SYSTEM_PROMPT,
)
