"""Stream-JSON parser for Gemini CLI.

Gemini CLI format:
  - Event type field: ``type``
  - Session id field: ``session_id`` (on every event)
  - ``message`` events with ``role`` gate (only ``assistant`` is meaningful)
  - ``tool_use`` events: top-level ``tool_name``/``parameters``
  - ``tool_result`` events: top-level ``output``
  - ``result`` events: ``stats.duration_ms``, ``stats.tool_calls``
"""
from __future__ import annotations

from ai_client.providers.provider_base import ResultInfo, StreamJsonParser, ToolUseInfo


class Parser(StreamJsonParser):

    def get_json_type(self, event: dict) -> list[str]:
        etype = event.get("type", "")
        if etype == "message":
            if event.get("role") == "assistant":
                return ["text"]
            return []
        if etype == "tool_use":
            return ["tool_use"]
        if etype == "tool_result":
            return ["tool_result"]
        if etype == "result":
            return ["result"]
        return []

    def parse_text(self, event: dict) -> list[str]:
        text = event.get("content", "")
        if isinstance(text, str) and text:
            return [text]
        return []

    def parse_thinking(self, event: dict) -> list[str]:
        return []

    def parse_tool_use(self, event: dict) -> list[ToolUseInfo]:
        name = event.get("tool_name", "") or event.get("name", "unknown")
        raw_input = event.get("parameters", {}) or event.get("input", {})
        return [ToolUseInfo(name=name, input=self._parse_input(raw_input))]

    def parse_tool_result(self, event: dict) -> list[str]:
        output = event.get("output", "")
        if isinstance(output, str) and output:
            return [output]
        return []

    def parse_session_id(self, event: dict) -> str | None:
        sid = event.get("session_id", "")
        return sid if sid else None

    def parse_result(self, event: dict) -> ResultInfo | None:
        if event.get("type") != "result":
            return None
        is_error = event.get("status") == "error"
        duration_ms = self._resolve(event, "stats.duration_ms", 0)
        if not isinstance(duration_ms, (int, float)):
            duration_ms = 0
        num_turns = self._resolve(event, "stats.tool_calls", 0)
        if not isinstance(num_turns, (int, float)):
            num_turns = 0
        return ResultInfo(
            is_error=is_error,
            duration_ms=duration_ms,
            num_turns=int(num_turns),
            result_text=event.get("result", ""),
        )

    def is_new_turn(self, event: dict) -> bool:
        return event.get("type") == "message" and event.get("role") == "assistant"
