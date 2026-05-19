import re
import sys
import json
import time
import asyncio
import logging
import subprocess
from typing import Union, Optional

from ai_client.ai_providers import AIProvider
from ai_client.ai_client_common import (
    AICallError,
    BashTimeoutError,
    SessionTimeoutError,
    StreamTimeoutError,
    RateLimitError,
)
from util.truncation_limits import limits
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)


class AIClientSDK:
    """
    AI client using the CodeBuddy Agent SDK (Python package) instead of CLI subprocess.

    This provides the same ask() interface as AIClient, but calls the SDK's
    async query() function directly, avoiding shell/process overhead and
    platform-specific quirks (e.g. stdin piping, encoding issues on Windows).

    Only works with the CodeBuddy provider. Other providers (Claude, Gemini)
    are not supported via SDK and should continue using AIClient.

    Requires: pip install codebuddy-agent-sdk
    """

    def __init__(
        self,
        provider: AIProvider,
        workspace: str = ".",
        timeout: int = None,
        bash_timeout: int = None,
        context_id: str = None,
    ):
        """
        Initialize AIClientSDK.

        Args:
            provider: AI provider instance
            workspace: Working directory
            timeout: Session timeout in seconds (hard cap on total session time)
            bash_timeout: No-new-output timeout in seconds.  If the AI
                produces no new output for this many seconds, the session
                is killed.
            context_id: Context identifier for logging/tracking
        """
        if timeout is None:
            timeout = DEFAULTS['session_timeout']
        if bash_timeout is None:
            bash_timeout = DEFAULTS['bash_timeout']

        self.provider = provider

        self.workspace = workspace
        self.timeout = timeout
        self.bash_timeout = bash_timeout
        self.context_id = context_id
        self._session_id = None  # SDK session ID for conversation continuity
        self.last_full_log = ""
        # Callback to notify session_id changes (for state persistence)
        self._on_session_id_changed = None
        # Exponential backoff state
        self._consecutive_failures = 0
        self._backoff_base = DEFAULTS['backoff_base']  # seconds
        self._backoff_max = DEFAULTS['backoff_max_wait']  # default max wait, overridden by config

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
        Send a prompt to CodeBuddy via SDK and get a response.

        Session continuity is handled automatically via session_id:
        - If a session_id exists (from a previous call or resume_session()),
          the SDK will continue that session.
        - Otherwise, a new session is started.

        Args:
            prompt: The prompt to send
            expect_json: Whether to parse the response as JSON
            timeout: Override default timeout
            system_prompt: Optional system prompt.  The SDK does not
                support a separate system prompt channel, so it is
                appended to the user prompt.

        Returns:
            str or dict: The AI response (parsed as JSON if expect_json=True)

        Raises:
            AICallError: If the call fails
        """
        effective_timeout = timeout or self.timeout

        # SDK does not support a separate system prompt; append to user prompt
        # so the AI sees the task description first and instructions second.
        if system_prompt:
            prompt = prompt + "\n\n" + system_prompt

        # Exponential backoff: wait before retrying after consecutive failures
        if self._consecutive_failures > 0:
            delay = min(
                self._backoff_base * (2 ** (self._consecutive_failures - 1)),
                self._backoff_max,
            )
            logger.info(
                f"[{self.context_id}] Backoff: waiting {delay}s before retry "
                f"(consecutive failures: {self._consecutive_failures})"
            )
            print(
                f"   ⏳ Waiting {delay}s before retry (attempt after {self._consecutive_failures} consecutive failure(s))"
            )
            time.sleep(delay)

        logger.info(
            f"[{self.context_id}] Calling CodeBuddy SDK "
            f"(session_id={self.session_id or 'new'}, model={self.provider.model}, timeout={effective_timeout}s)"
        )
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:limits.get('log_promptlike_preview')]}...")

        try:
            response, full_log = self._run_query(prompt, effective_timeout)
        except AICallError:
            self._consecutive_failures += 1
            raise
        except Exception as e:
            self._consecutive_failures += 1
            # Detect SDK-level timeout errors — the session is likely
            # still alive, so raise StreamTimeoutError to let the caller
            # continue in the same session instead of resetting.
            err_lower = str(e).lower()
            if "timeout" in err_lower:
                raise StreamTimeoutError(f"Failed to call CodeBuddy SDK: {e}")
            # Detect rate-limit (429) and server errors (503) — these are
            # transient and should not consume retry attempts.
            if self._is_rate_limit_error(str(e)):
                raise RateLimitError(f"Failed to call CodeBuddy SDK: {e}")
            raise AICallError(f"Failed to call CodeBuddy SDK: {e}")

        if not response:
            self._consecutive_failures += 1
            raise AICallError("CodeBuddy SDK returned empty response")

        self.last_full_log = full_log or response
        # Session is now active (session_id captured from ResultMessage)
        self._consecutive_failures = 0  # Reset backoff on success

        logger.info(f"[{self.context_id}] Got response ({len(response)} chars)")
        logger.debug(f"[{self.context_id}] Response: {response[:limits.get('log_promptlike_preview')]}...")

        if expect_json:
            return self._parse_json_response(response)
        return response

    def _run_query(self, prompt: str, timeout: int) -> tuple:
        """
        Run the SDK query in an asyncio event loop.

        Returns:
            tuple: (response_text, full_log_text)
        """
        try:
            from codebuddy_agent_sdk import (
                query as sdk_query,
                AssistantMessage,
                ResultMessage,
                SystemMessage,
                CodeBuddyAgentOptions,
            )
            from codebuddy_agent_sdk.types import (
                TextBlock,
                ThinkingBlock,
                ToolUseBlock,
                ToolResultBlock,
                UserMessage,
                StreamEvent,
            )
        except ImportError:
            raise AICallError(
                "codebuddy-agent-sdk is not installed. "
                "Install it with: pip install codebuddy-agent-sdk"
            )

        assistant_text_parts = []
        full_log_parts = []

        # Run the async query with a timeout
        # We use session timeout (hard cap) for asyncio.wait_for,
        # and track last_output_time inside _do_query for bash timeout.
        _bash_timeout_triggered = False
        _last_output_time = time.monotonic()
        _bash_timeout_val = self.bash_timeout

        # Wrap _do_query to add bash_timeout checking
        async def _do_query_with_bash_timeout():
            nonlocal _bash_timeout_triggered, _last_output_time
            # Build options
            options = CodeBuddyAgentOptions(
                model=self.provider.model,
                cwd=self.workspace,
                permission_mode="bypassPermissions",
                thinking={"type": "adaptive"},
            )

            # Set executable path if custom
            if self.provider.executable and self.provider.executable != "codebuddy":
                options.codebuddy_code_path = self.provider.executable

            # Session continuity: resume if we have a session_id
            if self._session_id:
                options.continue_conversation = True
                options.session_id = self._session_id

            # Extra args from provider
            if self.provider.extra_args:
                parts = self.provider.extra_args.split()
                i = 0
                while i < len(parts):
                    key = parts[i].lstrip("-")
                    if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                        options.extra_args[key] = parts[i + 1]
                        i += 2
                    else:
                        options.extra_args[key] = None
                        i += 1

            logger.debug(
                f"[{self.context_id}] SDK options: model={options.model}, "
                f"cwd={options.cwd}, "
                f"session_id={options.session_id}"
            )

            async for message in sdk_query(prompt=prompt, options=options):
                # Check bash timeout (no new output for N seconds)
                now = time.monotonic()
                if _bash_timeout_val and (now - _last_output_time) > _bash_timeout_val:
                    _bash_timeout_triggered = True
                    raise asyncio.CancelledError("bash timeout")
                _last_output_time = now

                if isinstance(message, SystemMessage):
                    if hasattr(message, "data") and isinstance(message.data, dict):
                        sid = message.data.get("session_id", "")
                        if sid and sid != self._session_id:
                            self._session_id = sid
                            if self._on_session_id_changed:
                                self._on_session_id_changed(sid)
                    continue

                if isinstance(message, AssistantMessage):
                    # Ensure newline between separate assistant messages
                    if assistant_text_parts and not assistant_text_parts[-1].endswith(
                        "\n"
                    ):
                        assistant_text_parts.append("\n")
                    for block in message.content or []:
                        if isinstance(block, TextBlock):
                            text = block.text or ""
                            if text:
                                sys.stdout.write(text)
                                sys.stdout.flush()
                                assistant_text_parts.append(text)
                                full_log_parts.append(text)
                        elif isinstance(block, ThinkingBlock):
                            thinking = block.thinking or ""
                            if thinking:
                                sys.stdout.write(f"\n💭 [Thinking] {thinking}\n")
                                sys.stdout.flush()
                                full_log_parts.append(
                                    f"\n<details><summary>💭 Thinking</summary>\n\n{thinking}\n\n</details>\n"
                                )
                        elif isinstance(block, ToolUseBlock):
                            tool_name = block.name or "unknown"
                            tool_input = block.input or {}
                            self._display_tool_use(tool_name, tool_input)
                            full_log_parts.append(
                                f"\n🔧 [Tool: {tool_name}] Input: "
                                f"{json.dumps(tool_input, ensure_ascii=False)[:limits.get('log_tool_result')]}\n"
                            )
                        elif isinstance(block, ToolResultBlock):
                            content = block.content or ""
                            if isinstance(content, list):
                                content = " ".join(
                                    str(c.get("text", ""))
                                    if isinstance(c, dict)
                                    else str(c)
                                    for c in content
                                )
                            preview = str(content)[:limits.get('log_tool_result')]
                            full_log_parts.append(f"   Result: {preview}\n")

                elif isinstance(message, ResultMessage):
                    if message.session_id:
                        self._session_id = message.session_id
                        if self._on_session_id_changed:
                            self._on_session_id_changed(message.session_id)

                    result_text = message.result or ""
                    # Only use result_text as fallback when no text was
                    # collected from streaming AssistantMessage events,
                    # to avoid duplicating content.
                    if result_text and not assistant_text_parts:
                        assistant_text_parts.append(result_text)

                    is_error = message.is_error
                    duration_ms = message.duration_ms or 0
                    num_turns = message.num_turns or 0
                    status = "❌ Error" if is_error else "✅ Done"
                    summary = f"\n--- {status} ({num_turns} turns, {duration_ms / 1000:.1f}s) ---\n"
                    sys.stdout.write(summary)
                    sys.stdout.flush()
                    full_log_parts.append(f"\n{summary}")

                    if is_error:
                        errors = message.errors or []
                        if errors:
                            error_type = getattr(message, "error_type", None) or ""
                            prefix = f"[{error_type}] " if error_type else ""
                            error_msg = f"CodeBuddy SDK error: {prefix}{'; '.join(str(e) for e in errors)}"
                            if AIClientSDK._is_rate_limit_error(error_msg):
                                raise RateLimitError(error_msg)
                            raise AICallError(error_msg)

                elif isinstance(message, StreamEvent):
                    pass

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    asyncio.wait_for(_do_query_with_bash_timeout(), timeout=timeout)
                )
            finally:
                loop.close()
        except asyncio.CancelledError:
            if _bash_timeout_triggered:
                raise BashTimeoutError(
                    f"CodeBuddy SDK bash timed out — no new output for {_bash_timeout_val}s"
                )
            raise SessionTimeoutError(
                f"CodeBuddy SDK session timed out after {timeout}s"
            )
        except asyncio.TimeoutError:
            raise SessionTimeoutError(
                f"CodeBuddy SDK session timed out after {timeout}s"
            )

        response = "".join(assistant_text_parts).strip()
        full_log = "\n".join(full_log_parts).strip()
        return response, full_log

    def _display_tool_use(self, tool_name: str, tool_input: dict):
        """Display a tool use event with a readable summary.

        Uses the provider's tool_names configuration to categorize tools.
        """
        tool_names_config = {}
        if self.provider.config and self.provider.config.tool_names:
            tool_names_config = self.provider.config.tool_names

        # Valid categories
        VALID_CATEGORIES = {"read", "write", "glob", "bash", "list"}

        name_lower = tool_name.lower()

        # Build reverse lookup: tool_name_pattern -> category
        category = None
        for cat, patterns_str in tool_names_config.items():
            if cat not in VALID_CATEGORIES:
                continue
            if not patterns_str:
                continue
            patterns = [p.strip().lower() for p in patterns_str.split(";") if p.strip()]
            if name_lower in patterns:
                category = cat
                break

        # Default categories if not configured
        if category is None:
            if name_lower in ("read", "read_file"):
                category = "read"
            elif name_lower in ("write", "write_file", "edit", "multiedit", "replace"):
                category = "write"
            elif name_lower in ("glob", "grep", "grep_search"):
                category = "glob"
            elif name_lower in ("bash", "run_shell_command"):
                category = "bash"
            elif name_lower in ("ls", "list_dir", "list_directory"):
                category = "list"

        # Display based on category
        if category == "read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📖 [Read] {path}\n")
        elif category == "write":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📝 [Write] {path}\n")
        elif category == "glob":
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            sys.stdout.write(f"\n🔍 [Glob] {pattern}\n")
        elif category == "bash":
            cmd = tool_input.get("command", "")
            sys.stdout.write(f"\n🔧 [Bash] {cmd}\n")
        elif category == "list":
            path = tool_input.get("path", ".")
            sys.stdout.write(f"\n📂 [List] {path}\n")
        else:
            sys.stdout.write(f"\n🔧 [{tool_name}]\n")
        sys.stdout.flush()

    def _format_tool_use_for_log(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use event as a Markdown string for the conversation log.

        Uses the provider's tool_names configuration to categorize tools.
        """
        tool_names_config = {}
        if self.provider.config and self.provider.config.tool_names:
            tool_names_config = self.provider.config.tool_names

        # Valid categories
        VALID_CATEGORIES = {"read", "write", "glob", "bash", "list"}

        name_lower = tool_name.lower()

        # Build reverse lookup: tool_name_pattern -> category
        category = None
        for cat, patterns_str in tool_names_config.items():
            if cat not in VALID_CATEGORIES:
                continue
            if not patterns_str:
                continue
            patterns = [p.strip().lower() for p in patterns_str.split(";") if p.strip()]
            if name_lower in patterns:
                category = cat
                break

        # Default categories if not configured
        if category is None:
            if name_lower in ("read", "read_file"):
                category = "read"
            elif name_lower in ("write", "write_file", "edit", "multiedit"):
                category = "write"
            elif name_lower in ("glob", "grep", "grep_search"):
                category = "glob"
            elif name_lower in ("bash", "run_shell_command"):
                category = "bash"
            elif name_lower in ("ls", "list_dir"):
                category = "list"

        # Format based on category
        if category == "bash":
            cmd = tool_input.get("command", "")
            return f"\n🔧 **[Bash]**\n```bash\n{cmd}\n```\n"
        elif category == "write":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            content = tool_input.get("content", tool_input.get("new_string", ""))
            result = f"\n📝 **[Write]** `{path}`\n"
            if content:
                preview = content[:limits.get('log_tool_result')]
                if len(content) > limits.get('log_tool_result'):
                    preview += f"\n... ({len(content)} chars total)"
                result += f"```\n{preview}\n```\n"
            return result
        elif category == "read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            return f"\n📖 **[Read]** `{path}`\n"
        elif category == "glob":
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            return f"\n🔍 **[{tool_name}]** `{pattern}`\n"
        elif category == "list":
            path = tool_input.get("path", ".")
            return f"\n📂 **[List]** `{path}`\n"
        else:
            # Generic tool - check for special cases
            if name_lower == "todoread":
                return f"\n📋 **[TodoRead]**\n"
            elif name_lower in ("taskcreate", "taskupdate"):
                task_desc = tool_input.get("description", tool_input.get("task", ""))
                if isinstance(task_desc, str) and task_desc:
                    return f"\n🔧 **[{tool_name}]** {task_desc[:limits.get('log_tool_result')]}\n"
                return f"\n🔧 **[{tool_name}]**\n"
            else:
                summary = json.dumps(tool_input, ensure_ascii=False)[:limits.get('log_tool_result')]
                return f"\n🔧 **[{tool_name}]** {summary}\n"

    def _parse_json_response(self, response: str) -> dict:
        """Extract and parse JSON from AI response (same logic as AIClient)."""
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
            match = re.search(pattern, response, re.DOTALL)
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
            f"Failed to parse JSON from CodeBuddy response. "
            f"Response preview: {response[:limits.get('previous_subtask_summary')]}"
        )

    @staticmethod
    def _is_rate_limit_error(error_msg: str) -> bool:
        """Check if an error message indicates a rate-limit (429) or server error (503).

        These are transient errors from the AI service that should not
        consume retry attempts.
        """
        lower = error_msg.lower()
        # HTTP 429 rate limit patterns
        if "429" in error_msg and ("rate" in lower or "limit" in lower or "frequency" in lower or "usage exceeds" in lower):
            return True
        # HTTP 503 server error patterns
        if "503" in error_msg and "server error" in lower:
            return True
        # Generic rate limit phrases
        if "rate limit" in lower or "rate_limit" in lower:
            return True
        if "usage exceeds frequency limit" in lower:
            return True
        return False

    def reset_session(self):
        """Reset the session state, so next call starts a new session."""
        self._session_id = None
        logger.info(f"[{self.context_id}] Session reset")