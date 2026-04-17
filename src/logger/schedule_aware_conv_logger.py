
from logger.conversation_logger import ConversationLogger


class ScheduleAwareConvLogger:
    """Wrapper around ConversationLogger that prefixes log filenames with schedule round.

    In AI scheduling mode, log files are named with a ``schedule_N_`` prefix
    to distinguish logs from different scheduling rounds of the same task.

    Expected naming (per DESIGN.md §4.5):
        - ``schedule_1_task_1.1_round_1.1.md``
        - ``schedule_1_failure_analysis_1.1_round_1.1.md``
        - ``schedule_1_main_task_evaluation_round_1.md``

    The ``subtask_X/`` subdirectory names are **not** modified — only the
    filenames inside them receive the ``schedule_N_`` prefix.

    This wrapper intercepts calls to the underlying ConversationLogger and
    passes a ``filename_prefix`` so that the schedule round appears at the
    very start of each filename, while task_id and parent_task_id remain
    unchanged (keeping task IDs at most two levels in filenames).
    """

    def __init__(self, inner: 'ConversationLogger', schedule_round: int):
        self._inner = inner
        self._schedule_round = schedule_round
        self._prefix = f"schedule_{schedule_round}"

    # ------------------------------------------------------------------
    # Nested task registration — directory uses original task_id
    # ------------------------------------------------------------------

    def register_nested_task(self, task_id: str, task_name: str, subtask_ids: list):
        # Register with original IDs so subtask_X/ directory is unchanged
        self._inner.register_nested_task(task_id, task_name, subtask_ids)

    # ------------------------------------------------------------------
    # Task conversation logging — filename gets schedule prefix
    # ------------------------------------------------------------------

    def log_prompt(self, task_id: str, task_name: str, prompt: str,
                   attempt, parent_task_id=None, metadata=None,
                   system_prompt=None):
        self._inner.log_prompt(
            task_id=task_id,
            task_name=task_name,
            prompt=prompt,
            attempt=attempt,
            parent_task_id=parent_task_id,
            metadata=metadata,
            system_prompt=system_prompt,
            filename_prefix=self._prefix,
        )

    def log_response(self, task_id: str, response: str,
                     parent_task_id=None, attempt=None):
        self._inner.log_response(
            task_id=task_id,
            response=response,
            parent_task_id=parent_task_id,
            attempt=attempt,
            filename_prefix=self._prefix,
        )

    def log_conversation(self, task_id: str, task_name: str, prompt: str,
                         response: str, attempt, parent_task_id=None,
                         metadata=None):
        self.log_prompt(task_id, task_name, prompt, attempt, parent_task_id, metadata)
        self.log_response(task_id, response, parent_task_id, attempt=attempt)

    # ------------------------------------------------------------------
    # Nested / Looping task AI decision logging
    # ------------------------------------------------------------------

    def log_nested_prompt(self, task_id: str, task_name: str, call_type: str,
                          prompt: str, round_num, failed_subtask_id=None):
        self._inner.log_nested_prompt(
            task_id=task_id,
            task_name=task_name,
            call_type=call_type,
            prompt=prompt,
            round_num=round_num,
            failed_subtask_id=failed_subtask_id,
            filename_prefix=self._prefix,
        )

    def log_nested_response(self, task_id: str, task_name: str, response,
                            call_type=None, round_num=None,
                            failed_subtask_id=None):
        self._inner.log_nested_response(
            task_id=task_id,
            task_name=task_name,
            response=response,
            call_type=call_type,
            round_num=round_num,
            failed_subtask_id=failed_subtask_id,
            filename_prefix=self._prefix,
        )

    def log_nested_task_ai_call(self, task_id: str, task_name: str,
                                call_type: str, prompt: str, response: str,
                                round_num: int, metadata=None,
                                failed_subtask_id=None):
        self.log_nested_prompt(
            task_id, task_name, call_type, prompt, round_num,
            failed_subtask_id=failed_subtask_id,
        )
        self.log_nested_response(
            task_id, task_name, response,
            call_type=call_type,
            round_num=round_num,
            failed_subtask_id=failed_subtask_id,
        )

    # ------------------------------------------------------------------
    # Index & finalize — pass through with original IDs
    # ------------------------------------------------------------------

    def build_index_file(self, task_id: str):
        self._inner.build_index_file(task_id)

    def finalize(self):
        self._inner.finalize()
