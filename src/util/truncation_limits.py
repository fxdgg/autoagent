"""Centralized truncation limits loaded from config.yaml.

Usage:
    from truncation_limits import limits
    limits.get('max')  # returns configured value or default
"""

import os
import yaml

_DEFAULTS = {
    'previous_subtask_summary': 4000,
    'previous_attempt_output': 4000,
    'history_summary': 300,
    'max': 50000,
}


def _load():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return config.get('truncation_limits', {})
        except Exception:
            pass
    return {}


class _Limits:
    def __init__(self):
        self._overrides = _load()

    def get(self, key: str) -> int:
        return self._overrides.get(key, _DEFAULTS.get(key, 2000))

    def reload(self):
        self._overrides = _load()


limits = _Limits()
