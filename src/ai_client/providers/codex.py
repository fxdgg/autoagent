"""Stream-JSON parser for Codex.

Codex format:
  - Event type field: ``type``
  - ``thread.started``: session id in ``thread_id``
  - ``item.completed``: sub-type dispatch on ``item.type``:
      - ``agent_message``: text in ``item.text``
      - ``command_execution``: tool name hardcoded ``Bash``, input is ``item.command``
      - ``tool_call``: tool name in ``item.name``, input in ``item.arguments``
      - ``tool_call_output``: output in ``item.output``
  - ``turn.completed``: token usage in ``usage``
"""
from __future__ import annotations

from ai_client.providers.provider_base import ResultInfo, StreamJsonParser, ToolUseInfo


class Parser(StreamJsonParser):

    def get_json_type(self, event: dict) -> list[str]:
        etype = event.get("type", "")
        if etype == "item.completed":
            item_type = self._resolve(event, "item.type", "")
            if item_type == "agent_message":
                return ["text"]
            if item_type == "command_execution":
                return ["tool_use", "tool_result"]
            if item_type == "tool_call":
                return ["tool_use"]
            if item_type == "tool_call_output":
                return ["tool_result"]
            return []
        if etype == "turn.completed":
            return ["result"]
        if etype == "thread.started":
            return []
        return []

    def parse_text(self, event: dict) -> list[str]:
        text = self._resolve(event, "item.text", "")
        if isinstance(text, str) and text:
            return [text]
        return []

    def parse_thinking(self, event: dict) -> list[str]:
        return []

    def parse_tool_use(self, event: dict) -> list[ToolUseInfo]:
        item_type = self._resolve(event, "item.type", "")
        if item_type == "command_execution":
            command = self._resolve(event, "item.command", "")
            return [ToolUseInfo(name="Bash", input={"command": command})]
        if item_type == "tool_call":
            name = self._resolve(event, "item.name", "") or self._resolve(event, "item.tool_name", "unknown")
            raw_input = self._resolve(event, "item.arguments", {}) or self._resolve(event, "item.input", {})
            return [ToolUseInfo(name=name, input=self._parse_input(raw_input))]
        return []

    def parse_tool_result(self, event: dict) -> list[str]:
        item_type = self._resolve(event, "item.type", "")
        if item_type == "command_execution":
            output = self._resolve(event, "item.aggregated_output", "")
            if isinstance(output, str) and output:
                return [output]
            return []
        if item_type == "tool_call_output":
            output = self._resolve(event, "item.output", "") or self._resolve(event, "item.result", "")
            if isinstance(output, str) and output:
                return [output]
            return []
        return []

    def parse_session_id(self, event: dict) -> str | None:
        if event.get("type") == "thread.started":
            tid = event.get("thread_id", "")
            return tid if tid else None
        return None

    def parse_result(self, event: dict) -> ResultInfo | None:
        if event.get("type") != "turn.completed":
            return None
        usage = event.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return ResultInfo(
            tokens=usage,
        )

    def is_new_turn(self, event: dict) -> bool:
        return (
            event.get("type") == "item.completed"
            and self._resolve(event, "item.type") == "agent_message"
        )
