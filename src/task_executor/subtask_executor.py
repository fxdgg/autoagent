
import os
import json
import time
import logging

from ai_client import AIClient, AICallError, BashTimeoutError, SessionTimeoutError, StreamTimeoutError
from logger import ConversationLogger
from task_executor.task_executor_common import (
    ConfigError,
    SubtaskResult,
    _state_key,
    _write_autoagent_exec_script,
    _load_fast_fail_timeout,
    _load_show_console,
    _read_log_file_smart,
)
from prompts.shared import build_system_prompt_coding_agent, prepend_system_prompt_prefix
from prompts.long_running_task import (
    build_long_running_prompt as _build_lr_prompt,
    build_long_running_analysis_prompt as _build_lr_analysis_prompt,
)
from prompts.timeout_continuation import (
    BASH_TIMEOUT_CONTINUATION_PROMPT,
    STREAM_TIMEOUT_CONTINUATION_PROMPT,
    INTERRUPT_CONTINUATION_PROMPT,
)
from util.truncation_limits import limits
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)


class SubtaskExecutor:
    """
    Dispatches subtask execution based on type (simple or long_running).
    """

    def __init__(self, session_dir: str = None, model_roles: dict = None, default_max_attempts: int = None):
        # Lazy import to break circular dependency:
        # subtask_executor <-> simple_task_executor
        from task_executor.simple_task_executor import SimpleTaskExecutor
        if default_max_attempts is None:
            default_max_attempts = DEFAULTS['default_max_attempts']
        self.simple_executor = SimpleTaskExecutor(session_dir=session_dir, default_max_attempts=default_max_attempts)
        # Back-reference so SimpleTaskExecutor can delegate long-running
        # handling (poll + callback) when AI uses autoagent-exec in a simple task
        self.simple_executor._subtask_executor = self
        self.session_dir = session_dir
        self.model_roles = model_roles or {}
        self.default_max_attempts = default_max_attempts

    def execute(self, subtask: dict, client: AIClient, state_manager, conv_logger=None, parent_task_id: str = None, parent_context: dict = None) -> SubtaskResult:
        """
        Execute a single subtask.
        
        Args:
            subtask: Subtask configuration
            client: AIClient instance
            state_manager: State manager
            conv_logger: Optional ConversationLogger instance
            parent_task_id: Parent task ID for log organization
            parent_context: Optional context from parent task for prompt enrichment
            
        Returns:
            SubtaskResult: Result of execution
        """
        subtask_type = subtask.get('type', 'simple')
        subtask_id = str(subtask['id'])
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(subtask, round_label) if round_label else subtask_id

        # Skip already-completed subtasks (in this round)
        subtask_state = state_manager.get_task_state(sk)
        if subtask_state.get('status') == 'completed':
            logger.info(f"Subtask {subtask_id} already completed (key={sk}), skipping")
            return SubtaskResult(
                success=True,
                output=subtask_state.get('ai_reasoning', ''),
                logs="",
            )

        # Switch model based on subtask's model field (default/simple or direct model name)
        subtask_model_role = subtask.get('model', 'default')
        if self.model_roles and hasattr(client, 'provider') and client.provider:
            if subtask_model_role in self.model_roles:
                target_model = self.model_roles[subtask_model_role]
            else:
                # Treat as a direct model name
                target_model = subtask_model_role
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
        elif subtask_type == 'nested':
            return self._execute_nested_subtask(
                subtask, client, state_manager,
                conv_logger=conv_logger,
                parent_context=parent_context,
            )
        elif subtask_type == 'looping':
            return self._execute_looping_subtask(
                subtask, client, state_manager,
                conv_logger=conv_logger,
                parent_context=parent_context,
            )
        else:
            raise ConfigError(f"Unknown subtask type: {subtask_type}")

    def _execute_simple_subtask(
        self, subtask: dict, client: AIClient, state_manager,
        conv_logger=None, parent_task_id: str = None, parent_context: dict = None,
    ) -> SubtaskResult:
        """Execute a simple subtask via AI."""
        project_description = (parent_context or {}).get('project_description', '')
        success = self.simple_executor.execute(
            subtask, client, state_manager,
            conv_logger=conv_logger, parent_task_id=parent_task_id,
            parent_context=parent_context,
            project_description=project_description,
        )
        
        subtask_id = str(subtask['id'])
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(subtask, round_label) if round_label else subtask_id
        state = state_manager.get_task_state(sk)

        return SubtaskResult(
            success=success,
            output=state.get('ai_reasoning', ''),
            logs="",
            error_type=None if success else "ai_failed",
            response_text=self.simple_executor.last_response_text,
        )

    def _execute_nested_subtask(
        self, subtask: dict, client: AIClient, state_manager,
        conv_logger=None, parent_context: dict = None,
    ) -> SubtaskResult:
        """Execute a nested subtask by delegating to NestedTaskExecutor."""
        # Lazy import to break circular dependency:
        # subtask_executor <-> nested_task_executor
        from task_executor.nested_task_executor import NestedTaskExecutor
        project_description = (parent_context or {}).get('project_description', '')
        executor = NestedTaskExecutor(
            session_dir=self.session_dir, model_roles=self.model_roles,
        )
        success = executor.execute(
            subtask, client, state_manager, conv_logger=conv_logger,
            project_description=project_description,
        )
        subtask_id = str(subtask['id'])
        state = state_manager.get_task_state(subtask_id)
        return SubtaskResult(
            success=success,
            output=state.get('ai_reasoning', '') or state.get('status', ''),
            logs="",
            error_type=None if success else "nested_failed",
        )

    def _execute_looping_subtask(
        self, subtask: dict, client: AIClient, state_manager,
        conv_logger=None, parent_context: dict = None,
    ) -> SubtaskResult:
        """Execute a looping subtask by delegating to LoopingTaskExecutor."""
        # Lazy import to break circular dependency:
        # subtask_executor <-> looping_task_executor
        from task_executor.looping_task_executor import LoopingTaskExecutor
        project_description = (parent_context or {}).get('project_description', '')
        executor = LoopingTaskExecutor(
            session_dir=self.session_dir, model_roles=self.model_roles,
        )
        success = executor.execute(
            subtask, client, state_manager, conv_logger=conv_logger,
            project_description=project_description,
        )
        subtask_id = str(subtask['id'])
        state = state_manager.get_task_state(subtask_id)
        return SubtaskResult(
            success=success,
            output=state.get('ai_reasoning', '') or state.get('status', ''),
            logs="",
            error_type=None if success else "looping_failed",
        )

    def _execute_long_running_subtask(
        self, subtask: dict, client: AIClient, state_manager,
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
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(subtask, round_label) if round_label else subtask_id
        max_attempts = subtask.get('max_attempts', self.default_max_attempts)

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
            show_console=_load_show_console(),
        )
        
        logger.info(f"Executing long-running subtask {subtask_id}: {subtask['name']}")
        logger.info(f"  autoagent-exec script: {exec_script_path}")
        logger.info(f"  log session dir: {log_session_dir}")

        should_reset = True   # Whether to reset session before next retry
        last_timeout_type = None  # "bash", "stream", or "interrupt"

        # Check if the task was interrupted by user (Ctrl+C) in a previous
        # run.  If the session was preserved, use in-session continuation.
        # Also check the parent task state — the orchestrator sets
        # interrupt_pending on the parent key, not the subtask's round-scoped key.
        current_state = state_manager.get_task_state(sk)
        _interrupt_pending = current_state.get('interrupt_pending')
        if not _interrupt_pending and parent_task_id:
            parent_state = state_manager.get_task_state(parent_task_id)
            _interrupt_pending = parent_state.get('interrupt_pending')
            if _interrupt_pending:
                state_manager.update_task_field(parent_task_id, "interrupt_pending", None)
        # ── Interrupt-during-polling recovery ──────────────────────────
        # If the previous run was interrupted while polling a signal file
        # (i.e. a background task was already submitted), we should resume
        # polling or go straight to analysis — NOT send a continuation
        # prompt that would confuse the AI into re-submitting the task.
        #
        # We perform the signal-file check in TWO cases:
        #   1. _interrupt_pending is set  (graceful Ctrl+C)
        #   2. No interrupt_pending, but a signal file already exists with
        #      status "starting" or "running"  (non-graceful termination
        #      such as kill -9, OOM, power loss, or crash)
        _pending_lr_signal = None  # Will hold (signal_file, output_log, signal_status) if applicable
        signal_file = os.path.join(log_session_dir, "lr_tasks", f"lr_{subtask_id}_signal.json")

        if _interrupt_pending:
            state_manager.update_task_field(sk, "interrupt_pending", None)
            if parent_task_id:
                # Already consumed from parent above; clear subtask's own flag too
                pass

        # Check signal file regardless of interrupt_pending — a running
        # background task may survive a non-graceful process death.
        if os.path.isfile(signal_file):
            try:
                with open(signal_file, "r", encoding="utf-8") as f:
                    sig = json.load(f)
                sig_status = sig.get("status")
            except Exception:
                sig_status = None

            # Interrupt recovery: all statuses are relevant because the
            # signal file reflects the *current* interrupted run — even
            # "finished"/"error" means the task finished but analysis
            # was never performed.
            #
            # Non-interrupt (orphan recovery): only "starting"/"running"
            # indicate a truly orphaned background task.  "finished"/"error"
            # from a previous attempt is expected and should be overwritten
            # by the normal retry prompt + autoagent-exec cycle.
            _match_statuses = (
                ("starting", "running", "finished", "error")
                if _interrupt_pending
                else ("starting", "running")
            )
            if sig_status in _match_statuses:
                _pending_lr_signal = (signal_file, sig_status)
                should_reset = False
                logger.info(
                    f"Long-running task {subtask_id}: signal file detected "
                    f"with status={sig_status} — will resume "
                    f"{'polling' if sig_status in ('starting', 'running') else 'analysis'}"
                )
                print(
                    f"      🔄 Resuming long-running task {subtask_id} "
                    f"(signal status: {sig_status})"
                )

        # No signal file and interrupt_pending — fall back to normal
        # interrupt continuation prompt (the AI was interrupted before
        # submitting).
        if _pending_lr_signal is None and _interrupt_pending and client.session_id:
            last_timeout_type = "interrupt"
            should_reset = False
            logger.info(
                f"Long-running task {subtask_id}: interrupt_pending detected "
                f"with no signal file — will continue in same session"
            )

        for attempt in range(1, max_attempts + 1):
            # Reset session before each retry to prevent context accumulation
            # (same rationale as SimpleTaskExecutor — see comment there).
            # Skip reset after StreamTimeoutError (session still alive).
            if attempt > 1 and should_reset:
                client.reset_session()
                logger.info(
                    f"Long-running task {subtask_id}: reset session before retry "
                    f"attempt {attempt} (preventing context accumulation)"
                )

            state_manager.mark_task_status(
                sk, "in_progress",
                attempts=attempt,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )

            print(f"\n      Long-running task attempt #{attempt}")

            # ── Fast-path: resume polling / analysis for interrupted LR task ──
            # If we detected a signal file from the previous interrupted run,
            # skip the AI call entirely and jump straight to poll or analysis.
            if _pending_lr_signal is not None:
                signal_file, sig_status = _pending_lr_signal
                output_log = signal_file.replace("_signal.json", "_output.log")
                _pending_lr_signal = None  # Consume — only applies once
                _log_round = (parent_context or {}).get('round_label') or str(attempt)

                if sig_status in ("starting", "running"):
                    print(f"      ⏳ Background task still running, resuming poll...")
                    monitor_status = self._poll_signal_file(
                        subtask_id, signal_file,
                        max_initial_wait=_load_fast_fail_timeout() * 2,
                    )
                else:
                    # "finished" or "error" — already done
                    monitor_status = sig_status
                    print(f"      📋 Background task already {sig_status}, analyzing result...")

                analyze_result = self._ai_analyze_long_running_result(
                    subtask, client, state_manager,
                    monitor_status, output_log,
                    conv_logger=conv_logger, parent_task_id=parent_task_id,
                    parent_context=parent_context, signal_file=signal_file,
                    exec_script_path=exec_script_path,
                    log_round=_log_round,
                )

                if analyze_result.success:
                    return analyze_result

                # Analysis says not completed — fall through to normal retry
                print(f"      ⏳ Long-running callback analysis failed, retrying...")
                state_manager.add_task_history(sk, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "not_completed",
                    "summary": analyze_result.output or "Long-running task did not meet completion criteria",
                })
                state_manager.mark_task_status(
                    sk, "in_progress",
                    attempts=attempt,
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                should_reset = True
                continue

            # Build prompt for AI.  After a timeout or user interrupt,
            # send a short continuation prompt instead of the full task
            # prompt (same logic as SimpleTaskExecutor).
            _is_continuation = False
            if last_timeout_type in ("bash", "stream", "interrupt") and not should_reset:
                if last_timeout_type == "bash":
                    prompt = BASH_TIMEOUT_CONTINUATION_PROMPT
                elif last_timeout_type == "stream":
                    prompt = STREAM_TIMEOUT_CONTINUATION_PROMPT
                else:  # interrupt
                    prompt = INTERRUPT_CONTINUATION_PROMPT
                _is_continuation = True
            else:
                prompt = self._build_long_running_prompt(
                    subtask, exec_script_path, attempt, state_manager,
                    parent_context=parent_context,
                )
            last_timeout_type = None
            should_reset = True  # Default: next retry will reset
            
            try:
                # Write prompt to log BEFORE calling AI (crash safety)
                system_prompt = build_system_prompt_coding_agent(
                    exec_script_path,
                    supports_system_prompt=client.provider.supports_system_prompt,
                )
                # Prepend system_prompt_prefix — skip for continuation prompts
                if _is_continuation:
                    effective_prompt = prompt
                else:
                    effective_prompt = prepend_system_prompt_prefix(prompt, subtask)
                _log_round = (parent_context or {}).get('round_label') or str(attempt)
                if conv_logger:
                    conv_logger.log_prompt(
                        task_id=subtask_id,
                        task_name=subtask['name'],
                        prompt=effective_prompt,
                        attempt=_log_round,
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
                        attempt=_log_round,
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
                        log_round=_log_round,
                    )
                    
                    if analyze_result.success:
                        return analyze_result
                    
                    # Analysis says not completed — retry within long-running loop
                    print(f"      ⏳ Long-running callback analysis failed, retrying...")
                    state_manager.add_task_history(sk, {
                        "attempt": attempt,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "result": "not_completed",
                        "summary": analyze_result.output or "Long-running task did not meet completion criteria",
                    })
                    # Reset status back to in_progress for retry (undo the "failed" set by _ai_analyze)
                    state_manager.mark_task_status(
                        sk, "in_progress",
                        attempts=attempt,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    continue
                
                # Check for normal completion (AI might have handled it directly)
                completion_status = self.simple_executor._check_completion(result)

                # Nudge for marker if missing (same logic as SimpleTaskExecutor)
                if completion_status is None:
                    nudge_result = self.simple_executor._nudge_for_marker(
                        client, subtask, result,
                        conv_logger=conv_logger,
                        parent_task_id=parent_task_id,
                        log_round=_log_round,
                    )
                    if nudge_result is not None:
                        result = nudge_result
                        # Check for LONG_RUNNING_IN_PROGRESS first (may come
                        # from signal-file detection or AI's nudge response).
                        if self._check_long_running_in_progress(result):
                            print(f"      ⏳ Nudge detected long-running task, waiting for completion...")
                            import re as _re
                            lr_task_id = subtask_id
                            _tid_match = _re.search(r'--task-id\s+(\S+)', result)
                            if _tid_match:
                                lr_task_id = _tid_match.group(1)
                            signal_file = os.path.join(log_session_dir, "lr_tasks", f"lr_{lr_task_id}_signal.json")
                            output_log = os.path.join(log_session_dir, "lr_tasks", f"lr_{lr_task_id}_output.log")
                            monitor_status = self._poll_signal_file(
                                subtask_id, signal_file,
                                max_initial_wait=_load_fast_fail_timeout() * 2,
                            )
                            analyze_result = self._ai_analyze_long_running_result(
                                subtask, client, state_manager,
                                monitor_status, output_log,
                                conv_logger=conv_logger, parent_task_id=parent_task_id,
                                parent_context=parent_context, signal_file=signal_file,
                                exec_script_path=exec_script_path,
                                log_round=_log_round,
                            )
                            if analyze_result.success:
                                return analyze_result
                            # Not successful — fall through to retry
                            state_manager.add_task_history(sk, {
                                "attempt": attempt,
                                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "result": "not_completed",
                                "summary": analyze_result.output or "Long-running task did not meet completion criteria",
                            })
                            state_manager.mark_task_status(
                                sk, "in_progress",
                                attempts=attempt,
                                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            continue
                        completion_status = self.simple_executor._check_completion(result)
                    else:
                        # All nudges exhausted.  Last resort: check the
                        # signal file — the AI may have launched
                        # autoagent-exec but never emitted the marker.
                        lr_synthetic = self.simple_executor._check_signal_file_for_running_task(subtask_id, include_finished=True)
                        if lr_synthetic is not None:
                            print(f"      ⏳ Signal file detected after nudge exhaustion, entering LR path...")
                            signal_file = os.path.join(log_session_dir, "lr_tasks", f"lr_{subtask_id}_signal.json")
                            output_log = os.path.join(log_session_dir, "lr_tasks", f"lr_{subtask_id}_output.log")
                            monitor_status = self._poll_signal_file(
                                subtask_id, signal_file,
                                max_initial_wait=_load_fast_fail_timeout() * 2,
                            )
                            analyze_result = self._ai_analyze_long_running_result(
                                subtask, client, state_manager,
                                monitor_status, output_log,
                                conv_logger=conv_logger, parent_task_id=parent_task_id,
                                parent_context=parent_context, signal_file=signal_file,
                                exec_script_path=exec_script_path,
                                log_round=_log_round,
                            )
                            if analyze_result.success:
                                return analyze_result
                            state_manager.add_task_history(sk, {
                                "attempt": attempt,
                                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "result": "not_completed",
                                "summary": analyze_result.output or "Long-running task did not meet completion criteria",
                            })
                            state_manager.mark_task_status(
                                sk, "in_progress",
                                attempts=attempt,
                                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            continue

                if completion_status is True:
                    summary = self.simple_executor._extract_summary(result)
                    print(f"      ✅ Long-running task {subtask_id} completed directly!")
                    state_manager.mark_task_status(
                        sk, "completed",
                        attempts=attempt,
                        last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                        ai_reasoning=summary,
                    )
                    return SubtaskResult(success=True, output=summary, response_text=result)
                
                # AI didn't complete and didn't submit long-running — maybe fast-fail retry
                if completion_status is None:
                    last_line = result.strip().rsplit('\n', 1)[-1].strip() if result.strip() else '(empty)'
                    summary = (
                        f"Cannot find {self.simple_executor._LONG_RUNNING_MARKERS} "
                        f"in previous response. "
                        f"(The last line in your response is: {last_line[:limits.get('history_summary')]}) "
                        f"Please include the required status marker."
                    )
                    print(f"      ⚠️ No completion/long-running marker found in response for task {subtask_id}")
                else:
                    summary = self.simple_executor._extract_summary(result)
                    print(f"      ⏳ Not completed yet, retrying...")
                state_manager.add_task_history(sk, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "not_completed",
                    "summary": summary,
                })

            except AICallError as e:
                logger.error(f"AI call failed for long-running task {subtask_id}: {e}")
                print(f"      ❌ AI call error: {e}")
                if isinstance(e, BashTimeoutError):
                    should_reset = False
                    last_timeout_type = "bash"
                    print(f"      ⏰ Bash timeout detected — will continue in same session")
                elif isinstance(e, SessionTimeoutError):
                    should_reset = True
                    last_timeout_type = "session"
                    print(f"      ⏰ Session timeout detected — next attempt will start fresh")
                elif isinstance(e, StreamTimeoutError):
                    should_reset = False
                    last_timeout_type = "stream"
                    print(f"      ⏰ Stream timeout detected — will continue in same session")
                else:
                    should_reset = True
                state_manager.add_task_history(sk, {
                    "attempt": attempt,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "result": "error",
                    "error": str(e),
                })
        
        # Max attempts exhausted
        print(f"      ❌ Long-running task {subtask_id} failed after {max_attempts} attempts")
        state_manager.mark_task_status(
            sk, "failed",
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
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(subtask, round_label) if round_label else subtask_id
        state = state_manager.get_task_state(sk) if attempt > 1 else {}

        return _build_lr_prompt(
            subtask=subtask,
            exec_script_path=exec_script_path,
            attempt=attempt,
            state=state,
            extract_summary_fn=self.simple_executor._extract_summary,
            parent_context=parent_context,
            project_description=(parent_context or {}).get('project_description', ''),
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
        check_interval: int = None, max_wait: int = None,
        max_initial_wait: int = None,
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
                Default 20s (suitable for the default fast_fail_timeout=30s).
        
        Returns:
            str: "finished", "error", or "timeout"
        """
        if check_interval is None:
            check_interval = DEFAULTS['signal_check_interval']
        if max_wait is None:
            max_wait = DEFAULTS['signal_max_wait']
        if max_initial_wait is None:
            max_initial_wait = DEFAULTS['signal_max_initial_wait']

        elapsed = 0
        pid = None  # Will be read from signal file
        consecutive_errors = 0
        max_consecutive_errors = DEFAULTS['max_signal_retry']  # After 10 consecutive read failures, escalate
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
                    
                    # status == "starting" or "running" — check if process is still alive
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

    def _poll_and_reanalyze(
        self,
        subtask: dict,
        client,
        subtask_id: str,
        signal_file: str,
        output_log: str,
        command_info: str,
        conv_logger=None,
        parent_task_id: str = None,
        _log_round: str = "1",
    ) -> tuple:
        """Poll a re-submitted long-running task and re-analyze.

        Called when AI re-submits a long-running task during callback
        analysis (e.g. fixed a bug and re-launched training).  Polls
        the signal file, then sends a fresh analysis prompt.

        Returns:
            (result_text, updated_command_info)
        """
        self._poll_signal_file(
            subtask_id, signal_file,
            max_initial_wait=_load_fast_fail_timeout() * 2,
        )
        # Re-read signal file for possibly updated command
        if os.path.exists(signal_file):
            try:
                with open(signal_file, 'r', encoding='utf-8') as _f:
                    _sig = json.load(_f)
                _cmd = _sig.get('command', '')
                if _cmd:
                    command_info = f"\nCommand: {_cmd}"
            except Exception:
                pass
        reanalyze_prompt = _build_lr_analysis_prompt(
            output_log=output_log,
            command_info=command_info,
        )
        if conv_logger:
            conv_logger.log_prompt(
                task_id=subtask_id,
                task_name=subtask['name'],
                prompt=reanalyze_prompt,
                attempt=_log_round,
                parent_task_id=parent_task_id,
                metadata={"type": "long_running_analysis_retry"},
            )
        result = client.ask(reanalyze_prompt)
        if conv_logger:
            conv_logger.log_response(
                task_id=subtask_id,
                response=client.last_full_log or result,
                parent_task_id=parent_task_id,
                attempt=_log_round,
            )
        return result, command_info

    def _ai_analyze_long_running_result(
        self, subtask, client, state_manager, status, output_log,
        conv_logger=None, parent_task_id: str = None,
        parent_context: dict = None, signal_file: str = None,
        exec_script_path: str = "",
        log_round: str = None,
    ) -> SubtaskResult:
        """
        Ask AI to analyze the result of a long-running task.
        
        Instead of embedding log content in the prompt, we provide the
        file path so the AI can read it using its Read tool.
        """
        subtask_id = str(subtask['id'])
        round_label = (parent_context or {}).get('round_label')
        sk = _state_key(subtask, round_label) if round_label else subtask_id

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
            output_log=output_log,
            command_info=command_info,
        )
        try:
            # No system_prompt or system_prompt_prefix needed here —
            # this is a follow-up message in the same conversation context.
            _log_round = log_round or (parent_context or {}).get('round_label') or '1'
            if conv_logger:
                conv_logger.log_prompt(
                    task_id=subtask_id,
                    task_name=subtask['name'],
                    prompt=prompt,
                    attempt=_log_round,
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
                    attempt=_log_round,
                )
            
            # Reuse the same robust check logic from SimpleTaskExecutor
            completion_status = self.simple_executor._check_completion(result)

            # If AI re-submitted a long-running task during callback analysis
            # (e.g. fixed a bug and re-launched training), poll for the new
            # task and re-analyze — mirroring SimpleTaskExecutor.execute()
            # lines 514-523.
            if self.simple_executor._check_long_running_in_progress_static(result):
                result, command_info = self._poll_and_reanalyze(
                    subtask, client, subtask_id, signal_file, output_log,
                    command_info, conv_logger, parent_task_id, _log_round,
                )
                completion_status = self.simple_executor._check_completion(result)

            # Nudge for marker if still missing (same logic as SimpleTaskExecutor)
            if completion_status is None:
                nudge_result = self.simple_executor._nudge_for_marker(
                    client, subtask, result,
                    conv_logger=conv_logger,
                    parent_task_id=parent_task_id,
                    log_round=_log_round,
                )
                if nudge_result is not None:
                    result = nudge_result
                    # Nudge may also detect a re-submitted long-running task
                    # (synthetic LONG_RUNNING_IN_PROGRESS from signal file)
                    if self.simple_executor._check_long_running_in_progress_static(result):
                        result, command_info = self._poll_and_reanalyze(
                            subtask, client, subtask_id, signal_file, output_log,
                            command_info, conv_logger, parent_task_id, _log_round,
                        )
                    completion_status = self.simple_executor._check_completion(result)

            is_completed = completion_status is True
            
            # Read log content for SubtaskResult
            log_content = ""
            if os.path.exists(output_log):
                try:
                    content = _read_log_file_smart(output_log)
                    _lf = limits.get('previous_subtask_summary')
                    log_content = content[-_lf:] if len(content) > _lf else content
                except Exception:
                    log_content = "(failed to read log file)"
            
            if is_completed:
                summary = self.simple_executor._extract_summary(result)
                state_manager.mark_task_status(
                    sk, "completed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                    ai_reasoning=summary,
                )
                print(f"      ✅ Long-running task {subtask_id} completed!")
            else:
                if completion_status is None:
                    last_line = result.strip().rsplit('\n', 1)[-1].strip() if result.strip() else '(empty)'
                    summary = (
                        f"Cannot find {self.simple_executor._SIMPLE_TASK_MARKERS} "
                        f"in previous response. "
                        f"(The last line in your response is: {last_line[:limits.get('history_summary')]}) "
                        f"Please include the required status marker."
                    )
                    print(f"      ⚠️ No completion marker found in response for task {subtask_id}")
                else:
                    summary = self.simple_executor._extract_summary(result)
                    print(f"      ❌ Long-running task {subtask_id} did not meet criteria")
                state_manager.mark_task_status(
                    sk, "failed",
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
                sk, "failed",
                error_type=status,
                last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return SubtaskResult(
                success=False,
                output=f"AI analysis failed: {e}",
                logs="",
                error_type=status,
            )
