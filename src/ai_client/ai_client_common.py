import os
import yaml

from util.default_value import DEFAULTS


class AICallError(Exception):
    """AI call error (auth failure, response parse failure, etc.)"""

    pass


class BashTimeoutError(AICallError):
    """Raised when the AI produces no new output for bash_timeout seconds.

    This usually means a long-running command is blocking the session.
    The caller should inject long-running-command guidance in the next prompt.
    """

    pass


class SessionTimeoutError(AICallError):
    """Raised when the total session time exceeds session_timeout.

    The caller should tell the AI it was interrupted by the user (Ctrl+C).
    """

    pass


class StreamTimeoutError(AICallError):
    """Raised when the SDK stream times out (no data for an extended period).

    This typically means the AI backend is temporarily unresponsive.
    The session is likely still alive — the caller should continue
    in the same session with a short follow-up prompt rather than
    resetting and replaying the full task prompt.
    """

    pass


class RateLimitError(AICallError):
    """Raised when the AI service returns a transient rate-limit (429) or server error (503).

    These errors are external to the task execution and should NOT consume
    retry attempts.  The backoff mechanism in AIClient/AIClientSDK will
    handle the wait-and-retry automatically.
    """

    pass

def _load_default_model():
    """Load default model from config registry or config.yaml."""
    from util.config_registry import get_config, is_registered
    if is_registered():
        return get_config().get("default_model", DEFAULTS["default_model"])

    # Fallback: load from disk
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config.get("default_model", DEFAULTS["default_model"])
        except Exception:
            pass
    return DEFAULTS["default_model"]


# Default model loaded from config.yaml
DEFAULT_MODEL = _load_default_model()