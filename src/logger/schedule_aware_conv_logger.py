
from logger.conversation_logger import ConversationLogger


class ScheduleAwareConvLogger:
    """Wrapper around ConversationLogger that prefixes log filenames with schedule round.

    In AI scheduling mode, log files are named with a ``schedule_N_`` prefix
    to distinguish logs from different scheduling rounds of the same task.

    This wrapper intercepts calls to the underlying ConversationLogger and
    modifies the task_id and filenames to include the schedule round prefix.
    """

    def __init__(self, inner: 'ConversationLogger', schedule_round: int):
        self._inner = inner
        self._schedule_round = schedule_round
        self._prefix = f"schedule_{schedule_round}"

    def _prefixed_task_id(self, task_id: str) -> str:
        """Add schedule prefix to task_id for file naming."""
        return f"{self._prefix}_{task_id}"

    def _prefixed_parent_id(self, parent_task_id: str | None) -> str | None:
        """Add schedule prefix to parent_task_id for directory naming."""
        if parent_task_id is None:
            return None
        return f"{self._prefix}_{parent_task_id}"

    def register_nested_task(self, task_id: str, task_name: str, subtask_ids: list):
        self._inner.register_nested_task(
            self._prefixed_task_id(task_id), task_name,
            [self._prefixed_task_id(sid) for sid in subtask_ids],
        )

    def log_prompt(self, task_id: str, task_name: str, prompt: str,
                   attempt, parent_task_id=None, metadata=None,
                   system_prompt=None):
        self._inner.log_prompt(
            task_id=self._prefixed_task_id(task_id),
            task_name=task_name,
            prompt=prompt,
            attempt=attempt,
            parent_task_id=self._prefixed_parent_id(parent_task_id),
            metadata=metadata,
            system_prompt=system_prompt,
        )

    def log_response(self, task_id: str, response: str,
                     parent_task_id=None, attempt=None):
        self._inner.log_response(
            task_id=self._prefixed_task_id(task_id),
            response=response,
            parent_task_id=self._prefixed_parent_id(parent_task_id),
            attempt=attempt,
        )

    def log_conversation(self, task_id: str, task_name: str, prompt: str,
                         response: str, attempt, parent_task_id=None,
                         metadata=None):
        self._inner.log_conversation(
            task_id=self._prefixed_task_id(task_id),
            task_name=task_name,
            prompt=prompt,
            response=response,
            attempt=attempt,
            parent_task_id=self._prefixed_parent_id(parent_task_id),
            metadata=metadata,
        )

    def log_nested_prompt(self, task_id: str, task_name: str, call_type: str,
                          prompt: str, round_num, failed_subtask_id=None):
        self._inner.log_nested_prompt(
            task_id=self._prefixed_task_id(task_id),
            task_name=task_name,
            call_type=call_type,
            prompt=prompt,
            round_num=round_num,
            failed_subtask_id=self._prefixed_task_id(failed_subtask_id) if failed_subtask_id else None,
        )

    def log_nested_response(self, task_id: str, task_name: str, response,
                            call_type=None, round_num=None,
                            failed_subtask_id=None):
        self._inner.log_nested_response(
            task_id=self._prefixed_task_id(task_id),
            task_name=task_name,
            response=response,
            call_type=call_type,
            round_num=round_num,
            failed_subtask_id=self._prefixed_task_id(failed_subtask_id) if failed_subtask_id else None,
        )

    def log_nested_task_ai_call(self, task_id: str, task_name: str,
                                call_type: str, prompt: str, response: str,
                                round_num: int, metadata=None,
                                failed_subtask_id=None):
        self._inner.log_nested_task_ai_call(
            task_id=self._prefixed_task_id(task_id),
            task_name=task_name,
            call_type=call_type,
            prompt=prompt,
            response=response,
            round_num=round_num,
            metadata=metadata,
            failed_subtask_id=self._prefixed_task_id(failed_subtask_id) if failed_subtask_id else None,
        )

    def build_index_file(self, task_id: str):
        self._inner.build_index_file(self._prefixed_task_id(task_id))

    def finalize(self):
        self._inner.finalize()
