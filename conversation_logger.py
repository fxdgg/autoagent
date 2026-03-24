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
        logs/
        └── 202603241542/
            ├── task_1.md          (index with links to subtasks)
            └── subtask_1/
                ├── task_1.1.md
                ├── task_1.2.md
                └── ...

    Directory structure example (simple task):
        logs/
        └── 202603241542/
            └── task_1.md          (full conversation content)
    """

    def __init__(self, log_root_dir: str):
        """
        Initialize ConversationLogger.

        Args:
            log_root_dir: Root directory for logs (e.g. "logs")
        """
        self.log_root_dir = log_root_dir
        # Create timestamped session directory
        timestamp = time.strftime("%Y%m%d%H%M")
        self.session_dir = os.path.join(log_root_dir, timestamp)
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
        Log a single conversation turn (prompt + response) to the appropriate markdown file.

        For simple/long_running top-level tasks: appends to task_<id>.md
        For subtasks of nested tasks: appends to subtask_<parent_id>/task_<id>.md

        Args:
            task_id: Task ID (e.g. "1" or "1.1")
            task_name: Task name
            prompt: The prompt sent to AI
            response: The AI response
            attempt: Attempt number
            parent_task_id: Parent task ID if this is a subtask (e.g. "1" for subtask "1.1")
            metadata: Optional dict with extra info (e.g. {"type": "failure_analysis"})
        """
        # Determine file path
        if parent_task_id and parent_task_id in self._nested_subtasks:
            # This is a subtask of a nested task
            subtask_dir = os.path.join(self.session_dir, f"subtask_{parent_task_id}")
            os.makedirs(subtask_dir, exist_ok=True)
            filepath = os.path.join(subtask_dir, f"task_{task_id}.md")
        else:
            # Top-level simple/long_running task, or nested task's own AI calls
            filepath = os.path.join(self.session_dir, f"task_{task_id}.md")

        # Build markdown content
        content_parts = []

        # Add header only if file doesn't exist yet
        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            content_parts.append(f"# Task {task_id}: {task_name}\n\n")

        # Add attempt section
        meta_label = ""
        if metadata and metadata.get("type"):
            meta_label = f" ({metadata['type']})"
        content_parts.append(f"## Attempt #{attempt}{meta_label}\n\n")

        # Prompt
        content_parts.append(f"### Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

        # Response
        content_parts.append(f"### Response\n\n")
        content_parts.append(f"{response}\n\n")

        # Separator
        content_parts.append(f"---\n\n")

        # Write to file (append mode)
        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged conversation to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write conversation log to {filepath}: {e}")

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
        Log an AI decision call for a nested task (failure analysis, main task evaluation).
        These go into a special section of the subtask folder as decision logs.

        Args:
            task_id: Main task ID (e.g. "1")
            task_name: Main task name
            call_type: Type of AI call (e.g. "failure_analysis", "main_task_evaluation")
            prompt: The prompt sent to AI
            response: The AI response (may be JSON string)
            round_num: Current round number
            metadata: Optional extra info
        """
        subtask_dir = os.path.join(self.session_dir, f"subtask_{task_id}")
        os.makedirs(subtask_dir, exist_ok=True)
        filepath = os.path.join(subtask_dir, f"_decisions.md")

        content_parts = []

        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            content_parts.append(f"# Task {task_id}: {task_name} - AI Decisions\n\n")

        content_parts.append(f"## Round #{round_num} - {call_type}\n\n")

        content_parts.append(f"### Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

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
            logger.debug(f"Logged nested task AI call to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write decision log to {filepath}: {e}")

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
