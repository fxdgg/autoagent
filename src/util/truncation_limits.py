"""Centralized truncation limits loaded from config.yaml.

Usage:
    from truncation_limits import limits
    limits.get('max')  # returns configured value or default
"""

import os
import yaml

from util.default_value import DEFAULTS as _GLOBAL_DEFAULTS

_DEFAULTS = {
    **_GLOBAL_DEFAULTS['truncation_limits'],
    'log_promptlike_preview': 200,
    'log_tool_result': 1000,
    'idea_yaml_preview': 4000,
}


def _load():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml")
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
