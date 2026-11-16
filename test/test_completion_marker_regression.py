"""Regression tests for the opencode completion-marker infinite loop.

Covers the tool-only-turn sentinel contract end to end: AIClient.ask()
returns a sentinel instead of falling back to raw stdout, _check_completion()
recognises it as a fourth state, and _nudge_for_marker() converges.
"""

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from ai_providers import get_provider
from codebuddy_client import (
    AICallError,
    AIClient,
    NO_ASSISTANT_TEXT,
    is_no_assistant_text,
)
from prompts.marker_nudge import TOOL_ONLY_NUDGE_PROMPT
from task_executor import SimpleTaskExecutor, TOOL_ONLY_TURN


def _stream(*events):
    """Serialise stream-json events into a raw CLI stdout string."""
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"


def _tool_only_stream(tool_output="On branch main"):
    """Build an opencode turn that only called tools and emitted no text event."""
    return _stream(
        {"type": "step_start", "sessionID": "s1"},
        {
            "type": "tool_use",
            "part": {
                "tool": "bash",
                "state": {"input": {"command": "git status"}},
            },
        },
        {"type": "tool_result", "status": "success", "output": tool_output},
        {
            "type": "step_finish",
            "part": {"reason": "stop", "tokens": {"total": 91481}, "cost": 0},
        },
    )


TOOL_ONLY_STREAM = _tool_only_stream()
TEXT_JSON_STREAM = _stream(
    {"type": "step_start", "sessionID": "s1"},
    {
        "type": "text",
        "part": {"text": '{"decision": "retry", "analysis": "more work needed"}'},
    },
    {
        "type": "step_finish",
        "part": {"reason": "stop", "tokens": {"total": 100}, "cost": 0},
    },
)


class _FakeProcess:
    """Minimal subprocess.Popen stand-in used by AIClient.ask()."""

    def __init__(self, raw_stream):
        self.stdout = io.StringIO(raw_stream)
        self.stderr = io.StringIO("")
        self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class CompletionMarkerRegressionTest(unittest.TestCase):
    """T1-T11 from design.md section 6."""

    @staticmethod
    def _new_client():
        return AIClient(provider=get_provider("codebuddy"), context_id="regression")

    def _ask(self, raw_stream, expect_json=False):
        client = self._new_client()
        with patch("subprocess.Popen", return_value=_FakeProcess(raw_stream)):
            return client, client.ask("do the task", expect_json=expect_json)

    @staticmethod
    def _new_executor():
        # _check_completion / _nudge_for_marker need no __init__ state.
        return SimpleTaskExecutor.__new__(SimpleTaskExecutor)

    def _run_tool_only_nudge(self, executor, client, max_nudges=2):
        with patch.object(
            executor, "_check_signal_file_for_running_task", return_value=None
        ):
            return executor._nudge_for_marker(
                client,
                {"id": "task-1", "name": "regression task"},
                "previous tool-only response",
                max_nudges=max_nudges,
                tool_only=True,
            )

    # --- T1 ----------------------------------------------------------------
    def test_t1_tool_only_turn_returns_sentinel_and_preserves_full_log(self):
        client, result = self._ask(TOOL_ONLY_STREAM)
        self.assertEqual(result, NO_ASSISTANT_TEXT)
        self.assertTrue(is_no_assistant_text(result))
        self.assertIn("✅ Done", client.last_full_log)
        self.assertNotEqual(client.last_full_log, NO_ASSISTANT_TEXT)

    # --- T2 ----------------------------------------------------------------
    def test_t2_tool_output_with_fail_still_returns_sentinel(self):
        _, result = self._ask(_tool_only_stream("build failed: 3 tests fail"))
        self.assertTrue(is_no_assistant_text(result))
        self.assertEqual(result, NO_ASSISTANT_TEXT)

    # --- T3 ----------------------------------------------------------------
    def test_t3_tool_output_without_fail_still_returns_sentinel(self):
        # Before the fix, raw stdout contained "✅ Done" with no "fail", so
        # _check_completion Layer 3 misjudged this as a completed task.
        _, result = self._ask(_tool_only_stream("all checks done successfully"))
        self.assertTrue(is_no_assistant_text(result))

    # --- T4 ----------------------------------------------------------------
    def test_t4_raw_stdout_marker_line_is_not_fallback(self):
        raw = "✅ completed\n" + TOOL_ONLY_STREAM
        _, result = self._ask(raw)
        self.assertTrue(is_no_assistant_text(result))
        self.assertNotEqual(result, "✅ completed")

    # --- T5 ----------------------------------------------------------------
    def test_t5_expect_json_without_text_raises_aicallerror(self):
        client = self._new_client()
        with patch("subprocess.Popen", return_value=_FakeProcess(TOOL_ONLY_STREAM)):
            with self.assertRaises(AICallError) as ctx:
                client.ask("do the task", expect_json=True)
        self.assertIn("no assistant text", str(ctx.exception))

    # --- T6 ----------------------------------------------------------------
    def test_t6_normal_text_json_path_still_returns_dict(self):
        _, result = self._ask(TEXT_JSON_STREAM, expect_json=True)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["decision"], "retry")

    # --- T7 ----------------------------------------------------------------
    def test_t7_sentinel_constant_contract(self):
        self.assertNotIn("{", NO_ASSISTANT_TEXT)
        self.assertNotIn("}", NO_ASSISTANT_TEXT)
        self.assertNotIn("✅", NO_ASSISTANT_TEXT)
        self.assertIs(
            self._new_executor()._check_completion(NO_ASSISTANT_TEXT), TOOL_ONLY_TURN
        )

    # --- T8 ----------------------------------------------------------------
    def test_t8_check_completion_four_states(self):
        executor = self._new_executor()
        self.assertIs(executor._check_completion("✅ completed"), True)
        self.assertIs(executor._check_completion("❌ not completed"), False)
        self.assertIsNone(executor._check_completion("plain text without marker"))
        self.assertIs(executor._check_completion(NO_ASSISTANT_TEXT), TOOL_ONLY_TURN)

    # --- T9 ----------------------------------------------------------------
    def test_t9_tool_only_nudge_converges_after_max_nudges(self):
        executor = self._new_executor()
        client = MagicMock()
        client.ask.return_value = NO_ASSISTANT_TEXT
        client.last_full_log = ""

        result = self._run_tool_only_nudge(executor, client, max_nudges=2)

        self.assertEqual(client.ask.call_count, 2)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("❌ not completed:"))
        self.assertIs(executor._check_completion(result), False)

    # --- T10 ---------------------------------------------------------------
    def test_t10_tool_only_nudge_uses_strengthened_prompt(self):
        executor = self._new_executor()
        client = MagicMock()
        client.ask.return_value = NO_ASSISTANT_TEXT
        client.last_full_log = ""

        self._run_tool_only_nudge(executor, client, max_nudges=2)

        self.assertIs(client.ask.call_args[0][0], TOOL_ONLY_NUDGE_PROMPT)
        self.assertIn(
            "你上一回合只执行了工具而没有输出任何文本，这是不被接受的",
            TOOL_ONLY_NUDGE_PROMPT,
        )
        self.assertIn("Do NOT call any tool", TOOL_ONLY_NUDGE_PROMPT)
        self.assertIn("TEXT ONLY", TOOL_ONLY_NUDGE_PROMPT)

    # --- T11 ---------------------------------------------------------------
    def test_t11_static_coverage_guard(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "task_executor.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual(source.count("_check_completion("), 9)
        self.assertGreaterEqual(source.count("is TOOL_ONLY_TURN"), 8)


if __name__ == "__main__":
    unittest.main()
