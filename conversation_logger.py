"""
Conversation Logger - Logs full AI conversation content to Markdown files.

This module manages:
- Creating timestamped log directories
- Writing conversation content for simple/long_running tasks
- Creating index files with links for nested tasks
- Organizing subtask logs in subdirectories
"""

import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ConversationLogger:
    """
    Manages conversation log output to Markdown files.

    Directory structure example (nested task):
        <session_dir>/
        └── conversations/
            ├── task_1.md          (index with links to subtasks)
            └── subtask_1/
                ├── task_1.1.md
                ├── task_1.2.md
                └── ...

    Directory structure example (simple task):
        <session_dir>/
        └── conversations/
            └── task_1.md          (full conversation content)
    """

    def __init__(self, session_dir: str):
        """
        Initialize ConversationLogger.

        Args:
            session_dir: Project-specific session directory
                         (e.g. logs/cufftdx_optimization_ko53bi1b).
                         A fixed ``conversations`` subdirectory will be
                         created inside it.
        """
        self.log_root_dir = session_dir
        # Use a fixed "conversations" subdirectory (no timestamp)
        self.session_dir = os.path.join(session_dir, "conversations")
        os.makedirs(self.session_dir, exist_ok=True)
        logger.info(f"Conversation log directory: {self.session_dir}")

        # Track nested task subtask info for building index files
        # { task_id: [subtask_id, ...] }
        self._nested_subtasks = {}
        # { task_id: task_name }
        self._task_names = {}

    def get_session_dir(self) -> str:
        """Return the session log directory path."""
        return self.session_dir

    def register_nested_task(self, task_id: str, task_name: str, subtask_ids: list):
        """
        Register a nested task and its subtask IDs.
        This creates the subtask directory and prepares the index file.

        Args:
            task_id: Main task ID (e.g. "1")
            task_name: Main task name
            subtask_ids: List of subtask IDs (e.g. ["1.1", "1.2", ...])
        """
        self._nested_subtasks[task_id] = subtask_ids
        self._task_names[task_id] = task_name

        # Create subtask directory
        subtask_dir = os.path.join(self.session_dir, f"subtask_{task_id}")
        os.makedirs(subtask_dir, exist_ok=True)

    def _resolve_filepath(self, task_id: str, parent_task_id: Optional[str] = None) -> str:
        """Resolve the markdown log file path for a given task."""
        if parent_task_id and parent_task_id in self._nested_subtasks:
            subtask_dir = os.path.join(self.session_dir, f"subtask_{parent_task_id}")
            os.makedirs(subtask_dir, exist_ok=True)
            return os.path.join(subtask_dir, f"task_{task_id}.md")
        else:
            return os.path.join(self.session_dir, f"task_{task_id}.md")

    def log_prompt(
        self,
        task_id: str,
        task_name: str,
        prompt: str,
        attempt: int,
        parent_task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """
        Write the prompt section to the log file immediately (before AI call).

        This ensures the prompt is persisted even if the process is interrupted
        (e.g. Ctrl+C) while waiting for the AI response.

        Args:
            task_id: Task ID (e.g. "1" or "1.1")
            task_name: Task name
            prompt: The prompt sent to AI
            attempt: Attempt number
            parent_task_id: Parent task ID if this is a subtask
            metadata: Optional dict with extra info
        """
        filepath = self._resolve_filepath(task_id, parent_task_id)

        content_parts = []

        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            content_parts.append(f"# Task {task_id}: {task_name}\n\n")

        meta_label = ""
        if metadata and metadata.get("type"):
            meta_label = f" ({metadata['type']})"
        content_parts.append(f"## Attempt #{attempt}{meta_label}\n\n")

        content_parts.append(f"### Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged prompt to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write prompt log to {filepath}: {e}")

    def log_response(
        self,
        task_id: str,
        response: str,
        parent_task_id: Optional[str] = None,
    ):
        """
        Append the response section (and separator) to the log file after AI returns.

        Must be called after ``log_prompt`` for the same task/attempt.

        Args:
            task_id: Task ID
            response: The AI response
            parent_task_id: Parent task ID if this is a subtask
        """
        filepath = self._resolve_filepath(task_id, parent_task_id)

        content_parts = []
        content_parts.append(f"### Response\n\n")
        content_parts.append(f"{response}\n\n")
        content_parts.append(f"---\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged response to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write response log to {filepath}: {e}")

    def log_conversation(
        self,
        task_id: str,
        task_name: str,
        prompt: str,
        response: str,
        attempt: int,
        parent_task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """
        Log a single conversation turn (prompt + response) atomically.

        This is a convenience wrapper that calls ``log_prompt`` + ``log_response``.
        Prefer using the two-step approach in new code for crash safety.
        """
        self.log_prompt(task_id, task_name, prompt, attempt, parent_task_id, metadata)
        self.log_response(task_id, response, parent_task_id)

    def _resolve_decisions_filepath(self, task_id: str, task_name: str) -> str:
        """Resolve the decisions markdown log file path for a nested task."""
        subtask_dir = os.path.join(self.session_dir, f"subtask_{task_id}")
        os.makedirs(subtask_dir, exist_ok=True)
        return os.path.join(subtask_dir, f"_decisions.md")

    def log_nested_prompt(
        self,
        task_id: str,
        task_name: str,
        call_type: str,
        prompt: str,
        round_num: int,
    ):
        """
        Write the prompt section of a nested task AI decision call immediately.

        Args:
            task_id: Main task ID (e.g. "1")
            task_name: Main task name
            call_type: Type of AI call (e.g. "failure_analysis", "main_task_evaluation")
            prompt: The prompt sent to AI
            round_num: Current round number
        """
        filepath = self._resolve_decisions_filepath(task_id, task_name)

        content_parts = []

        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            content_parts.append(f"# Task {task_id}: {task_name} - AI Decisions\n\n")

        content_parts.append(f"## Round #{round_num} - {call_type}\n\n")
        content_parts.append(f"### Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged nested prompt to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write nested prompt log to {filepath}: {e}")

    def log_nested_response(
        self,
        task_id: str,
        task_name: str,
        response,
    ):
        """
        Append the response section of a nested task AI decision call.

        Must be called after ``log_nested_prompt`` for the same task/round.

        Args:
            task_id: Main task ID
            task_name: Main task name
            response: The AI response (str or dict)
        """
        filepath = self._resolve_decisions_filepath(task_id, task_name)

        content_parts = []
        content_parts.append(f"### Response\n\n")
        if isinstance(response, dict):
            import json
            response_str = json.dumps(response, indent=2, ensure_ascii=False)
            content_parts.append(f"```json\n{response_str}\n```\n\n")
        else:
            content_parts.append(f"{response}\n\n")
        content_parts.append(f"---\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged nested response to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write nested response log to {filepath}: {e}")

    def log_nested_task_ai_call(
        self,
        task_id: str,
        task_name: str,
        call_type: str,
        prompt: str,
        response: str,
        round_num: int,
        metadata: Optional[dict] = None,
    ):
        """
        Log an AI decision call atomically (prompt + response).

        This is a convenience wrapper. Prefer ``log_nested_prompt`` +
        ``log_nested_response`` in new code for crash safety.
        """
        self.log_nested_prompt(task_id, task_name, call_type, prompt, round_num)
        self.log_nested_response(task_id, task_name, response)

    def build_index_file(self, task_id: str):
        """
        Build or rebuild the index markdown file for a nested task.
        The index file contains links to all subtask markdown files.

        Args:
            task_id: Main task ID (e.g. "1")
        """
        if task_id not in self._nested_subtasks:
            return

        task_name = self._task_names.get(task_id, f"Task {task_id}")
        subtask_ids = self._nested_subtasks[task_id]
        filepath = os.path.join(self.session_dir, f"task_{task_id}.md")

        content_parts = []
        content_parts.append(f"# Task {task_id}: {task_name}\n\n")
        content_parts.append(f"## Subtask Logs\n\n")

        for st_id in subtask_ids:
            st_file = f"subtask_{task_id}/task_{st_id}.md"
            # Check if file exists to mark it
            full_path = os.path.join(self.session_dir, st_file)
            exists_marker = "" if os.path.exists(full_path) else " *(no log yet)*"
            content_parts.append(f"- [Task {st_id}]({st_file}){exists_marker}\n")

        # Also link to decisions file if it exists
        decisions_file = f"subtask_{task_id}/_decisions.md"
        decisions_full_path = os.path.join(self.session_dir, decisions_file)
        if os.path.exists(decisions_full_path):
            content_parts.append(f"\n## AI Decisions\n\n")
            content_parts.append(f"- [AI Decisions Log]({decisions_file})\n")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Built index file: {filepath}")
        except Exception as e:
            logger.error(f"Failed to write index file {filepath}: {e}")

    def finalize(self):
        """
        Finalize all logs. Rebuild index files for nested tasks.
        Should be called at the end of orchestrator execution.
        """
        for task_id in self._nested_subtasks:
            self.build_index_file(task_id)
        logger.info(f"Conversation logs finalized in {self.session_dir}")
