# -*- coding: utf-8 -*-
"""Tests for cross-provider AI model fallback rotation (design v2).

AIClientTest.ask() 中的 NO_ASSISTANT_TEXT sentinel 分支属前序 completion-marker 修复遗留，非本 fallback 变更引入；本测试套件仅覆盖 FallbackMixin 相关行为。
"""

import argparse
import io
import os
import re
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from ai_providers import CodeBuddyProvider, get_provider
from codebuddy_client import (
    AICallError,
    AIClient,
    FallbackMixin,
    FallbackTarget,
    RateLimitError,
    SessionTimeoutError,
)
from state_manager import StateManager
import orchestrator


PRIMARY_MODEL = "magpie/presence-deepseek/deepseek-v4-1-flash-261017"
FREE_MODEL = "opencode/deepseek-v4.1-flash-free"


def make_client(model=PRIMARY_MODEL):
    """Build a real AIClient (opencode) without touching subprocess."""
    provider = get_provider("opencode", model=model)
    client = AIClient(provider=provider, context_id="fallback-test")
    return client


def run_silently(client, call_fn, **kwargs):
    """Run the fallback chain while swallowing console output."""
    with redirect_stdout(io.StringIO()):
        return client._call_with_fallback(call_fn, **kwargs)


class TestFallbackConfigParsing(unittest.TestCase):
    """AC-1.x: CLI/preset parsing, cross-provider syntax, dedup, defaults."""

    def test_cli_dedup_and_order(self):
        specs = orchestrator.parse_fallback_models("A, B, A")
        self.assertEqual(specs, ["A", "B"])

    def test_provider_colon_split_and_compound_name(self):
        specs = orchestrator.parse_fallback_models(
            "codebuddy:glm-5,opencode/deepseek-v4.1-flash-free"
        )
        self.assertEqual(specs, ["codebuddy:glm-5", FREE_MODEL])

    def test_compound_name_not_split_into_provider(self):
        specs = orchestrator.parse_fallback_models(FREE_MODEL, provider_name="opencode")
        self.assertEqual(specs, [FREE_MODEL])

        client = make_client()
        client.configure_fallback([FREE_MODEL])
        self.assertEqual(len(client._fallback_targets), 1)
        target = client._fallback_targets[0]
        self.assertIsNone(target.provider_name)
        self.assertEqual(target.model, FREE_MODEL)
        self.assertEqual(target.quota_domain, "opencode")

    def test_bare_opencode_model_warning(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            orchestrator.parse_fallback_models(
                "deepseek-v4.1-flash-free", provider_name="opencode"
            )
        self.assertIn("provider/model", buf.getvalue())

    def test_invalid_provider_raises_with_available_list(self):
        with self.assertRaises(ValueError) as ctx:
            orchestrator.parse_fallback_models("bogus:glm-5")
        self.assertIn("bogus", str(ctx.exception))
        self.assertIn("opencode", str(ctx.exception))
        self.assertIn("codebuddy", str(ctx.exception))

    def test_preset_applies_when_cli_default_is_none(self):
        args = argparse.Namespace(
            fallback_models=None,
            config="todos.yaml",
            provider="codebuddy",
            workspace=".",
            idle_interval=30,
            verbose=False,
            no_skip=False,
            no_idle=False,
            use_cli=False,
            ideas_only=False,
            human_review=False,
        )
        preset = {"fallback_models": [FREE_MODEL]}
        merged = orchestrator._merge_preset_with_args(args, preset)
        self.assertEqual(merged.fallback_models, [FREE_MODEL])

        # CLI value wins over preset
        cli_args = argparse.Namespace(**vars(args))
        cli_args.fallback_models = "codebuddy:glm-5"
        merged_cli = orchestrator._merge_preset_with_args(cli_args, preset)
        self.assertEqual(merged_cli.fallback_models, "codebuddy:glm-5")

    def test_argparse_default_none_and_defaults_not_set(self):
        with open(
            os.path.join(os.path.dirname(__file__), "..", "orchestrator.py"),
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            source = handle.read()
        match = re.search(
            r"add_argument\(\s*'--fallback-models',(.*?)\n\s*\)", source, re.S
        )
        self.assertIsNotNone(match, "--fallback-models argument missing")
        self.assertIn("default=None", match.group(1))
        self.assertIn("'fallback_models': 'fallback_models'", source)
        self.assertIn("'fallback_models': None", source)

    def test_normalize_filters_primary_and_blanks(self):
        client = make_client()
        client.configure_fallback([PRIMARY_MODEL, "", "   ", FREE_MODEL, FREE_MODEL])
        self.assertEqual([t.model for t in client._fallback_targets], [FREE_MODEL])


class TestFallbackRotation(unittest.TestCase):
    """AC-2.x / AC-3.x: rotation, cross-domain, cross-provider, sticky."""

    def test_no_fallback_behavior_unchanged(self):
        client = make_client()
        client.configure_fallback([])
        calls = []

        def call_fn(**kwargs):
            calls.append(kwargs)
            raise SessionTimeoutError("primary down")

        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SessionTimeoutError):
                client._call_with_fallback(call_fn, prompt="p", system_prompt="s")
        self.assertEqual(len(calls), 1)
        self.assertEqual(buf.getvalue(), "")

    def test_primary_fail_fallback_success(self):
        client = make_client()
        client.configure_fallback(FREE_MODEL)
        seen_models = []

        def call_fn(**kwargs):
            seen_models.append(client.provider.model)
            if len(seen_models) == 1:
                raise SessionTimeoutError("primary down")
            return "ok"

        result = run_silently(client, call_fn, prompt="p")
        self.assertEqual(result, "ok")
        self.assertEqual(seen_models, [PRIMARY_MODEL, FREE_MODEL])
        self.assertEqual(client.provider.model, FREE_MODEL)  # sticky
        self.assertEqual(client._consecutive_failures, 0)

    def test_all_failed_raises_primary_and_no_wrap(self):
        client = make_client()
        client.configure_fallback(["opencode/fallback-a", "opencode/fallback-b"])
        seen_models = []

        def call_fn(**kwargs):
            seen_models.append(client.provider.model)
            if len(seen_models) == 1:
                raise RateLimitError("primary rate limited")
            raise AICallError("fallback %d failed" % len(seen_models))

        with redirect_stdout(io.StringIO()):
            with self.assertRaises(RateLimitError) as ctx:
                client._call_with_fallback(call_fn, prompt="p")
        self.assertEqual(
            seen_models,
            [PRIMARY_MODEL, "opencode/fallback-a", "opencode/fallback-b"],
        )
        self.assertIn("fallback exhausted", str(ctx.exception))
        self.assertIn("opencode/fallback-b", str(ctx.exception))
        self.assertEqual(client.provider.model, PRIMARY_MODEL)  # restored

    def test_rate_limit_triggers_fallback_success(self):
        client = make_client()
        client.configure_fallback(FREE_MODEL)
        calls = []

        def call_fn(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RateLimitError("429 rate limit")
            return "ok"

        self.assertEqual(run_silently(client, call_fn, prompt="p"), "ok")
        self.assertEqual(len(calls), 2)

    def test_quota_403_triggers_cross_domain(self):
        client = make_client()
        client.configure_fallback(FREE_MODEL)
        seen_domains = []

        def call_fn(**kwargs):
            seen_domains.append(client.provider.model.split("/", 1)[0])
            if len(seen_domains) == 1:
                raise AICallError("403 token quota is not enough")
            return "ok"

        result = run_silently(client, call_fn, prompt="p")
        self.assertEqual(result, "ok")
        self.assertEqual(seen_domains, ["magpie", "opencode"])
        self.assertIn("magpie", client._exhausted_quota_domains)

    def test_auth_misjudge_triggers_fallback(self):
        client = make_client()
        client.configure_fallback(FREE_MODEL)
        calls = []

        def call_fn(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise AICallError(
                    "opencode authentication required ... step_start ..."
                )
            return "ok"

        self.assertEqual(run_silently(client, call_fn, prompt="p"), "ok")
        self.assertEqual(len(calls), 2)

    def test_cross_provider_switch_uses_resolver(self):
        client = make_client(model="opencode/some-model")
        resolver_calls = []

        def resolver(name, model, executable, extra_args):
            resolver_calls.append((name, model, executable, extra_args))
            return CodeBuddyProvider(model=model, executable=executable)

        client.configure_fallback(
            [
                {
                    "provider": "codebuddy",
                    "model": "glm-5",
                    "executable": "codebuddy-cli",
                    "extra_args": "--verbose",
                }
            ],
            provider_resolver=resolver,
        )
        calls = []

        def call_fn(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise SessionTimeoutError("down")
            return "ok"

        self.assertEqual(run_silently(client, call_fn, prompt="p"), "ok")
        self.assertEqual(
            resolver_calls,
            [("codebuddy", "glm-5", "codebuddy-cli", "--verbose")],
        )
        self.assertIsInstance(client.provider, CodeBuddyProvider)
        self.assertEqual(client.provider.model, "glm-5")

    def test_cross_provider_colon_form_and_switch_failure_skipped(self):
        client = make_client(model="opencode/some-model")
        calls = []

        def resolver(name, model, executable, extra_args):
            raise ValueError("unknown provider " + name)

        def call_fn(**kwargs):
            calls.append(client.provider.model)
            if len(calls) == 1:
                raise SessionTimeoutError("down")
            return "ok"

        client.configure_fallback("codebuddy:glm-5", provider_resolver=resolver)
        # resolver fails -> candidate skipped -> all failed -> primary exception
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(SessionTimeoutError):
                client._call_with_fallback(call_fn, prompt="p")
        self.assertEqual(calls, ["opencode/some-model"])

    def test_fallback_containing_primary_is_filtered(self):
        client = make_client()
        client.configure_fallback([PRIMARY_MODEL])
        self.assertEqual(client._fallback_candidates().__len__(), 1)

    def test_sdk_path_uses_same_mixin(self):
        self.assertTrue(issubclass(orchestrator.AIClientSDK, FallbackMixin))
        self.assertTrue(issubclass(AIClient, FallbackMixin))


class TestFallbackSemantics(unittest.TestCase):
    """AC-4.x / AC-5.x / AC-6.x / AC-8.x: backoff, session, circuit breaker."""

    def test_backoff_reset_on_switch_and_restore_on_exhaust(self):
        client = make_client()
        client.configure_fallback(["opencode/fallback-a", "opencode/fallback-b"])
        base_failures = 3
        client._consecutive_failures = base_failures
        observed = []
        sleeps = []

        def fake_ask_once(**kwargs):
            """Mirror _ask_once's backoff prologue (C-5: real backoff logic)."""
            observed.append(client._consecutive_failures)
            if client._consecutive_failures > 0:
                delay = min(5 * (2 ** (client._consecutive_failures - 1)), 300)
                sleeps.append(delay)
                time.sleep(delay)
            client._consecutive_failures += 1
            raise AICallError("fail")

        with patch("codebuddy_client.time.sleep") as sleep_mock:
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(AICallError):
                    client._call_with_fallback(fake_ask_once, prompt="p")
        self.assertEqual(observed, [base_failures, 0, 0])
        self.assertEqual(sleeps, [5 * (2 ** (base_failures - 1))])
        sleep_mock.assert_called_once()
        self.assertEqual(client._consecutive_failures, base_failures + 1)

    def test_session_rollback_memory_and_persist(self):
        client = make_client()
        restored = []
        client.resume_session("mem-original")
        client.configure_fallback(
            FREE_MODEL,
            on_session_restore=lambda session_id: restored.append(session_id),
            persistent_session_getter=lambda: "persist-original",
        )
        resets = []
        original_reset = client.reset_session

        def tracking_reset():
            resets.append(client._session_id)
            original_reset()

        client.reset_session = tracking_reset

        def call_fn(**kwargs):
            client._session_id = "polluted-session"
            raise AICallError("fail")

        with redirect_stdout(io.StringIO()):
            with self.assertRaises(AICallError):
                client._call_with_fallback(call_fn, prompt="p")
        self.assertEqual(client._session_id, "mem-original")
        self.assertEqual(restored, ["persist-original"])
        self.assertEqual(len(resets), 1)

    def test_session_rollback_without_restore_callback_degrades(self):
        client = make_client()
        client.resume_session("mem-original")
        client.configure_fallback(FREE_MODEL)

        def call_fn(**kwargs):
            client._session_id = "polluted-session"
            raise AICallError("fail")

        with redirect_stdout(io.StringIO()):
            with self.assertRaises(AICallError):
                client._call_with_fallback(call_fn, prompt="p")
        self.assertEqual(client._session_id, "mem-original")

    def test_prompt_not_duplicated_across_fallback(self):
        client = make_client()
        client.configure_fallback(FREE_MODEL)
        prompts = []

        def fake_ask_once(prompt, expect_json=False, timeout=None, system_prompt=None, **kwargs):
            """Mirror _ask_once prompt assembly from the ORIGINAL arguments."""
            if system_prompt and not client.provider.supports_system_prompt:
                prompt = prompt + "\n\n" + system_prompt
                system_prompt = None
            prompts.append((prompt, system_prompt))
            if len(prompts) == 1:
                raise AICallError("fail")
            return "ok"

        with patch.object(client, "_ask_once", side_effect=fake_ask_once):
            result = client.ask("TASK", system_prompt="SYS")

        self.assertEqual(result, "ok")
        self.assertEqual(prompts, [("TASK\n\nSYS", None), ("TASK\n\nSYS", None)])
        for prompt, __ in prompts:
            self.assertEqual(prompt.count("SYS"), 1)

    def test_circuit_breaker_skips_exhausted_domain(self):
        client = make_client()
        client.configure_fallback(["opencode/fb-free", "magpie/fb-exhausted", "codebuddy:fb-last"])

        def resolver(name, model, executable, extra_args):
            return CodeBuddyProvider(model=model)

        client._fallback_resolver = resolver

        # Round 1: magpie 403 -> breaker; opencode 403 -> breaker; codebuddy succeeds.
        calls1 = []

        def first(**kwargs):
            calls1.append(client.provider.model)
            if len(calls1) <= 2:
                raise AICallError("403 token quota is not enough")
            return "ok"

        self.assertEqual(run_silently(client, first, prompt="p1"), "ok")
        self.assertEqual(
            calls1, [PRIMARY_MODEL, "opencode/fb-free", "fb-last"]
        )
        self.assertEqual(client._exhausted_quota_domains, {"magpie", "opencode"})

        # Simulate next task: primary reset (AC-8.3: primary still tried once).
        client.provider.set_model(PRIMARY_MODEL)
        calls2 = []

        def second(**kwargs):
            calls2.append(client.provider.model)
            if len(calls2) == 1:
                raise AICallError("still 403")
            return "ok"

        skip_log = io.StringIO()
        with redirect_stdout(skip_log):
            result = client._call_with_fallback(second, prompt="p2")
        self.assertEqual(result, "ok")
        self.assertEqual(calls2, [PRIMARY_MODEL, "fb-last"])
        self.assertNotIn("magpie/fb-exhausted", calls2)
        self.assertNotIn("opencode/fb-free", calls2)
        self.assertIn("skip exhausted domain: magpie", skip_log.getvalue())

    def test_switch_log_contains_context(self):
        client = make_client()
        client.configure_fallback(FREE_MODEL)
        buf = io.StringIO()
        calls = []

        def call_fn(**kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise SessionTimeoutError("down")
            return "ok"

        with redirect_stdout(buf):
            client._call_with_fallback(call_fn, prompt="p")
        output = buf.getvalue()
        self.assertIn("fallback-test", output)
        self.assertIn(PRIMARY_MODEL, output)
        self.assertIn(FREE_MODEL, output)
        self.assertIn("SessionTimeoutError", output)


class TestCreationPointCoverage(unittest.TestCase):
    """AC-7.1 (F-1): all 6 non-Test creation points configured, Test untouched."""

    def test_all_six_creation_points_configured(self):
        with open(
            os.path.join(os.path.dirname(__file__), "..", "orchestrator.py"),
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            lines = handle.read().splitlines()

        create_re = re.compile(r"^\s*(client|review_client) = AIClient(SDK)?\($")
        non_test = 0
        for index, line in enumerate(lines):
            if not create_re.match(line):
                continue
            non_test += 1
            variable = "review_client" if "review_client" in line else "client"
            backoff = variable + "._backoff_max = self.backoff_max_wait"
            found = False
            for cursor in range(index, min(index + 15, len(lines))):
                if backoff in lines[cursor]:
                    self.assertIn(
                        "configure_fallback(",
                        lines[cursor + 1],
                        "creation point at line %d not configured" % (index + 1),
                    )
                    found = True
                    break
            self.assertTrue(found, "no backoff anchor after line %d" % (index + 1))
        self.assertEqual(non_test, 6)

        test_points = [line for line in lines if "= AIClientTest(" in line]
        self.assertEqual(len(test_points), 3)

    def test_main_cli_creation_point_configured(self):
        """User opencode path: use_cli=True -> AIClient at main task."""
        with open(
            os.path.join(os.path.dirname(__file__), "..", "orchestrator.py"),
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            lines = handle.read().splitlines()
        for index, line in enumerate(lines):
            if "client = AIClient(" in line:
                window = "\n".join(lines[index:index + 15])
                if "context_id=context_id," in window:
                    self.assertIn("configure_fallback(", window)
                    self.assertIn("on_session_restore=on_session_restore", window)
                    return
        self.fail("main CLI AIClient creation point not found")


class TestNoRerunWithRealState(unittest.TestCase):
    """AC-9.1/9.2: completed subtasks skipped, failed/in_progress redone.

    Fallback is orthogonal to skip: it only fires for calls that are actually
    issued.  Uses a copy of the real h8hplirg state, never the live file.
    """

    REAL_STATE = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            ".autoagent",
            "autoagent_h8hplirg",
            "todos_state.yaml",
        )
    )

    def test_no_rerun_completed_subtask_uses_product_skip_rule(self):
        if not os.path.exists(self.REAL_STATE):
            self.skipTest("real h8hplirg state not available")

        temp_dir = tempfile.mkdtemp(prefix="fallback-state-")
        try:
            state_copy = os.path.join(temp_dir, "todos_state.yaml")
            shutil.copy2(self.REAL_STATE, state_copy)
            state_manager = StateManager(state_copy)

            self.assertEqual(
                state_manager.get_task_state("1").get("status"), "in_progress"
            )
            self.assertEqual(
                state_manager.get_task_state("1.1@1.1").get("status"), "completed"
            )
            self.assertEqual(
                state_manager.get_task_state("1.1@1.2").get("status"), "completed"
            )
            self.assertEqual(
                state_manager.get_task_state("1.2@1.1").get("status"), "failed"
            )
            self.assertEqual(
                state_manager.get_task_state("1.2@1.2").get("status"), "in_progress"
            )

            keys = ["1", "1.1@1.1", "1.1@1.2", "1.2@1.1", "1.2@1.2"]
            call_log = []

            for key in keys:
                subtask_state = state_manager.get_task_state(key)
                # 逐字复制产品判定表达式（来源 task_executor.py:1281）：
                # Skip already completed subtasks (in this round)
                if subtask_state.get('status') == 'completed':
                    continue

                client = make_client()
                client.configure_fallback(FREE_MODEL)
                per_call = []

                def fake(**kwargs):
                    per_call.append(client.provider.model)
                    call_log.append((key, client.provider.model))
                    if len(per_call) == 1:
                        raise AICallError("403 token quota is not enough")
                    return "ok"

                result = run_silently(client, fake, prompt="p")
                self.assertEqual(result, "ok")
                self.assertEqual(per_call, [PRIMARY_MODEL, FREE_MODEL])

            logged_keys = {key for key, __ in call_log}
            self.assertNotIn("1.1@1.1", logged_keys)
            self.assertNotIn("1.1@1.2", logged_keys)
            self.assertIn("1.2@1.1", logged_keys)
            self.assertIn("1.2@1.2", logged_keys)
            self.assertIn("1", logged_keys)
        finally:
            shutil.rmtree(temp_dir)


class TestHelperTypes(unittest.TestCase):
    """Basic invariants of the new helper types."""

    def test_fallback_target_domain_from_compound_name(self):
        target = FallbackTarget(model=FREE_MODEL)
        self.assertEqual(target.quota_domain, "opencode")
        target = FallbackTarget(model="glm-5", provider_name="codebuddy")
        self.assertEqual(target.quota_domain, "codebuddy")

    def test_should_fallback_accepts_all_ai_call_errors(self):
        self.assertTrue(FallbackMixin.should_fallback(AICallError("x")))
        self.assertTrue(FallbackMixin.should_fallback(RateLimitError("x")))
        self.assertTrue(FallbackMixin.should_fallback(SessionTimeoutError("x")))
        self.assertFalse(FallbackMixin.should_fallback(ValueError("x")))


if __name__ == "__main__":
    unittest.main()
