"""AI Orchestrator Mixin - AI-driven task scheduling logic.

This mixin provides the AI scheduling methods which are mixed into
``TodoOrchestrator``:
- ``run_ai_scheduled``          — main AI scheduling loop
- ``_get_scheduler_decision``   — call AI to get next task decision
- ``_parse_scheduler_response`` — extract JSON from AI response
- ``_execute_scheduled_task``   — execute a task within AI scheduling context
- ``_build_scheduled_task``     — build schedule-round-prefixed task dict
- ``_prefix_subtask_ids``       — recursively prefix subtask IDs
- ``_save_task_response_result``— save task response for type=response tasks
- ``_validate_ai_orchestrator`` — validate ai_orchestrator config section

It relies on attributes and helper methods defined on the host class
(TodoOrchestrator), such as ``self.todos``, ``self.state_manager``,
``self.provider``, ``self.model_roles``, ``self.conv_logger``,
``self.session_dir``, ``self.simple_executor``, ``self.nested_executor``,
``self.looping_executor``, ``self._get_latest_description``, ``reload_todos``.
"""

import copy
import glob
import json
import os
import re
import time
import logging

from ai_client import AICallError, BashTimeoutError, SessionTimeoutError, StreamTimeoutError, RateLimitError
from logger import ScheduleAwareConvLogger
from state_manager import StateManager
from orchestrator.orchestrator_common import (
    ConfigError,
    ExecutionError,
    create_ai_client,
    load_orchestrator_config,
)
from prompts.scheduler import (
    build_scheduler_prompt,
    save_response_result,
    SCHEDULER_SYSTEM_PROMPT,
    _get_response_result_path,
)
from task_executor import SubtaskExecutor
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)


