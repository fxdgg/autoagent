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
from prompts.main_evaluation import build_main_evaluation_prompt
from util.truncation_limits import limits

logger = logging.getLogger(__name__)


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

    def execute(self, task: dict, client: AIClient, state_manager, conv_logger=None, project_description: str = "", **kwargs) -> bool:
        """
        Execute a nested task.

        Args:
            task: Task configuration with subtasks
            client: AIClient instance
            state_manager: State manager for persistence
            conv_logger: Optional ConversationLogger instance
            project_description: Optional project-level description from todos.yaml

        Returns:
            bool: True if main task completed
        """
        task_id = str(task['id'])
        max_attempts = task.get('max_attempts', 5)
        subtasks = task.get('subtasks', [])
        
        if not subtasks:
            raise ConfigError(f"Nested task {task_id} has no subtasks")
        
        # Register nested task with conversation logger
        if conv_logger:
            subtask_ids = [str(st['id']) for st in subtasks]
            conv_logger.register_nested_task(task_id, task['name'], subtask_ids)
        
        logger.info(f"Executing nested task {task_id}: {task['name']}")

        # Clear stale previous_subtask_summary from prior top-level tasks
        _save_previous_subtask_summary(self.session_dir, "")

        current_state = state_manager.get_task_state(task_id)
        attempts = current_state.get('attempts', 0)

        # If the task was interrupted by Ctrl+C, roll back the attempt
        # counter so the interrupted round is not counted as a failure.
        # The interrupt_pending flag is consumed by the subtask executor,
        # but we still need to adjust the parent's attempt counter here.
        if current_state.get('interrupt_pending'):
            if attempts > 0:
                attempts -= 1
                logger.info(
                    f"Nested task {task_id}: interrupt_pending detected — "
                    f"rolling back attempts to {attempts}"
                )

        # Round labelling: X.Y where X = main evaluation round, Y = failure sub-round
        # X increments after each main_task_evaluation; Y increments after each failure_analysis
        _main_round = len(current_state.get('main_task_evaluations', [])) + 1
        # Resume: restore _failure_sub_round from persisted ai_decisions
        ai_decisions_all = current_state.get('ai_decisions', [])
        _failure_sub_round = sum(
            1 for d in ai_decisions_all
            if d.get('_main_round', d.get('attempt', 0)) == _main_round
        ) + 1

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
            # Get the latest AI decision (suggested_fix) from the CURRENT main round only
            parent_state = state_manager.get_task_state(task_id)
            ai_decisions = parent_state.get('ai_decisions', [])
            current_round_decisions = [
                d for d in ai_decisions
                if d.get('_main_round', d.get('attempt', 0)) == _main_round
            ]
            latest_fix = current_round_decisions[-1].get('suggested_fix', '') if current_round_decisions else ''
            fix_target_id = current_round_decisions[-1].get('retry_from', '') if current_round_decisions else ''
            # Also check main_task_evaluations for next_strategy
            evaluations = parent_state.get('main_task_evaluations', [])
            next_strategy = ""
            if evaluations:
                last_eval = evaluations[-1]
                if not last_eval.get('completed', False):
                    next_strategy = last_eval.get('next_strategy', '')

            # Cap composite fix context to avoid oversized prompts
            if latest_fix and len(latest_fix) > limits.get('max'):
                latest_fix = "(truncated)\n..." + latest_fix[-limits.get('max'):]

            parent_context = {
                'subtasks': subtasks,
                'suggested_fix': '',  # Will be set per-subtask below
                '_suggested_fix_full': latest_fix,  # Stored for the target subtask
                '_fix_target_id': fix_target_id,
                'ai_decisions': ai_decisions,
                'main_task_criteria': task.get('completion_criteria', ''),
                'round_label': f"{_main_round}.{_failure_sub_round}",
                'project_description': project_description,
                'next_strategy': next_strategy,
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
                # However, skip the reset when the parent task was interrupted
                # (Ctrl+C) — the orchestrator restored the session so the
                # subtask can send a lightweight follow-up instead of replaying
                # the full prompt.
                parent_interrupt_pending = state_manager.get_task_state(task_id).get('interrupt_pending')
                if previous_subtask_summary and not parent_interrupt_pending:
                    client.reset_session()

                parent_context['previous_subtask_summary'] = previous_subtask_summary
                parent_context['previous_subtask_id'] = previous_subtask_id

                print(f"\n   📌 Executing subtask {subtask_id}: {subtask['name']}")
                print(f"      Type: {subtask['type']}")

                result = self.subtask_executor.execute(
                    subtask, client, state_manager,
                    conv_logger=conv_logger, parent_task_id=task_id,
                    parent_context=parent_context,
                )

                # Clear one-shot guidance after first execution consumes it
                parent_context['next_strategy'] = ''

                if not result.success:
                    all_completed = False
                    print(f"\n   ❌ Subtask {subtask_id} failed!")

                    # AI Decision Point 1: Analyze failure
                    round_label = f"{_main_round}.{_failure_sub_round}"
                    ai_decision = self._ai_analyze_failure(
                        client, task, subtask, subtasks, result, state_manager,
                        conv_logger=conv_logger, round_num=attempts,
                        round_label=round_label,
                        previous_context=previous_subtask_summary,
                        previous_subtask_id=previous_subtask_id,
                    )

                    # Reset subtasks based on AI decision
                    retry_from = ai_decision.get('retry_from', subtask_id)

                    # Carry forward completed subtasks before retry_from
                    old_rl = f"{_main_round}.{_failure_sub_round}"
                    _failure_sub_round += 1
                    new_rl = f"{_main_round}.{_failure_sub_round}"
                    self._carry_forward_completed(retry_from, subtasks, state_manager, old_rl, new_rl)

                    # Record AI decision
                    state_manager.add_ai_decision(task_id, {
                        "attempt": attempts,
                        "_main_round": _main_round,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "failed_at": subtask_id,
                        "retry_from": retry_from,
                        "suggested_fix": ai_decision.get('suggested_fix', ''),
                    })

                    break  # Break subtask loop, start new round
                else:
                    # Capture response for next subtask's context
                    previous_subtask_summary = result.response_text or result.output
                    previous_subtask_id = subtask_id
                    # Persist to disk so it survives interruptions
                    _save_previous_subtask_summary(self.session_dir, previous_subtask_summary)

            if not all_completed:
                print(f"\n   ⏳ Subtask failed, starting new round...")
                continue

            # All subtasks completed - AI Decision Point 2: Evaluate main task
            print(f"\n   📊 All subtasks completed, evaluating main task...")
            ai_evaluation = self._ai_evaluate_main_task(
                client, task, subtasks, state_manager,
                conv_logger=conv_logger, round_num=_main_round,
                round_label=f"{_main_round}.{_failure_sub_round}",
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
                    "round": _main_round,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed": True,
                    "analysis": ai_evaluation.get('analysis', ''),
                })
                return True
            else:
                print(f"\n   ⏳ Main task not yet completed.")
                print(f"      Analysis: {ai_evaluation.get('analysis', 'N/A')}")
                print(f"      Next strategy: {ai_evaluation.get('next_strategy', 'N/A')}")

                # Record evaluation (before incrementing _main_round)
                retry_from = ai_evaluation.get('retry_from', str(subtasks[0]['id']))
                state_manager.add_main_task_evaluation(task_id, {
                    "round": _main_round,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "completed": False,
                    "analysis": ai_evaluation.get('analysis', ''),
                    "next_strategy": ai_evaluation.get('next_strategy', ''),
                    "retry_from": retry_from,
                })

                # Carry forward completed subtasks into next main round
                old_rl = f"{_main_round}.{_failure_sub_round}"
                _main_round += 1
                _failure_sub_round = 1
                new_rl = f"{_main_round}.{_failure_sub_round}"
                self._carry_forward_completed(retry_from, subtasks, state_manager, old_rl, new_rl)

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
        conv_logger=None, round_num=1, round_label=None, previous_context="",
        previous_subtask_id="",
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
        # main round (earlier rounds are irrelevant and waste tokens).
        parent_state = state_manager.get_task_state(task_id)
        prev_decisions = parent_state.get('ai_decisions', [])
        prev_decisions_text = ""
        if prev_decisions:
            # Extract current main round from round_label (e.g. "3.2" → 3)
            current_main_round = None
            if round_label:
                try:
                    current_main_round = int(round_label.split('.')[0])
                except (ValueError, IndexError):
                    pass
            # Filter to decisions from the current main round only
            if current_main_round is not None:
                round_decisions = [
                    d for d in prev_decisions
                    if d.get('_main_round', d.get('attempt', 0)) == current_main_round
                ]
            else:
                round_decisions = prev_decisions
            recent_decisions = round_decisions[-3:]
            decision_lines = []
            for d in recent_decisions:
                decision_lines.append(
                    f"  - Round {d.get('attempt', '?')}: failed at {d.get('failed_at', '?')}, "
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
        print(f"\n   🤖 [AI Decision Point 1: Failure Analysis]")

        # Switch to evaluation model if configured
        original_model = client.provider.model if hasattr(client, 'provider') and client.provider else None
        eval_model = self.model_roles.get('evaluation')
        if eval_model and original_model and eval_model != original_model:
            client.provider.set_model(eval_model)

        # NOTE: Do NOT prepend system_prompt_prefix here — failure analysis
        # is a follow-up message in the same conversation context.
        effective_prompt = prompt

        try:
            # Write prompt to log BEFORE calling AI (crash safety)
            _rl = round_label or str(round_num)
            if conv_logger:
                conv_logger.log_nested_prompt(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    call_type="failure_analysis",
                    prompt=effective_prompt,
                    round_num=_rl,
                    failed_subtask_id=failed_id,
                )

            decision = client.ask(effective_prompt, expect_json=True)
            print(f"      AI Analysis: {decision.get('analysis', 'N/A')[:limits.get('log_promptlike_preview')]}")
            print(f"      AI Decision: retry_from = {decision.get('retry_from', failed_id)}")
            print(f"      Suggested Fix: {decision.get('suggested_fix', 'N/A')[:limits.get('log_promptlike_preview')]}")            # Append response to log AFTER AI returns
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(decision, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    response=response_for_log,
                    call_type="failure_analysis",
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

    def _ai_evaluate_main_task(
        self, client, task, subtasks, state_manager,
        conv_logger=None, round_num=1, round_label=None,
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
            # Use round-scoped key to get the correct state for this round
            st_key = StateManager.round_key(st_id, round_label)
            st_state = state_manager.get_task_state(st_key)
            # For *_once types, also check the plain key (shared across rounds)
            if st_state.get('status', 'pending') == 'pending' and st.get('type', '').endswith('_once'):
                plain_state = state_manager.get_task_state(st_id)
                if plain_state.get('status') == 'completed':
                    st_state = plain_state
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
                    f"    Analysis: {ev.get('analysis', 'N/A')[:limits.get('max')]}\n"
                    f"    Strategy: {ev.get('next_strategy', 'N/A')[:limits.get('max')]}"
                )
            prev_eval_section = "\n".join(eval_lines)
        
        prompt = build_main_evaluation_prompt(
            task=task,
            subtasks=subtasks,
            prev_eval_section=prev_eval_section,
            subtasks_with_status=execution_results,
        )
        
        print(f"\n   🤖 [AI Decision Point 2: Main Task Evaluation]")

        # Switch to evaluation model if configured
        original_model = client.provider.model if hasattr(client, 'provider') and client.provider else None
        eval_model = self.model_roles.get('evaluation')
        if eval_model and original_model and eval_model != original_model:
            client.provider.set_model(eval_model)

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
            print(f"      Analysis: {evaluation.get('analysis', 'N/A')[:limits.get('log_promptlike_preview')]}")
            # Append response to log AFTER AI returns
            if conv_logger:
                import json
                response_for_log = client.last_full_log or json.dumps(evaluation, indent=2, ensure_ascii=False)
                conv_logger.log_nested_response(
                    task_id=str(task['id']),
                    task_name=task['name'],
                    response=response_for_log,
                    call_type="main_task_evaluation",
                    round_num=round_num,
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

