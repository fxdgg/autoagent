"""
AI Client - Wraps AI CLI tool interactions with context management.

This module provides the AIClient class that handles:
- Calling AI tools (CodeBuddy, Claude Code, Gemini CLI) via subprocess
- Managing conversation context (session_id based resumption)
- Parsing JSON responses from AI
- Timeout handling

Provides AIClient (CLI mode), AIClientSDK (SDK mode), and AIClientTest (test mode).
"""

import subprocess
import json
import re
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import asyncio
from typing import Union, Optional, List

from ai_providers import AIProvider, CodeBuddyProvider, get_provider

logger = logging.getLogger(__name__)



class AIClient:
    """
    AI CLI client with context management.

    Supports multiple AI backends through the provider abstraction:
    - CodeBuddy (codebuddy)
    - Claude Code (claude)
    - Gemini Cli (gemini)
    - OpenCode (opencode)

    Each main task should create its own AIClient instance.
    Sessions are reset between subtasks to prevent unbounded context growth.
    Retries within the same subtask share the session via session_id (--resume).
    """

    def __init__(
        self,
        provider: AIProvider,
        workspace: str = ".",
        timeout: int = 3600,
        bash_timeout: int = 300,
        context_id: str = None,
    ):
        """
        Initialize AIClient.

        Args:
            provider: AI provider instance
            workspace: Working directory
            timeout: Session timeout in seconds (hard cap on total session time)
            bash_timeout: No-new-output timeout in seconds.  If the AI
                produces no new output for this many seconds, the session
                is killed.
            context_id: Context identifier for logging/tracking
        """
        self.provider = provider

        self.workspace = workspace
        self.timeout = timeout
        self.bash_timeout = bash_timeout
        self.context_id = context_id
        self._session_id = None  # Session ID for conversation continuity
        # Full conversation log including tool calls (set after each ask() call)
        self.last_full_log = ""
        # Callback to notify session_id changes (for state persistence)
        self._on_session_id_changed = None
        # Exponential backoff state
        self._consecutive_failures = 0
        self._backoff_base = 5  # seconds
        self._backoff_max = 300  # default max wait, overridden by config

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
        Send a prompt to CodeBuddy and get a response.

        Session continuity is handled automatically via session_id:
        - If a session_id exists (from a previous call or resume_session()),
          the CLI will resume that session.
        - Otherwise, a new session is started.

        Args:
            prompt: The prompt to send
            expect_json: Whether to parse the response as JSON
            timeout: Override default timeout
            system_prompt: Optional system prompt.  For providers that
                support ``--append-system-prompt`` it is passed via CLI;
                for others it is prepended to the user prompt.

        Returns:
            str or dict: The AI response (parsed as JSON if expect_json=True)

        Raises:
            AICallError: If the call fails
        """
        effective_timeout = timeout or self.timeout

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

        # Build command args (without prompt - prompt goes via stdin)
        # If the provider supports --append-system-prompt, pass it via CLI;
        # otherwise append it to the user prompt so the AI sees the task
        # description first and the operational instructions second.
        effective_system_prompt = system_prompt
        if effective_system_prompt and not self.provider.supports_system_prompt:
            prompt = prompt + "\n\n" + effective_system_prompt
            effective_system_prompt = None  # Already in prompt

        cmd_args = self._build_command(system_prompt=effective_system_prompt)

        logger.info(
            f"[{self.context_id}] Calling {self.provider.name} "
            f"(session_id={self.session_id or 'new'}, model={self.provider.model}, timeout={effective_timeout}s)"
        )
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:200]}...")
        logger.debug(f"[{self.context_id}] Command: {cmd_args}")

        # Write prompt to a temp file to avoid shell escaping issues
        prompt_file_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as pf:
                pf.write(prompt)
                prompt_file_path = pf.name

            # Build full command: pipe the temp file content as stdin
            full_cmd = self.provider.get_stdin_command(prompt_file_path, cmd_args)

            logger.debug(f"[{self.context_id}] Full command: {full_cmd}")

            # Use shell=True so Windows can find .cmd/.bat wrappers
            process = subprocess.Popen(
                full_cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self.workspace,
                bufsize=1,  # Line-buffered
            )

            # Collect stderr in a background thread to avoid blocking
            stderr_chunks = []

            def _read_stderr():
                for line in process.stderr:
                    stderr_chunks.append(line)

            stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
            stderr_thread.start()

            # Stream stdout in real-time while collecting the full response
            stdout_chunks = []
            assistant_text_parts = []
            full_log_parts = []  # Collect full log including tool calls
            session_deadline = time.monotonic() + effective_timeout
            bash_timeout = self.bash_timeout
            last_output_time = time.monotonic()
            _timeout_type = None  # "session" or "bash"
            try:
                for line in process.stdout:
                    now = time.monotonic()
                    if now > session_deadline:
                        _timeout_type = "session"
                        process.kill()
                        raise subprocess.TimeoutExpired(full_cmd, effective_timeout)
                    if bash_timeout and (now - last_output_time) > bash_timeout:
                        _timeout_type = "bash"
                        process.kill()
                        raise subprocess.TimeoutExpired(full_cmd, bash_timeout)
                    last_output_time = now
                    stdout_chunks.append(line)
                    # Parse stream-json lines for real-time display
                    self._handle_stream_line(
                        line.rstrip("\n"), assistant_text_parts, full_log_parts
                    )
            except subprocess.TimeoutExpired:
                process.kill()
                if _timeout_type == "bash":
                    raise BashTimeoutError(
                        f"{self.provider.name} bash timed out — no new output for {bash_timeout}s"
                    )
                else:
                    raise SessionTimeoutError(
                        f"{self.provider.name} session timed out after {effective_timeout}s"
                    )

            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Process did not exit within 30s after stdout closed, killing"
                )
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.error("Process still alive after kill, abandoning")
            stderr_thread.join(timeout=5)

            stdout_text = "".join(stdout_chunks)
            stderr_text = "".join(stderr_chunks)

            if process.returncode != 0:
                raw_error = stderr_text.strip() or stdout_text.strip()
                message, error_type = self._parse_cli_error(raw_error)
                # Check for authentication error
                if (
                    error_type in ("authentication_error", "authentication_failed")
                    or "Authentication" in message
                    or "login" in message.lower()
                ):
                    raise AICallError(
                        f"{self.provider.name} authentication required. "
                        f"Please run '{self.provider.executable} --help' to check. "
                        f"Error: {message}"
                    )
                prefix = f"[{error_type}] " if error_type else ""
                raise AICallError(
                    f"{self.provider.name} returned exit code {process.returncode}: "
                    f"{prefix}{message}"
                )

            # Combine all assistant text from stream-json events
            response = "".join(assistant_text_parts).strip()
            # Fallback: if stream-json parsing yielded nothing, use raw stdout
            if not response:
                response = stdout_text.strip()
            if not response:
                raise AICallError(f"{self.provider.name} returned empty response")

            # Store full log (with tool calls) for conversation logger
            self.last_full_log = "\n".join(full_log_parts).strip()
            if not self.last_full_log:
                self.last_full_log = response

            # Session is now active (session_id captured from stream events)
            self._consecutive_failures = 0  # Reset backoff on success
            logger.info(f"[{self.context_id}] Got response ({len(response)} chars)")
            logger.debug(f"[{self.context_id}] Response: {response[:200]}...")

            if expect_json:
                return self._parse_json_response(response)
            return response

        except (BashTimeoutError, SessionTimeoutError):
            self._consecutive_failures += 1
            raise
        except subprocess.TimeoutExpired:
            # Safety net for process.wait() timeout after stdout closed
            self._consecutive_failures += 1
            raise SessionTimeoutError(
                f"{self.provider.name} session timed out after {effective_timeout}s"
            )
        except AICallError:
            self._consecutive_failures += 1
            raise
        except Exception as e:
            self._consecutive_failures += 1
            raise AICallError(f"Failed to call {self.provider.name}: {e}")
        finally:
            # Clean up temp file
            if prompt_file_path:
                try:
                    os.unlink(prompt_file_path)
                except OSError:
                    pass

    def _build_command(self, system_prompt: str = None) -> str:
        """
        Build the AI CLI command string (without prompt).

        Delegates to the provider to build the correct command for the
        specific AI tool being used. If a session_id exists, it is passed
        to the provider so the CLI resumes that session.

        Args:
            system_prompt: Optional system prompt to pass to the provider.

        Returns:
            str: The command string (prompt will be piped via stdin)
        """
        return self.provider.build_command(
            session_id=self._session_id,
            system_prompt=system_prompt,
        )

    def _handle_stream_line(
        self, line: str, assistant_text_parts: list, full_log_parts: list = None
    ):
        """
        Parse a single line of stream-json output and display relevant info in real-time.

        Supports four stream-json dialects:

        **CodeBuddy / Claude Code format:**
          - "assistant": AI message with message.content[] array (text blocks and/or tool_use)
          - "user": Contains tool_result in message.content[] array
          - "result": Final result with "result", "is_error", "duration_ms", "num_turns"

        **Gemini CLI format:**
          - "message" + role="assistant": AI text in "content" string, with "delta":true
          - "tool_use": Top-level event with "tool_name" and "parameters"
          - "tool_result": Top-level event with "status", "output", "error"
          - "result": Final result with "status", "stats.duration_ms", "stats.tool_calls"
          - "init": Session init (ignored)
          - "message" + role="user": Echo of user prompt (ignored)

        **OpenCode format:**
          - "step_start": Session start, contains "sessionID" (at top level or in data)
          - "text": AI text in data.text
          - "tool_call": Tool invocation with data.name (tool name) and data.input (JSON string)
          - "tool_result": Tool result (handled by existing tool_result branch)
          - "step_finish": Step finished with data.reason (and optional data.tokens, data.cost)

        **Codex format:**
          - "thread.started": Session start with "thread_id"
          - "turn.started" / "turn.completed": Turn boundaries
          - "item.started": Item in progress (ignored — wait for completed)
          - "item.completed": Completed item:
            - "agent_message": AI text in item.text
            - "command_execution": Tool call with item.command, item.aggregated_output, item.exit_code
            - "reasoning": Thinking (ignored)
            - "tool_call" / "tool_call_output": Generic tool call/result (fallback)

        Args:
            line: A single line of stream-json output
            assistant_text_parts: List to collect assistant text for final response
            full_log_parts: List to collect full log including tool calls
        """
        if full_log_parts is None:
            full_log_parts = []

        if not line.strip():
            return

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Not valid JSON - print raw line as fallback
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            return

        event_type = event.get("type", "")
        # DEBUG: Log the stream json (disabled currently)
        # logger.debug(f"[{self.context_id}] Event content: {json.dumps(event, ensure_ascii=False)[:500]}")

        # Capture session_id as early as possible from any event that
        # carries it (system/init, assistant, result, step_start).
        # This is critical for Ctrl+C recovery: if the user interrupts
        # before the final "result" event, we still have the session_id.
        early_sid = event.get("session_id", "")
        if early_sid and early_sid != self._session_id:
            self._session_id = early_sid
            if self._on_session_id_changed:
                self._on_session_id_changed(early_sid)

        if event_type == "system":
            # CodeBuddy CLI: system/init event — session_id already
            # captured above via the generic early-capture block.
            #
            # Claude Code also emits "system" events with subtype
            # "api_retry" when an API request fails with a retryable
            # error (rate_limit, server_error, etc.).  The CLI handles
            # retries internally; we just display progress.
            subtype = event.get("subtype", "")
            if subtype == "api_retry":
                error_cat = event.get("error", "unknown")
                attempt = event.get("attempt", "?")
                max_retries = event.get("max_retries", "?")
                delay_ms = event.get("retry_delay_ms", 0)
                http_status = event.get("error_status")
                status_str = f" (HTTP {http_status})" if http_status else ""
                msg = (
                    f"   ⚠️  API retry {attempt}/{max_retries}: "
                    f"{error_cat}{status_str}, "
                    f"waiting {delay_ms / 1000:.1f}s..."
                )
                sys.stdout.write(f"\033[31m{msg}\033[0m\n")
                sys.stdout.flush()
                full_log_parts.append(msg)

        elif event_type == "assistant":
            # CodeBuddy/Claude format: AI message with content[] array
            # Ensure newline between separate assistant messages
            if assistant_text_parts and not assistant_text_parts[-1].endswith("\n"):
                assistant_text_parts.append("\n")
            message = event.get("message", {})
            content_blocks = message.get("content", [])
            for block in content_blocks:
                block_type = block.get("type", "")
                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        assistant_text_parts.append(text)
                        full_log_parts.append(text)
                        sys.stdout.write(text)
                        sys.stdout.flush()
                elif block_type == "thinking":
                    thinking = block.get("thinking", "")
                    if thinking:
                        sys.stdout.write(f"\n💭 [Thinking] {thinking}\n")
                        sys.stdout.flush()
                        full_log_parts.append(
                            f"\n<details><summary>💭 Thinking</summary>\n\n{thinking}\n\n</details>\n"
                        )
                elif block_type == "tool_use":
                    tool_name = block.get("name", "unknown")
                    tool_input = block.get("input", {})
                    self._display_tool_use(tool_name, tool_input)
                    tool_log = self._format_tool_use_for_log(tool_name, tool_input)
                    full_log_parts.append(tool_log)

        elif event_type == "message":
            # Gemini format: "message" event with "role" field
            role = event.get("role", "")
            if role == "assistant":
                # Ensure newline between separate assistant messages
                if assistant_text_parts and not assistant_text_parts[-1].endswith("\n"):
                    assistant_text_parts.append("\n")
                content = event.get("content", "")
                if isinstance(content, str) and content:
                    assistant_text_parts.append(content)
                    full_log_parts.append(content)
                    sys.stdout.write(content)
                    sys.stdout.flush()
            # role="user" is just an echo of the prompt — ignore it

        elif event_type == "tool_use":
            # Handle both Gemini and OpenCode formats
            if "part" in event:
                # OpenCode format: tool info in part.tool and part.state.input
                part = event.get("part", {})
                tool_name = part.get("tool", part.get("name", "unknown"))
                state = part.get("state", {})
                tool_input_raw = state.get("input", part.get("input", {}))
                if isinstance(tool_input_raw, str):
                    try:
                        tool_input = json.loads(tool_input_raw)
                    except json.JSONDecodeError:
                        tool_input = {"raw": tool_input_raw}
                else:
                    tool_input = (
                        tool_input_raw if isinstance(tool_input_raw, dict) else {}
                    )
            else:
                # Gemini format: top-level tool_name and parameters
                tool_name = event.get("tool_name", event.get("name", "unknown"))
                tool_input = event.get("parameters", event.get("input", {}))
            self._display_tool_use(tool_name, tool_input)
            tool_log = self._format_tool_use_for_log(tool_name, tool_input)
            full_log_parts.append(tool_log)

        elif event_type == "tool_result":
            # Gemini format: top-level tool_result event
            status = event.get("status", "")
            output = event.get("output", "")
            error_info = event.get("error", {})
            is_error = status == "error"
            content = (
                output
                if output
                else (
                    error_info.get("message", "")
                    if isinstance(error_info, dict)
                    else str(error_info)
                )
            )
            if content:
                error_marker = " ❌" if is_error else ""
                log_content = content[:2000]
                if len(content) > 2000:
                    log_content += f"\n... ({len(content)} chars total)"
                full_log_parts.append(
                    f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                )

        elif event_type == "user":
            # CodeBuddy/Claude format: user message containing tool_result
            message = event.get("message", {})
            content_blocks = message.get("content", [])
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        content = block.get("content", "")
                        is_error = block.get("is_error", False)
                        if isinstance(content, str) and content:
                            error_marker = " ❌" if is_error else ""
                            log_content = content[:2000]
                            if len(content) > 2000:
                                log_content += f"\n... ({len(content)} chars total)"
                            full_log_parts.append(
                                f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                            )

        elif event_type == "result":
            # Final result — supports both CodeBuddy/Claude and Gemini formats
            result_text = event.get("result", "")
            # Only use result_text as fallback when no text was collected
            # from streaming assistant events, to avoid duplicating content.
            if result_text and not assistant_text_parts:
                assistant_text_parts.append(result_text)

            # Extract session_id from result event (Claude Code / CodeBuddy)
            session_id = event.get("session_id", "")
            if session_id and session_id != self._session_id:
                self._session_id = session_id
                if self._on_session_id_changed:
                    self._on_session_id_changed(session_id)

            # CodeBuddy/Claude fields
            is_error = event.get("is_error", False)
            duration_ms = event.get("duration_ms", 0)
            num_turns = event.get("num_turns", 0)

            # Gemini fields (fallback)
            if not is_error and event.get("status") == "error":
                is_error = True
            stats = event.get("stats", {})
            if duration_ms == 0 and isinstance(stats, dict):
                duration_ms = stats.get("duration_ms", 0)
            if num_turns == 0 and isinstance(stats, dict):
                num_turns = stats.get("tool_calls", 0)

            status = "❌ Error" if is_error else "✅ Done"
            summary = (
                f"\n--- {status} ({num_turns} turns, {duration_ms / 1000:.1f}s) ---\n"
            )
            if is_error:
                sys.stdout.write(f"\033[31m{summary}\033[0m")
            else:
                sys.stdout.write(summary)
            sys.stdout.flush()
            full_log_parts.append(f"\n{summary}")

            # When is_error is True and no assistant text was collected,
            # the caller would only see "empty response".  Attach error
            # details so the AICallError message is informative.
            if is_error and not assistant_text_parts:
                error_detail = event.get("error", result_text or "unknown error")
                if isinstance(error_detail, dict):
                    error_detail = error_detail.get("message", str(error_detail))
                assistant_text_parts.append(f"[ERROR] {error_detail}")

        elif event_type == "step_start":
            # OpenCode format: session start event — extract session ID
            # sessionID may be at top level or in data
            session_id = event.get("sessionID", "")
            if not session_id:
                data = event.get("data", {})
                if isinstance(data, dict):
                    session_id = data.get("sessionID", data.get("sessionId", ""))
            if session_id:
                self._session_id = session_id
                # Notify external listener for state persistence
                if self._on_session_id_changed:
                    self._on_session_id_changed(session_id)

        elif event_type == "text":
            # OpenCode format: text event with part.text
            part = event.get("part", {})
            text = part.get("text", "")
            if text:
                assistant_text_parts.append(text)
                full_log_parts.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()

        elif event_type == "step_finish":
            # OpenCode format: step finished — extract token info from part
            part = event.get("part", {})
            tokens = part.get("tokens", {})
            total_tokens = tokens.get("total", 0) if isinstance(tokens, dict) else 0
            cost = part.get("cost", 0)
            reason = part.get("reason", "stop")
            status = "❌ Error" if reason == "error" else "✅ Done"
            summary = (
                f"\n--- {status} (tokens: {total_tokens}, cost: ${cost:.4f}) ---\n"
            )
            sys.stdout.write(summary)
            sys.stdout.flush()
            full_log_parts.append(f"\n{summary}")

        elif event_type == "thread.started":
            # Codex format: session/thread start — capture thread_id as session_id
            thread_id = event.get("thread_id", "")
            if thread_id and thread_id != self._session_id:
                self._session_id = thread_id
                if self._on_session_id_changed:
                    self._on_session_id_changed(thread_id)

        elif event_type == "item.completed":
            # Codex format: completed item (message, tool call, tool result)
            item = event.get("item", {})
            item_type = item.get("type", "")

            if item_type == "agent_message":
                # AI assistant text response
                text = item.get("text", "")
                if text:
                    if assistant_text_parts and not assistant_text_parts[-1].endswith(
                        "\n"
                    ):
                        assistant_text_parts.append("\n")
                    assistant_text_parts.append(text)
                    full_log_parts.append(text)
                    sys.stdout.write(text)
                    if not text.endswith("\n"):
                        sys.stdout.write("\n")
                    sys.stdout.flush()

            elif item_type == "command_execution":
                # Codex runs tools as "command_execution" items.
                # item.started has status="in_progress" (no output yet);
                # item.completed has the full aggregated_output + exit_code.
                status = item.get("status", "")
                command = item.get("command", "")
                output = item.get("aggregated_output", "")
                exit_code = item.get("exit_code")

                if status == "completed" and command:
                    # Display tool call
                    self._display_tool_use("Bash", {"command": command})
                    tool_log = self._format_tool_use_for_log("Bash", {"command": command})
                    full_log_parts.append(tool_log)

                    # Display/log tool result
                    if output:
                        is_error = exit_code is not None and exit_code != 0
                        sys.stdout.flush()
                        error_marker = " ❌" if is_error else ""
                        log_content = output[:2000]
                        if len(output) > 2000:
                            log_content += f"\n... ({len(output)} chars total)"
                        full_log_parts.append(
                            f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                        )

            elif item_type == "tool_call":
                # Generic tool invocation (non-command_execution)
                tool_name = item.get("name", item.get("tool_name", "unknown"))
                tool_input = item.get("arguments", item.get("input", {}))
                if isinstance(tool_input, str):
                    try:
                        tool_input = json.loads(tool_input)
                    except json.JSONDecodeError:
                        tool_input = {"raw": tool_input}
                self._display_tool_use(tool_name, tool_input)
                tool_log = self._format_tool_use_for_log(tool_name, tool_input)
                full_log_parts.append(tool_log)

            elif item_type == "tool_call_output":
                # Tool result
                output = item.get("output", item.get("result", ""))
                is_error = item.get("is_error", False)
                if isinstance(output, str) and output:
                    error_marker = " ❌" if is_error else ""
                    log_content = output[:2000]
                    if len(output) > 2000:
                        log_content += f"\n... ({len(output)} chars total)"
                    full_log_parts.append(
                        f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                    )

            # Silently ignore: "reasoning" (thinking), etc.

        elif event_type == "turn.completed":
            # Codex format: turn finished — display summary
            usage = event.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            total_tokens = input_tokens + output_tokens
            status = "✅ Done"
            summary = f"\n--- {status} (tokens: {total_tokens}) ---\n"
            sys.stdout.write(summary)
            sys.stdout.flush()
            full_log_parts.append(f"\n{summary}")

        # Silently ignore: "init", "system", "topic", "item.started",
        # "turn.started", etc.

    def _display_tool_use(self, tool_name: str, tool_input: dict):
        """Display a tool use event with a readable summary."""
        tool_name_lower = tool_name.lower()
        if tool_name_lower in ("bash", "run_shell_command"):
            cmd = tool_input.get("command", "")
            sys.stdout.write(f"\n🔧 [{tool_name}] {cmd}\n")
        elif tool_name_lower in ("edit", "write", "multiedit", "write_file"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📝 [{tool_name}] {path}\n")
        elif tool_name_lower in ("read", "read_file"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📖 [{tool_name}] {path}\n")
        elif tool_name_lower in ("glob", "grep"):
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            sys.stdout.write(f"\n🔍 [{tool_name}] {pattern}\n")
        else:
            sys.stdout.write(f"\n🔧 [{tool_name}]\n")
        sys.stdout.flush()

    def _format_tool_use_for_log(self, tool_name: str, tool_input: dict) -> str:
        """
        Format a tool use event as a Markdown string for the conversation log.

        Args:
            tool_name: Tool name (e.g. "Bash", "Read", "Edit")
            tool_input: Tool input parameters

        Returns:
            str: Formatted markdown string for the tool call
        """
        tool_name_lower = tool_name.lower()
        if tool_name_lower in ("bash", "run_shell_command"):
            cmd = tool_input.get("command", "")
            return f"\n🔧 **[Bash]**\n```bash\n{cmd}\n```\n"
        elif tool_name_lower in ("edit", "write"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            content = tool_input.get("content", tool_input.get("new_string", ""))
            result = f"\n📝 **[{tool_name}]** `{path}`\n"
            if content:
                # Truncate very long edits for readability
                preview = content[:1000]
                if len(content) > 1000:
                    preview += f"\n... ({len(content)} chars total)"
                result += f"```\n{preview}\n```\n"
            return result
        elif tool_name_lower == "multiEdit":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            edits = tool_input.get("edits", [])
            return f"\n📝 **[MultiEdit]** `{path}` ({len(edits)} edits)\n"
        elif tool_name_lower in ("read", "read_file"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            return f"\n📖 **[Read]** `{path}`\n"
        elif tool_name_lower in ("glob", "grep"):
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            return f"\n🔍 **[{tool_name}]** `{pattern}`\n"
        elif tool_name_lower == "todoread":
            return f"\n📋 **[TodoRead]**\n"
        elif tool_name_lower in ("taskcreate", "taskupdate"):
            task_desc = tool_input.get("description", tool_input.get("task", ""))
            if isinstance(task_desc, str) and task_desc:
                return f"\n🔧 **[{tool_name}]** {task_desc[:200]}\n"
            return f"\n🔧 **[{tool_name}]**\n"
        else:
            # Generic tool
            summary = json.dumps(tool_input, ensure_ascii=False)[:200]
            return f"\n🔧 **[{tool_name}]** {summary}\n"

    @staticmethod
    def _parse_cli_error(raw_error: str) -> tuple:
        """Parse CLI error output, extracting structured info if available.

        AI CLI tools (Claude Code, CodeBuddy, Gemini CLI, etc.) may
        return structured JSON errors when they fail.  Common formats:

        - Anthropic/Claude: ``{"type":"error","error":{"type":"overloaded_error","message":"..."}}``
        - Flat JSON: ``{"error":"rate_limit","message":"..."}``
        - Plain text (fallback)

        The raw error string may also be multi-line stream-json output
        where only the last line is the error JSON.

        Returns:
            ``(message, error_type)`` where *error_type* is ``None``
            for unstructured errors, or a string like
            ``"overloaded_error"``, ``"rate_limit"``,
            ``"authentication_error"`` etc.
        """
        text = raw_error.strip()
        if not text:
            return ("(empty error output)", None)

        # Try the full text first, then just the last line (stream-json)
        for candidate in [text, text.rsplit("\n", 1)[-1].strip()]:
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            # Anthropic nested format: {"type":"error","error":{"type":"...","message":"..."}}
            err = data.get("error", {})
            if isinstance(err, dict) and ("message" in err or "type" in err):
                return (
                    err.get("message", json.dumps(err, ensure_ascii=False)),
                    err.get("type"),
                )
            # Flat format: {"message":"...", "error":"...", "type":"..."}
            if "message" in data:
                return (
                    data["message"],
                    data.get("type")
                    or (
                        data.get("error")
                        if isinstance(data.get("error"), str)
                        else None
                    ),
                )

        return (text, None)

    def _parse_json_response(self, response: str) -> dict:
        """
        Extract and parse JSON from AI response.

        The AI response might contain markdown code blocks or extra text
        surrounding the JSON. This method tries multiple strategies.

        Args:
            response: Raw AI response text

        Returns:
            dict: Parsed JSON object

        Raises:
            AICallError: If JSON parsing fails
        """
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
            f"Response preview: {response[:500]}"
        )

    def reset_session(self):
        """Reset the session state, so next call starts a new session."""
        self._session_id = None
        logger.info(f"[{self.context_id}] Session reset")