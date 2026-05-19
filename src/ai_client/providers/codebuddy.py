"""Stream-JSON parser for CodeBuddy and Claude Code.

Both tools emit the same stream-JSON format:
  - Event type field: ``type``
  - Session id field: ``session_id`` (on every event)
  - ``assistant`` events: ``message.content[]`` block array with typed blocks
  - ``user`` events: ``message.content[]`` with ``tool_result`` blocks
  - ``result`` events: ``result``, ``is_error``, ``duration_ms``, ``num_turns``
"""
from __future__ import annotations

from ai_client.providers.provider_base import ResultInfo, StreamJsonParser, ToolUseInfo


class Parser(StreamJsonParser):

    def get_json_type(self, event: dict) -> list[str]:
        etype = event.get("type", "")
        if etype == "assistant":
            types: list[str] = []
            for block in self._content_blocks(event):
                bt = block.get("type", "")
                if bt == "text" and "text" not in types:
                    types.append("text")
                elif bt == "thinking" and "thinking" not in types:
                    types.append("thinking")
                elif bt == "tool_use" and "tool_use" not in types:
                    types.append("tool_use")
            return types
        if etype == "user":
            for block in self._content_blocks(event):
                if block.get("type") == "tool_result":
                    return ["tool_result"]
            return []
        if etype == "result":
            return ["result"]
        return []

    def parse_text(self, event: dict) -> list[str]:
        result: list[str] = []
        for block in self._content_blocks(event):
            if block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    result.append(text)
        return result

    def parse_thinking(self, event: dict) -> list[str]:
        result: list[str] = []
        for block in self._content_blocks(event):
            if block.get("type") == "thinking":
                text = block.get("thinking", "")
                if text:
                    result.append(text)
        return result

    def parse_tool_use(self, event: dict) -> list[ToolUseInfo]:
        result: list[ToolUseInfo] = []
        for block in self._content_blocks(event):
            if block.get("type") == "tool_use":
                name = block.get("name", "unknown")
                raw_input = block.get("input", {})
                result.append(ToolUseInfo(name=name, input=self._parse_input(raw_input)))
        return result

    def parse_tool_result(self, event: dict) -> list[str]:
        result: list[str] = []
        for block in self._content_blocks(event):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, str) and content:
                    result.append(content)
        return result

    def parse_session_id(self, event: dict) -> str | None:
        sid = event.get("session_id", "")
        return sid if sid else None

    def parse_result(self, event: dict) -> ResultInfo | None:
        if event.get("type") != "result":
            return None
        is_error = bool(event.get("is_error", False))
        duration_ms = event.get("duration_ms", 0)
        if not isinstance(duration_ms, (int, float)):
            duration_ms = 0
        num_turns = event.get("num_turns", 0)
        if not isinstance(num_turns, (int, float)):
            num_turns = 0
        return ResultInfo(
            is_error=is_error,
            duration_ms=duration_ms,
            num_turns=int(num_turns),
            result_text=event.get("result", ""),
        )

    def is_new_turn(self, event: dict) -> bool:
        return event.get("type") == "assistant"

    # ------------------------------------------------------------------
    @staticmethod
    def _content_blocks(event: dict) -> list[dict]:
        blocks = StreamJsonParser._resolve(event, "message.content")
        if isinstance(blocks, list):
            return [b for b in blocks if isinstance(b, dict)]
        return []
