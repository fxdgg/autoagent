"""Centralized truncation limits loaded from config.yaml.

Usage:
    from truncation_limits import limits
    limits.get('suggested_fix')  # returns configured value or default
"""

import os
import yaml

_DEFAULTS = {
    'suggested_fix': 1500,
    'history_summary': 300,
    'nested_latest_fix': 2000,
    'looping_latest_fix': 1500,
    'log_section': 6000,
    'execution_results': 4000,
    'idea_content': 8000,
    'tasks_yaml': 10000,
    'review_feedback': 3000,
    'human_feedback': 3000,
    'error_text': 2000,
    'log_file': 2000,
    'previous_subtask_summary': 4000,
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
