"""Base class for stream-JSON provider parsers."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolUseInfo:
    name: str
    input: dict


@dataclass
class ResultInfo:
    is_error: bool = False
    duration_ms: float = 0
    num_turns: int = 0
    tokens: dict = field(default_factory=dict)
    cost: float = 0
    reason: str = ""
    result_text: str = ""


class StreamJsonParser(ABC):
    """Abstract base for parsing stream-JSON events from a CLI provider.

    Each concrete subclass handles one stream-JSON dialect.  The caller
    invokes methods in this order for every JSON line:

    1. ``parse_session_id(event)`` — always called, extracts session id.
    2. ``is_new_turn(event)`` — always called, signals turn boundary.
    3. ``get_json_type(event)`` — returns semantic types present in this
       event (e.g. ``["text", "tool_use"]``).  If empty, the caller
       skips all remaining parse calls.
    4. For each type returned by ``get_json_type``, the matching
       ``parse_*`` method is called.
    """

    @abstractmethod
    def get_json_type(self, event: dict) -> list[str]:
        """Return semantic types present in *event*.

        Valid type strings: ``"text"``, ``"thinking"``, ``"tool_use"``,
        ``"tool_result"``, ``"result"``.
        """
        ...

    @abstractmethod
    def parse_text(self, event: dict) -> list[str]:
        """Extract assistant text strings from *event*."""
        ...

    @abstractmethod
    def parse_thinking(self, event: dict) -> list[str]:
        """Extract thinking/reasoning strings from *event*."""
        ...

    @abstractmethod
    def parse_tool_use(self, event: dict) -> list[ToolUseInfo]:
        """Extract tool use entries from *event*."""
        ...

    @abstractmethod
    def parse_tool_result(self, event: dict) -> list[str]:
        """Extract tool result output strings from *event*."""
        ...

    @abstractmethod
    def parse_session_id(self, event: dict) -> str | None:
        """Extract session/thread id from *event*, or ``None``."""
        ...

    @abstractmethod
    def parse_result(self, event: dict) -> ResultInfo | None:
        """Extract finish/result summary from *event*, or ``None``."""
        ...

    @abstractmethod
    def is_new_turn(self, event: dict) -> bool:
        """Return ``True`` if *event* marks a new assistant turn."""
        ...

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve(obj: Any, path: str, default: Any = None) -> Any:
        """Resolve a dot-separated path against a nested dict."""
        if not path:
            return default
        current = obj
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return default
            if current is None:
                return default
        return current

    @staticmethod
    def _parse_input(raw: Any) -> dict:
        """Normalise a tool input value to a dict."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return {"command": raw}
        return {}
