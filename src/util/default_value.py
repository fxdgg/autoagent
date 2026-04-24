"""
Centralized default values for AutoAgent configuration.

Every configurable knob lives in the ``DEFAULTS`` dict below.  All other
modules should ``from util.default_value import DEFAULTS`` and use
``DEFAULTS["key"]`` as their fallback instead of hard-coding magic
numbers.

``DEFAULT_CONFIG_YAML`` is the human-readable config.yaml text that
``--generate-default-config`` writes to disk.  It is built dynamically
from ``DEFAULTS`` so the two can never drift apart.
"""

import os

# ── Single source of truth for every default value ────────────────────

DEFAULTS = {
    # general
    "system_prompt_prefix": (
        "You are an AI coding agent. You can read/write files, run shell "
        "commands, and analyze outputs. Complete the following task."
    ),
    "default_model": "deepseek-v3.2",
    "default_model_provider": {
        "claude": "claude-opus-4.6",
        "gemini": "gemini-3.1-pro-preview",
        "codex": "gpt-5.4"
    },
    "truncation_limits": {
        "previous_subtask_summary": 4000,
        "history_summary": 300,
        "max": 50000,
    },

    # timeout & wait
    "session_timeout": 3600,
    "bash_timeout": 300,
    "fast_fail_timeout": 30,
    "backoff_base": 5,
    "backoff_max_wait": 600,
    "idle_interval": 30,

    "signal_check_interval": 15,
    "signal_max_wait": 24 * 3600,
    "signal_max_initial_wait": 20,

    # max rounds & retries
    "max_plan_retries": 3,
    "max_review_rounds": 5,
    "max_adversarial_rounds": 2,
    "max_validation_retries": 3,
    "default_max_attempts": 5,
    "max_marker_nudges": 3,

    "max_signal_retry": 10,

    # AI scheduler
    "scheduler_history_limit": 10,
    "scheduler_decision_max_retries": 3,
    "scheduler_max_session_retries": 2,
    "scheduler_overtime_rounds": 5,

    # debug
    "autoagent_exec_show_console": False,
}


# ── Config-file template (values are filled from DEFAULTS) ────────────

# We use str.format_map() with DEFAULTS to inject values.  Nested dicts
# (truncation_limits) are handled by explicit key references.

