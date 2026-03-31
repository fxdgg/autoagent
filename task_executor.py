"""
Task Executors - Handle execution logic for different task types.

This module provides:
- SimpleTaskExecutor: Executes simple tasks with AI self-evaluation loop
- NestedTaskExecutor: Executes nested tasks with subtasks and AI decision points
- LoopingTaskExecutor: Executes looping tasks that repeat subtasks a fixed number of times
- SubtaskExecutor: Dispatches subtask execution based on type
"""

import os
import json
import time
import subprocess
import logging
from typing import Optional, Tuple

import yaml

from codebuddy_client import AIClient, CodeBuddyClient, AICallError, BashTimeoutError, SessionTimeoutError
from prompts.shared import build_system_prompt_coding_agent, prepend_system_prompt_prefix
from prompts.simple_task import build_simple_task_prompt
from prompts.long_running_task import (
    build_long_running_prompt as _build_lr_prompt,
    build_long_running_analysis_prompt as _build_lr_analysis_prompt,
)
from prompts.failure_analysis import (
    build_nested_failure_analysis_prompt,
    build_looping_failure_analysis_prompt,
)
from prompts.main_evaluation import build_main_evaluation_prompt
from truncation_limits import limits

logger = logging.getLogger(__name__)


_fast_fail_timeout_cache: int | None = None


def _load_fast_fail_timeout() -> int:
    """Load fast_fail_timeout from config.yaml (cached after first call).

    Returns:
        The configured fast-fail timeout in seconds (default 10).
    """
    global _fast_fail_timeout_cache
    if _fast_fail_timeout_cache is not None:
        return _fast_fail_timeout_cache

    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            value = config.get("fast_fail_timeout", 10)
            _fast_fail_timeout_cache = int(value)
            return _fast_fail_timeout_cache
        except Exception:
            pass
    _fast_fail_timeout_cache = 10
    return _fast_fail_timeout_cache


def _read_log_file_smart(path: str) -> str:
    """Read a log file with smart encoding detection.

    The log file may be written in binary mode (raw bytes from the subprocess),
    so we try multiple encodings:
      1. UTF-8 (strict)
      2. System console encoding (e.g. GBK on Chinese Windows)
      3. latin-1 (never fails)
    """
    with open(path, "rb") as f:
        raw = f.read()
    # Try UTF-8 first
    try:
        return raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        pass
    # Try system console encoding
    import locale
    console_enc = locale.getpreferredencoding(False)
    if console_enc and console_enc.lower() not in ("utf-8", "utf8"):
        try:
            return raw.decode(console_enc)
        except (UnicodeDecodeError, ValueError, LookupError):
            pass
    # Last resort
    return raw.decode("latin-1")


