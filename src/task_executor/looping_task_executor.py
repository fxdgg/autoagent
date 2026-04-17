
import json
import time
import logging
import yaml

from ai_client import AIClient, AICallError
from state_manager import StateManager
from logger import ConversationLogger
from task_executor.task_executor_common import (
    ConfigError,
    _state_key,
    _build_failed_subtask_history,
    _save_previous_subtask_summary,
    _load_previous_subtask_summary,
)
from task_executor.subtask_executor import SubtaskExecutor
from prompts.failure_analysis import build_failure_analysis_prompt
from util.truncation_limits import limits

logger = logging.getLogger(__name__)


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

    def __init__(self, session_dir: str = None, model_roles: dict = None, default_max_attempts: int = 5):
        self.subtask_executor = SubtaskExecutor(session_dir=session_dir, model_roles=model_roles, default_max_attempts=default_max_attempts)
        self.session_dir = session_dir
        self.model_roles = model_roles or {}
        self.default_max_attempts = default_max_attempts

    def execute(self, task: dict, client: AIClient, state_manager, conv_logger=None, project_description: str = "", **kwargs) -> bool:
        """
        Execute a looping task.

        Args:
            task: Task configuration with subtasks and repeat_count
            client: AIClient instance
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance
            project_description: Optional project-level description from todos.yaml

        Returns:
            bool: True if all iterations completed successfully
        """
        task_id = str(task['id'])
        repeat_count = task.get('repeat_count', 1)
        max_attempts_per_loop = task.get('max_attempts_per_loop', self.default_max_attempts)
        subtasks = task.get('subtasks', [])

        if not subtasks:
            raise ConfigError(f"Looping task {task_id} has no subtasks")

        # Register with conversation logger
        if conv_logger:
            subtask_ids = [str(st['id']) for st in subtasks]
            conv_logger.register_nested_task(task_id, task['name'], subtask_ids)

        logger.info(f"Executing looping task {task_id}: {task['name']} (repeat_count={repeat_count})")

        # Clear stale previous_subtask_summary from prior top-level tasks
        _save_previous_subtask_summary(self.session_dir, "")

        # Resume from the last saved loop index if the task was interrupted.
        # current_loop is persisted in state on each iteration start, so on
        # restart we pick up where we left off instead of re-running from 1.
        current_state = state_manager.get_task_state(task_id)
        start_loop = current_state.get('current_loop', 1)
        if start_loop > 1:
            logger.info(f"Resuming looping task {task_id} from loop {start_loop} (was interrupted)")
            print(f"   🔄 Resuming from loop {start_loop}/{repeat_count}")

        for loop_idx in range(start_loop, repeat_count + 1):
            print(f"\n   🔁 Loop iteration {loop_idx}/{repeat_count} of task {task_id}")

            # No blanket reset — each round uses @-suffixed state keys
            # (e.g. "1.2@3.1"), so new rounds start with empty state
            # automatically.  *_once subtasks use plain keys and are
            # checked in _state_key().

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
                project_description=project_description,
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
        conv_logger=None, loop_idx=1, max_attempts=5,
        project_description: str = "",
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

        # Resume: restore _failure_sub_round from persisted ai_decisions
        parent_state = state_manager.get_task_state(task_id)
        ai_decisions = parent_state.get('ai_decisions', [])
        _failure_sub_round = sum(1 for d in ai_decisions if d.get('loop') == loop_idx) + 1

        while attempts < max_attempts:
            attempts += 1

            if attempts > 1:
                print(f"\n   📋 Retry attempt #{attempts} within loop {loop_idx}")

            all_completed = True

            # Build parent context for subtask prompt enrichment
            parent_state = state_manager.get_task_state(task_id)
            ai_decisions = parent_state.get('ai_decisions', [])
            # Only use suggested_fix from the current loop iteration
            loop_decisions = [d for d in ai_decisions if d.get('loop') == loop_idx]
            latest_fix = loop_decisions[-1].get('suggested_fix', '') if loop_decisions else ''
            fix_target_id = loop_decisions[-1].get('retry_from', '') if loop_decisions else ''
            # Cap fix context to avoid oversized prompts
            if latest_fix and len(latest_fix) > limits.get('max'):
                latest_fix = "(truncated)\n..." + latest_fix[-limits.get('max'):]

            parent_context = {
                'subtasks': subtasks,
                'suggested_fix': '',  # Will be set per-subtask below
                '_suggested_fix_full': latest_fix,
                '_fix_target_id': fix_target_id,
                'ai_decisions': ai_decisions,
                'main_task_criteria': task.get('completion_criteria', ''),
                'round_label': f"{loop_idx}.{_failure_sub_round}",
                'project_description': project_description,
            }

            # Restore previous_subtask_summary from disk so that retries
            # within the same round have context.  For the first attempt
            # of a new round, start fresh (don't carry stale context).
            if attempts > 1:
                previous_subtask_summary = _load_previous_subtask_summary(self.session_dir)
            else:
                previous_subtask_summary = ""
                _save_previous_subtask_summary(self.session_dir, "")
            previous_subtask_id = ""

            for subtask in subtasks:
                subtask_id = str(subtask['id'])
                round_label = parent_context['round_label']
                sk = _state_key(subtask, round_label)
                subtask_state = state_manager.get_task_state(sk)

                # Only pass suggested_fix to the retry target subtask.
                # If the target was a *_once subtask that got skipped,
                # carry the fix forward to the first subtask that actually runs.
                if subtask_id == parent_context.get('_fix_target_id'):
                    parent_context['suggested_fix'] = parent_context.get('_suggested_fix_full', '')
                    parent_context['_fix_carried'] = False
                elif parent_context.get('_fix_carried'):
                    # Previous target was skipped — this is the first real execution
                    parent_context['_fix_carried'] = False
                else:
                    parent_context['suggested_fix'] = ''

                # Skip already completed subtasks (in this round)
                if subtask_state.get('status') == 'completed':
                    print(f"\n   📌 Subtask {subtask_id}: {subtask['name']} (already completed, skipping)")
                    previous_subtask_id = subtask_id
                    # If this skipped subtask holds suggested_fix, carry forward
                    if parent_context.get('suggested_fix'):
                        parent_context['_fix_carried'] = True
                    continue

                # Reset session before each subtask (except the first) to
                # prevent unbounded context growth across subtasks.
                # Skip reset when parent was interrupted (Ctrl+C) — session
                # needs to stay alive for the lightweight follow-up.
                parent_interrupt_pending = state_manager.get_task_state(task_id).get('interrupt_pending')
                if previous_subtask_summary and not parent_interrupt_pending:
                    client.reset_session()

                parent_context['previous_subtask_summary'] = previous_subtask_summary
                parent_context['previous_subtask_id'] = previous_subtask_id

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
                    round_label = f"{loop_idx}.{_failure_sub_round}"
                    ai_decision = self._ai_analyze_failure(
                        client, task, subtask, subtasks, result, state_manager,
                        conv_logger=conv_logger, loop_idx=loop_idx,
                        round_label=round_label,
                        previous_context=previous_subtask_summary,
                        previous_subtask_id=previous_subtask_id,
                    )

                    retry_from = ai_decision.get('retry_from', subtask_id)

                    # Carry forward completed subtasks before retry_from
                    old_rl = f"{loop_idx}.{_failure_sub_round}"
                    _failure_sub_round += 1
                    new_rl = f"{loop_idx}.{_failure_sub_round}"
                    self._carry_forward_completed(retry_from, subtasks, state_manager, old_rl, new_rl)

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
                    previous_subtask_id = subtask_id
                    # Persist to disk so it survives interruptions
                    _save_previous_subtask_summary(self.session_dir, previous_subtask_summary)

            if all_completed:
                return True

        return False

    def _ai_analyze_failure(
        self, client, task, failed_subtask, all_subtasks, result, state_manager,
        conv_logger=None, loop_idx=1, round_label=None, previous_context="",
        previous_subtask_id="",
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
            # Use round-scoped key to get the correct state for this round
            st_key = StateManager.round_key(st_id, round_label)
            st_state = state_manager.get_task_state(st_key)
            # For *_once types, also check the plain key (shared across rounds)
            if st_state.get('status', 'pending') == 'pending' and st.get('type', '').endswith('_once'):
                plain_state = state_manager.get_task_state(st_id)
                if plain_state.get('status') == 'completed':
                    st_state = plain_state
            task_history.append({
                "subtask_id": st_id,
                "name": st['name'],
                "type": st['type'],
                "completion_criteria": st.get('completion_criteria', ''),
                "status": st_state.get('status', 'pending'),
                "attempts": st_state.get('attempts', 0),
                "ai_reasoning": st_state.get('ai_reasoning', ''),
            })

        # Include previous AI decisions for context — only from the current
        # loop iteration (earlier loops are irrelevant and waste tokens).
        parent_state = state_manager.get_task_state(task_id)
        prev_decisions = parent_state.get('ai_decisions', [])
        prev_decisions_text = ""
        if prev_decisions:
            # Filter to decisions from the current loop only
            loop_decisions = [d for d in prev_decisions if d.get('loop') == loop_idx]
            recent_decisions = loop_decisions[-3:]
            decision_lines = []
            for d in recent_decisions:
                decision_lines.append(
                    f"  - Loop {d.get('loop', '?')}: failed at {d.get('failed_at', '?')}, "
                    f"retried from {d.get('retry_from', '?')}\n"
                    f"    Fix attempted: {d.get('suggested_fix', 'N/A')[:limits.get('max')]}"
                )
            prev_decisions_text = "\n".join(decision_lines)

        # Build error text: prefer logs, then AI response, then output summary
        error_text = result.logs or result.response_text or result.output
        error_text = self._truncate_error(error_text)

        # Build per-attempt history for the failed subtask
        failed_subtask_history = _build_failed_subtask_history(
            failed_id, state_manager, round_label,
        )

        prompt = build_failure_analysis_prompt(
            task=task,
            failed_subtask=failed_subtask,
            all_subtasks=all_subtasks,
            error_text=error_text,
            prev_decisions_text=prev_decisions_text,
            previous_context=self._truncate_error(previous_context) if previous_context else "",
            failed_subtask_history=failed_subtask_history,
            previous_subtask_id=previous_subtask_id,
            subtasks_with_status=task_history,
        )

        print(f"\n   🤖 [AI: Failure Analysis (loop {loop_idx})]")

        # Switch to evaluation model if configured
        original_model = client.provider.model if hasattr(client, 'provider') and client.provider else None
        eval_model = self.model_roles.get('evaluation')
        if eval_model and original_model and eval_model != original_model:
            client.provider.set_model(eval_model)

        # NOTE: Do NOT prepend system_prompt_prefix here — failure analysis
        # is a follow-up message in the same conversation context.
        effective_prompt = prompt

        try:
            _rl = round_label or str(loop_idx)
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=task_id,
                    task_name=task['name'],
                    call_type="looping_failure_analysis",
                    prompt=effective_prompt,
                    round_num=_rl,
                    failed_subtask_id=failed_id,
                )

            decision = client.ask(effective_prompt, expect_json=True)
            print(f"      AI Analysis: {decision.get('analysis', 'N/A')[:limits.get('log_promptlike_preview')]}")
            print(f"      AI Decision: retry_from = {decision.get('retry_from', failed_id)}")

            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=task_id,
                    task_name=task['name'],
                    response=response_for_log,
                    call_type="looping_failure_analysis",
                    round_num=_rl,
                    failed_subtask_id=failed_id,
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
        finally:
            # Restore original model
            if original_model and hasattr(client, 'provider') and client.provider:
                client.provider.set_model(original_model)

    def _carry_forward_completed(
        self, retry_from: str, subtasks: list, state_manager,
        old_round_label: str, new_round_label: str,
    ):
        """Copy completed subtask states from *old_round_label* to *new_round_label*.

        Subtasks **before** *retry_from* are fully copied (if completed).
        The *retry_from* subtask itself gets only its ``history`` list
        carried forward (status stays ``pending``, attempts stays ``0``)
        so the AI can see what failed in the previous round.

        ``*_once`` subtasks are skipped (they use plain keys shared
        across rounds).
        """
        retry_from = str(retry_from)
        for subtask in subtasks:
            st_id = str(subtask['id'])
            if st_id == retry_from:
                # Carry forward only the history for the retry target
                if not subtask.get('type', '').endswith('_once'):
                    old_key = StateManager.round_key(st_id, old_round_label)
                    old_state = state_manager.get_task_state(old_key)
                    old_history = old_state.get('history', [])
                    if old_history:
                        new_key = StateManager.round_key(st_id, new_round_label)
                        state_manager.state["tasks"][new_key] = {
                            "status": "pending",
                            "attempts": 0,
                            "history": list(old_history),
                        }
                break
            if subtask.get('type', '').endswith('_once'):
                continue
            old_key = StateManager.round_key(st_id, old_round_label)
            old_state = state_manager.get_task_state(old_key)
            # All subtasks before retry_from should be marked completed
            # in the new round — even if they were the failed subtask
            # (e.g. retry_from points to a LATER subtask).
            if old_state.get('status') in ('completed', 'failed'):
                new_key = StateManager.round_key(st_id, new_round_label)
                carried = dict(old_state)
                carried['status'] = 'completed'
                state_manager.state["tasks"][new_key] = carried
        state_manager.save_state()
        # Clear stale previous_subtask_summary — the new round should not
        # inherit context from the old round's last completed subtask.
        _save_previous_subtask_summary(self.session_dir, "")

    @staticmethod
    def _truncate_error(error_text: str, max_chars: int = None) -> str:
        """Truncate error text to avoid wasting tokens on overly long errors."""
        if max_chars is None:
            max_chars = limits.get('previous_subtask_summary')
        if not error_text:
            return "(no error output)"
        error_text = str(error_text)
        if len(error_text) <= max_chars:
            return error_text
        return f"(truncated, showing last {max_chars} chars)\n...{error_text[-max_chars:]}"
