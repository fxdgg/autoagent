"""Stream-JSON parser for OpenCode.

OpenCode format:
  - Event type field: ``type``
  - ``step_start``: session id in ``sessionID`` or ``data.sessionID``
  - ``text``: assistant text in ``part.text``
  - ``tool_use``: tool name in ``part.tool``, input in ``part.state.input``
  - ``tool_result``: output in ``output``
  - ``step_finish``: ``part.reason``, ``part.tokens``, ``part.cost``
"""
from __future__ import annotations

from ai_client.providers.provider_base import ResultInfo, StreamJsonParser, ToolUseInfo


class Parser(StreamJsonParser):

    def get_json_type(self, event: dict) -> list[str]:
        etype = event.get("type", "")
        if etype == "text":
            return ["text"]
        if etype == "tool_use":
            return ["tool_use"]
        if etype == "tool_result":
            return ["tool_result"]
        if etype == "step_finish":
            return ["result"]
        return []

    def parse_text(self, event: dict) -> list[str]:
        text = self._resolve(event, "part.text", "")
        if isinstance(text, str) and text:
            return [text]
        return []

    def parse_thinking(self, event: dict) -> list[str]:
        return []

    def parse_tool_use(self, event: dict) -> list[ToolUseInfo]:
        name = self._resolve(event, "part.tool", "") or self._resolve(event, "part.name", "unknown")
        raw_input = self._resolve(event, "part.state.input", {})
        return [ToolUseInfo(name=name, input=self._parse_input(raw_input))]

    def parse_tool_result(self, event: dict) -> list[str]:
        output = event.get("output", "")
        if isinstance(output, str) and output:
            return [output]
        return []

    def parse_session_id(self, event: dict) -> str | None:
        etype = event.get("type", "")
        if etype == "step_start":
            sid = event.get("sessionID", "")
            if not sid:
                sid = self._resolve(event, "data.sessionID", "")
            if not sid:
                sid = self._resolve(event, "data.sessionId", "")
            return sid if sid else None
        return None

    def parse_result(self, event: dict) -> ResultInfo | None:
        if event.get("type") != "step_finish":
            return None
        reason = self._resolve(event, "part.reason", "stop")
        tokens_info = self._resolve(event, "part.tokens", {})
        total_tokens = 0
        if isinstance(tokens_info, dict):
            total_tokens = tokens_info.get("total", 0)
        cost = self._resolve(event, "part.cost", 0)
        if not isinstance(cost, (int, float)):
            cost = 0
        return ResultInfo(
            is_error=(reason == "error"),
            reason=reason,
            tokens=tokens_info if isinstance(tokens_info, dict) else {},
            cost=cost,
        )

    def is_new_turn(self, event: dict) -> bool:
        return event.get("type") == "text"
