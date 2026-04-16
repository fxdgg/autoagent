import os
import yaml


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

def _load_default_model():
    """Load default model from config.yaml."""
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config.get("default_model", "deepseek-v3.2")
        except Exception:
            pass
    return "deepseek-v3.2"


# Default model loaded from config.yaml, fallback to deepseek-v3.2
DEFAULT_MODEL = _load_default_model()