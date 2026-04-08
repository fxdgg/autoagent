"""
Prompt constants for in-session timeout continuation.

When the AI's session is interrupted by a timeout but the session is still
alive (BashTimeoutError, StreamTimeoutError), we send a lightweight
follow-up *in the same session* instead of resetting and replaying the
entire task prompt.
"""

# ── Bash timeout ────────────────────────────────────────────────────
# The AI ran a command that produced no output for an extended period.
# Typically means the command is too long-running for direct Bash
# execution and should use autoagent-exec instead.
BASH_TIMEOUT_CONTINUATION_PROMPT = (
    "Your previous command was terminated because it produced "
    "no output for an extended period.\n"
    "The command was likely too long-running for direct Bash "
    "execution. Please use autoagent-exec for long-running "
    "commands (see system instructions).\n"
    "Continue working on the task from where you left off.\n"
    "When you are done, end your response with EXACTLY one of:\n"
    "  ✅ completed\n"
    "  ❌ not completed: <reason>\n"
    "  ⏳ LONG_RUNNING_IN_PROGRESS\n"
)

# ── Stream timeout ──────────────────────────────────────────────────
# The SDK's data stream timed out (e.g. "no data received for 120000ms")
# but the session is likely still alive.  The AI may have already
# completed its work — we just need it to continue/confirm.
STREAM_TIMEOUT_CONTINUATION_PROMPT = (
    "Your previous response was interrupted due to a "
    "network/stream timeout.\n"
    "Please continue from where you left off.\n"
    "When you are done, end your response with EXACTLY one of:\n"
    "  ✅ completed\n"
    "  ❌ not completed: <reason>\n"
    "  ⏳ LONG_RUNNING_IN_PROGRESS\n"
)
