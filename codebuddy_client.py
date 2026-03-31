"""
AI Client - Wraps AI CLI tool interactions with context management.

This module provides the AIClient class that handles:
- Calling AI tools (CodeBuddy, Claude Code, Gemini CLI) via subprocess
- Managing conversation context (session_id based resumption)
- Parsing JSON responses from AI
- Timeout handling

Backward compatible: CodeBuddyClient is an alias for AIClient.
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


class AICallError(Exception):
    """AI call error (auth failure, response parse failure, etc.)"""
    pass


class AIClient:
    """
    AI CLI client with context management.
    
    Supports multiple AI backends through the provider abstraction:
    - CodeBuddy (codebuddy)
    - Claude Code (claude)
    - Gemini Cli (gemini)
    - OpenCode (opencode)
    
    Each main task should create its own AIClient instance.
    Subtasks within the same main task share context via session_id (--resume).
    """

    def __init__(
        self,
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        context_id: str = None,
        # Legacy parameters for backward compatibility
        codebuddy_path: str = None,
        model: str = None,
    ):
        """
        Initialize AIClient.
        
        Args:
            provider: AI provider instance (takes precedence over legacy params)
            workspace: Working directory
            timeout: Default timeout in seconds
            context_id: Context identifier for logging/tracking
            codebuddy_path: (Legacy) Path to CodeBuddy executable
            model: (Legacy) AI model to use
        """
        # Support both new provider-based and legacy initialization
        if provider is not None:
            self.provider = provider
        else:
            # Legacy: create a CodeBuddyProvider from old-style params
            self.provider = CodeBuddyProvider(
                executable=codebuddy_path or "codebuddy",
                model=model,  # Use provider's default_model if not specified
            )
        
        self.workspace = workspace
        self.timeout = timeout
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
    
    # Legacy property accessors for backward compatibility
    @property
    def codebuddy_path(self):
        return self.provider.executable
    
    @property
    def model(self):
        return self.provider.model

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
            print(f"   ⏳ Waiting {delay}s before retry (attempt after {self._consecutive_failures} consecutive failure(s))")
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
            f"(session_id={self.session_id or 'new'}, model={self.model}, timeout={effective_timeout}s)"
        )
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:200]}...")
        logger.debug(f"[{self.context_id}] Command: {cmd_args}")
        
        # Write prompt to a temp file to avoid shell escaping issues
        prompt_file_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', delete=False, encoding='utf-8'
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
                encoding='utf-8',
                errors='replace',
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
            deadline = time.monotonic() + effective_timeout
            try:
                for line in process.stdout:
                    if time.monotonic() > deadline:
                        process.kill()
                        raise subprocess.TimeoutExpired(
                            full_cmd, effective_timeout
                        )
                    stdout_chunks.append(line)
                    # Parse stream-json lines for real-time display
                    self._handle_stream_line(
                        line.rstrip('\n'), assistant_text_parts, full_log_parts
                    )
            except subprocess.TimeoutExpired:
                process.kill()
                raise

            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning("Process did not exit within 30s after stdout closed, killing")
                process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.error("Process still alive after kill, abandoning")
            stderr_thread.join(timeout=5)

            stdout_text = "".join(stdout_chunks)
            stderr_text = "".join(stderr_chunks)

            if process.returncode != 0:
                error_msg = stderr_text.strip() or stdout_text.strip()
                # Check for authentication error
                if "Authentication" in error_msg or "login" in error_msg.lower():
                    raise AICallError(
                        f"{self.provider.name} authentication required. "
                        f"Please run '{self.provider.executable} --help' to check. "
                        f"Error: {error_msg}"
                    )
                raise AICallError(
                    f"{self.provider.name} returned exit code {process.returncode}: {error_msg}"
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

        except subprocess.TimeoutExpired:
            self._consecutive_failures += 1
            raise AICallError(
                f"{self.provider.name} timed out after {effective_timeout}s"
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

    def _handle_stream_line(self, line: str, assistant_text_parts: list, full_log_parts: list = None):
        """
        Parse a single line of stream-json output and display relevant info in real-time.
        
        Supports three stream-json dialects:
        
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
        
        if event_type == "assistant":
            # CodeBuddy/Claude format: AI message with content[] array
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
                    tool_input = tool_input_raw if isinstance(tool_input_raw, dict) else {}
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
            is_error = (status == "error")
            content = output if output else (error_info.get("message", "") if isinstance(error_info, dict) else str(error_info))
            if content:
                preview = content[:500]
                if len(content) > 500:
                    preview += f"... ({len(content)} chars total)"
                sys.stdout.write(f"   ↳ {preview}\n")
                sys.stdout.flush()
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
                            preview = content[:500]
                            if len(content) > 500:
                                preview += f"... ({len(content)} chars total)"
                            sys.stdout.write(f"   ↳ {preview}\n")
                            sys.stdout.flush()
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
            if result_text:
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
            summary = f"\n--- {status} ({num_turns} turns, {duration_ms/1000:.1f}s) ---\n"
            sys.stdout.write(summary)
            sys.stdout.flush()
            full_log_parts.append(f"\n{summary}")
        
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
            summary = f"\n--- {status} (tokens: {total_tokens}, cost: ${cost:.4f}) ---\n"
            sys.stdout.write(summary)
            sys.stdout.flush()
            full_log_parts.append(f"\n{summary}")

        # Silently ignore: "init", "system", "topic", etc.

    def _display_tool_use(self, tool_name: str, tool_input: dict):
        """Display a tool use event with a readable summary."""
        tool_name_lower = tool_name.lower()
        if tool_name_lower == "bash":
            cmd = tool_input.get("command", "")
            sys.stdout.write(f"\n🔧 [{tool_name}] {cmd}\n")
        elif tool_name_lower in ("edit", "write", "multiedit"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📝 [{tool_name}] {path}\n")
        elif tool_name_lower == "read":
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
        if tool_name_lower == "bash":
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
        elif tool_name_lower == "read":
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
            r'```json\s*\n(.*?)\n\s*```',
            r'```\s*\n(.*?)\n\s*```',
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
            if char == '{':
                if brace_depth == 0:
                    start_idx = i
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
                if brace_depth == 0 and start_idx is not None:
                    try:
                        return json.loads(response[start_idx:i + 1])
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


# Backward compatibility alias
CodeBuddyClient = AIClient


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
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        context_id: str = None,
        # Legacy parameters for backward compatibility
        codebuddy_path: str = None,
        model: str = None,
    ):
        """
        Initialize AIClientSDK.
        
        Args:
            provider: AI provider instance (must be CodeBuddyProvider or None)
            workspace: Working directory
            timeout: Default timeout in seconds
            context_id: Context identifier for logging/tracking
            codebuddy_path: (Legacy) Path to CodeBuddy executable
            model: (Legacy) AI model to use
        """
        # Support both new provider-based and legacy initialization
        if provider is not None:
            self.provider = provider
        else:
            self.provider = CodeBuddyProvider(
                executable=codebuddy_path or "codebuddy",
                model=model,  # Use provider's default_model if not specified
            )

        self.workspace = workspace
        self.timeout = timeout
        self.context_id = context_id
        self._session_id = None  # SDK session ID for conversation continuity
        self.last_full_log = ""
        # Callback to notify session_id changes (for state persistence)
        self._on_session_id_changed = None
        # Exponential backoff state
        self._consecutive_failures = 0
        self._backoff_base = 5  # seconds
        self._backoff_max = 300  # default max wait, overridden by config

    # Legacy property accessors for backward compatibility
    @property
    def codebuddy_path(self):
        return self.provider.executable

    @property
    def model(self):
        return self.provider.model

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
            print(f"   ⏳ Waiting {delay}s before retry (attempt after {self._consecutive_failures} consecutive failure(s))")
            time.sleep(delay)

        logger.info(
            f"[{self.context_id}] Calling CodeBuddy SDK "
            f"(session_id={self.session_id or 'new'}, model={self.model}, timeout={effective_timeout}s)"
        )
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:200]}...")

        try:
            response, full_log = self._run_query(
                prompt, effective_timeout
            )
        except AICallError:
            self._consecutive_failures += 1
            raise
        except Exception as e:
            self._consecutive_failures += 1
            raise AICallError(f"Failed to call CodeBuddy SDK: {e}")

        if not response:
            self._consecutive_failures += 1
            raise AICallError("CodeBuddy SDK returned empty response")

        self.last_full_log = full_log or response
        # Session is now active (session_id captured from ResultMessage)
        self._consecutive_failures = 0  # Reset backoff on success

        logger.info(f"[{self.context_id}] Got response ({len(response)} chars)")
        logger.debug(f"[{self.context_id}] Response: {response[:200]}...")

        if expect_json:
            return self._parse_json_response(response)
        return response

    def _run_query(
        self, prompt: str, timeout: int
    ) -> tuple:
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

        async def _do_query():
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
                # Parse space-separated extra args into dict
                # e.g. "--debug --verbose" -> {"debug": None, "verbose": None}
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
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ThinkingBlock):
                            thinking_text = block.thinking
                            if thinking_text:
                                # Display thinking in a visually distinct way
                                sys.stdout.write("\n💭 [Thinking]\n")
                                for line in thinking_text.splitlines():
                                    sys.stdout.write(f"  │ {line}\n")
                                sys.stdout.write("  └─\n")
                                sys.stdout.flush()
                                # Include thinking in full log
                                full_log_parts.append(
                                    f"\n<details><summary>💭 Thinking</summary>\n\n{thinking_text}\n\n</details>\n"
                                )
                        elif isinstance(block, TextBlock):
                            text = block.text
                            if text:
                                assistant_text_parts.append(text)
                                full_log_parts.append(text)
                                sys.stdout.write(text)
                                sys.stdout.flush()
                        elif isinstance(block, ToolUseBlock):
                            self._display_tool_use(block.name, block.input)
                            tool_log = self._format_tool_use_for_log(
                                block.name, block.input
                            )
                            full_log_parts.append(tool_log)
                        elif isinstance(block, ToolResultBlock):
                            content = block.content or ""
                            is_error = block.is_error or False
                            if isinstance(content, str) and content:
                                preview = content[:500]
                                if len(content) > 500:
                                    preview += f"... ({len(content)} chars total)"
                                sys.stdout.write(f"   ↳ {preview}\n")
                                sys.stdout.flush()
                                error_marker = " ❌" if is_error else ""
                                log_content = content[:2000]
                                if len(content) > 2000:
                                    log_content += f"\n... ({len(content)} chars total)"
                                full_log_parts.append(
                                    f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                                )

                elif isinstance(message, UserMessage):
                    # User messages may contain tool results
                    if hasattr(message, 'content') and isinstance(message.content, list):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                content = block.content or ""
                                is_error = block.is_error or False
                                if isinstance(content, str) and content:
                                    preview = content[:500]
                                    if len(content) > 500:
                                        preview += f"... ({len(content)} chars total)"
                                    sys.stdout.write(f"   ↳ {preview}\n")
                                    sys.stdout.flush()
                                    error_marker = " ❌" if is_error else ""
                                    log_content = content[:2000]
                                    if len(content) > 2000:
                                        log_content += f"\n... ({len(content)} chars total)"
                                    full_log_parts.append(
                                        f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                                    )

                elif isinstance(message, ResultMessage):
                    # Capture session_id for future resumption
                    if message.session_id:
                        self._session_id = message.session_id
                        # Notify external listener for state persistence
                        if self._on_session_id_changed:
                            self._on_session_id_changed(message.session_id)

                    result_text = message.result or ""
                    if result_text:
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
                            raise AICallError(
                                f"CodeBuddy SDK error: {'; '.join(errors)}"
                            )

                elif isinstance(message, StreamEvent):
                    # StreamEvent contains partial updates during streaming;
                    # we can optionally log them but they're already reflected
                    # in AssistantMessage blocks above.
                    pass

        # Run the async query with a timeout
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    asyncio.wait_for(_do_query(), timeout=timeout)
                )
            finally:
                loop.close()
        except asyncio.TimeoutError:
            raise AICallError(
                f"CodeBuddy SDK timed out after {timeout}s"
            )

        response = "".join(assistant_text_parts).strip()
        full_log = "\n".join(full_log_parts).strip()
        return response, full_log

    def _display_tool_use(self, tool_name: str, tool_input: dict):
        """Display a tool use event with a readable summary."""
        tool_name_lower = tool_name.lower()
        if tool_name_lower == "bash":
            cmd = tool_input.get("command", "")
            sys.stdout.write(f"\n🔧 [{tool_name}] {cmd}\n")
        elif tool_name_lower in ("edit", "write", "multiEdit"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📝 [{tool_name}] {path}\n")
        elif tool_name_lower == "read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📖 [{tool_name}] {path}\n")
        elif tool_name_lower in ("glob", "grep"):
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            sys.stdout.write(f"\n🔍 [{tool_name}] {pattern}\n")
        else:
            sys.stdout.write(f"\n🔧 [{tool_name}]\n")
        sys.stdout.flush()

    def _format_tool_use_for_log(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use event as a Markdown string for the conversation log."""
        tool_name_lower = tool_name.lower()
        if tool_name_lower == "bash":
            cmd = tool_input.get("command", "")
            return f"\n🔧 **[Bash]**\n```bash\n{cmd}\n```\n"
        elif tool_name_lower in ("edit", "write"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            content = tool_input.get("content", tool_input.get("new_string", ""))
            result = f"\n📝 **[{tool_name}]** `{path}`\n"
            if content:
                preview = content[:1000]
                if len(content) > 1000:
                    preview += f"\n... ({len(content)} chars total)"
                result += f"```\n{preview}\n```\n"
            return result
        elif tool_name_lower == "multiedit":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            edits = tool_input.get("edits", [])
            return f"\n📝 **[MultiEdit]** `{path}` ({len(edits)} edits)\n"
        elif tool_name_lower == "read":
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
            summary = json.dumps(tool_input, ensure_ascii=False)[:200]
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
            r'```json\s*\n(.*?)\n\s*```',
            r'```\s*\n(.*?)\n\s*```',
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
            if char == '{':
                if brace_depth == 0:
                    start_idx = i
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
                if brace_depth == 0 and start_idx is not None:
                    try:
                        return json.loads(response[start_idx:i + 1])
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
        from ai_providers import TestProvider
        provider = TestProvider(test_rules_file="test_rules.txt")
        client = AIClientTest(provider=provider, context_id="task_1")
        response = client.ask("some prompt")  # Returns first rule
        response = client.ask("another prompt")  # Returns second rule
    """

    def __init__(
        self,
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        context_id: str = None,
        # Legacy parameters (ignored for test client)
        codebuddy_path: str = None,
        model: str = None,
    ):
        from ai_providers import TestProvider
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
    def codebuddy_path(self):
        return self.provider.executable

    @property
    def model(self):
        return self.provider.model

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
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:200]}...")

        # Get next response from provider
        response = self.provider.get_next_response()

        # Display the response like a real client would
        print(f"\n🧪 [TestProvider] Rule #{self.provider._rule_index}/{len(self.provider._rules)}")
        print(f"   Response: {response[:200]}{'...' if len(response) > 200 else ''}")

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
            except OSError as e:
                logger.warning(
                    f"[{self.context_id}] Failed to read autoagent-exec script "
                    f"{script_path}: {e}"
                )

        if not exec_path or not log_dir:
            # Legacy format: python "<exec_path>" --log-dir "<log_dir>" --task-id <id> -- <command>
            legacy_match = re.search(
                r'python\s+["\'](.+?autoagent_exec\.py)["\']\s+--log-dir\s+["\'](.+?)["\']',
                prompt,
            )
            if legacy_match:
                exec_path = legacy_match.group(1)
                log_dir = legacy_match.group(2)

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

        print(f"\n🧪 [TestProvider] Detected autoagent-exec command, executing for real:")
        print(f"   exec_path: {exec_path}")
        print(f"   log_dir:   {log_dir}")
        print(f"   task_id:   {task_id}")
        print(f"   command:   {cmd}")

        # Build the real autoagent_exec.py command as a list to avoid
        # shell quoting issues (especially on Linux where /bin/sh handles
        # quotes differently from cmd.exe).
        # We use shlex.split to properly tokenize the cmd string (which
        # may contain quoted arguments like: python -c "import time; ...")
        import shlex
        if os.name == 'nt':
            # On Windows, shlex.split doesn't handle Windows paths well;
            # use a simple split but preserve quoted strings
            cmd_parts = shlex.split(cmd, posix=False)
            # Remove surrounding quotes that shlex.split(posix=False) preserves
            cmd_parts = [p.strip('"').strip("'") for p in cmd_parts]
        else:
            cmd_parts = shlex.split(cmd)

        full_cmd = [
            sys.executable, exec_path,
            '--log-dir', log_dir,
            '--task-id', task_id,
            '--',
        ] + cmd_parts

        try:
            result = subprocess.run(
                full_cmd,
                shell=False,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30,  # autoagent-exec itself should return within ~10s
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
                f"[{self.context_id}] autoagent-exec timed out (30s) "
                f"for task {task_id}"
            )
            print(f"   ❌ autoagent-exec timed out!")
        except Exception as e:
            logger.error(
                f"[{self.context_id}] Failed to run autoagent-exec: {e}"
            )
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
            r'```json\s*\n(.*?)\n\s*```',
            r'```\s*\n(.*?)\n\s*```',
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
            if char == '{':
                if brace_depth == 0:
                    start_idx = i
                brace_depth += 1
            elif char == '}':
                brace_depth -= 1
                if brace_depth == 0 and start_idx is not None:
                    try:
                        return json.loads(response[start_idx:i + 1])
                    except json.JSONDecodeError:
                        start_idx = None

        raise AICallError(
            f"Failed to parse JSON from test response. "
            f"Response preview: {response[:500]}"
        )

    def reset_session(self):
        """Reset the session state."""
        self._session_id = None
        logger.info(f"[{self.context_id}] Test session reset")
