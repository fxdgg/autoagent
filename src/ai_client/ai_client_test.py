import re
import sys
import json
import time
import logging
import subprocess
from typing import Union, Optional

from ai_client.ai_providers import AIProvider, TestProvider
from ai_client.ai_client_common import AICallError
from util.truncation_limits import limits

logger = logging.getLogger(__name__)


class AIClientTest:
    """
    Test client that returns pre-defined responses from a TestProvider.

    This client does NOT call any real AI tool. Instead, it reads responses
    sequentially from the TestProvider's rules list. Each call to ask()
    consumes the next rule.

    For long_running tasks, if the response contains an autoagent-exec
    command (e.g. ``autoagent-exec --cmd "sleep 3" --task-id 1.2``),
    the client will **actually execute** the command via autoagent_exec.py
    so that signal files are created and the orchestrator's polling logic
    works correctly.

    This is useful for testing the orchestration logic (retry, looping,
    failure analysis, etc.) without incurring AI costs or requiring
    any AI CLI tool to be installed.

    Usage:
        from ai_client.ai_providers import TestProvider
        provider = TestProvider(test_rules_file="test_rules.txt")
        client = AIClientTest(provider=provider, context_id="task_1")
        response = client.ask("some prompt")  # Returns first rule
        response = client.ask("another prompt")  # Returns second rule
    """

    def __init__(
        self,
        provider: AIProvider,
        workspace: str = ".",
        timeout: int = 3600,
        bash_timeout: int = 300,
        context_id: str = None,
    ):
        from ai_client.ai_providers import TestProvider

        if not isinstance(provider, TestProvider):
            raise ValueError(
                f"AIClientTest requires a TestProvider, got {type(provider).__name__}"
            )
        self.provider = provider
        self.workspace = workspace
        self.timeout = timeout
        self.context_id = context_id
        self._session_id = None  # Session ID for test client (not actually used)
        self.last_full_log = ""
        # Fallback exec_path and log_dir for autoagent-exec commands
        # when the prompt doesn't contain them (e.g. simple tasks where
        # AI remembers the paths from context).
        # These are set by the orchestrator (run_test.py) after client creation.
        self._fallback_exec_path = None
        self._fallback_log_dir = None
        # Callback to notify session_id changes (for state persistence)
        self._on_session_id_changed = None

    @property
    def session_id(self) -> str:
        """Get the current session ID (for context persistence)."""
        return self._session_id or ""

    def resume_session(self, session_id: str):
        """
        Resume a previous session by setting the session ID.

        Args:
            session_id: The session ID to resume (e.g., from a previous run)
        """
        if session_id:
            self._session_id = session_id
            logger.info(f"[{self.context_id}] Resuming session: {session_id}")

    def ask(
        self,
        prompt: str,
        expect_json: bool = False,
        timeout: int = None,
        system_prompt: str = None,
        **kwargs,
    ) -> Union[str, dict]:
        """
        Return the next pre-defined response from the test rules.

        The prompt is logged but otherwise ignored — the response is
        determined entirely by the order of rules in the test file.

        For long_running tasks: if the response contains an autoagent-exec
        command pattern, the actual command is extracted and executed via
        autoagent_exec.py so that signal files are created correctly.

        Args:
            prompt: The prompt (used to extract exec_path/log_dir for
                    long_running tasks, otherwise logged only)
            expect_json: Whether to parse the response as JSON
            timeout: Ignored
            system_prompt: Optional system prompt (prepended to prompt
                for logging purposes only; does not affect test responses)

        Returns:
            str or dict: The next test response
        """
        # Log the prompt for debugging
        logger.info(
            f"[{self.context_id}] TestClient.ask() called "
            f"(remaining rules: {self.provider.peek_remaining()})"
        )
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:limits.get('log_promptlike_preview')]}...")

        # Get next response from provider
        response = self.provider.get_next_response()

        # Display the response like a real client would
        print(
            f"\n🧪 [TestProvider] Rule #{self.provider._rule_index}/{len(self.provider._rules)}"
        )
        print(f"   Response: {response[:limits.get('log_promptlike_preview')]}{'...' if len(response) > limits.get('log_promptlike_preview') else ''}")

        # For long_running tasks: if the response contains an autoagent-exec
        # command, actually execute it so signal files are created.
        response = self._maybe_run_autoagent_exec(prompt, response)

        self.last_full_log = response

        if expect_json:
            return self._parse_json_response(response)
        return response

    def _maybe_run_autoagent_exec(self, prompt: str, response: str) -> str:
        """
        If the response contains an autoagent-exec command, actually execute it.

        The test_rules.txt uses a simplified format:
            autoagent-exec --cmd "<command>" --task-id <id>

        This method extracts the command and task-id from the response,
        then extracts exec_path and log_dir from the prompt (which contains
        the full autoagent-exec usage template), and runs the real
        autoagent_exec.py script.

        After execution, the original response text is returned unchanged
        so that the orchestrator can detect LONG_RUNNING_IN_PROGRESS.

        Args:
            prompt: The prompt sent to the AI (contains exec_path and log_dir)
            response: The test response text

        Returns:
            str: The original response (possibly with exec output appended)
        """
        # Check if response contains the simplified autoagent-exec pattern
        # The --cmd value may contain nested quotes (e.g. python -c "..."),
        # so we match greedily up to the --task-id flag.
        exec_match = re.search(
            r'autoagent-exec\s+--cmd\s+"(.+)"\s+--task-id\s+(\S+)',
            response,
        )
        if not exec_match:
            # Try single-quoted variant
            exec_match = re.search(
                r"autoagent-exec\s+--cmd\s+'(.+)'\s+--task-id\s+(\S+)",
                response,
            )
        if not exec_match:
            return response

        cmd = exec_match.group(1)
        task_id = exec_match.group(2)

        # Clean up escaped quotes that may come from test_rules.txt
        # e.g. python -c \"import time; time.sleep(5)\" → python -c "import time; time.sleep(5)"
        cmd = cmd.replace('\\"', '"')

        # Extract exec_path and log_dir from the prompt.
        # New format: the prompt contains a script path like
        #   "<session_dir>/scripts/autoagent-exec.bat" <cmd>
        # We read the script to extract the embedded exec_path and log_dir.
        exec_path = None
        log_dir = None
        fast_fail_timeout = 10  # default; may be overridden from script content

        script_match = re.search(
            r'["\'](.+?/scripts/autoagent-exec\.(?:bat|sh))["\']',
            prompt,
        )
        if script_match:
            script_path = script_match.group(1)
            try:
                with open(script_path, "r", encoding="utf-8") as f:
                    script_content = f.read()
                # Parse: python "<exec_path>" --log-dir "<log_dir>" --task-id <id> -- ...
                inner_match = re.search(
                    r'python[3]?\s+["\'](.+?autoagent_exec\.py)["\']\s+--log-dir\s+["\'](.+?)["\']',
                    script_content,
                )
                if inner_match:
                    exec_path = inner_match.group(1)
                    log_dir = inner_match.group(2)
                # Also extract --fast-fail-timeout if present
                fft_match = re.search(
                    r"--fast-fail-timeout\s+(\d+)",
                    script_content,
                )
                fast_fail_timeout = int(fft_match.group(1)) if fft_match else 10
            except OSError as e:
                logger.warning(
                    f"[{self.context_id}] Failed to read autoagent-exec script "
                    f"{script_path}: {e}"
                )

        if not exec_path or not log_dir:
            if self._fallback_exec_path and self._fallback_log_dir:
                exec_path = self._fallback_exec_path
                log_dir = self._fallback_log_dir
                logger.info(
                    f"[{self.context_id}] Using fallback exec_path/log_dir "
                    f"for autoagent-exec in non-long_running task"
                )
            else:
                logger.warning(
                    f"[{self.context_id}] Response contains autoagent-exec command "
                    f"but could not extract exec_path/log_dir from prompt "
                    f"and no fallback is configured. Skipping actual execution."
                )
                return response

        print(
            f"\n🧪 [TestProvider] Detected autoagent-exec command, executing for real:"
        )
        print(f"   exec_path: {exec_path}")
        print(f"   log_dir:   {log_dir}")
        print(f"   task_id:   {task_id}")
        print(f"   command:   {cmd}")

        # Build the real autoagent_exec.py command.
        # Use --cmd to pass the entire command as a single shell string,
        # preserving shell operators (&&, |, ;, etc.) correctly.
        full_cmd = [
            sys.executable,
            exec_path,
            "--log-dir",
            log_dir,
            "--task-id",
            task_id,
            "--fast-fail-timeout",
            str(fast_fail_timeout),
            "--cmd",
            cmd,
        ]

        try:
            result = subprocess.run(
                full_cmd,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=fast_fail_timeout
                + 20,  # autoagent-exec itself should return within fast_fail_timeout
                cwd=self.workspace,
            )
            exec_output = result.stdout.strip()
            if result.stderr.strip():
                exec_output += "\n" + result.stderr.strip()

            print(f"   exit_code: {result.returncode}")
            if exec_output:
                print(f"   output:\n{exec_output}")

            # Append exec output to response so the orchestrator can see it
            if exec_output:
                response = response + "\n\n" + exec_output

        except subprocess.TimeoutExpired:
            logger.error(
                f"[{self.context_id}] autoagent-exec timed out for task {task_id}"
            )
            print(f"   ❌ autoagent-exec timed out!")
        except Exception as e:
            logger.error(f"[{self.context_id}] Failed to run autoagent-exec: {e}")
            print(f"   ❌ Failed to run autoagent-exec: {e}")

        return response

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from test response (same logic as AIClient)."""
        import re as _re

        # Strategy 1: Try parsing the entire response as JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON from markdown code block
        json_patterns = [
            r"```json\s*\n(.*?)\n\s*```",
            r"```\s*\n(.*?)\n\s*```",
        ]
        for pattern in json_patterns:
            match = _re.search(pattern, response, _re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

        # Strategy 3: Find the first { ... } block
        brace_depth = 0
        start_idx = None
        for i, char in enumerate(response):
            if char == "{":
                if brace_depth == 0:
                    start_idx = i
                brace_depth += 1
            elif char == "}":
                brace_depth -= 1
                if brace_depth == 0 and start_idx is not None:
                    try:
                        return json.loads(response[start_idx : i + 1])
                    except json.JSONDecodeError:
                        start_idx = None

        raise AICallError(
            f"Failed to parse JSON from test response. "
            f"Response preview: {response[:limits.get('previous_subtask_summary')]}"
        )

    def reset_session(self):
        """Reset the session state."""
        self._session_id = None
        logger.info(f"[{self.context_id}] Test session reset")