class AISchedulerMixin:
    """Mixin that provides AI-driven task scheduling logic.

    Must be mixed into a class that provides the following attributes/methods:
    - ``self.todos: list``
    - ``self.ai_orchestrator: dict``
    - ``self.state_manager: StateManager``
    - ``self.provider: AIProvider``
    - ``self.model_roles: dict``
    - ``self.conv_logger: ConversationLogger``
    - ``self.session_dir: str``
    - ``self.workspace: str``
    - ``self.timeout: int``
    - ``self.bash_timeout: int``
    - ``self.use_cli: bool``
    - ``self.backoff_max_wait: int``
    - ``self.todos_file: str``
    - ``self.simple_executor``
    - ``self.nested_executor``
    - ``self.looping_executor``
    - ``self._get_latest_description() -> str``
    - ``self.reload_todos()``
    """

    def _validate_ai_orchestrator(self, ai_orch: dict, tasks: list) -> dict:
        """Validate and normalize the ai_orchestrator configuration.

        Args:
            ai_orch: Raw ai_orchestrator dict from todos.yaml.
            tasks: List of task configuration dicts.

        Returns:
            Normalized ai_orchestrator dict.

        Raises:
            ConfigError: If validation fails.
        """
        if not isinstance(ai_orch, dict):
            raise ConfigError("'ai_orchestrator' must be a dict")

        # strategy is required
        strategy = ai_orch.get('strategy')
        if not strategy or not isinstance(strategy, str):
            raise ConfigError("'ai_orchestrator.strategy' is required and must be a string")

        # max_rounds is optional, default 50
        max_rounds = ai_orch.get('max_rounds', 50)
        if not isinstance(max_rounds, int) or max_rounds < 1:
            raise ConfigError("'ai_orchestrator.max_rounds' must be a positive integer")

        # stop_condition is optional
        stop_condition = ai_orch.get('stop_condition', '')
        if stop_condition and not isinstance(stop_condition, str):
            raise ConfigError("'ai_orchestrator.stop_condition' must be a string")

        # Validate last_result
        last_result = ai_orch.get('last_result', {})
        if not isinstance(last_result, dict):
            raise ConfigError("'ai_orchestrator.last_result' must be a dict")

        # Build set of valid task IDs
        valid_task_ids = {str(t['id']) for t in tasks}

        normalized_last_result = {}
        for tid_key, lr_config in last_result.items():
            tid_str = str(tid_key)
            if tid_str not in valid_task_ids:
                raise ConfigError(
                    f"'ai_orchestrator.last_result' references non-existent task_id: {tid_str}"
                )
            if not isinstance(lr_config, dict):
                raise ConfigError(
                    f"'ai_orchestrator.last_result.{tid_str}' must be a dict"
                )

            lr_type = lr_config.get('type')
            if lr_type not in ('none', 'response', 'file'):
                raise ConfigError(
                    f"'ai_orchestrator.last_result.{tid_str}.type' must be "
                    f"'none', 'response', or 'file' (got: {lr_type!r})"
                )

            if lr_type == 'file':
                path = lr_config.get('path')
                if path is None:
                    raise ConfigError(
                        f"'ai_orchestrator.last_result.{tid_str}.path' is required "
                        f"when type='file'"
                    )
                # Validate path: can be string or list of strings
                if isinstance(path, str):
                    if not os.path.isabs(path):
                        raise ConfigError(
                            f"'ai_orchestrator.last_result.{tid_str}.path' must be "
                            f"an absolute path (got: {path!r})"
                        )
                elif isinstance(path, list):
                    if not path:
                        raise ConfigError(
                            f"'ai_orchestrator.last_result.{tid_str}.path' list must "
                            f"not be empty"
                        )
                    for i, p in enumerate(path):
                        if not isinstance(p, str) or not os.path.isabs(p):
                            raise ConfigError(
                                f"'ai_orchestrator.last_result.{tid_str}.path[{i}]' "
                                f"must be an absolute path string (got: {p!r})"
                            )
                else:
                    raise ConfigError(
                        f"'ai_orchestrator.last_result.{tid_str}.path' must be "
                        f"a string or list of strings"
                    )

            normalized_last_result[tid_str] = lr_config

        # max_attempts is optional, overrides config.yaml scheduler_decision_max_retries
        ai_max_attempts = ai_orch.get('max_attempts')
        if ai_max_attempts is not None:
            if not isinstance(ai_max_attempts, int) or ai_max_attempts < 1:
                raise ConfigError("'ai_orchestrator.max_attempts' must be a positive integer")

        # Ensure all tasks have a description for AI scheduling prompts.
        # If missing, fall back to the task name.
        for task in tasks:
            if not task.get('description'):
                task['description'] = task.get('name', f"Task {task.get('id', '?')}")

        result = {
            'strategy': strategy,
            'max_rounds': max_rounds,
            'stop_condition': stop_condition or '',
            'last_result': normalized_last_result,
        }
        if ai_max_attempts is not None:
            result['max_attempts'] = ai_max_attempts
        return result

    def run_ai_scheduled(self) -> dict:
        """Run tasks using AI-driven scheduling.

        Instead of executing tasks in linear order, an AI scheduler
        decides which task to execute next (or stop) based on the
        current state, execution history, and the user-defined strategy.

        Returns:
            dict: Execution results summary.
        """
        ai_orch = self.ai_orchestrator
        if not ai_orch:
            raise ConfigError("run_ai_scheduled called but ai_orchestrator is not configured")

        # Populate ai_task_ids on the provider for sequential test strategy.
        # This must happen before the scheduling loop so that TestProvider
        # knows the task order for auto-generated scheduler decisions.
        from ai_client.ai_providers import TestProvider
        if isinstance(self.provider, TestProvider) and self.provider.ai_strategy:
            self.provider.ai_task_ids = [str(t['id']) for t in self.todos]
            logger.info(
                f"Set TestProvider.ai_task_ids = {self.provider.ai_task_ids} "
                f"(ai_strategy={self.provider.ai_strategy})"
            )

        config = load_orchestrator_config()
        scheduler_history_limit = config.get('scheduler_history_limit', DEFAULTS['scheduler_history_limit'])
        scheduler_decision_max_retries = config.get('scheduler_decision_max_retries', DEFAULTS['scheduler_decision_max_retries'])
        scheduler_max_session_retries = config.get('scheduler_max_session_retries', DEFAULTS['scheduler_max_session_retries'])
        scheduler_overtime_rounds = config.get('scheduler_overtime_rounds', DEFAULTS['scheduler_overtime_rounds'])

        strategy = ai_orch['strategy']
        max_rounds = ai_orch['max_rounds']
        stop_condition = ai_orch['stop_condition']
        last_result_config = ai_orch['last_result']

        # Override scheduler_decision_max_retries if ai_orchestrator specifies max_attempts
        if 'max_attempts' in ai_orch:
            scheduler_decision_max_retries = ai_orch['max_attempts']
            logger.info(f"AI orchestrator overriding scheduler_decision_max_retries to {scheduler_decision_max_retries}")

        start_time = time.time()

        # ── Initialize or restore orchestrator state ──────────────
        orch_state = self.state_manager.get_orchestrator_state()
        if orch_state is None:
            # Fresh start — but check for conflicting linear-mode state
            existing_tasks = self.state_manager.state.get("tasks", {})
            # Exclude round-scoped keys (contain "@") — they are subtask bookkeeping
            top_level_tasks = {
                k: v for k, v in existing_tasks.items()
                if StateManager.ROUND_SEP not in k
            }
            if top_level_tasks:
                raise ConfigError(
                    "Cannot run in AI orchestrator mode: existing linear-mode task "
                    "state found (tasks with progress but no orchestrator state). "
                    "Use --reset to clear state before switching modes."
                )

            orch_state = {
                'mode': 'ai',
                'current_round': 0,
                'max_rounds': max_rounds,
                'status': 'in_progress',
                'session_id': '',
                'schedule_history': [],
                'task_execution_counts': {},
            }
            self.state_manager.save_orchestrator_state(orch_state)
        else:
            # Resuming — check if already done
            if orch_state.get('status') in ('completed', 'stopped'):
                # Check if new tasks were added (Ideas Watcher restart)
                existing_ids = set(orch_state.get('task_execution_counts', {}).keys())
                current_ids = {str(t['id']) for t in self.todos}
                new_ids = current_ids - existing_ids
                if new_ids:
                    print(f"🔄 New tasks detected ({', '.join(sorted(new_ids))}), restarting scheduler...")
                    orch_state['status'] = 'in_progress'
                    self.state_manager.save_orchestrator_state(orch_state)
                else:
                    print(f"✅ AI Orchestrator has already {orch_state['status']}.")
                    return {
                        "total_tasks": 0, "successful_tasks": 0,
                        "failed_tasks": 0, "results": {},
                    }

        current_round = orch_state.get('current_round', 0)
        schedule_history = orch_state.get('schedule_history', [])
        task_execution_counts = orch_state.get('task_execution_counts', {})

        # Ensure all task IDs are in the counts dict
        for task in self.todos:
            tid = str(task['id'])
            if tid not in task_execution_counts:
                task_execution_counts[tid] = 0

        # ── Check if last round's task was interrupted ────────────
        if schedule_history:
            last_entry = schedule_history[-1]
            if last_entry.get('result') is None:
                # Last round's task was not completed — check if we need to resume it
                last_task_id = str(last_entry.get('task_id', ''))
                last_task = next((t for t in self.todos if str(t['id']) == last_task_id), None)
                if last_task:
                    # Check the task's state key for this schedule round
                    sched_round = last_entry.get('round', current_round)
                    task_sk = f"{sched_round}.{last_task_id}"
                    task_state = self.state_manager.get_task_state(task_sk)
                    if task_state.get('status') == 'in_progress':
                        print(f"\n🔄 Resuming interrupted task {last_task_id} from schedule round {sched_round}...")
                        success = self._execute_scheduled_task(
                            last_task, sched_round, task_execution_counts
                        )
                        last_entry['result'] = 'success' if success else 'failed'
                        last_entry['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S")
                        task_execution_counts[last_task_id] = task_execution_counts.get(last_task_id, 0) + 1
                        orch_state['task_execution_counts'] = task_execution_counts
                        self.state_manager.save_orchestrator_state(orch_state)
                        self._append_schedule_history_file(last_entry)

        # ── Orphan recovery: detect running background tasks from a ──
        # ── round that has no history entry (non-graceful kill)      ──
        # If current_round is ahead of the last history entry's round,
        # it means the process was killed after current_round was saved
        # but before the history entry was created.  Check for orphaned
        # signal files from that round.
        last_history_round = schedule_history[-1]['round'] if schedule_history else 0
        if current_round > last_history_round:
            orphan_round = self._detect_orphan_signal_file(current_round, last_history_round)
            if orphan_round is not None:
                orphan_sched_round, orphan_task_id = orphan_round
                orphan_task = next(
                    (t for t in self.todos if str(t['id']) == orphan_task_id), None
                )
                if orphan_task:
                    print(f"\n🔄 Detected running background task from schedule round {orphan_sched_round}, resuming...")
                    # Create a synthetic history entry for the orphaned round
                    history_entry = {
                        'round': orphan_sched_round,
                        'task_id': orphan_task_id,
                        'task_name': orphan_task['name'],
                        'session_id': '',
                        'result': None,
                        'reasoning': '(recovered from orphaned background task)',
                        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    schedule_history.append(history_entry)
                    orch_state['schedule_history'] = schedule_history
                    self.state_manager.save_orchestrator_state(orch_state)

                    success = self._execute_scheduled_task(
                        orphan_task, orphan_sched_round, task_execution_counts
                    )
                    history_entry['result'] = 'success' if success else 'failed'
                    history_entry['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S")
                    task_execution_counts[orphan_task_id] = task_execution_counts.get(orphan_task_id, 0) + 1
                    orch_state['task_execution_counts'] = task_execution_counts
                    self.state_manager.save_orchestrator_state(orch_state)
                    self._append_schedule_history_file(history_entry)

        print(f"{'=' * 60}")
        print(f"  AutoAgent (AI Orchestrator Mode)")
        print(f"  Tasks available: {len(self.todos)}")
        print(f"  Max rounds: {max_rounds}")
        print(f"  Config: {self.todos_file}")
        print(f"  Provider: {self.provider.name}")
        print(f"  Model: {self.provider.model}")
        print(f"  Scheduler model: {self.model_roles.get('scheduler', self.model_roles['default'])}")
        print(f"{'=' * 60}")

        # ── Main scheduling loop ──────────────────────────────────
        results = {}

        while current_round < max_rounds + scheduler_overtime_rounds:
            current_round += 1

            print(f"\n{'─' * 60}")
            print(f"🤖 Schedule Round {current_round}/{max_rounds}")
            print(f"{'─' * 60}")

            # ── Reload todos (Ideas Watcher may have added new tasks) ──
            self.reload_todos()
            # Re-validate ai_orchestrator after reload
            if self.ai_orchestrator:
                last_result_config = self.ai_orchestrator['last_result']
            # Ensure new tasks are in counts
            for task in self.todos:
                tid = str(task['id'])
                if tid not in task_execution_counts:
                    task_execution_counts[tid] = 0

            # ── Get AI scheduling decision ────────────────────────
            project_desc = self._get_latest_description()

            decision = self._get_scheduler_decision(
                current_round=current_round,
                max_rounds=max_rounds,
                project_description=project_desc,
                strategy=strategy,
                stop_condition=stop_condition,
                last_result_config=last_result_config,
                task_execution_counts=task_execution_counts,
                schedule_history=schedule_history,
                scheduler_history_limit=scheduler_history_limit,
                max_retries=scheduler_decision_max_retries,
                max_session_retries=scheduler_max_session_retries,
                orch_state=orch_state,
            )

            if decision is None:
                # Failed to get a valid decision after retries
                print(f"\n❌ Scheduler failed to produce a valid decision. Stopping.")
                orch_state['current_round'] = current_round
                orch_state['status'] = 'stopped'
                self.state_manager.save_orchestrator_state(orch_state)
                break

            action = decision.get('action')
            reasoning = decision.get('reasoning', '')

            if action == 'stop':
                print(f"\n🛑 Scheduler decided to stop: {reasoning}")
                stop_entry = {
                    'round': current_round,
                    'task_id': None,
                    'task_name': None,
                    'result': 'stopped',
                    'reasoning': reasoning,
                    'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                schedule_history.append(stop_entry)
                orch_state['current_round'] = current_round
                orch_state['status'] = 'stopped'
                orch_state['schedule_history'] = schedule_history
                self.state_manager.save_orchestrator_state(orch_state)
                self._append_schedule_history_file(stop_entry)
                break

            # action == 'execute'
            selected_task_id = str(decision.get('task_id'))
            selected_task = next(
                (t for t in self.todos if str(t['id']) == selected_task_id), None
            )
            if not selected_task:
                print(f"\n❌ Scheduler selected non-existent task {selected_task_id}. Stopping.")
                orch_state['current_round'] = current_round
                orch_state['status'] = 'stopped'
                self.state_manager.save_orchestrator_state(orch_state)
                break

            print(f"\n📋 Scheduler selected: Task {selected_task_id} ({selected_task['name']})")
            print(f"   Reasoning: {reasoning}")

            # Record the scheduling decision (result=None until task completes)
            # Also persist current_round here (not earlier) so that if the
            # process is killed during the scheduler AI call, current_round
            # won't be ahead of the history — enabling correct resume.
            history_entry = {
                'round': current_round,
                'task_id': selected_task_id,
                'task_name': selected_task['name'],
                'session_id': orch_state.get('session_id', ''),
                'result': None,
                'reasoning': reasoning,
                'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            schedule_history.append(history_entry)
            orch_state['current_round'] = current_round
            orch_state['schedule_history'] = schedule_history
            self.state_manager.save_orchestrator_state(orch_state)

            # ── Execute the selected task ─────────────────────────
            try:
                success = self._execute_scheduled_task(
                    selected_task, current_round, task_execution_counts
                )
            except KeyboardInterrupt:
                # Save state and re-raise
                history_entry['result'] = None  # Mark as incomplete
                orch_state['schedule_history'] = schedule_history
                orch_state['task_execution_counts'] = task_execution_counts
                self.state_manager.save_orchestrator_state(orch_state)
                raise

            # Update history entry with result
            history_entry['result'] = 'success' if success else 'failed'
            history_entry['timestamp'] = time.strftime("%Y-%m-%d %H:%M:%S")
            task_execution_counts[selected_task_id] = task_execution_counts.get(selected_task_id, 0) + 1
            orch_state['task_execution_counts'] = task_execution_counts
            orch_state['schedule_history'] = schedule_history
            self.state_manager.save_orchestrator_state(orch_state)
            self._append_schedule_history_file(history_entry)

            results[f"round_{current_round}"] = success

            if success:
                print(f"\n✅ Task {selected_task_id} completed successfully!")
            else:
                print(f"\n❌ Task {selected_task_id} failed!")

        else:
            # Reached hard limit (max_rounds + overtime)
            print(f"\n⚠️  Reached maximum scheduling rounds ({max_rounds} + {scheduler_overtime_rounds} overtime)")
            orch_state['status'] = 'completed'
            self.state_manager.save_orchestrator_state(orch_state)

        duration = time.time() - start_time
        successful = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)

        # ── Per-task breakdown from schedule_history ──────────────
        task_stats = {}  # task_id -> {'name': str, 'success': int, 'failed': int}
        for entry in schedule_history:
            tid = entry.get('task_id')
            if tid is None:
                continue  # skip 'stop' entries
            result = entry.get('result')
            if result not in ('success', 'failed'):
                continue  # skip incomplete entries
            if tid not in task_stats:
                task_name = entry.get('task_name', f'Task {tid}')
                task_stats[tid] = {'name': task_name, 'success': 0, 'failed': 0}
            if result == 'success':
                task_stats[tid]['success'] += 1
            else:
                task_stats[tid]['failed'] += 1

        print(f"\n{'=' * 60}")
        print(f"  AI Orchestrator Summary")
        print(f"  Rounds: {current_round}/{max_rounds} | ✅ Success: {successful} | ❌ Failed: {failed}")
        for tid in sorted(task_stats.keys(), key=lambda x: int(x) if x.isdigit() else x):
            stats = task_stats[tid]
            total = stats['success'] + stats['failed']
            print(f"  Task {tid} | Total: {total} | ✅ Success: {stats['success']} | ❌ Failed: {stats['failed']}")
        print(f"  Duration: {duration:.1f}s")
        print(f"{'=' * 60}")

        return {
            "total_tasks": len(results),
            "successful_tasks": successful,
            "failed_tasks": failed,
            "results": results,
            "task_stats": task_stats,
            "duration": duration,
        }

    def _append_schedule_history_file(self, entry: dict) -> None:
        """Append a formatted schedule history entry to schedule_history.txt.

        The file is located at the root of the session (log) directory,
        providing a persistent, human-readable record of all scheduling
        decisions across the entire run.
        """
        history_file = os.path.join(self.session_dir, "schedule_history.txt")
        rnd = entry.get('round', '?')
        task_id = entry.get('task_id', '-')
        task_name = entry.get('task_name', '-')
        result = entry.get('result', 'unknown')
        reasoning = entry.get('reasoning', '')
        timestamp = entry.get('timestamp', '')

        if result == 'success':
            marker = '✅'
        elif result == 'failed':
            marker = '❌'
        elif result == 'stopped':
            marker = '🛑'
        else:
            marker = '⏳'

        if task_id is None:
            # Stop decision
            line = f"[{timestamp}] Round {rnd}: {marker} STOP | Reasoning: {reasoning}\n"
        else:
            line = f"[{timestamp}] Round {rnd}: {marker} Task {task_id} ({task_name}) | Reasoning: {reasoning}\n"

        try:
            with open(history_file, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError as e:
            logger.warning(f"Failed to write schedule_history.txt: {e}")

    def _get_scheduler_decision(
        self,
        current_round: int,
        max_rounds: int,
        project_description: str,
        strategy: str,
        stop_condition: str,
        last_result_config: dict,
        task_execution_counts: dict,
        schedule_history: list,
        scheduler_history_limit: int,
        max_retries: int,
        max_session_retries: int,
        orch_state: dict,
    ) -> dict | None:
        """Call the AI scheduler to get the next scheduling decision.

        Uses a two-level retry strategy:

        **Level-1 (in-session):** On invalid JSON, invalid action, invalid
        task_id, BashTimeoutError, or StreamTimeoutError, retry within the
        same AI session up to *max_retries* times.

        **Level-2 (session-reset):** When level-1 retries are exhausted, or
        on SessionTimeoutError / other ``AICallError``, create a fresh AI
        session and resend the full prompt.  Up to *max_session_retries*
        session resets are allowed.

        Returns:
            Parsed decision dict, or ``None`` if all retries exhausted.
        """
        scheduler_model = self.model_roles.get('scheduler', self.model_roles['default'])
        original_model = self.provider.model
        self.provider.set_model(scheduler_model)

        valid_task_ids = {str(t['id']) for t in self.todos}

        # Build the scheduler prompt (reused across session resets)
        prompt = build_scheduler_prompt(
            current_round=current_round,
            max_rounds=max_rounds,
            project_description=project_description,
            strategy=strategy,
            stop_condition=stop_condition,
            tasks=self.todos,
            task_execution_counts=task_execution_counts,
            schedule_history=schedule_history,
            last_result_config=last_result_config,
            session_dir=self.session_dir,
            scheduler_history_limit=scheduler_history_limit,
        )

        # Log the scheduler prompt (once per scheduling round)
        if self.conv_logger:
            self.conv_logger.log_scheduler_prompt(
                schedule_round=current_round,
                prompt=prompt,
                system_prompt=SCHEDULER_SYSTEM_PROMPT,
            )

        decision = None

        # ── Level-2 loop: session-reset retries ───────────────────
        for session_attempt in range(max_session_retries + 1):
            if session_attempt > 0:
                logger.info(
                    f"Scheduler round {current_round}: session reset "
                    f"(session attempt {session_attempt + 1}/{max_session_retries + 1})"
                )
                print(f"   🔄 Scheduler session reset (attempt {session_attempt + 1}/{max_session_retries + 1})")

            # Create a fresh AI client for this session attempt
            context_id = f"scheduler_round_{current_round}"
            if session_attempt > 0:
                context_id = f"scheduler_round_{current_round}_s{session_attempt}"
            client = create_ai_client(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
                use_cli=self.use_cli,
                backoff_max_wait=self.backoff_max_wait,
                session_dir=self.session_dir,
            )

            # Resume previous scheduler session only on the first attempt
            if session_attempt == 0:
                saved_session_id = orch_state.get('session_id', '')
                if saved_session_id:
                    client.resume_session(saved_session_id)
                    logger.info(f"Resuming scheduler session: {saved_session_id}")

            # Track session_id changes
            def on_session_id_changed(new_session_id: str):
                orch_state['session_id'] = new_session_id
                self.state_manager.save_orchestrator_state(orch_state)

            client._on_session_id_changed = on_session_id_changed

            # Whether to escalate to level-2 (break inner loop, continue outer)
            _escalate_to_session_reset = False

            # ── Level-1 loop: in-session retries ──────────────────
            for retry in range(max_retries + 1):
                try:
                    if retry == 0:
                        response = client.ask(
                            prompt,
                            system_prompt=SCHEDULER_SYSTEM_PROMPT,
                        )
                    else:
                        # Retry with error feedback in the same session
                        response = client.ask(
                            f"Your previous response was invalid: {error_msg}\n"
                            f"Please respond with a valid JSON object.",
                            system_prompt=SCHEDULER_SYSTEM_PROMPT,
                        )

                    # Log the response
                    if self.conv_logger:
                        self.conv_logger.log_scheduler_response(
                            schedule_round=current_round,
                            response=response,
                        )

                    # Parse JSON from response
                    decision = self._parse_scheduler_response(response)
                    if decision is None:
                        error_msg = "Could not parse a valid JSON decision from your response."
                        logger.warning(
                            f"Scheduler round {current_round}: invalid JSON "
                            f"(L1 retry {retry}, session attempt {session_attempt})"
                        )
                        continue

                    action = decision.get('action')
                    if action not in ('execute', 'stop'):
                        error_msg = f"Invalid action: {action!r}. Must be 'execute' or 'stop'."
                        decision = None
                        continue

                    if action == 'execute':
                        task_id = str(decision.get('task_id', ''))
                        if task_id not in valid_task_ids:
                            error_msg = (
                                f"Invalid task_id: {task_id!r}. "
                                f"Valid task IDs: {', '.join(sorted(valid_task_ids))}"
                            )
                            decision = None
                            continue

                    # Valid decision — break both loops
                    break

                except (BashTimeoutError, StreamTimeoutError) as e:
                    # Session still alive — retry in-session (level-1)
                    logger.warning(
                        f"Scheduler round {current_round}: {type(e).__name__} "
                        f"(L1 retry {retry}, session attempt {session_attempt}): {e}"
                    )
                    timeout_type = "Bash" if isinstance(e, BashTimeoutError) else "Stream"
                    print(f"   ⏰ {timeout_type} timeout — retrying in same session")
                    error_msg = (
                        f"Your previous response was interrupted by a {timeout_type.lower()} timeout. "
                        f"Please respond with a valid JSON scheduling decision."
                    )
                    # Log the timeout as a response
                    if self.conv_logger:
                        self.conv_logger.log_scheduler_response(
                            schedule_round=current_round,
                            response=f"[{timeout_type} Timeout]: {e}",
                        )
                    # Continue to next level-1 retry (the error_msg will be
                    # sent as the prompt on the next iteration, but we need
                    # to increment retry first — the for-loop handles that).
                    # However, since we caught the exception, the for-loop
                    # will naturally advance to the next iteration.
                    continue

                except SessionTimeoutError as e:
                    # Session killed — must escalate to level-2 (session reset)
                    logger.warning(
                        f"Scheduler round {current_round}: SessionTimeoutError "
                        f"(session attempt {session_attempt}): {e}"
                    )
                    print(f"   ⏰ Session timeout — will reset session")
                    if self.conv_logger:
                        self.conv_logger.log_scheduler_response(
                            schedule_round=current_round,
                            response=f"[Session Timeout]: {e}",
                        )
                    decision = None
                    _escalate_to_session_reset = True
                    break  # Break level-1 loop

                except RateLimitError as e:
                    # Rate-limit (429) / server error (503) — transient,
                    # retry in same session (backoff handles the wait).
                    logger.warning(
                        f"Scheduler round {current_round}: RateLimitError "
                        f"(L1 retry {retry}, session attempt {session_attempt}): {e}"
                    )
                    print(f"   ⚠️ Rate-limit/server error — retrying (attempt NOT consumed)")
                    if self.conv_logger:
                        self.conv_logger.log_scheduler_response(
                            schedule_round=current_round,
                            response=f"[Rate Limit]: {e}",
                        )
                    error_msg = "CLI/SDK Rate-limited. Please try again and respond with a valid JSON scheduling decision."
                    continue  # Stay in level-1 loop

                except AICallError as e:
                    # Other AI errors — escalate to level-2 (session reset)
                    logger.error(
                        f"Scheduler round {current_round}: AICallError "
                        f"(session attempt {session_attempt}): {e}"
                    )
                    print(f"   ❌ AI call error: {e} — will reset session")
                    if self.conv_logger:
                        self.conv_logger.log_scheduler_response(
                            schedule_round=current_round,
                            response=f"[AI Call Error]: {e}",
                        )
                    decision = None
                    _escalate_to_session_reset = True
                    break  # Break level-1 loop

            # Check if we got a valid decision
            if decision is not None:
                break  # Break level-2 loop — success

            # If level-1 exhausted without escalation flag, set it
            if not _escalate_to_session_reset:
                logger.warning(
                    f"Scheduler round {current_round}: level-1 retries exhausted "
                    f"(session attempt {session_attempt}) — escalating to session reset"
                )
                print(f"   ⚠️ In-session retries exhausted — will reset session")
                _escalate_to_session_reset = True

            # Continue to next session attempt (level-2 loop will create fresh client)

        # Clear scheduler session_id for next round (each round gets fresh session)
        orch_state['session_id'] = ''
        self.state_manager.save_orchestrator_state(orch_state)

        # Restore original model
        self.provider.set_model(original_model)

        return decision

    @staticmethod
    def _parse_scheduler_response(response: str) -> dict | None:
        """Extract a JSON decision object from the scheduler's response.

        The response may contain markdown code fences or extra text around
        the JSON. This method tries several strategies to extract the JSON.

        Returns:
            Parsed dict, or None if parsing fails.
        """
        if not response:
            return None

        # Strategy 1: Try parsing the entire response as JSON
        try:
            return json.loads(response.strip())
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: Extract JSON from markdown code fence
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except (json.JSONDecodeError, ValueError):
                pass

        # Strategy 3: Find the first { ... } block
        brace_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    def _execute_scheduled_task(
        self,
        task: dict,
        schedule_round: int,
        task_execution_counts: dict,
    ) -> bool:
        """Execute a task within the AI scheduling context.

        Creates a fresh AI client (new session) for the task. Uses
        schedule-round-prefixed task IDs for state isolation.

        Returns:
            True if the task completed successfully.
        """
        task_id = str(task['id'])
        task_type = task['type']

        # Build schedule-round-prefixed task ID for state isolation
        sched_task_id = f"{schedule_round}.{task_id}"

        # Switch model based on task's model field
        task_model_role = task.get('model', 'default')
        if task_model_role in self.model_roles:
            task_model = self.model_roles[task_model_role]
        else:
            task_model = task_model_role
        self.provider.set_model(task_model)

        # Create a new AIClient (fresh session — no reuse across schedule rounds)
        context_id = f"schedule_{schedule_round}_task_{task_id}"
        client = create_ai_client(
            provider=self.provider,
            workspace=self.workspace,
            timeout=self.timeout,
            bash_timeout=self.bash_timeout,
            context_id=context_id,
            use_cli=self.use_cli,
            backoff_max_wait=self.backoff_max_wait,
            session_dir=self.session_dir,
        )

        # Check if this task was interrupted and has a saved session_id
        task_state = self.state_manager.get_task_state(sched_task_id)
        saved_session_id = task_state.get("session_id", "")
        if saved_session_id:
            client.resume_session(saved_session_id)
            print(f"   🔄 Resuming session: {saved_session_id}")

        # Set up callback to save session_id
        def on_session_id_changed(new_session_id: str):
            self.state_manager.update_task_field(sched_task_id, "session_id", new_session_id)

        client._on_session_id_changed = on_session_id_changed

        # Record context info in state
        self.state_manager.mark_task_status(
            sched_task_id, "in_progress",
            context_id=context_id,
            context_created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Create a modified task dict with schedule-round-prefixed IDs
        # for subtasks (if nested/looping)
        scheduled_task = self._build_scheduled_task(task, schedule_round)

        try:
            task_description = self._get_latest_description()

            # Create a schedule-aware conv_logger wrapper
            sched_conv_logger = ScheduleAwareConvLogger(
                self.conv_logger, schedule_round
            ) if self.conv_logger else None

            if task_type == 'simple':
                success = self.simple_executor.execute(
                    scheduled_task, client, self.state_manager, is_subtask=False,
                    conv_logger=sched_conv_logger,
                    project_description=task_description,
                )
            elif task_type == 'nested':
                success = self.nested_executor.execute(
                    scheduled_task, client, self.state_manager,
                    conv_logger=sched_conv_logger,
                    project_description=task_description,
                )
            elif task_type == 'looping':
                success = self.looping_executor.execute(
                    scheduled_task, client, self.state_manager,
                    conv_logger=sched_conv_logger,
                    project_description=task_description,
                )
            elif task_type == 'long_running':
                lr_executor = SubtaskExecutor(
                    session_dir=self.session_dir,
                    model_roles=self.model_roles,
                    default_max_attempts=self.default_max_attempts,
                )
                result = lr_executor._execute_long_running_subtask(
                    scheduled_task, client, self.state_manager,
                    conv_logger=sched_conv_logger,
                    parent_task_id=None,
                    parent_context={
                        'project_description': task_description,
                    },
                )
                success = result.success
                # Store response_text for _save_task_response_result
                self._last_lr_response_text = getattr(result, 'response_text', '') or ''
            else:
                raise ConfigError(f"Unknown task type: {task_type}")

            # Save response result for type=response tasks
            self._save_task_response_result(task_id, task_type, success)

            # Update the schedule-round task state
            if success:
                self.state_manager.mark_task_status(
                    sched_task_id, "completed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
            else:
                self.state_manager.mark_task_status(
                    sched_task_id, "failed",
                    last_attempt=time.strftime("%Y-%m-%d %H:%M:%S"),
                )

            return success

        except KeyboardInterrupt:
            if client.session_id:
                self.state_manager.update_task_field(
                    sched_task_id, "session_id", client.session_id
                )
                self.state_manager.update_task_field(
                    sched_task_id, "interrupt_pending", True
                )
            raise
        except (ConfigError, ExecutionError, AICallError) as e:
            print(f"   ❌ Error: {e}")
            self.state_manager.mark_task_status(sched_task_id, "failed", error=str(e))
            return False

    @staticmethod
    def _build_scheduled_task(task: dict, schedule_round: int) -> dict:
        """Build a task dict with schedule-round-prefixed IDs.

        For simple tasks, the ID becomes ``{schedule_round}.{task_id}``.
        For nested/looping tasks, subtask IDs become
        ``{schedule_round}.{task_id}.{subtask_id_suffix}``.

        Each modified dict also receives a ``_display_id`` field that
        preserves the **original** (pre-prefix) ID.  Prompt builders
        should use ``_display_id`` so the AI never sees the internal
        three-level state key.
        """
        scheduled = copy.deepcopy(task)
        original_id = str(task['id'])
        scheduled['_display_id'] = original_id
        scheduled['id'] = f"{schedule_round}.{original_id}"

        # Prefix subtask IDs for nested/looping tasks
        if task['type'] in ('nested', 'looping'):
            subtasks = scheduled.get('subtasks', [])
            for st in subtasks:
                original_st_id = str(st['id'])
                st['_display_id'] = original_st_id
                # Original subtask ID is like "1.1", "1.2" etc.
                # Extract the suffix after the first dot
                parts = original_st_id.split('.', 1)
                if len(parts) == 2:
                    suffix = parts[1]
                else:
                    suffix = original_st_id
                st['id'] = f"{schedule_round}.{original_id}.{suffix}"

                # Recursively handle nested subtasks
                if st.get('type') in ('nested', 'looping'):
                    AISchedulerMixin._prefix_subtask_ids(st, schedule_round, original_id)

        return scheduled

    @staticmethod
    def _prefix_subtask_ids(task: dict, schedule_round: int, root_task_id: str):
        """Recursively prefix subtask IDs for deeply nested tasks."""
        subtasks = task.get('subtasks', [])
        for st in subtasks:
            original_st_id = str(st['id'])
            st['_display_id'] = original_st_id
            # Keep the relative structure but add schedule_round prefix
            parts = original_st_id.split('.', 1)
            if len(parts) == 2:
                st['id'] = f"{schedule_round}.{parts[0]}.{parts[1]}"
            if st.get('type') in ('nested', 'looping'):
                AISchedulerMixin._prefix_subtask_ids(st, schedule_round, root_task_id)

    def _save_task_response_result(self, task_id: str, task_type: str, success: bool):
        """Save the task's response to a result file if configured as type=response."""
        if not self.ai_orchestrator:
            return

        lr_config = self.ai_orchestrator['last_result'].get(task_id, {})
        if lr_config.get('type') != 'response':
            return

        # Get the last response text from the appropriate executor
        response_text = ""
        if task_type == 'simple':
            response_text = getattr(self.simple_executor, 'last_response_text', '')
        elif task_type in ('nested', 'looping'):
            # For nested/looping, get the last subtask's response
            # from the nested executor's subtask executor
            nested_exec = self.nested_executor if task_type == 'nested' else self.looping_executor
            subtask_exec = getattr(nested_exec, 'subtask_executor', None)
            if subtask_exec:
                simple_exec = getattr(subtask_exec, 'simple_executor', None)
                if simple_exec:
                    response_text = getattr(simple_exec, 'last_response_text', '')
        elif task_type == 'long_running':
            # For long_running tasks, response_text is stored by
            # _execute_scheduled_task after execution completes.
            response_text = getattr(self, '_last_lr_response_text', '')
            self._last_lr_response_text = ''  # Consume after use

        if response_text:
            from util.truncation_limits import limits
            save_response_result(
                task_id=task_id,
                response_text=response_text,
                session_dir=self.session_dir,
                max_length=limits.get('previous_subtask_summary'),
            )

    def _detect_orphan_signal_file(
        self, current_round: int, last_history_round: int
    ):
        """Detect orphaned signal files from rounds without history entries.

        When the process is killed non-gracefully after current_round is
        saved but before the history entry is persisted, there may be
        signal files from that round with status "starting" or "running"
        indicating a background task is still alive.

        Scans for signal files matching rounds between last_history_round+1
        and current_round (inclusive).

        Returns:
            A tuple (schedule_round, task_id) if an orphan is found,
            or None if no orphans detected.
        """
        lr_tasks_dir = os.path.join(self.session_dir, "lr_tasks")
        if not os.path.isdir(lr_tasks_dir):
            return None

        signal_files = glob.glob(os.path.join(lr_tasks_dir, "lr_*_signal.json"))

        for sf_path in signal_files:
            try:
                with open(sf_path, "r", encoding="utf-8") as f:
                    sig = json.load(f)
                sig_status = sig.get("status")
                if sig_status not in ("starting", "running"):
                    continue

                # Extract the task_id from the signal file name
                # Format: lr_{subtask_id}_signal.json
                basename = os.path.basename(sf_path)
                # Remove "lr_" prefix and "_signal.json" suffix
                subtask_id = basename[3:-12]  # "lr_" = 3 chars, "_signal.json" = 12 chars

                # Parse the schedule_round from the subtask_id
                # Format: "{schedule_round}.{task_id}" or "{schedule_round}.{task_id}.{suffix}"
                parts = subtask_id.split('.', 1)
                if len(parts) < 2:
                    continue
                try:
                    sched_round = int(parts[0])
                except (ValueError, TypeError):
                    continue

                # Check if this round is in the orphan range
                if last_history_round < sched_round <= current_round:
                    # Extract the original task_id (second part)
                    remaining = parts[1]
                    # remaining could be "3" or "3.1" (task_id or task_id.suffix)
                    task_id = remaining.split('.', 1)[0]
                    logger.info(
                        f"Orphan signal file detected: {basename} "
                        f"(round={sched_round}, task_id={task_id}, status={sig_status})"
                    )
                    return (sched_round, task_id)

            except Exception as e:
                logger.warning(f"Error reading signal file {sf_path}: {e}")
                continue

        return None
