import os
import json
import time
import logging
import yaml
from typing import Optional

from ai_client import AIClient, AICallError, BashTimeoutError, SessionTimeoutError, StreamTimeoutError
from state_manager import StateManager
from logger import ConversationLogger
from task_executor.task_executor_common import (
    _state_key,
    _write_autoagent_exec_script,
    _load_fast_fail_timeout,
    _load_show_console,
    _read_log_file_smart,
    SubtaskResult,
)
from prompts.shared import build_system_prompt_coding_agent, prepend_system_prompt_prefix
from prompts.simple_task import build_simple_task_prompt
from prompts.long_running_task import (
    build_long_running_prompt as _build_lr_prompt,
    build_long_running_analysis_prompt as _build_lr_analysis_prompt,
)
from prompts.marker_nudge import MAX_MARKER_NUDGES, MARKER_NUDGE_PROMPT
from prompts.timeout_continuation import (
    BASH_TIMEOUT_CONTINUATION_PROMPT,
    STREAM_TIMEOUT_CONTINUATION_PROMPT,
    INTERRUPT_CONTINUATION_PROMPT,
)
from util.truncation_limits import limits

logger = logging.getLogger(__name__)


class SimpleTaskExecutor:
    """
    Executes simple tasks using AI self-evaluation loop.
    
    The AI attempts the task, evaluates completion, and iterates
    until the criteria are met or max attempts are reached.
    """

    def __init__(self, session_dir: str = None, default_max_attempts: int = 5):
        self.session_dir = session_dir
        self.default_max_attempts = default_max_attempts
        self.last_response_text = ""

    def execute(self, task: dict, client: AIClient, state_manager, conv_logger=None, parent_task_id: str = None, parent_context: dict = None, project_description: str = "", **kwargs) -> bool:
        """
        Execute a simple task.

        Args:
            task: Task configuration dict
            client: AIClient instance
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance
            parent_task_id: Parent task ID if this is a subtask (for log organization)
            parent_context: Optional context from parent task for prompt enrichment
            project_description: Optional project-level description from todos.yaml

        Returns:
            bool: True if task completed successfully
        """
        task_id = str(task['id'])
        max_attempts = task.get('max_attempts', self.default_max_attempts)

        # Compute round-scoped state key: when called as a subtask
        # (parent_context present), use @round_label suffix; when called
        # as a top-level simple task, use the plain task_id.
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(task, round_label) if round_label else task_id

        current_state = state_manager.get_task_state(sk)
        attempts = current_state.get('attempts', 0)
        
        logger.info(f"Executing simple task {task_id}: {task['name']}")

        last_timeout_error = None  # Track if previous attempt timed out
        last_timeout_type = None   # "bash", "session", "stream", or "interrupt"
        should_reset = True        # Whether to reset session before next retry
        last_ai_output = None      # Full AI output from previous attempt

        # Check if the task was interrupted by user (Ctrl+C) in a previous
        # run.  If the session was preserved (session_id restored by the
        # orchestrator), skip the session reset and send a lightweight
        # in-session follow-up instead — just like BashTimeoutError.
        #
        # When running as a subtask inside a nested parent, the orchestrator
        # sets interrupt_pending on the *parent* task key (e.g. "1"), not on
        # the subtask's round-scoped key (e.g. "4@1.1").  So we also check
        # the parent task state when the subtask's own state has no flag.
        _interrupt_pending = current_state.get('interrupt_pending')
        if not _interrupt_pending and parent_task_id:
            parent_state = state_manager.get_task_state(parent_task_id)
            _interrupt_pending = parent_state.get('interrupt_pending')
            if _interrupt_pending:
                # Consume the flag from the parent so it isn't re-used
                state_manager.update_task_field(parent_task_id, "interrupt_pending", None)
        if _interrupt_pending and client.session_id:
            last_timeout_type = "interrupt"
            should_reset = False
            state_manager.update_task_field(sk, "interrupt_pending", None)
            # Roll back the attempt counter so the interrupted attempt is not
            # counted as a failure.  The while-loop below will increment it
            # back, effectively resuming at the same attempt number.
            if attempts > 0:
                attempts -= 1
            logger.info(
                f"Task {task_id}: interrupt_pending detected with session_id — "
                f"will continue in same session (attempts rolled back to {attempts})"
            )

        while attempts < max_attempts:
            attempts += 1

            # Reset session before retry — but skip reset when the previous
            # failure was a BashTimeoutError (the session is still alive and
            # the AI's work context is preserved; we just need to tell it
            # the command was killed).
            if attempts > 1 and should_reset:
                client.reset_session()
                logger.info(
                    f"Task {task_id}: reset session before retry attempt {attempts} "
                    f"(preventing context accumulation)"
                )
            state_manager.mark_task_status(
                sk, "in_progress",
                attempts=attempts,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )

            print(f"\n   Attempt #{attempts}")

            # Re-fetch state each attempt so history from previous attempts is visible
            current_state = state_manager.get_task_state(sk)

            # Build prompt.  When retrying after a session reset, include
            # the previous attempt's full AI output so the AI can see what
            # it already did.  When continuing in the same session (e.g.
            # after BashTimeoutError), use a lightweight in-session follow-up
            # instead of rebuilding the full task prompt.
            _log_round = (parent_context or {}).get('round_label') or str(attempts)
            _is_continuation = False  # True for lightweight in-session follow-ups
            if last_timeout_type in ("bash", "stream", "interrupt") and not should_reset:
                # In-session continuation after BashTimeoutError,
                # StreamTimeoutError, or user interrupt — the AI's
                # context is intact, just tell it what happened.
                _is_continuation = True
                if last_timeout_type == "bash":
                    prompt = BASH_TIMEOUT_CONTINUATION_PROMPT
                elif last_timeout_type == "stream":
                    prompt = STREAM_TIMEOUT_CONTINUATION_PROMPT
                else:  # interrupt
                    prompt = INTERRUPT_CONTINUATION_PROMPT
                exec_script_path = ""
                if self.session_dir:
                    exec_script_path = _write_autoagent_exec_script(
                        session_dir=self.session_dir,
                        task_id=task_id,
                        fast_fail_timeout=_load_fast_fail_timeout(),
                        show_console=_load_show_console(),
                    )
            else:
                prompt, exec_script_path = self._build_prompt(
                    task, attempts, current_state,
                    parent_context=parent_context,
                    timeout_feedback=last_timeout_error,
                    timeout_type=last_timeout_type,
                    project_description=project_description,
                    previous_attempt_output=last_ai_output,
                )
            last_timeout_error = None  # Reset after injecting into prompt
            last_timeout_type = None
            # Default: next retry will reset (overridden by BashTimeoutError handler)
            should_reset = True
            try:
                # Write prompt to log BEFORE calling AI (crash safety)
                system_prompt = build_system_prompt_coding_agent(
                    exec_script_path,
                    supports_system_prompt=client.provider.supports_system_prompt,
                )
                # Prepend system_prompt_prefix to user prompt — but skip for
                # lightweight continuation prompts (the session already has
                # the role/persona from the original prompt).
                if _is_continuation:
                    effective_prompt = prompt
                else:
                    effective_prompt = prepend_system_prompt_prefix(prompt, task)
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=task_id,
                        task_name=task['name'],
                        prompt=effective_prompt,
                        attempt=_log_round,
                        parent_task_id=parent_task_id,
                        system_prompt=system_prompt,
                    )

                result = client.ask(
                    effective_prompt,
                    system_prompt=system_prompt,
                )
                self.last_response_text = result
                last_ai_output = result  # Save for next retry's prompt

                # Append response to log AFTER AI returns
                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=client.last_full_log or result,
                        parent_task_id=parent_task_id,
                        attempt=_log_round,
                    )
                
                # Check if AI reports LONG_RUNNING_IN_PROGRESS
                # (AI has context and may use autoagent-exec even in a simple task)
                if self._handle_long_running_in_simple_task(
                    result, task, task_id, attempts, client, state_manager,
                    conv_logger=conv_logger, parent_task_id=parent_task_id,
                    log_round=_log_round, parent_context=parent_context,
                ):
                    # Successfully handled as long-running — treat as completed
                    return True
                
                # Check if AI reports completion
                # Extract a meaningful summary from the AI response
                completion_status = self._check_completion(result)

                # If no marker found, nudge AI in the same session instead
                # of wasting a full retry attempt.  The AI just finished its
                # work — all context is fresh — so a short follow-up asking
                # "did you meet the criteria?" is far cheaper than a full
                # session reset + re-execution.
                if completion_status is None:
                    nudge_result = self._nudge_for_marker(
                        client, task, result,
                        conv_logger=conv_logger,
                        parent_task_id=parent_task_id,
                        log_round=_log_round,
                    )
                    if nudge_result is not None:
                        result = nudge_result
                        # Check for LONG_RUNNING_IN_PROGRESS first (may come
                        # from signal-file detection or AI's nudge response)
                        if self._check_long_running_in_progress_static(result):
                            if self._handle_long_running_in_simple_task(
                                result, task, task_id, attempts, client,
                                state_manager, conv_logger=conv_logger,
                                parent_task_id=parent_task_id,
                                log_round=_log_round, parent_context=parent_context,
                            ):
                                return True
                        completion_status = self._check_completion(result)
                    else:
                        # All nudges exhausted without a marker.  As a last
                        # resort, check the signal file — the AI may have
                        # launched autoagent-exec but never emitted the
                        # LONG_RUNNING_IN_PROGRESS marker (or the LR task
                        # finished during the nudge window).
                        lr_synthetic = self._check_signal_file_for_running_task(task_id, include_finished=True)
                        if lr_synthetic is not None:
                            if self._handle_long_running_in_simple_task(
                                lr_synthetic, task, task_id, attempts, client,
                                state_manager, conv_logger=conv_logger,
                                parent_task_id=parent_task_id,
                                log_round=_log_round, parent_context=parent_context,
                            ):
                                return True

                if completion_status is True:
                    summary = self._extract_summary(result)
                    print(f"   ✅ Task {task_id} completed!")
                    state_manager.mark_task_status(
                        sk, "completed",
                        attempts=attempts,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ai_reasoning=summary,
                    )
                    # Record history
                    state_manager.add_task_history(sk, {
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
                            f"(The last line in your response is: {last_line[:limits.get('history_summary')]}) "
                            f"Please include the required status marker."
                        )
                        print(f"   ⚠️ No completion marker found in response for task {task_id}")
                    else:
                        # Explicitly marked as not completed
                        summary = self._extract_summary(result)
                        print(f"   ⏳ Not completed yet, AI will try to improve...")
                    state_manager.add_task_history(sk, {
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
                    should_reset = False  # Session still alive — continue in-session
                    last_ai_output = None  # Not needed (AI still has context)
                    print(f"   ⏰ Bash timeout detected — will continue in same session")
                elif isinstance(e, SessionTimeoutError):
                    last_timeout_error = str(e)
                    last_timeout_type = "session"
                    should_reset = True  # Session killed — must reset
                    print(f"   ⏰ Session timeout detected — next attempt will start fresh with previous output")
                elif isinstance(e, StreamTimeoutError):
                    last_timeout_error = None  # No special feedback needed
                    last_timeout_type = "stream"
                    should_reset = False  # Session still alive — continue in-session
                    last_ai_output = None  # AI still has context
                    print(f"   ⏰ Stream timeout detected — will continue in same session")
                else:
                    should_reset = True  # Other errors — reset
                # Append error as response (prompt was already logged above)
                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=f"AI Call Error: {e}",
                        parent_task_id=parent_task_id,
                        attempt=_log_round,
                    )
                state_manager.add_task_history(sk, {
                    "attempt": attempts,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "error",
                    "error": str(e),
                })

        # Max attempts reached
        print(f"   ❌ Task {task_id} failed after {max_attempts} attempts")
        state_manager.mark_task_status(
            sk, "failed",
            attempts=attempts,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def _build_prompt(self, task: dict, attempt: int, state: dict, parent_context: dict = None, timeout_feedback: str = None, timeout_type: str = None, project_description: str = "", previous_attempt_output: str = None) -> tuple:
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
                show_console=_load_show_console(),
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
            project_description=project_description,
            previous_attempt_output=previous_attempt_output,
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
            return ' '.join(meaningful_lines)[:limits.get('history_summary')]
        
        # Fallback: just take the last 300 chars
        return ai_response.strip()[-limits.get('history_summary'):]

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

    def _nudge_for_marker(
        self,
        client,
        task: dict,
        last_response: str,
        conv_logger=None,
        parent_task_id: str = None,
        log_round: str = None,
        max_nudges: int = None,
    ) -> Optional[str]:
        """Send a lightweight follow-up in the same session to elicit a marker.

        When the AI finishes its work but forgets to emit a completion
        marker, the worst thing we can do is reset the session and replay
        everything — the AI already *has* all the context.  Instead, we
        send a tiny prompt asking it to evaluate and reply with just the
        marker.

        Args:
            client: The AI client (session is kept alive).
            task: Current task dict (used only for logging).
            last_response: The AI's previous response (for logging context).
            conv_logger: Optional conversation logger.
            parent_task_id: Parent task ID for log organisation.
            log_round: Round label for log file naming.
            max_nudges: Override ``MAX_MARKER_NUDGES`` (for tests).

        Returns:
            The AI's response string if a nudge was sent and answered,
            or ``None`` if all nudges were exhausted without a marker.
        """
        task_id = str(task['id'])
        remaining = max_nudges if max_nudges is not None else MAX_MARKER_NUDGES

        # ── Pre-nudge check: detect already-running long-running tasks ──
        # If autoagent-exec already submitted a background task (signal file
        # exists with status "running"), the AI simply forgot to output
        # LONG_RUNNING_IN_PROGRESS.  Return a synthetic response immediately
        # — sending a nudge risks the AI re-launching the task.
        lr_synthetic = self._check_signal_file_for_running_task(task_id)
        if lr_synthetic is not None:
            print(f"   🔍 Detected active long-running signal file for task {task_id}, "
                  f"skipping nudge → synthetic LONG_RUNNING_IN_PROGRESS")
            return lr_synthetic

        for i in range(1, remaining + 1):
            print(f"   🔔 Nudging AI for status marker (nudge {i}/{remaining})...")
            try:
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=task_id,
                        task_name=task['name'],
                        prompt=MARKER_NUDGE_PROMPT,
                        attempt=log_round or "nudge",
                        parent_task_id=parent_task_id,
                        metadata={"type": "marker_nudge", "nudge": i},
                    )

                result = client.ask(MARKER_NUDGE_PROMPT)
                self.last_response_text = result

                if conv_logger:
                    conv_logger.log_response(
                        task_id=task_id,
                        response=client.last_full_log or result,
                        parent_task_id=parent_task_id,
                        attempt=log_round or "nudge",
                    )

                # Check if the nudge response contains a marker
                status = self._check_completion(result)
                if status is not None:
                    # Got a definitive answer (True or False)
                    return result

                lr_check = self._check_long_running_in_progress_static(result)
                if lr_check:
                    return result

                logger.info(
                    f"Task {task_id}: nudge {i} still no marker, "
                    f"response: {result.strip()[:limits.get('history_summary')]}"
                )
            except AICallError as e:
                logger.warning(f"Task {task_id}: nudge {i} failed: {e}")
                break  # Don't keep nudging if the API is failing

        # All nudges exhausted — caller will fall through to normal retry
        return None

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

    def _check_signal_file_for_running_task(self, task_id: str, include_finished: bool = False) -> Optional[str]:
        """Check if autoagent-exec has created a signal file for this task.

        When the AI calls autoagent-exec but forgets to output the
        LONG_RUNNING_IN_PROGRESS marker, we can detect this by checking
        for the signal file.

        By default (``include_finished=False``), only ``running`` status
        is matched — this is used as a **pre-nudge** check to prevent
        a nudge from accidentally re-launching the task.

        When ``include_finished=True``, ``finished`` and ``error`` are
        also matched — this is used as a **post-nudge fallback** to
        catch the race condition where the background task finishes
        during the AI's response or during the nudge window.

        Args:
            task_id: The task ID to look up the signal file for.
            include_finished: If True, also match ``finished``/``error``
                signal files (not just ``running``).

        Returns:
            A synthetic ``"⏳ LONG_RUNNING_IN_PROGRESS"`` string if a
            signal file is detected, or ``None`` otherwise.
        """
        # Resolve session_dir
        session_dir = self.session_dir
        if not session_dir:
            subtask_exec = getattr(self, '_subtask_executor', None)
            if subtask_exec and subtask_exec.session_dir:
                session_dir = subtask_exec.session_dir
        if not session_dir:
            return None

        lr_tasks_dir = os.path.join(session_dir, "lr_tasks")
        if not os.path.isdir(lr_tasks_dir):
            return None

        signal_file = os.path.join(lr_tasks_dir, f"lr_{task_id}_signal.json")
        if not os.path.isfile(signal_file):
            return None

        try:
            with open(signal_file, "r", encoding="utf-8") as f:
                signal_data = json.load(f)
            status = signal_data.get("status")
            match_statuses = ("starting", "running", "finished", "error") if include_finished else ("starting", "running")
            if status in match_statuses:
                logger.info(
                    f"Task {task_id}: signal file found with status={status}, "
                    f"returning synthetic LONG_RUNNING_IN_PROGRESS"
                )
                return "⏳ LONG_RUNNING_IN_PROGRESS"
        except Exception as e:
            logger.warning(f"Task {task_id}: failed to read signal file: {e}")

        return None

    def _handle_long_running_in_simple_task(
        self, response: str, task: dict, task_id: str, attempt: int,
        client, state_manager, conv_logger=None, parent_task_id: str = None,
        log_round: str = None, parent_context: dict = None,
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
            # Lazy import to break circular dependency:
            # simple_task_executor <-> subtask_executor
            from task_executor.subtask_executor import SubtaskExecutor
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
            show_console=_load_show_console(),
        )

        # Restart AI to analyze the result
        analyze_result = subtask_exec._ai_analyze_long_running_result(
            task, client, state_manager,
            monitor_status, output_log,
            conv_logger=conv_logger, parent_task_id=parent_task_id,
            parent_context=parent_context,
            signal_file=signal_file,
            exec_script_path=exec_script_path,
            log_round=log_round or str(attempt),
        )

        # Use round-scoped key for state operations
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(task, round_label) if round_label else task_id

        if analyze_result.success:
            state_manager.add_task_history(sk, {
                "attempt": attempt,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "result": "completed",
                "summary": analyze_result.output,
            })
            return True

        # Analysis says not completed — record and let the retry loop continue
        state_manager.add_task_history(sk, {
            "attempt": attempt,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "result": "not_completed",
            "summary": analyze_result.output or "Long-running task did not meet completion criteria",
        })
        # Reset status back to in_progress for retry
        state_manager.mark_task_status(
            sk, "in_progress",
            attempts=attempt,
            last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(f"   ⏳ Long-running callback analysis failed, retrying...")
        return False