def _write_autoagent_exec_script(
    session_dir: str,
    task_id: str,
    fast_fail_timeout: int = 10,
) -> str:
    """Write (or overwrite) the ``autoagent-exec`` convenience script.

    The script is placed in ``<session_dir>/scripts/`` so the AI can invoke
    it by its absolute path without knowing the full
    ``python … --log-dir … --task-id …`` incantation.

    On Windows a ``.bat`` file is generated; on other platforms a ``.sh``
    file is generated.  Both accept arbitrary trailing arguments which are
    forwarded to ``autoagent_exec.py`` as the command to run.

    The script is regenerated every time a new (sub)task starts so that
    ``--task-id`` always matches the current task.

    Args:
        session_dir: Absolute path to the log session directory.
        task_id: Current task / subtask ID (e.g. ``"1"`` or ``"2.1"``).
        fast_fail_timeout: Seconds to wait before treating the command as
            long-running (default 10, from config.yaml ``fast_fail_timeout``).

    Returns:
        The absolute path to the generated script.
    """
    exec_py = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "autoagent_exec.py"
    ).replace("\\", "/")
    log_dir = session_dir.replace("\\", "/")

    scripts_dir = os.path.join(session_dir, "scripts")
    os.makedirs(scripts_dir, exist_ok=True)

    if os.name == "nt":
        script_name = "autoagent-exec.bat"
        # %* forwards all arguments.  The AI is instructed to wrap the
        # entire command in quotes so that shell operators (&&, |, ;)
        # are preserved as a single argument.
        content = (
            "@echo off\r\n"
            f'python "{exec_py}" --log-dir "{log_dir}" --task-id {task_id}'
            f' --fast-fail-timeout {fast_fail_timeout} --cmd %*\r\n'
        )
    else:
        script_name = "autoagent-exec.sh"
        # "$*" joins all positional parameters into a single string
        # (separated by the first character of IFS, which is space by
        # default).  This preserves the command as a single shell string
        # when the AI wraps it in quotes.
        content = (
            "#!/usr/bin/env bash\n"
            f'python3 "{exec_py}" --log-dir "{log_dir}" --task-id {task_id}'
            f' --fast-fail-timeout {fast_fail_timeout} --cmd "$*"\n'
        )

    script_path = os.path.join(scripts_dir, script_name)
    try:
        with open(script_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        # Make executable on Unix
        if os.name != "nt":
            os.chmod(script_path, 0o755)
        logger.debug(f"Wrote {script_path} (task_id={task_id})")
    except OSError as e:
        logger.warning(f"Failed to write {script_path}: {e}")

    return script_path.replace("\\", "/")


class ConfigError(Exception):
    """Configuration file error (YAML syntax, missing fields, etc.)"""
    pass


class ExecutionError(Exception):
    """Task execution error (command failure, timeout, etc.)"""
    pass


class SubtaskResult:
    """Result of a subtask execution."""
    
    def __init__(self, success: bool, output: str = "", logs: str = "", error_type: str = None, response_text: str = ""):
        self.success = success
        self.output = output
        self.logs = logs
        self.error_type = error_type
        self.response_text = response_text


class SimpleTaskExecutor:
    """
    Executes simple tasks using AI self-evaluation loop.
    
    The AI attempts the task, evaluates completion, and iterates
    until the criteria are met or max attempts are reached.
    """

    def __init__(self, session_dir: str = None):
        self.session_dir = session_dir
        self.last_response_text = ""

    def execute(self, task: dict, client: CodeBuddyClient, state_manager, conv_logger=None, parent_task_id: str = None, parent_context: dict = None, **kwargs) -> bool:
        """
        Execute a simple task.
        
        Args:
            task: Task configuration dict
            client: CodeBuddyClient instance
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance
            parent_task_id: Parent task ID if this is a subtask (for log organization)
            parent_context: Optional context from parent task for prompt enrichment
            
        Returns:
            bool: True if task completed successfully
        """
        task_id = str(task['id'])
        max_attempts = task.get('max_attempts', 20)
        
        current_state = state_manager.get_task_state(task_id)
        attempts = current_state.get('attempts', 0)
        
        logger.info(f"Executing simple task {task_id}: {task['name']}")
        
        last_timeout_error = None  # Track if previous attempt timed out
        last_timeout_type = None   # "bash" or "session"
        
        while attempts < max_attempts:
            attempts += 1
            state_manager.mark_task_status(
                task_id, "in_progress",
                attempts=attempts,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            
            print(f"\n   Attempt #{attempts}")
            
            # Re-fetch state each attempt so history from previous attempts is visible
            current_state = state_manager.get_task_state(task_id)
            
            # Build prompt (with timeout feedback if previous attempt timed out)
            prompt, exec_script_path = self._build_prompt(
                task, attempts, current_state,
                parent_context=parent_context,
                timeout_feedback=last_timeout_error,
                timeout_type=last_timeout_type,
            )
            last_timeout_error = None  # Reset after injecting into prompt
            last_timeout_type = None
            try:
                # Write prompt to log BEFORE calling AI (crash safety)
                system_prompt = build_system_prompt_coding_agent(
                    exec_script_path,
                    supports_system_prompt=client.provider.supports_system_prompt,
                    task=task,
                )
                # Always prepend system_prompt_prefix to user prompt
                effective_prompt = prepend_system_prompt_prefix(prompt, task)
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=task_id,
                        task_name=task['name'],
                        prompt=effective_prompt,
                        attempt=attempts,
                        parent_task_id=parent_task_id,
                        system_prompt=system_prompt,
                    )
                
                result = client.ask(
                    effective_prompt,
                    system_prompt=system_prompt,
                )
                self.last_response_text = result
                
                # Append response to log AFTER AI returns
                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=client.last_full_log or result,
                        parent_task_id=parent_task_id,
                    )
                
                # Check if AI reports LONG_RUNNING_IN_PROGRESS
                # (AI has context and may use autoagent-exec even in a simple task)
                if self._handle_long_running_in_simple_task(
                    result, task, task_id, attempts, client, state_manager,
                    conv_logger=conv_logger, parent_task_id=parent_task_id,
                ):
                    # Successfully handled as long-running — treat as completed
                    return True
                
                # Check if AI reports completion
                # Extract a meaningful summary from the AI response
                completion_status = self._check_completion(result)
                
                if completion_status is True:
                    summary = self._extract_summary(result)
                    print(f"   ✅ Task {task_id} completed!")
                    state_manager.mark_task_status(
                        task_id, "completed",
                        attempts=attempts,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ai_reasoning=summary,
                    )
                    # Record history
                    state_manager.add_task_history(task_id, {
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": "completed",
                        "summary": summary,
                    })
                    return True
                else:
                    if completion_status is None:
                        # No marker found at all — give AI a clear hint
                        last_line = result.strip().rsplit('\n', 1)[-1].strip() if result.strip() else '(empty)'
                        summary = (
                            f"Cannot find {self._SIMPLE_TASK_MARKERS} "
                            f"in previous response. "
                            f"(The last line in your response is: {last_line[:200]}) "
                            f"Please include the required status marker."
                        )
                        print(f"   ⚠️ No completion marker found in response for task {task_id}")
                    else:
                        # Explicitly marked as not completed
                        summary = self._extract_summary(result)
                        print(f"   ⏳ Not completed yet, AI will try to improve...")
                    state_manager.add_task_history(task_id, {
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": "not_completed",
                        "summary": summary,
                    })
                    
            except AICallError as e:
                logger.error(f"AI call failed for task {task_id}: {e}")
                print(f"   ❌ AI call error: {e}")
                # Detect timeout errors so we can inject feedback in the next prompt
                if isinstance(e, BashTimeoutError):
                    last_timeout_error = str(e)
                    last_timeout_type = "bash"
                    print(f"   ⏰ Bash timeout detected — next attempt will include long-running task guidance")
                elif isinstance(e, SessionTimeoutError):
                    last_timeout_error = str(e)
                    last_timeout_type = "session"
                    print(f"   ⏰ Session timeout detected — next attempt will continue where left off")
                # Append error as response (prompt was already logged above)
                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=f"AI Call Error: {e}",
                        parent_task_id=parent_task_id,
                    )
                state_manager.add_task_history(task_id, {
                    "attempt": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "error",
                    "error": str(e),
                })
        
        # Max attempts reached
        print(f"   ❌ Task {task_id} failed after {max_attempts} attempts")
        state_manager.mark_task_status(
            task_id, "failed",
            attempts=attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def _build_prompt(self, task: dict, attempt: int, state: dict, parent_context: dict = None, timeout_feedback: str = None, timeout_type: str = None) -> tuple:
        """Build the prompt for AI.
        
        Delegates to ``prompts.simple_task.build_simple_task_prompt``.

        Returns:
            A ``(prompt, exec_script_path)`` tuple.  *exec_script_path*
            is the absolute path to the generated autoagent-exec script
            (empty string when unavailable).
        """
        # Resolve session_dir: prefer own, fall back to _subtask_executor's.
        log_session_dir = ""
        if self.session_dir:
            log_session_dir = self.session_dir
        else:
            subtask_exec = getattr(self, '_subtask_executor', None)
            if subtask_exec and subtask_exec.session_dir:
                log_session_dir = subtask_exec.session_dir

        # Generate / update the autoagent-exec convenience script
        exec_script_path = ""
        if log_session_dir:
            exec_script_path = _write_autoagent_exec_script(
                session_dir=log_session_dir,
                task_id=str(task['id']),
                fast_fail_timeout=_load_fast_fail_timeout(),
            )

        return build_simple_task_prompt(
            task=task,
            attempt=attempt,
            state=state,
            extract_summary_fn=self._extract_summary,
            parent_context=parent_context,
            timeout_feedback=timeout_feedback,
            timeout_type=timeout_type,
            exec_script_path=exec_script_path,
        ), exec_script_path

    @staticmethod
    def _extract_summary(ai_response: str) -> str:        
        """Extract a meaningful summary from AI response.
        
        The AI's raw response is a concatenation of tool calls and text,
        which is not useful as context. Instead, we look for the final
        status/conclusion section which typically contains the meaningful summary.
        """
        if not ai_response:
            return ""
        
        # Look for the final status line and nearby context
        # AI responses typically end with a summary before the status marker
        lines = ai_response.strip().split('\n')
        
        # Find the last meaningful paragraph (skip empty lines from the end)
        meaningful_lines = []
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                if meaningful_lines:
                    break  # Stop at first blank line after finding content
                continue
            meaningful_lines.insert(0, stripped)
            if len(meaningful_lines) >= 5:  # Cap at 5 lines
                break
        
        if meaningful_lines:
            return ' '.join(meaningful_lines)[:300]
        
        # Fallback: just take the last 300 chars
        return ai_response.strip()[-300:]

    def _check_completion(self, response: str) -> Optional[bool]:
        """
        Check if the AI reports the task as completed.
        
        Uses a multi-layer strategy:
        1. Check for strict markers (✅ COMPLETED / ❌ NOT_COMPLETED)
        2. Check for common variations the AI might use despite instructions
        3. Scan for contextual completion phrases as a fallback
        
        Args:
            response: AI response text
            
        Returns:
            True  - AI explicitly indicates completion
            False - AI explicitly indicates not completed
            None  - No completion/not-completion marker found in response
        """
        response_lower = response.lower()
        import re

        # --- Layer 1: Strict negative markers (check first, most specific) ---
        # Match: ❌ (optional spaces/stars/underscores) not (optional _) complete(d)
        # Covers: ❌ not_completed, ❌ **not completed**, ❌not_complete, ❌ 未完成, etc.
        strict_failure_patterns = [
            r'❌[\s*_]*not[\s*_]*complete[d]?',
            r'❌[\s*_]*未完成',
        ]
        for pattern in strict_failure_patterns:
            if re.search(pattern, response_lower):
                return False
        
        # --- Layer 2: Strict positive markers ---
        # Match: ✅ (optional spaces/stars/underscores) complete(d)
        # Covers: ✅ completed, ✅ **completed**, ✅complete, ✅ 完成, etc.
        strict_success_patterns = [
            r'✅[\s*_]*complete[d]?',
            r'✅[\s*_]*完成',
        ]
        for pattern in strict_success_patterns:
            if re.search(pattern, response_lower):
                return True
        
        # --- Layer 3: Fuzzy positive patterns (AI often rephrases) ---
        # These catch cases like "✅ Task Completed Successfully",
        # "✅ All criteria met", "✅ Done", etc.
        fuzzy_positive_patterns = [
            r'✅.*(?:completed?|done|success|criteria\s+(?:are\s+)?met|finish)',
            r'(?:task|all)\s+(?:has been\s+)?completed?\s+successfully',
            r'all\s+completion\s+criteria\s+(?:have been\s+|are\s+)?met',
            r'(?:completed?|done|success).*✅',
        ]
        # Only check the last 1000 chars to focus on the conclusion
        tail = response_lower[-1000:] if len(response_lower) > 1000 else response_lower
        for pattern in fuzzy_positive_patterns:
            if re.search(pattern, tail):
                # Double-check: make sure there's no "not completed" nearby
                not_patterns = [
                    r'not\s+(?:yet\s+)?completed?',
                    r'criteria\s+(?:are\s+)?not\s+met',
                    r'fail',
                ]
                has_negation = any(re.search(np, tail) for np in not_patterns)
                if not has_negation:
                    return True
        
        # No marker found at all
        return None

    # Marker names used in "Cannot find ... in previous response" messages
    _SIMPLE_TASK_MARKERS = "'✅ completed', '❌ not completed', or '⏳ LONG_RUNNING_IN_PROGRESS'"
    _LONG_RUNNING_MARKERS = "'✅ completed', '❌ not completed', or '⏳ LONG_RUNNING_IN_PROGRESS'"

    @staticmethod
    def _check_long_running_in_progress_static(response: str) -> bool:
        """Check if AI reported that a long-running task has been submitted."""
        response_lower = response.lower()
        patterns = [
            "long_running_in_progress",
            "long running in progress",
            "⏳ long_running_in_progress",
        ]
        return any(p in response_lower for p in patterns)

    def _handle_long_running_in_simple_task(
        self, response: str, task: dict, task_id: str, attempt: int,
        client, state_manager, conv_logger=None, parent_task_id: str = None,
    ) -> bool:
        """
        Handle LONG_RUNNING_IN_PROGRESS in a simple task.
        
        AI has context about autoagent-exec and may use it even in a simple task.
        When detected, delegate to SubtaskExecutor's poll + callback logic.
        
        Returns:
            True if the long-running task completed successfully,
            False otherwise (caller should continue the retry loop).
        """
        subtask_exec = getattr(self, '_subtask_executor', None)

        # Determine the check function source
        check_fn = subtask_exec._check_long_running_in_progress if subtask_exec else self._check_long_running_in_progress_static
        if not check_fn(response):
            return False

        # Resolve session_dir: prefer _subtask_executor, fall back to self
        log_session_dir = None
        if subtask_exec and subtask_exec.session_dir:
            log_session_dir = subtask_exec.session_dir
        elif self.session_dir:
            log_session_dir = self.session_dir

        if not log_session_dir:
            logger.warning(
                f"Task {task_id}: AI returned LONG_RUNNING_IN_PROGRESS in simple task "
                f"but no session_dir is configured. Treating as not completed."
            )
            return False

        # Ensure we have a SubtaskExecutor for poll + callback logic
        if subtask_exec is None:
            subtask_exec = SubtaskExecutor(session_dir=log_session_dir)
        
        print(f"   ⏳ AI submitted long-running task in simple task, waiting for completion...")
        
        log_session_dir = subtask_exec.session_dir
        
        # Extract the actual task-id used in the autoagent-exec command.
        # The AI may use a different task-id than the current subtask
        # (e.g. AI in subtask 1.3 might use --task-id 1.2).
        # We must use the same task-id to find the correct signal file.
        import re as _re
        lr_task_id = task_id  # default fallback
        tid_match = _re.search(
            r'--task-id\s+(\S+)', response
        )
        if tid_match:
            lr_task_id = tid_match.group(1)
            if lr_task_id != task_id:
                logger.info(
                    f"Task {task_id}: AI used --task-id {lr_task_id} in "
                    f"autoagent-exec (differs from current subtask id). "
                    f"Using {lr_task_id} for signal file lookup."
                )
        
        signal_file = os.path.join(log_session_dir, "lr_tasks", f"lr_{lr_task_id}_signal.json")
        output_log = os.path.join(log_session_dir, "lr_tasks", f"lr_{lr_task_id}_output.log")
        
        monitor_status = subtask_exec._poll_signal_file(
            lr_task_id, signal_file,
            max_initial_wait=_load_fast_fail_timeout() * 2,
        )
        
        # Generate exec_script_path for the system prompt
        exec_script_path = _write_autoagent_exec_script(
            session_dir=log_session_dir,
            task_id=task_id,
            fast_fail_timeout=_load_fast_fail_timeout(),
        )

        # Restart AI to analyze the result
        analyze_result = subtask_exec._ai_analyze_long_running_result(
            task, client, state_manager,
            monitor_status, output_log,
            conv_logger=conv_logger, parent_task_id=parent_task_id,
            signal_file=signal_file,
            exec_script_path=exec_script_path,
        )
        
        if analyze_result.success:
            state_manager.add_task_history(task_id, {
                "attempt": attempt,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "result": "completed",
                "summary": analyze_result.output,
            })
            return True
        
        # Analysis says not completed — record and let the retry loop continue
        state_manager.add_task_history(task_id, {
            "attempt": attempt,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "result": "not_completed",
            "summary": analyze_result.output or "Long-running task did not meet completion criteria",
        })
        # Reset status back to in_progress for retry
        state_manager.mark_task_status(
            task_id, "in_progress",
            attempts=attempt,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(f"   ⏳ Long-running callback analysis failed, retrying...")
        return False


class NestedTaskExecutor:
    """
    Executes nested tasks with subtasks and AI decision points.

    Two AI decision points:
    1. When a subtask fails: AI analyzes and decides retry_from
    2. When all subtasks complete: AI evaluates if main task is done
    """

    def __init__(self, session_dir: str = None, model_roles: dict = None):
        self.subtask_executor = SubtaskExecutor(session_dir=session_dir, model_roles=model_roles)
        self.session_dir = session_dir
        self.model_roles = model_roles or {}

    def execute(self, task: dict, client: CodeBuddyClient, state_manager, conv_logger=None) -> bool:
        """
        Execute a nested task.
        
        Args:
            task: Task configuration with subtasks
            client: CodeBuddyClient instance  
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance
            
        Returns:
            bool: True if main task completed
        """
        task_id = str(task['id'])
        max_attempts = task.get('max_attempts', 20)
        subtasks = task.get('subtasks', [])
        
        if not subtasks:
            raise ConfigError(f"Nested task {task_id} has no subtasks")
        
        # Register nested task with conversation logger
        if conv_logger:
            subtask_ids = [str(st['id']) for st in subtasks]
            conv_logger.register_nested_task(task_id, task['name'], subtask_ids)
        
        logger.info(f"Executing nested task {task_id}: {task['name']}")
        
        current_state = state_manager.get_task_state(task_id)
        attempts = current_state.get('attempts', 0)
        
        while attempts < max_attempts:
            attempts += 1
            state_manager.mark_task_status(
                task_id, "in_progress",
                attempts=attempts,
                current_round=attempts,
                max_attempts=max_attempts,
            )
            
            print(f"\n   📋 Round #{attempts} of nested task {task_id}")
            
            # Execute subtasks in order
            all_completed = True
            
            # Build parent context for subtask prompt enrichment
            # Get the latest AI decision (suggested_fix) from previous rounds
            parent_state = state_manager.get_task_state(task_id)
            ai_decisions = parent_state.get('ai_decisions', [])
            latest_fix = ai_decisions[-1].get('suggested_fix', '') if ai_decisions else ''
            # Also check main_task_evaluations for suggested improvements
            evaluations = parent_state.get('main_task_evaluations', [])
            if evaluations:
                last_eval = evaluations[-1]
                eval_context_parts = []
                if last_eval.get('next_strategy'):
                    eval_context_parts.append(f"Strategy from previous evaluation: {last_eval['next_strategy']}")
                if eval_context_parts:
                    eval_context = "\n".join(eval_context_parts)
                    latest_fix = f"{latest_fix}\n\n{eval_context}".strip() if latest_fix else eval_context

            # Cap composite fix context to avoid oversized prompts
            if latest_fix and len(latest_fix) > limits.get('nested_latest_fix'):
                latest_fix = "(truncated)\n..." + latest_fix[-limits.get('nested_latest_fix'):]
            
            parent_context = {
                'subtasks': subtasks,
                'suggested_fix': latest_fix,
                'ai_decisions': ai_decisions,
                'main_task_criteria': task.get('completion_criteria', ''),
            }

            context_isolation = task.get('context_isolation', True)
            previous_subtask_summary = ""
            
            for subtask in subtasks:
                subtask_id = str(subtask['id'])
                subtask_state = state_manager.get_task_state(subtask_id)
                
                # Skip already completed subtasks
                if subtask_state.get('status') == 'completed':
                    print(f"\n   📌 Subtask {subtask_id}: {subtask['name']} (already completed, skipping)")
                    continue

                # Reset session before each subtask (except the first) to
                # prevent unbounded context growth across subtasks.
                if context_isolation and previous_subtask_summary:
                    client.reset_session()

                parent_context['previous_subtask_summary'] = previous_subtask_summary
                
                print(f"\n   📌 Executing subtask {subtask_id}: {subtask['name']}")
                print(f"      Type: {subtask['type']}")
                
                result = self.subtask_executor.execute(
                    subtask, client, state_manager,
                    conv_logger=conv_logger, parent_task_id=task_id,
                    parent_context=parent_context,
                )
                
                if not result.success:
                    all_completed = False
                    print(f"\n   ❌ Subtask {subtask_id} failed!")
                    
                    # AI Decision Point 1: Analyze failure
                    ai_decision = self._ai_analyze_failure(
                        client, task, subtask, subtasks, result, state_manager,
                        conv_logger=conv_logger, round_num=attempts,
                    )
                    
                    # Reset subtasks based on AI decision
                    retry_from = ai_decision.get('retry_from', subtask_id)
                    self._reset_subtasks_from(retry_from, subtasks, state_manager)
                    
                    # Record AI decision
                    state_manager.add_ai_decision(task_id, {
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "failed_at": subtask_id,
                        "retry_from": retry_from,
                        "suggested_fix": ai_decision.get('suggested_fix', ''),
                    })
                    
                    break  # Break subtask loop, start new round
                else:
                    # Capture response for next subtask's context
                    previous_subtask_summary = result.response_text or result.output
            
            if not all_completed:
                print(f"\n   ⏳ Subtask failed, starting new round...")
                continue
            
            # All subtasks completed - AI Decision Point 2: Evaluate main task
            print(f"\n   📊 All subtasks completed, evaluating main task...")
            ai_evaluation = self._ai_evaluate_main_task(
                client, task, subtasks, state_manager,
                conv_logger=conv_logger, round_num=attempts,
            )
            
            if ai_evaluation.get('main_task_completed', False):
                print(f"\n   ✅ Main task {task_id} completed!")
                state_manager.mark_task_status(
                    task_id, "completed",
                    attempts=attempts,
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                
                # Record evaluation
                state_manager.add_main_task_evaluation(task_id, {
                    "round": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed": True,
                    "analysis": ai_evaluation.get('analysis', ''),
                })
                return True
            else:
                print(f"\n   ⏳ Main task not yet completed.")
                print(f"      Analysis: {ai_evaluation.get('analysis', 'N/A')}")
                print(f"      Next strategy: {ai_evaluation.get('next_strategy', 'N/A')}")
                
                # Reset subtasks based on AI decision
                retry_from = ai_evaluation.get('retry_from', str(subtasks[0]['id']))
                self._reset_subtasks_from(retry_from, subtasks, state_manager)
                
                # Record evaluation
                state_manager.add_main_task_evaluation(task_id, {
                    "round": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed": False,
                    "analysis": ai_evaluation.get('analysis', ''),
                    "next_strategy": ai_evaluation.get('next_strategy', ''),
                    "retry_from": retry_from,
                })
        
        # Max attempts reached
        print(f"\n   ❌ Nested task {task_id} failed after {max_attempts} rounds")
        state_manager.mark_task_status(
            task_id, "failed",
            attempts=attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def _ai_analyze_failure(
        self, client, task, failed_subtask, all_subtasks, result, state_manager,
        conv_logger=None, round_num=1,
    ) -> dict:
        """
        AI Decision Point 1: Analyze subtask failure.
        
        Returns:
            dict with keys: analysis, retry_from, suggested_fix
        """
        task_id = str(task['id'])
        failed_id = str(failed_subtask['id'])
        
        # Build context for AI — include completion_criteria for each subtask
        task_history = []
        for st in all_subtasks:
            st_id = str(st['id'])
            st_state = state_manager.get_task_state(st_id)
            task_history.append({
                "subtask_id": st_id,
                "name": st['name'],
                "type": st['type'],
                "completion_criteria": st.get('completion_criteria', ''),
                "status": st_state.get('status', 'pending'),
                "attempts": st_state.get('attempts', 0),
                "ai_reasoning": st_state.get('ai_reasoning', ''),
            })
        
        # Include previous AI decisions for context
        parent_state = state_manager.get_task_state(task_id)
        prev_decisions = parent_state.get('ai_decisions', [])
        prev_decisions_text = ""
        if prev_decisions:
            recent_decisions = prev_decisions[-3:]
            decision_lines = []
            for d in recent_decisions:
                decision_lines.append(
                    f"  - Round {d.get('attempt', '?')}: failed at {d.get('failed_at', '?')}, "
                    f"retried from {d.get('retry_from', '?')}\n"
                    f"    Fix attempted: {d.get('suggested_fix', 'N/A')[:500]}"
                )
            prev_decisions_text = "\n".join(decision_lines)
        
        prompt = build_nested_failure_analysis_prompt(
            task=task,
            failed_subtask=failed_subtask,
            all_subtasks=all_subtasks,
            error_text=self._truncate_error(result.logs or result.output),
            error_type=result.error_type or 'unknown',
            task_history_text=self._format_task_history(task_history),
            prev_decisions_text=prev_decisions_text,
        )
        print(f"\n   🤖 [AI Decision Point 1: Failure Analysis]")
        
        # Always prepend system_prompt_prefix to user prompt
        effective_prompt = prepend_system_prompt_prefix(prompt, task)

        try:
            # Write prompt to log BEFORE calling AI (crash safety)
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="failure_analysis",
                    prompt=effective_prompt,
                    round_num=round_num,
                )
            
            decision = client.ask(effective_prompt, expect_json=True)
            print(f"      AI Analysis: {decision.get('analysis', 'N/A')[:200]}")
            print(f"      AI Decision: retry_from = {decision.get('retry_from', failed_id)}")
            print(f"      Suggested Fix: {decision.get('suggested_fix', 'N/A')[:200]}")            # Append response to log AFTER AI returns
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    response=response_for_log,
                )
            return decision
        except AICallError as e:
            logger.warning(f"Failed to get AI decision, using default: {e}")
            print(f"      ⚠️ AI analysis failed, retrying from {failed_id}")
            return {
                "analysis": f"AI analysis failed: {e}",
                "retry_from": failed_id,
                "suggested_fix": "Retry the same subtask",
            }

    def _ai_evaluate_main_task(
        self, client, task, subtasks, state_manager,
        conv_logger=None, round_num=1,
    ) -> dict:
        """
        AI Decision Point 2: Evaluate main task completion.
        
        Returns:
            dict with keys: main_task_completed, analysis, retry_from, next_strategy
        """
        task_id = str(task['id'])
        
        # Collect all subtask results
        execution_results = []
        for st in subtasks:
            st_id = str(st['id'])
            st_state = state_manager.get_task_state(st_id)
            execution_results.append({
                "subtask_id": st_id,
                "name": st['name'],
                "type": st['type'],
                "completion_criteria": st.get('completion_criteria', ''),
                "status": st_state.get('status', 'unknown'),
                "attempts": st_state.get('attempts', 0),
                "ai_reasoning": st_state.get('ai_reasoning', ''),
                "history": st_state.get('history', [])[-3:],  # Last 3 entries
            })
        
        # Build previous evaluations section for context
        parent_state = state_manager.get_task_state(task_id)
        prev_evaluations = parent_state.get('main_task_evaluations', [])
        prev_eval_section = ""
        if prev_evaluations:
            eval_lines = []
            for ev in prev_evaluations[-3:]:
                eval_lines.append(
                    f"  - Round {ev.get('round', '?')}: {'completed' if ev.get('completed') else 'not completed'}\n"
                    f"    Analysis: {ev.get('analysis', 'N/A')[:300]}\n"
                    f"    Strategy: {ev.get('next_strategy', 'N/A')[:200]}"
                )
            prev_eval_section = "\n".join(eval_lines)
        
        prompt = build_main_evaluation_prompt(
            task=task,
            subtasks=subtasks,
            execution_results_text=self._format_execution_results(execution_results),
            prev_eval_section=prev_eval_section,
        )
        
        print(f"\n   🤖 [AI Decision Point 2: Main Task Evaluation]")

        try:
            # No system_prompt_prefix needed here —
            # this is a follow-up message in the same conversation context.
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="main_task_evaluation",
                    prompt=prompt,
                    round_num=round_num,
                )
            
            evaluation = client.ask(prompt, expect_json=True)
            completed = evaluation.get('main_task_completed', False)
            print(f"      AI Evaluation: {'✅ COMPLETED' if completed else '❌ NOT COMPLETED'}")
            print(f"      Analysis: {evaluation.get('analysis', 'N/A')[:200]}")
            # Append response to log AFTER AI returns
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(evaluation, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    response=response_for_log,
                )
            return evaluation
        except AICallError as e:
            logger.warning(f"Failed to get AI evaluation, defaulting to not completed: {e}")
            print(f"      ⚠️ AI evaluation failed, marking as not completed")
            return {
                "main_task_completed": False,
                "analysis": f"AI evaluation failed: {e}",
                "retry_from": str(subtasks[0]['id']),
                "next_strategy": "Retry all subtasks",
            }

    def _reset_subtasks_from(self, retry_from: str, subtasks: list, state_manager):
        """
        Reset subtask states starting from retry_from.

        All subtasks from retry_from onwards are reset to 'pending',
        except *_once subtasks (simple_once / long_running_once) which
        are never reset once completed.
        Falls back to first subtask if retry_from ID is not found.
        """
        retry_from = str(retry_from)

        # Validate retry_from exists
        valid_ids = {str(s['id']) for s in subtasks}
        if retry_from not in valid_ids:
            logger.warning(f"retry_from '{retry_from}' not found in subtasks {valid_ids}, falling back to first subtask")
            retry_from = str(subtasks[0]['id']) if subtasks else retry_from

        should_reset = False
        for subtask in subtasks:
            st_id = str(subtask['id'])
            if st_id == retry_from:
                should_reset = True
            if should_reset:
                # Never reset *_once subtasks that have already completed
                if subtask.get('type', '').endswith('_once'):
                    st_state = state_manager.get_task_state(st_id)
                    if st_state.get('status') == 'completed':
                        logger.info(f"Skipping reset of once-subtask {st_id} (already completed)")
                        continue
                state_manager.mark_task_status(st_id, "pending", attempts=0)
                logger.info(f"Reset subtask {st_id} to pending")

    def _format_task_history(self, history: list) -> str:
        """Format task history for prompt, including completion criteria."""
        lines = []
        for item in history:
            lines.append(
                f"  - {item['subtask_id']} ({item['name']}): "
                f"status={item['status']}, attempts={item['attempts']}"
            )
            if item.get('completion_criteria'):
                lines.append(f"    Criteria: {item['completion_criteria'][:200]}")
            if item.get('ai_reasoning'):
                lines.append(f"    Summary: {item['ai_reasoning'][:300]}")
        return "\n".join(lines)

    @staticmethod
    def _truncate_error(error_text: str, max_chars: int = None) -> str:
        """Truncate error text to avoid wasting tokens on overly long errors."""
        if max_chars is None:
            max_chars = limits.get('error_text')
        if not error_text:
            return "(no error output)"
        error_text = str(error_text)
        if len(error_text) <= max_chars:
            return error_text
        return f"(truncated, showing last {max_chars} chars)\n...{error_text[-max_chars:]}"

    def _format_execution_results(self, results: list) -> str:
        """Format execution results for prompt.

        Note: completion_criteria is never truncated — the evaluator needs
        the full criteria to judge whether the task is complete.
        """
        lines = []
        for r in results:
            lines.append(
                f"  - {r['subtask_id']} ({r['name']}): "
                f"status={r['status']}, attempts={r['attempts']}"
            )
            if r.get('completion_criteria'):
                # Never truncate criteria — evaluator must see them in full
                lines.append(f"    Criteria: {r['completion_criteria']}")
            if r.get('ai_reasoning'):
                lines.append(f"    Result: {r['ai_reasoning'][:500]}")
        return "\n".join(lines)


class LoopingTaskExecutor:
    """
    Executes looping tasks that repeat their subtasks a fixed number of times.

    Unlike NestedTaskExecutor which uses AI to evaluate completion and decide
    retry strategy, LoopingTaskExecutor simply runs all subtasks in order for
    exactly ``repeat_count`` iterations. Each iteration resets all subtask
    states before starting.

    If a subtask fails during an iteration, the AI is asked to analyze the
    failure and decide which subtask to retry from (same as nested tasks).
    The retry happens within the same iteration and counts against
    ``max_attempts_per_loop``.
    """

    def __init__(self, session_dir: str = None, model_roles: dict = None):
        self.subtask_executor = SubtaskExecutor(session_dir=session_dir, model_roles=model_roles)
        self.session_dir = session_dir
        self.model_roles = model_roles or {}

    def execute(self, task: dict, client: CodeBuddyClient, state_manager, conv_logger=None) -> bool:
        """
        Execute a looping task.

        Args:
            task: Task configuration with subtasks and repeat_count
            client: CodeBuddyClient instance
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance

        Returns:
            bool: True if all iterations completed successfully
        """
        task_id = str(task['id'])
        repeat_count = task.get('repeat_count', 1)
        max_attempts_per_loop = task.get('max_attempts_per_loop', 20)
        subtasks = task.get('subtasks', [])

        if not subtasks:
            raise ConfigError(f"Looping task {task_id} has no subtasks")

        # Register with conversation logger
        if conv_logger:
            subtask_ids = [str(st['id']) for st in subtasks]
            conv_logger.register_nested_task(task_id, task['name'], subtask_ids)

        logger.info(f"Executing looping task {task_id}: {task['name']} (repeat_count={repeat_count})")

        for loop_idx in range(1, repeat_count + 1):
            print(f"\n   🔁 Loop iteration {loop_idx}/{repeat_count} of task {task_id}")

            # Reset all subtask states at the start of each iteration
            # (skip *_once subtasks that have already completed)
            for subtask in subtasks:
                st_id = str(subtask['id'])
                if subtask.get('type', '').endswith('_once'):
                    st_state = state_manager.get_task_state(st_id)
                    if st_state.get('status') == 'completed':
                        logger.info(f"Skipping reset of once-subtask {st_id} in loop {loop_idx} (already completed)")
                        continue
                state_manager.mark_task_status(st_id, "pending", attempts=0)

            state_manager.mark_task_status(
                task_id, "in_progress",
                current_loop=loop_idx,
                repeat_count=repeat_count,
            )

            # Run subtasks with retry logic within this iteration
            iteration_success = self._run_iteration(
                task, subtasks, client, state_manager,
                conv_logger=conv_logger,
                loop_idx=loop_idx,
                max_attempts=max_attempts_per_loop,
            )

            if not iteration_success:
                print(f"\n   ❌ Loop iteration {loop_idx}/{repeat_count} failed after max attempts")
                state_manager.mark_task_status(
                    task_id, "failed",
                    failed_at_loop=loop_idx,
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                return False

            print(f"\n   ✅ Loop iteration {loop_idx}/{repeat_count} completed")

        # All iterations completed
        print(f"\n   ✅ Looping task {task_id} completed all {repeat_count} iterations!")
        state_manager.mark_task_status(
            task_id, "completed",
            total_loops=repeat_count,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return True

    def _run_iteration(
        self, task, subtasks, client, state_manager,
        conv_logger=None, loop_idx=1, max_attempts=20,
    ) -> bool:
        """
        Run one iteration of the subtask sequence with retry support.

        If a subtask fails, the AI analyzes the failure and decides which
        subtask to retry from. This repeats until all subtasks complete
        or max_attempts is reached.

        Returns:
            bool: True if all subtasks completed in this iteration
        """
        task_id = str(task['id'])
        attempts = 0

        while attempts < max_attempts:
            attempts += 1

            if attempts > 1:
                print(f"\n   📋 Retry attempt #{attempts} within loop {loop_idx}")

            all_completed = True
            
            # Build parent context for subtask prompt enrichment
            parent_state = state_manager.get_task_state(task_id)
            ai_decisions = parent_state.get('ai_decisions', [])
            latest_fix = ai_decisions[-1].get('suggested_fix', '') if ai_decisions else ''
            # Cap fix context to avoid oversized prompts
            if latest_fix and len(latest_fix) > limits.get('looping_latest_fix'):
                latest_fix = "(truncated)\n..." + latest_fix[-limits.get('looping_latest_fix'):]

            parent_context = {
                'subtasks': subtasks,
                'suggested_fix': latest_fix,
                'ai_decisions': ai_decisions,
                'main_task_criteria': task.get('completion_criteria', ''),
            }

            context_isolation = task.get('context_isolation', True)
            previous_subtask_summary = ""

            for subtask in subtasks:
                subtask_id = str(subtask['id'])
                subtask_state = state_manager.get_task_state(subtask_id)

                # Skip already completed subtasks
                if subtask_state.get('status') == 'completed':
                    print(f"\n   📌 Subtask {subtask_id}: {subtask['name']} (already completed, skipping)")
                    continue

                # Reset session before each subtask (except the first) to
                # prevent unbounded context growth across subtasks.
                if context_isolation and previous_subtask_summary:
                    client.reset_session()

                parent_context['previous_subtask_summary'] = previous_subtask_summary

                print(f"\n   📌 Executing subtask {subtask_id}: {subtask['name']}")
                print(f"      Type: {subtask['type']} | Loop: {loop_idx} | Attempt: {attempts}")

                result = self.subtask_executor.execute(
                    subtask, client, state_manager,
                    conv_logger=conv_logger, parent_task_id=task_id,
                    parent_context=parent_context,
                )

                if not result.success:
                    all_completed = False
                    print(f"\n   ❌ Subtask {subtask_id} failed!")

                    # AI analyzes failure and decides retry_from
                    ai_decision = self._ai_analyze_failure(
                        client, task, subtask, subtasks, result, state_manager,
                        conv_logger=conv_logger, loop_idx=loop_idx,
                    )

                    retry_from = ai_decision.get('retry_from', subtask_id)
                    self._reset_subtasks_from(retry_from, subtasks, state_manager)

                    state_manager.add_ai_decision(task_id, {
                        "loop": loop_idx,
                        "attempt": attempts,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "failed_at": subtask_id,
                        "retry_from": retry_from,
                        "suggested_fix": ai_decision.get('suggested_fix', ''),
                    })

                    break  # Break subtask loop, retry
                else:
                    # Capture response for next subtask's context
                    previous_subtask_summary = result.response_text or result.output

            if all_completed:
                return True

        return False

    def _ai_analyze_failure(
        self, client, task, failed_subtask, all_subtasks, result, state_manager,
        conv_logger=None, loop_idx=1,
    ) -> dict:
        """
        AI analyzes subtask failure and decides retry strategy.

        Returns:
            dict with keys: analysis, retry_from, suggested_fix
        """
        task_id = str(task['id'])
        failed_id = str(failed_subtask['id'])

        task_history = []
        for st in all_subtasks:
            st_id = str(st['id'])
            st_state = state_manager.get_task_state(st_id)
            task_history.append({
                "subtask_id": st_id,
                "name": st['name'],
                "type": st['type'],
                "completion_criteria": st.get('completion_criteria', ''),
                "status": st_state.get('status', 'pending'),
                "attempts": st_state.get('attempts', 0),
                "ai_reasoning": st_state.get('ai_reasoning', ''),
            })

        history_lines = []
        for h in task_history:
            history_lines.append(
                f"  - {h['subtask_id']} ({h['name']}): status={h['status']}, attempts={h['attempts']}"
            )
            if h.get('completion_criteria'):
                history_lines.append(f"    Criteria: {h['completion_criteria'][:200]}")
            if h.get('ai_reasoning'):
                history_lines.append(f"    Summary: {h['ai_reasoning'][:300]}")
        history_text = "\n".join(history_lines)

        # Include previous AI decisions for context
        parent_state = state_manager.get_task_state(task_id)
        prev_decisions = parent_state.get('ai_decisions', [])
        prev_decisions_text = ""
        if prev_decisions:
            recent_decisions = prev_decisions[-3:]
            decision_lines = []
            for d in recent_decisions:
                decision_lines.append(
                    f"  - Loop {d.get('loop', '?')}: failed at {d.get('failed_at', '?')}, "
                    f"retried from {d.get('retry_from', '?')}\n"
                    f"    Fix attempted: {d.get('suggested_fix', 'N/A')[:500]}"
                )
            prev_decisions_text = "\n".join(decision_lines)

        prompt = build_looping_failure_analysis_prompt(
            task=task,
            failed_subtask=failed_subtask,
            all_subtasks=all_subtasks,
            error_text=self._truncate_error(result.logs or result.output),
            error_type=result.error_type or 'unknown',
            loop_idx=loop_idx,
            history_text=history_text,
            prev_decisions_text=prev_decisions_text,
        )

        print(f"\n   🤖 [AI: Failure Analysis (loop {loop_idx})]")

        # Always prepend system_prompt_prefix to user prompt
        effective_prompt = prepend_system_prompt_prefix(prompt, task)

        try:
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=task_id,
                    task_name=task['name'],
                    call_type="looping_failure_analysis",
                    prompt=effective_prompt,
                    round_num=loop_idx,
                )

            decision = client.ask(effective_prompt, expect_json=True)
            print(f"      AI Analysis: {decision.get('analysis', 'N/A')[:200]}")
            print(f"      AI Decision: retry_from = {decision.get('retry_from', failed_id)}")

            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=task_id,
                    task_name=task['name'],
                    response=response_for_log,
                )
            return decision
        except AICallError as e:
            logger.warning(f"Failed to get AI decision, using default: {e}")
            print(f"      ⚠️ AI analysis failed, retrying from {failed_id}")
            return {
                "analysis": f"AI analysis failed: {e}",
                "retry_from": failed_id,
                "suggested_fix": "Retry the same subtask",
            }

    def _reset_subtasks_from(self, retry_from: str, subtasks: list, state_manager):
        """Reset subtask states starting from retry_from onwards.

        *_once subtasks (simple_once / long_running_once) are never reset
        once completed.
        Falls back to first subtask if retry_from ID is not found."""
        retry_from = str(retry_from)

        # Validate retry_from exists
        valid_ids = {str(s['id']) for s in subtasks}
        if retry_from not in valid_ids:
            logger.warning(f"retry_from '{retry_from}' not found in subtasks {valid_ids}, falling back to first subtask")
            retry_from = str(subtasks[0]['id']) if subtasks else retry_from

        should_reset = False
        for subtask in subtasks:
            st_id = str(subtask['id'])
            if st_id == retry_from:
                should_reset = True
            if should_reset:
                # Never reset *_once subtasks that have already completed
                if subtask.get('type', '').endswith('_once'):
                    st_state = state_manager.get_task_state(st_id)
                    if st_state.get('status') == 'completed':
                        logger.info(f"Skipping reset of once-subtask {st_id} (already completed)")
                        continue
                state_manager.mark_task_status(st_id, "pending", attempts=0)
                logger.info(f"Reset subtask {st_id} to pending")

    @staticmethod
    def _truncate_error(error_text: str, max_chars: int = None) -> str:
        """Truncate error text to avoid wasting tokens on overly long errors."""
        if max_chars is None:
            max_chars = limits.get('error_text')
        if not error_text:
            return "(no error output)"
        error_text = str(error_text)
        if len(error_text) <= max_chars:
            return error_text
        return f"(truncated, showing last {max_chars} chars)\n...{error_text[-max_chars:]}"


class SubtaskExecutor:
    """
    Dispatches subtask execution based on type (simple or long_running).
    """

    def __init__(self, session_dir: str = None, model_roles: dict = None):
        self.simple_executor = SimpleTaskExecutor(session_dir=session_dir)
        # Back-reference so SimpleTaskExecutor can delegate long-running
        # handling (poll + callback) when AI uses autoagent-exec in a simple task
        self.simple_executor._subtask_executor = self
        self.session_dir = session_dir
        self.model_roles = model_roles or {}

    def execute(self, subtask: dict, client: CodeBuddyClient, state_manager, conv_logger=None, parent_task_id: str = None, parent_context: dict = None) -> SubtaskResult:
        """
        Execute a single subtask.
        
        Args:
            subtask: Subtask configuration
            client: CodeBuddyClient instance
            state_manager: State manager
            conv_logger: Optional ConversationLogger instance
            parent_task_id: Parent task ID for log organization
            parent_context: Optional context from parent task for prompt enrichment
            
        Returns:
            SubtaskResult: Result of execution
        """
        subtask_type = subtask.get('type', 'simple')

        # Switch model based on subtask's model field (default/simple)
        subtask_model_role = subtask.get('model', 'default')
        if self.model_roles and hasattr(client, 'provider') and client.provider:
            target_model = self.model_roles.get(subtask_model_role, self.model_roles.get('default', ''))
            if target_model:
                client.provider.set_model(target_model)
        
        if subtask_type in ('simple', 'simple_once'):
            return self._execute_simple_subtask(
                subtask, client, state_manager,
                conv_logger=conv_logger, parent_task_id=parent_task_id,
                parent_context=parent_context,
            )
        elif subtask_type in ('long_running', 'long_running_once'):
            return self._execute_long_running_subtask(
                subtask, client, state_manager,
                conv_logger=conv_logger, parent_task_id=parent_task_id,
                parent_context=parent_context,
            )
        else:
            raise ConfigError(f"Unknown subtask type: {subtask_type}")

    def _execute_simple_subtask(
        self, subtask: dict, client: CodeBuddyClient, state_manager,
        conv_logger=None, parent_task_id: str = None, parent_context: dict = None,
    ) -> SubtaskResult:
        """Execute a simple subtask via AI."""
        success = self.simple_executor.execute(
            subtask, client, state_manager,
            conv_logger=conv_logger, parent_task_id=parent_task_id,
            parent_context=parent_context,
        )
        
        subtask_id = str(subtask['id'])
        state = state_manager.get_task_state(subtask_id)
        
        return SubtaskResult(
            success=success,
            output=state.get('ai_reasoning', ''),
            logs="",
            error_type=None if success else "ai_failed",
            response_text=self.simple_executor.last_response_text,
        )

    def _execute_long_running_subtask(
        self, subtask: dict, client: CodeBuddyClient, state_manager,
        conv_logger=None, parent_task_id: str = None, parent_context: dict = None,
    ) -> SubtaskResult:
        """
        Execute a long-running subtask via autoagent-exec.
        
        Flow:
        1. Build a prompt telling the AI to use autoagent-exec
        2. AI calls autoagent-exec which starts the command with fast-fail detection
        3. If AI reports LONG_RUNNING_IN_PROGRESS, poll the signal file until done
        4. When done, restart AI to analyze results
        
        The autoagent-exec script handles:
        - Fast-fail detection (errors within 10s are reported immediately)
        - Background process management
        - Signal file creation and updates
        """
        subtask_id = str(subtask['id'])
        max_attempts = subtask.get('max_attempts', 5)
        
        # Use the session_dir passed from orchestrator
        if not self.session_dir:
            raise ConfigError(
                "SubtaskExecutor.session_dir is not set. "
                "Cannot execute long-running tasks without a log session directory."
            )
        log_session_dir = self.session_dir

        # Generate / update the autoagent-exec convenience script
        exec_script_path = _write_autoagent_exec_script(
            session_dir=log_session_dir,
            task_id=subtask_id,
            fast_fail_timeout=_load_fast_fail_timeout(),
        )
        
        logger.info(f"Executing long-running subtask {subtask_id}: {subtask['name']}")
        logger.info(f"  autoagent-exec script: {exec_script_path}")
        logger.info(f"  log session dir: {log_session_dir}")
        
        for attempt in range(1, max_attempts + 1):
            state_manager.mark_task_status(
                subtask_id, "in_progress",
                attempts=attempt,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            
            print(f"\n      Long-running task attempt #{attempt}")
            
            # Build prompt for AI
            prompt = self._build_long_running_prompt(
                subtask, exec_script_path, attempt, state_manager,
                parent_context=parent_context,
            )
            
            try:
                # Write prompt to log BEFORE calling AI (crash safety)
                system_prompt = build_system_prompt_coding_agent(
                    exec_script_path,
                    supports_system_prompt=client.provider.supports_system_prompt,
                    task=subtask,
                )
                # Always prepend system_prompt_prefix to user prompt
                effective_prompt = prepend_system_prompt_prefix(prompt, subtask)
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=subtask_id,
                        task_name=subtask['name'],
                        prompt=effective_prompt,
                        attempt=attempt,
                        parent_task_id=parent_task_id,
                        system_prompt=system_prompt,
                    )
                
                result = client.ask(
                    effective_prompt,
                    system_prompt=system_prompt,
                )
                
                # Append response to log AFTER AI returns
                if conv_logger:
                    conv_logger.log_response(
                        task_id=subtask_id,
                        response=client.last_full_log or result,
                        parent_task_id=parent_task_id,
                    )
                
                # Check if AI reported LONG_RUNNING_IN_PROGRESS
                if self._check_long_running_in_progress(result):
                    print(f"      ⏳ AI submitted long-running task, waiting for completion...")
                    
                    # Extract the actual task-id used in the autoagent-exec
                    # command from the AI response.  The AI *should* use
                    # subtask_id, but we defensively check in case it differs.
                    import re as _re
                    lr_task_id = subtask_id  # default
                    _tid_match = _re.search(r'--task-id\s+(\S+)', result)
                    if _tid_match:
                        lr_task_id = _tid_match.group(1)
                        if lr_task_id != subtask_id:
                            logger.info(
                                f"Subtask {subtask_id}: AI used --task-id "
                                f"{lr_task_id} in autoagent-exec. Using "
                                f"{lr_task_id} for signal file lookup."
                            )
                    
                    # Poll the signal file
                    signal_file = os.path.join(log_session_dir, "lr_tasks", f"lr_{lr_task_id}_signal.json")
                    output_log = os.path.join(log_session_dir, "lr_tasks", f"lr_{lr_task_id}_output.log")
                    
                    monitor_status = self._poll_signal_file(
                        subtask_id, signal_file,
                        max_initial_wait=_load_fast_fail_timeout() * 2,
                    )
                    
                    # Restart AI to analyze the result
                    analyze_result = self._ai_analyze_long_running_result(
                        subtask, client, state_manager,
                        monitor_status, output_log,
                        conv_logger=conv_logger, parent_task_id=parent_task_id,
                        parent_context=parent_context, signal_file=signal_file,
                        exec_script_path=exec_script_path,
                    )
                    
                    if analyze_result.success:
                        return analyze_result
                    
                    # Analysis says not completed — retry within long-running loop
                    print(f"      ⏳ Long-running callback analysis failed, retrying...")
                    state_manager.add_task_history(subtask_id, {
                        "attempt": attempt,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": "not_completed",
                        "summary": analyze_result.output or "Long-running task did not meet completion criteria",
                    })
                    # Reset status back to in_progress for retry (undo the "failed" set by _ai_analyze)
                    state_manager.mark_task_status(
                        subtask_id, "in_progress",
                        attempts=attempt,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    continue
                
                # Check for normal completion (AI might have handled it directly)
                completion_status = self.simple_executor._check_completion(result)
                if completion_status is True:
                    summary = SimpleTaskExecutor._extract_summary(result)
                    print(f"      ✅ Long-running task {subtask_id} completed directly!")
                    state_manager.mark_task_status(
                        subtask_id, "completed",
                        attempts=attempt,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ai_reasoning=summary,
                    )
                    return SubtaskResult(success=True, output=summary, response_text=result)
                
                # AI didn't complete and didn't submit long-running — maybe fast-fail retry
                if completion_status is None:
                    last_line = result.strip().rsplit('\n', 1)[-1].strip() if result.strip() else '(empty)'
                    summary = (
                        f"Cannot find {SimpleTaskExecutor._LONG_RUNNING_MARKERS} "
                        f"in previous response. "
                        f"(The last line in your response is: {last_line[:200]}) "
                        f"Please include the required status marker."
                    )
                    print(f"      ⚠️ No completion/long-running marker found in response for task {subtask_id}")
                else:
                    summary = SimpleTaskExecutor._extract_summary(result)
                    print(f"      ⏳ Not completed yet, retrying...")
                state_manager.add_task_history(subtask_id, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "not_completed",
                    "summary": summary,
                })
                
            except AICallError as e:
                logger.error(f"AI call failed for long-running task {subtask_id}: {e}")
                print(f"      ❌ AI call error: {e}")
                state_manager.add_task_history(subtask_id, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "error",
                    "error": str(e),
                })
        
        # Max attempts exhausted
        print(f"      ❌ Long-running task {subtask_id} failed after {max_attempts} attempts")
        state_manager.mark_task_status(
            subtask_id, "failed",
            attempts=max_attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return SubtaskResult(
            success=False,
            output=f"Failed after {max_attempts} attempts",
            error_type="max_attempts_exceeded",
        )

    def _build_long_running_prompt(
        self, subtask: dict, exec_script_path: str,
        attempt: int, state_manager, parent_context: dict = None,
    ) -> str:
        """
        Build the prompt that tells AI to use autoagent-exec for long-running tasks.

        Delegates to ``prompts.long_running_task.build_long_running_prompt``.
        """
        subtask_id = str(subtask['id'])
        state = state_manager.get_task_state(subtask_id) if attempt > 1 else {}

        return _build_lr_prompt(
            subtask=subtask,
            exec_script_path=exec_script_path,
            attempt=attempt,
            state=state,
            extract_summary_fn=SimpleTaskExecutor._extract_summary,
            parent_context=parent_context,
        )

    def _check_long_running_in_progress(self, response: str) -> bool:
        """
        Check if AI reported that a long-running task has been submitted.
        """
        response_lower = response.lower()
        patterns = [
            "long_running_in_progress",
            "long running in progress",
            "⏳ long_running_in_progress",
        ]
        return any(p in response_lower for p in patterns)

    def _poll_signal_file(
        self, subtask_id: str, signal_file: str,
        check_interval: int = 15, max_wait: int = 24 * 3600,
        max_initial_wait: int = 20,
    ) -> str:
        """
        Poll the signal file until the long-running task completes.
        
        Includes a fallback process-alive check: if the signal file
        still says "running" but the process has exited, we treat it
        as finished/error (in case the monitor process failed to update).
        
        Args:
            max_initial_wait: Maximum seconds to wait for the signal file
                to appear. If the file never appears (e.g. autoagent-exec
                fast-failed and exited without writing one), return "error"
                after this timeout. Should be set to ~2x fast_fail_timeout
                to give autoagent-exec enough time to write the signal file.
                Default 20s (suitable for the default fast_fail_timeout=10s).
        
        Returns:
            str: "finished", "error", or "timeout"
        """
        elapsed = 0
        pid = None  # Will be read from signal file
        consecutive_errors = 0
        max_consecutive_errors = 10  # After 10 consecutive read failures, escalate
        signal_file_seen = False  # Track if we've ever seen the signal file
        # Use a shorter interval during the initial wait phase so we don't
        # overshoot max_initial_wait when check_interval > max_initial_wait.
        initial_check_interval = min(2, check_interval)

        while elapsed < max_wait:
            # Choose interval: short polling until signal file first appears,
            # then switch to the normal (longer) check_interval.
            current_interval = check_interval if signal_file_seen else initial_check_interval

            if os.path.exists(signal_file):
                signal_file_seen = True
                try:
                    with open(signal_file, "r", encoding="utf-8") as f:
                        signal_data = json.load(f)

                    consecutive_errors = 0  # Reset on successful read
                    status = signal_data.get("status", "unknown")
                    
                    if status == "finished":
                        exit_code = signal_data.get("exit_code")
                        ec_display = exit_code if exit_code is not None else "N/A"
                        logger.info(
                            f"Long-running task {subtask_id} finished "
                            f"(exit code {ec_display})"
                        )
                        print(f"      [OK] Long-running task finished (exit code {ec_display})")
                        return "finished"
                    
                    elif status == "error":
                        exit_code = signal_data.get("exit_code")
                        ec_display = exit_code if exit_code is not None else "N/A"
                        logger.warning(
                            f"Long-running task {subtask_id} failed "
                            f"(exit code {ec_display})"
                        )
                        print(f"      [ERROR] Long-running task failed (exit code {ec_display})")
                        return "error"
                    
                    # status == "running" — check if process is still alive
                    if pid is None:
                        pid = signal_data.get("pid")
                    
                    if pid and not self._is_process_alive(pid):
                        logger.warning(
                            f"Long-running task {subtask_id} (PID {pid}) "
                            f"is no longer running but signal file was not updated"
                        )
                        print(f"      [WARNING] Process {pid} exited but signal not updated (monitor may have failed)")
                        # Treat as finished — the AI analysis step will
                        # look at output to determine success/failure
                        return "finished"
                    
                except (json.JSONDecodeError, IOError) as e:
                    consecutive_errors += 1
                    logger.debug(f"Signal file read error ({consecutive_errors}/{max_consecutive_errors}): {e}")
                    if consecutive_errors >= max_consecutive_errors:
                        logger.warning(
                            f"Signal file for {subtask_id} unreadable after "
                            f"{consecutive_errors} consecutive attempts, treating as error"
                        )
                        print(f"      [WARNING] Signal file corrupted after {consecutive_errors} retries, treating as finished")
                        return "finished"
            else:
                # Signal file doesn't exist yet — check initial wait timeout
                if not signal_file_seen and elapsed >= max_initial_wait:
                    logger.warning(
                        f"Signal file for {subtask_id} never appeared after "
                        f"{max_initial_wait}s. autoagent-exec likely fast-failed "
                        f"without writing a signal file."
                    )
                    print(
                        f"      [ERROR] Signal file never appeared after "
                        f"{max_initial_wait}s — autoagent-exec likely failed. "
                        f"Treating as error."
                    )
                    return "error"
            
            time.sleep(current_interval)
            elapsed += current_interval
            
            if elapsed % 300 == 0:  # Print status every 5 minutes
                print(f"      [WAITING] Still running... ({elapsed // 60} minutes elapsed)")
        
        print(f"      [TIMEOUT] Long-running task timed out after {max_wait // 3600}h")
        return "timeout"

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Check if a process with the given PID is still running."""
        if os.name == "nt":
            # Windows: try OpenProcess
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            # Check if process has exited
            STILL_ACTIVE = 259
            from ctypes import wintypes
            exit_code = wintypes.DWORD()
            alive = False
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                alive = (exit_code.value == STILL_ACTIVE)
            kernel32.CloseHandle(handle)
            return alive
        else:
            # Unix: check /proc status to detect zombies (os.kill can't)
            try:
                with open(f"/proc/{pid}/status") as f:
                    for line in f:
                        if line.startswith("State:"):
                            return "Z" not in line  # zombie = not alive
                return False
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                return False
            except OSError:
                # Fallback for platforms without /proc (e.g. macOS)
                try:
                    os.kill(pid, 0)
                    return True
                except OSError:
                    return False

    def _ai_analyze_long_running_result(
        self, subtask, client, state_manager, status, output_log,
        conv_logger=None, parent_task_id: str = None,
        parent_context: dict = None, signal_file: str = None,
        exec_script_path: str = "",
    ) -> SubtaskResult:
        """
        Ask AI to analyze the result of a long-running task.
        
        Instead of embedding log content in the prompt, we provide the
        file path so the AI can read it using its Read tool.
        """
        subtask_id = str(subtask['id'])
        
        # Normalize path for display
        output_log_display = output_log.replace("\\", "/")
        
        # Read exit code and command from signal file if available
        exit_code_info = ""
        command_info = ""
        if signal_file and os.path.exists(signal_file):
            try:
                with open(signal_file, 'r', encoding='utf-8') as f:
                    signal_data = json.load(f)
                exit_code = signal_data.get('exit_code')
                if exit_code is not None:
                    exit_code_info = f"\nExit Code: {exit_code}"
                command = signal_data.get('command')
                if command:
                    command_info = f"\nCommand: {command}"
            except Exception:
                pass
        
        prompt = _build_lr_analysis_prompt(
            subtask=subtask,
            status=status,
            output_log=output_log,
            command_info=command_info,
            exit_code_info=exit_code_info,
            parent_context=parent_context,
        )
        try:
            # No system_prompt or system_prompt_prefix needed here —
            # this is a follow-up message in the same conversation context.
            if conv_logger:
                conv_logger.log_prompt(
                    task_id=subtask_id,
                    task_name=subtask['name'],
                    prompt=prompt,
                    attempt=1,
                    parent_task_id=parent_task_id,
                    metadata={"type": "long_running_analysis"},
                )
            
            result = client.ask(prompt)
            
            # Append response to log AFTER AI returns
            if conv_logger:
                conv_logger.log_response(
                    task_id=subtask_id,
                    response=client.last_full_log or result,
                    parent_task_id=parent_task_id,
                )
            
            # Reuse the same robust check logic from SimpleTaskExecutor
            completion_status = self.simple_executor._check_completion(result)
            is_completed = completion_status is True
            
            # Read log content for SubtaskResult
            log_content = ""
            if os.path.exists(output_log):
                try:
                    content = _read_log_file_smart(output_log)
                    _lf = limits.get('log_file')
                    log_content = content[-_lf:] if len(content) > _lf else content
                except Exception:
                    log_content = "(failed to read log file)"
            
            if is_completed:
                summary = SimpleTaskExecutor._extract_summary(result)
                state_manager.mark_task_status(
                    subtask_id, "completed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    ai_reasoning=summary,
                )
                print(f"      ✅ Long-running task {subtask_id} completed!")
            else:
                if completion_status is None:
                    last_line = result.strip().rsplit('\n', 1)[-1].strip() if result.strip() else '(empty)'
                    summary = (
                        f"Cannot find {SimpleTaskExecutor._SIMPLE_TASK_MARKERS} "
                        f"in previous response. "
                        f"(The last line in your response is: {last_line[:200]}) "
                        f"Please include the required status marker."
                    )
                    print(f"      ⚠️ No completion marker found in response for task {subtask_id}")
                else:
                    summary = SimpleTaskExecutor._extract_summary(result)
                    print(f"      ❌ Long-running task {subtask_id} did not meet criteria")
                state_manager.mark_task_status(
                    subtask_id, "failed",
                    error_type="validation_failed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    ai_reasoning=summary,
                )
            
            return SubtaskResult(
                success=is_completed,
                output=summary,
                logs=log_content,
                error_type=None if is_completed else "validation_failed",
                response_text=result,
            )
            
        except AICallError as e:
            logger.error(f"Failed to analyze long-running result: {e}")
            state_manager.mark_task_status(
                subtask_id, "failed",
                error_type=status,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return SubtaskResult(
                success=False,
                output=f"AI analysis failed: {e}",
                logs="",
                error_type=status,
            )