_CONFIG_TEMPLATE = """\
# AutoAgent Configuration
# This file provides default settings for the orchestrator.
# Command-line argument will override these values.

# ------------------------------------------------------------
# general
# ------------------------------------------------------------

# System prompt prefix
# This text is inserted to the very start of each task's prompt.
# Use it to set the AI's persona, role, or any global instructions.
# Example: "You are an AI coding agent. You can read/write files, run shell commands, and analyze outputs."
# This can be overridden per-task in todos.yaml via the system_prompt_prefix field.
# Leave empty or remove to skip.
system_prompt_prefix: "{system_prompt_prefix}"

# Default AI model for providers that support model selection
# This is used when no model is specified via CLI --model or preset
# Supported models depend on the provider.
default_model: {default_model}

# Truncation limits for auto-built prompts (in characters).
# Only 3 keys are used:
#   previous_subtask_summary: for subtask summaries, error text, log files
#   history_summary: for history attempt summaries, ai_reasoning
#   max: defensive upper bound for fields that should not normally be truncated
truncation_limits:
  previous_subtask_summary: {tl_previous_subtask_summary}
  history_summary: {tl_history_summary}
  max: {tl_max}

# ------------------------------------------------------------
# timeout & wait
# ------------------------------------------------------------

# Session timeout (in seconds).
# If the total elapsed time of an AI session exceeds this limit, the
# session is killed. This is a hard cap on how long a single AI call
# can run, regardless of whether the AI is actively producing output.
session_timeout: {session_timeout}

# Bash timeout (in seconds).
# If the AI produces no new output for this many seconds, the session
# is killed. This detects cases where the AI is stuck waiting for a
# long-running command to finish. The next prompt will include guidance
# on using autoagent-exec for long-running commands.
bash_timeout: {bash_timeout}

# Fast-fail timeout for autoagent-exec (in seconds).
# When a long-running task is launched via autoagent-exec, the script
# waits this many seconds for the command to exit. If the command fails
# within this window, the error is shown immediately so the AI can fix it.
# If the command is still running after this timeout, it is detached to
# the background. Default: {fast_fail_timeout}
fast_fail_timeout: {fast_fail_timeout}

# Maximum backoff wait time (in seconds) when AI CLI calls fail repeatedly.
# Uses exponential backoff: 5s, 10s, 20s, 40s, ... up to this limit.
backoff_max_wait: {backoff_max_wait}

# Idle interval (in seconds).
# When idle mode is active (--ideas is set and --no-idle is not), the
# orchestrator polls for new ideas at this interval.
idle_interval: {idle_interval}

# ------------------------------------------------------------
# max rounds & retries
# ------------------------------------------------------------

# Maximum number of plan (decomposition) retries for a single idea.
# If the plan phase fails (AI call error, YAML parse failure, empty result,
# etc.), a fresh AI session is started and the plan is retried.
# After this many failures the idea is skipped for this run.
max_plan_retries: {max_plan_retries}

# Maximum number of AI review rounds when processing ideas into TODO tasks.
# Each round sends the generated tasks to a fresh reviewer AI for quality check.
# If the reviewer keeps rejecting, tasks are accepted after this many rounds.
max_review_rounds: {max_review_rounds}

# Maximum number of adversarial (red-team) review rounds per review iteration
# when processing ideas into TODO tasks. In each review iteration, after the
# positive reviewer passes, an adversarial reviewer checks for loopholes,
# ambiguities, and destructive potential. Set to 0 to disable adversarial review.
max_adversarial_rounds: {max_adversarial_rounds}

# Maximum number of schema-validation retries when processing ideas.
# If generated tasks fail schema validation, the errors are fed back to the
# reviewer AI for correction. Tasks are accepted as-is after this many retries.
max_validation_retries: {max_validation_retries}

# Default max_attempts for task/subtask execution.
# This is the global fallback when a task does not specify its own
# max_attempts field.  Individual tasks can override this value.
default_max_attempts: {default_max_attempts}

# Maximum number of lightweight "nudge" follow-ups when the AI forgets to
# emit a completion status marker (✅/❌/⏳).  Instead of resetting the
# session and replaying the entire task, a short prompt is sent in the same
# session asking the AI to self-evaluate.  After this many nudges without a
# marker, the system falls back to the normal retry loop.
max_marker_nudges: {max_marker_nudges}

# ------------------------------------------------------------
# AI scheduler
# ------------------------------------------------------------

# Maximum number of recent schedule_history entries included in scheduler prompt.
# Only relevant when ai_orchestrator mode is enabled in todos.yaml.
scheduler_history_limit: {scheduler_history_limit}

# Maximum number of in-session retries when the AI scheduler returns
# invalid JSON, invalid action, or invalid task_id.
# These retries happen within the same AI session (level-1 retry).
scheduler_decision_max_retries: {scheduler_decision_max_retries}

# Maximum number of session-reset retries for the AI scheduler.
# When level-1 retries are exhausted, or a SessionTimeout / fatal AI error
# occurs, the scheduler creates a fresh AI session and resends the full
# prompt.  This is the level-2 retry limit.
scheduler_max_session_retries: {scheduler_max_session_retries}

# Extra rounds allowed after max_rounds is reached (soft overtime).
# Once max_rounds is exceeded, the scheduler prompt includes a warning
# asking the AI to wrap up essential work. After this many extra rounds
# the loop hard-stops.
scheduler_overtime_rounds: {scheduler_overtime_rounds}

# ------------------------------------------------------------
# debug
# ------------------------------------------------------------

# Show console window for autoagent-exec subprocess (Windows only).
# When true, the subprocess launched by autoagent-exec gets its own
# visible console window (via DETACHED_PROCESS flag). Useful for
# debugging long-running commands. Has no effect on Linux/macOS.
# Default: false
autoagent_exec_show_console: {autoagent_exec_show_console}

# ------------------------------------------------------------
# preset
# ------------------------------------------------------------

# Preset configurations
# Each preset can define default values for command-line arguments.
# Use ${{workspace}} to refer to the current working directory.
# Command-line arguments will override preset values.
preset:
  - name: default

  - name: general
    ideas: ${{workspace}}/ideas.md
    config: ${{workspace}}/todos.yaml
    provider: codebuddy
    use_cli: false
    model:
      plan: {default_model}
      default: {default_model}
      lite: {default_model}
      evaluation: {default_model}
      scheduler: {default_model}
    human_review: true  # When processing ideas, force human review After AI review
    verbose: true
"""


def _build_config_yaml() -> str:
    """Render ``_CONFIG_TEMPLATE`` using values from ``DEFAULTS``."""
    tl = DEFAULTS["truncation_limits"]
    values = {
        **DEFAULTS,
        # Flatten nested truncation_limits for the template
        "tl_previous_subtask_summary": tl["previous_subtask_summary"],
        "tl_history_summary": tl["history_summary"],
        "tl_max": tl["max"],
        # Boolean → YAML lowercase
        "autoagent_exec_show_console": str(DEFAULTS["autoagent_exec_show_console"]).lower(),
    }
    return _CONFIG_TEMPLATE.format_map(values)


# The generated config.yaml text — always in sync with DEFAULTS.
DEFAULT_CONFIG_YAML = _build_config_yaml()


def generate_default_config(target_path: str) -> str:
    """Write the default config.yaml to *target_path* (overwriting if exists).

    Args:
        target_path: Absolute or relative path for the output file.

    Returns:
        The absolute path of the written file.
    """
    abs_path = os.path.abspath(target_path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(DEFAULT_CONFIG_YAML)
    return abs_path
