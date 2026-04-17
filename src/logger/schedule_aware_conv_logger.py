
from logger.conversation_logger import ConversationLogger


class ScheduleAwareConvLogger:
    """Wrapper around ConversationLogger that prefixes log filenames with schedule round.

    In AI scheduling mode, task IDs are three-level ``X.Y.Z`` where ``X`` is
    the schedule round.  For log **filenames** the round is expressed as a
    ``schedule_X_`` prefix instead, so the task ID inside the filename drops
    back to two levels (``Y.Z``).

    Expected naming (per DESIGN.md §4.5)::

        conversations/
        ├── schedule_1_task_1.md              ← index file
        ├── subtask_1/                        ← directory uses 1-level ID (Y)
        │   ├── schedule_1_task_1.1_round_1.1.md
        │   ├── schedule_1_failure_analysis_1.3_round_1.1.md
        │   └── schedule_1_main_task_evaluation_round_1.md

    This wrapper:
    1. Strips the schedule-round prefix from every ``task_id`` and
       ``parent_task_id`` before forwarding to the inner logger.
    2. Passes ``filename_prefix="schedule_N"`` so the prefix appears at the
       very start of each filename.
    """

    def __init__(self, inner: 'ConversationLogger', schedule_round: int):
        self._inner = inner
        self._schedule_round = schedule_round
        self._prefix = f"schedule_{schedule_round}"

    # ------------------------------------------------------------------
    # ID stripping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_first_level(dotted_id: str) -> str:
        """Remove the first dotted level from *dotted_id*.

        ``"1.1.1"`` → ``"1.1"``  (3-level → 2-level)
        ``"1.1"``   → ``"1"``    (2-level → 1-level)
        ``"1"``     → ``"1"``    (already 1-level, unchanged)
        """
        parts = dotted_id.split('.', 1)
        return parts[1] if len(parts) == 2 else dotted_id

    def _task_id(self, task_id: str) -> str:
        """Strip schedule-round prefix from task_id for filename use."""
        return self._strip_first_level(task_id)

    def _parent_id(self, parent_task_id: str | None) -> str | None:
        """Strip schedule-round prefix from parent_task_id for directory use."""
        if parent_task_id is None:
            return None
        return self._strip_first_level(parent_task_id)

    # ------------------------------------------------------------------
    # Nested task registration
    # ------------------------------------------------------------------

    def register_nested_task(self, task_id: str, task_name: str, subtask_ids: list):
        # Strip schedule prefix so directory is subtask_Y/ not subtask_X.Y/
        self._inner.register_nested_task(
            self._task_id(task_id),
            task_name,
            [self._task_id(sid) for sid in subtask_ids],
            filename_prefix=self._prefix,
        )

    # ------------------------------------------------------------------
    # Task conversation logging
    # ------------------------------------------------------------------

    def log_prompt(self, task_id: str, task_name: str, prompt: str,
                   attempt, parent_task_id=None, metadata=None,
                   system_prompt=None):
        self._inner.log_prompt(
            task_id=self._task_id(task_id),
            task_name=task_name,
            prompt=prompt,
            attempt=attempt,
            parent_task_id=self._parent_id(parent_task_id),
            metadata=metadata,
            system_prompt=system_prompt,
            filename_prefix=self._prefix,
        )

    def log_response(self, task_id: str, response: str,
                     parent_task_id=None, attempt=None):
        self._inner.log_response(
            task_id=self._task_id(task_id),
            response=response,
            parent_task_id=self._parent_id(parent_task_id),
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
            task_id=self._task_id(task_id),
            task_name=task_name,
            call_type=call_type,
            prompt=prompt,
            round_num=round_num,
            failed_subtask_id=self._task_id(failed_subtask_id) if failed_subtask_id else None,
            filename_prefix=self._prefix,
        )

    def log_nested_response(self, task_id: str, task_name: str, response,
                            call_type=None, round_num=None,
                            failed_subtask_id=None):
        self._inner.log_nested_response(
            task_id=self._task_id(task_id),
            task_name=task_name,
            response=response,
            call_type=call_type,
            round_num=round_num,
            failed_subtask_id=self._task_id(failed_subtask_id) if failed_subtask_id else None,
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
    # Index & finalize
    # ------------------------------------------------------------------

    def build_index_file(self, task_id: str):
        # Strip schedule prefix and pass filename_prefix for the index file
        self._inner.build_index_file(self._task_id(task_id))

    def finalize(self):
        self._inner.finalize()
