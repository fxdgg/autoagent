"""
AI Client - Wraps AI CLI tool interactions with context management.

This module provides the AIClient class that handles:
- Calling AI tools (CodeBuddy, Claude Code, Gemini CLI) via subprocess
- Managing conversation context (--continue flag)
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
    - Claude Code Internal (claude-internal)
    - Gemini CLI Internal (gemini-internal)
    
    Each main task should create its own AIClient instance.
    Subtasks within the same main task share context via --continue.
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
                model=model or "glm-5.0-ioa",
            )
        
        self.workspace = workspace
        self.timeout = timeout
        self.context_id = context_id
        self._session_started = False
        # Full conversation log including tool calls (set after each ask() call)
        self.last_full_log = ""
    
    # Legacy property accessors for backward compatibility
    @property
    def codebuddy_path(self):
        return self.provider.executable
    
    @property
    def model(self):
        return self.provider.model

    def ask(
        self,
        prompt: str,
        expect_json: bool = False,
        timeout: int = None,
        continue_session: bool = False,
    ) -> Union[str, dict]:
        """
        Send a prompt to CodeBuddy and get a response.
        
        Args:
            prompt: The prompt to send
            expect_json: Whether to parse the response as JSON
            timeout: Override default timeout
            continue_session: Whether to use --continue flag
            
        Returns:
            str or dict: The AI response (parsed as JSON if expect_json=True)
            
        Raises:
            AICallError: If the call fails
        """
        effective_timeout = timeout or self.timeout

        # Build command args (without prompt - prompt goes via stdin)
        cmd_args = self._build_command(continue_session)
        
        logger.info(
            f"[{self.context_id}] Calling {self.provider.name} "
            f"(continue={continue_session}, timeout={effective_timeout}s)"
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

            process.wait()
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

            self._session_started = True
            logger.info(f"[{self.context_id}] Got response ({len(response)} chars)")
            logger.debug(f"[{self.context_id}] Response: {response[:200]}...")

            if expect_json:
                return self._parse_json_response(response)
            return response

        except subprocess.TimeoutExpired:
            raise AICallError(
                f"{self.provider.name} timed out after {effective_timeout}s"
            )
        except AICallError:
            raise
        except Exception as e:
            raise AICallError(f"Failed to call {self.provider.name}: {e}")
        finally:
            # Clean up temp file
            if prompt_file_path:
                try:
                    os.unlink(prompt_file_path)
                except OSError:
                    pass

    def _build_command(self, continue_session: bool) -> str:
        """
        Build the AI CLI command string (without prompt).
        
        Delegates to the provider to build the correct command for the
        specific AI tool being used.
        
        Args:
            continue_session: Whether to continue existing session
            
        Returns:
            str: The command string (prompt will be piped via stdin)
        """
        use_continue = continue_session and self._session_started
        return self.provider.build_command(continue_session=use_continue)

    def _handle_stream_line(self, line: str, assistant_text_parts: list, full_log_parts: list = None):
        """
        Parse a single line of stream-json output and display relevant info in real-time.
        
        stream-json format produces one JSON object per line. Key event types:
          - "assistant": AI message with content array (text blocks and/or tool_use)
          - "user": Contains tool_result from tool executions
          - "result": Final result summary with "result" text
          - "system": System/session init messages
          - "topic": Conversation topic
        
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
        
        if event_type == "assistant":
            # AI message - content is in message.content[] array
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
                    # Log tool call to full_log
                    tool_log = self._format_tool_use_for_log(tool_name, tool_input)
                    full_log_parts.append(tool_log)
        
        elif event_type == "user":
            # User message containing tool_result
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
                            # Log tool result to full_log
                            error_marker = " ❌" if is_error else ""
                            # For log: include more content (up to 2000 chars)
                            log_content = content[:2000]
                            if len(content) > 2000:
                                log_content += f"\n... ({len(content)} chars total)"
                            full_log_parts.append(
                                f"\n<details><summary>Tool Result{error_marker}</summary>\n\n```\n{log_content}\n```\n</details>\n"
                            )
        
        elif event_type == "result":
            # Final result - always append result_text so that completion
            # markers (e.g. "✅ COMPLETED") emitted in the result event
            # are visible to _check_completion().
            result_text = event.get("result", "")
            if result_text:
                assistant_text_parts.append(result_text)
            # Always print a summary line
            is_error = event.get("is_error", False)
            duration_ms = event.get("duration_ms", 0)
            num_turns = event.get("num_turns", 0)
            status = "❌ Error" if is_error else "✅ Done"
            summary = f"\n--- {status} ({num_turns} turns, {duration_ms/1000:.1f}s) ---\n"
            sys.stdout.write(summary)
            sys.stdout.flush()
            full_log_parts.append(f"\n{summary}")

    def _display_tool_use(self, tool_name: str, tool_input: dict):
        """Display a tool use event with a readable summary."""
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            sys.stdout.write(f"\n🔧 [{tool_name}] {cmd}\n")
        elif tool_name in ("Edit", "Write", "MultiEdit"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📝 [{tool_name}] {path}\n")
        elif tool_name == "Read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📖 [{tool_name}] {path}\n")
        elif tool_name in ("Glob", "Grep"):
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
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return f"\n🔧 **[Bash]**\n```bash\n{cmd}\n```\n"
        elif tool_name in ("Edit", "Write"):
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
        elif tool_name == "MultiEdit":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            edits = tool_input.get("edits", [])
            return f"\n📝 **[MultiEdit]** `{path}` ({len(edits)} edits)\n"
        elif tool_name == "Read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            return f"\n📖 **[Read]** `{path}`\n"
        elif tool_name in ("Glob", "Grep"):
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            return f"\n🔍 **[{tool_name}]** `{pattern}`\n"
        elif tool_name == "TodoRead":
            return f"\n📋 **[TodoRead]**\n"
        elif tool_name in ("TaskCreate", "TaskUpdate"):
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
        """Reset the session state, so next call won't use --continue."""
        self._session_started = False
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
                model=model or "glm-5.0-ioa",
            )

        self.workspace = workspace
        self.timeout = timeout
        self.context_id = context_id
        self._session_id = None  # SDK session ID for conversation continuity
        self._session_started = False
        self.last_full_log = ""

    # Legacy property accessors for backward compatibility
    @property
    def codebuddy_path(self):
        return self.provider.executable

    @property
    def model(self):
        return self.provider.model

    def ask(
        self,
        prompt: str,
        expect_json: bool = False,
        timeout: int = None,
        continue_session: bool = False,
    ) -> Union[str, dict]:
        """
        Send a prompt to CodeBuddy via SDK and get a response.
        
        This is a synchronous wrapper around the async SDK query() call.
        
        Args:
            prompt: The prompt to send
            expect_json: Whether to parse the response as JSON
            timeout: Override default timeout
            continue_session: Whether to continue the existing session
            
        Returns:
            str or dict: The AI response (parsed as JSON if expect_json=True)
            
        Raises:
            AICallError: If the call fails
        """
        effective_timeout = timeout or self.timeout

        logger.info(
            f"[{self.context_id}] Calling CodeBuddy SDK "
            f"(continue={continue_session}, timeout={effective_timeout}s)"
        )
        logger.debug(f"[{self.context_id}] Prompt: {prompt[:200]}...")

        try:
            response, full_log = self._run_query(
                prompt, continue_session, effective_timeout
            )
        except AICallError:
            raise
        except Exception as e:
            raise AICallError(f"Failed to call CodeBuddy SDK: {e}")

        if not response:
            raise AICallError("CodeBuddy SDK returned empty response")

        self.last_full_log = full_log or response
        self._session_started = True

        logger.info(f"[{self.context_id}] Got response ({len(response)} chars)")
        logger.debug(f"[{self.context_id}] Response: {response[:200]}...")

        if expect_json:
            return self._parse_json_response(response)
        return response

    def _run_query(
        self, prompt: str, continue_session: bool, timeout: int
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

            # Session continuity
            use_continue = continue_session and self._session_started
            if use_continue and self._session_id:
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
                f"cwd={options.cwd}, continue={options.continue_conversation}, "
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
                    # Capture session_id for future --continue
                    if message.session_id:
                        self._session_id = message.session_id

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
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            sys.stdout.write(f"\n🔧 [{tool_name}] {cmd}\n")
        elif tool_name in ("Edit", "Write", "MultiEdit"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📝 [{tool_name}] {path}\n")
        elif tool_name == "Read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            sys.stdout.write(f"\n📖 [{tool_name}] {path}\n")
        elif tool_name in ("Glob", "Grep"):
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            sys.stdout.write(f"\n🔍 [{tool_name}] {pattern}\n")
        else:
            sys.stdout.write(f"\n🔧 [{tool_name}]\n")
        sys.stdout.flush()

    def _format_tool_use_for_log(self, tool_name: str, tool_input: dict) -> str:
        """Format a tool use event as a Markdown string for the conversation log."""
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return f"\n🔧 **[Bash]**\n```bash\n{cmd}\n```\n"
        elif tool_name in ("Edit", "Write"):
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            content = tool_input.get("content", tool_input.get("new_string", ""))
            result = f"\n📝 **[{tool_name}]** `{path}`\n"
            if content:
                preview = content[:1000]
                if len(content) > 1000:
                    preview += f"\n... ({len(content)} chars total)"
                result += f"```\n{preview}\n```\n"
            return result
        elif tool_name == "MultiEdit":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            edits = tool_input.get("edits", [])
            return f"\n📝 **[MultiEdit]** `{path}` ({len(edits)} edits)\n"
        elif tool_name == "Read":
            path = tool_input.get("file_path", tool_input.get("filePath", ""))
            return f"\n📖 **[Read]** `{path}`\n"
        elif tool_name in ("Glob", "Grep"):
            pattern = tool_input.get("pattern", tool_input.get("regex", ""))
            return f"\n🔍 **[{tool_name}]** `{pattern}`\n"
        elif tool_name == "TodoRead":
            return f"\n📋 **[TodoRead]**\n"
        elif tool_name in ("TaskCreate", "TaskUpdate"):
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
        """Reset the session state."""
        self._session_started = False
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
        self._session_started = False
        self.last_full_log = ""

    @property
    def codebuddy_path(self):
        return self.provider.executable

    @property
    def model(self):
        return self.provider.model

    def ask(
        self,
        prompt: str,
        expect_json: bool = False,
        timeout: int = None,
        continue_session: bool = False,
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
            continue_session: Ignored
            
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
        self._session_started = True

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

        # Extract exec_path from the prompt
        # The prompt contains: python "<exec_path>" --log-dir "<log_dir>" --task-id <id> -- <command>
        exec_path_match = re.search(
            r'python\s+["\'](.+?autoagent_exec\.py)["\']\s+--log-dir\s+["\'](.+?)["\']',
            prompt,
        )
        if not exec_path_match:
            logger.warning(
                f"[{self.context_id}] Response contains autoagent-exec command "
                f"but could not extract exec_path/log_dir from prompt. "
                f"Skipping actual execution."
            )
            return response

        exec_path = exec_path_match.group(1)
        log_dir = exec_path_match.group(2)

        print(f"\n🧪 [TestProvider] Detected autoagent-exec command, executing for real:")
        print(f"   exec_path: {exec_path}")
        print(f"   log_dir:   {log_dir}")
        print(f"   task_id:   {task_id}")
        print(f"   command:   {cmd}")

        # Build the real autoagent_exec.py command
        full_cmd = (
            f'{sys.executable} "{exec_path}" '
            f'--log-dir "{log_dir}" '
            f'--task-id {task_id} '
            f'-- {cmd}'
        )

        try:
            result = subprocess.run(
                full_cmd,
                shell=True,
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
        self._session_started = False
        logger.info(f"[{self.context_id}] Test session reset")
