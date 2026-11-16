"""Tests for the --auto permission flag added to OpenCodeProvider.build_command()."""

import unittest

from ai_providers import OpenCodeProvider, get_provider


class TestOpenCodeAutoPermission(unittest.TestCase):
    """Verify opencode always passes --auto to auto-approve Bash permissions."""

    def test_default_command_includes_auto(self):
        parts = OpenCodeProvider().build_command().split()
        self.assertIn("--auto", parts)

    def test_auto_present_with_model_and_session(self):
        provider = OpenCodeProvider(model="gpt-5")
        parts = provider.build_command(session_id="sess-123").split()
        self.assertIn("--auto", parts)
        self.assertIn("-m", parts)
        self.assertIn("gpt-5", parts)
        self.assertIn("-s", parts)
        self.assertIn("sess-123", parts)
        self.assertLess(parts.index("-s"), parts.index("--auto"))

    def test_extra_args_still_appended_after_auto(self):
        parts = OpenCodeProvider(extra_args="--verbose").build_command().split()
        self.assertIn("--auto", parts)
        self.assertLess(parts.index("--auto"), len(parts) - 1)
        self.assertEqual(parts[-1], "--verbose")

        duplicate = OpenCodeProvider(extra_args="--auto").build_command().split()
        self.assertEqual(duplicate.count("--auto"), 2)
        self.assertEqual(duplicate[-1], "--auto")

    def test_get_provider_factory_path(self):
        parts = get_provider("opencode").build_command().split()
        self.assertIn("--auto", parts)

    def test_get_stdin_command_preserves_auto(self):
        provider = OpenCodeProvider()
        stdin_command = provider.get_stdin_command(
            "prompt.txt", provider.build_command()
        )
        self.assertIn("--auto", stdin_command)


if __name__ == "__main__":
    unittest.main()
