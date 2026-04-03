"""
Prompt constants for the marker-nudge mechanism.

When the AI finishes its work but forgets to emit a completion status
marker, we send a lightweight follow-up *in the same session* instead
of resetting and replaying the entire task.  This module holds the
prompt text and tuning knobs for that mechanism.
"""

import os
import logging

import yaml

logger = logging.getLogger(__name__)

# Default number of lightweight nudge attempts before falling back to
# the normal retry loop (which resets the session).
_DEFAULT_MAX_MARKER_NUDGES = 2


def _load_max_marker_nudges() -> int:
    """Load ``max_marker_nudges`` from config.yaml.

    Falls back to ``_DEFAULT_MAX_MARKER_NUDGES`` if the key is missing
    or the file cannot be read.
    """
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.yaml",
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            val = config.get("max_marker_nudges")
            if val is not None:
                return int(val)
        except Exception as e:
            logger.warning(f"Failed to load max_marker_nudges from config.yaml: {e}")
    return _DEFAULT_MAX_MARKER_NUDGES


MAX_MARKER_NUDGES = _load_max_marker_nudges()

# The nudge prompt is deliberately minimal — it adds only a few dozen
# tokens to the existing session context instead of replaying the whole
# task description.
MARKER_NUDGE_PROMPT = (
    "Your previous response did not end with a status marker (possibly "
    "due to an unexpected interruption).\n"
    "Review what you have done so far against the completion criteria. "
    "You may read files or run commands to verify.\n"
    "\n"
    "CRITICAL: Do NOT re-run any command you have already executed. "
    "In particular, NEVER call autoagent-exec again — if you already "
    "called it (regardless of what output you saw), the background task "
    "is already running. Just reply with: ⏳ LONG_RUNNING_IN_PROGRESS\n"
    "\n"
    "If the task is not yet finished and you did NOT use autoagent-exec, "
    "continue working on it until it is done (or you are sure it cannot "
    "be completed).\n"
    "When you are done, end your response with EXACTLY one of:\n"
    "  ✅ completed\n"
    "  ❌ not completed: <reason>\n"
    "  ⏳ LONG_RUNNING_IN_PROGRESS\n"
)
