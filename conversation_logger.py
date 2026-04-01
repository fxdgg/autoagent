"""
Conversation Logger - Logs full AI conversation content to Markdown files.

This module manages:
- Creating per-round log files for each task attempt
- Creating per-type decision files for nested/looping task AI decisions
- Creating index files with links for nested tasks
- Organizing subtask logs in subdirectories
"""

import os
import re
import time
import logging
from typing import Optional, Union

logger = logging.getLogger(__name__)


class ConversationLogger:
    """
    Manages conversation log output to Markdown files.

    Each attempt/round is written to a separate file for easier navigation.

    Directory structure example (nested task):
        <session_dir>/
        └── conversations/
            ├── task_1.md                              (index with links)
            └── subtask_1/
                ├── task_1.1_round_1.md
                ├── task_1.1_round_2.md
                ├── failure_analysis_1.2_round_1.md
                ├── main_task_evaluation_round_1.md
                └── ...

    Directory structure example (simple task):
        <session_dir>/
        └── conversations/
            ├── task_1_round_1.md
            ├── task_1_round_2.md
            └── ...
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

    def _resolve_filepath(
        self,
        task_id: str,
        parent_task_id: Optional[str] = None,
        attempt: Optional[Union[int, str]] = None,
    ) -> str:
        """Resolve the markdown log file path for a given task.

        When *attempt* is provided the filename includes a ``_round_N``
        suffix so that each attempt gets its own file.  When *attempt*
        is ``None`` the legacy single-file behaviour is used (all
        attempts appended to the same file).
        """
        if attempt is not None:
            filename = f"task_{task_id}_round_{attempt}.md"
        else:
            filename = f"task_{task_id}.md"

        if parent_task_id and parent_task_id in self._nested_subtasks:
            subtask_dir = os.path.join(self.session_dir, f"subtask_{parent_task_id}")
            os.makedirs(subtask_dir, exist_ok=True)
            return os.path.join(subtask_dir, filename)
        else:
            return os.path.join(self.session_dir, filename)

    def log_prompt(
        self,
        task_id: str,
        task_name: str,
        prompt: str,
        attempt: Union[int, str],
        parent_task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        system_prompt: Optional[str] = None,
    ):
        """
        Write the prompt section to a per-round log file immediately
        (before AI call).

        Each attempt is written to its own file
        (``task_{id}_round_{attempt}.md``).

        Args:
            task_id: Task ID (e.g. "1" or "1.1")
            task_name: Task name
            prompt: The prompt sent to AI
            attempt: Attempt number (used for round file naming)
            parent_task_id: Parent task ID if this is a subtask
            metadata: Optional dict with extra info
            system_prompt: Optional system prompt sent alongside the user prompt
        """
        filepath = self._resolve_filepath(task_id, parent_task_id, attempt=attempt)

        content_parts = []

        # Each round file is self-contained — always write the header
        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            meta_label = ""
            if metadata and metadata.get("type"):
                meta_label = f" ({metadata['type']})"
            content_parts.append(f"# Task {task_id}: {task_name} — Round {attempt}{meta_label}\n\n")

        if system_prompt:
            content_parts.append(f"## System Prompt\n\n")
            content_parts.append(f"```\n{system_prompt}\n```\n\n")

        content_parts.append(f"## Prompt\n\n")
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
        attempt: Optional[Union[int, str]] = None,
    ):
        """
        Append the response section to the per-round log file after AI
        returns.

        Must be called after ``log_prompt`` for the same task/attempt.

        Args:
            task_id: Task ID
            response: The AI response
            parent_task_id: Parent task ID if this is a subtask
            attempt: Attempt number (must match the value passed to
                ``log_prompt``).  When ``None``, falls back to the
                legacy single-file path.
        """
        filepath = self._resolve_filepath(task_id, parent_task_id, attempt=attempt)

        content_parts = []
        content_parts.append(f"## Response\n\n")
        content_parts.append(f"{response}\n\n")

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
        attempt: Union[int, str],
        parent_task_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ):
        """
        Log a single conversation turn (prompt + response) atomically.

        This is a convenience wrapper that calls ``log_prompt`` + ``log_response``.
        Prefer using the two-step approach in new code for crash safety.
        """
        self.log_prompt(task_id, task_name, prompt, attempt, parent_task_id, metadata)
        self.log_response(task_id, response, parent_task_id, attempt=attempt)

    # ------------------------------------------------------------------
    # Nested / Looping task AI decision logging
    # ------------------------------------------------------------------

    def _resolve_decisions_filepath(
        self,
        task_id: str,
        task_name: str,
        call_type: Optional[str] = None,
        round_num: Optional[int] = None,
        failed_subtask_id: Optional[str] = None,
    ) -> str:
        """Resolve the decisions markdown log file path.

        When *call_type* and *round_num* are provided, each decision
        gets its own file:

        - ``failure_analysis_{subtask_id}_round_{N}.md``
        - ``looping_failure_analysis_{subtask_id}_round_{N}.md``
        - ``main_task_evaluation_round_{N}.md``

        When they are ``None`` the legacy ``_decisions.md`` path is used.
        """
        subtask_dir = os.path.join(self.session_dir, f"subtask_{task_id}")
        os.makedirs(subtask_dir, exist_ok=True)

        if call_type is not None and round_num is not None:
            if "failure_analysis" in call_type and failed_subtask_id:
                filename = f"{call_type}_{failed_subtask_id}_round_{round_num}.md"
            else:
                filename = f"{call_type}_round_{round_num}.md"
            return os.path.join(subtask_dir, filename)

        # Legacy fallback
        return os.path.join(subtask_dir, "_decisions.md")

    def log_nested_prompt(
        self,
        task_id: str,
        task_name: str,
        call_type: str,
        prompt: str,
        round_num: Union[int, str],
        failed_subtask_id: Optional[str] = None,
    ):
        """
        Write the prompt section of a nested task AI decision call
        immediately.

        Each decision is written to its own file, named by *call_type*
        and *round_num*.

        Args:
            task_id: Main task ID (e.g. "1")
            task_name: Main task name
            call_type: Type of AI call (e.g. "failure_analysis",
                "main_task_evaluation", "looping_failure_analysis")
            prompt: The prompt sent to AI
            round_num: Current round number
            failed_subtask_id: ID of the failed subtask (for
                failure_analysis types; included in the filename)
        """
        filepath = self._resolve_decisions_filepath(
            task_id, task_name,
            call_type=call_type,
            round_num=round_num,
            failed_subtask_id=failed_subtask_id,
        )

        content_parts = []

        # Each decision file is self-contained
        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            subtitle = call_type.replace("_", " ").title()
            if failed_subtask_id:
                content_parts.append(
                    f"# Task {task_id}: {task_name} — {subtitle} "
                    f"(subtask {failed_subtask_id}, round {round_num})\n\n"
                )
            else:
                content_parts.append(
                    f"# Task {task_id}: {task_name} — {subtitle} "
                    f"(round {round_num})\n\n"
                )

        content_parts.append(f"## Prompt\n\n")
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
        call_type: Optional[str] = None,
        round_num: Optional[Union[int, str]] = None,
        failed_subtask_id: Optional[str] = None,
    ):
        """
        Append the response section of a nested task AI decision call.

        Must be called after ``log_nested_prompt`` for the same decision.

        Args:
            task_id: Main task ID
            task_name: Main task name
            response: The AI response (str or dict)
            call_type: Type of AI call (must match ``log_nested_prompt``)
            round_num: Round number (must match ``log_nested_prompt``)
            failed_subtask_id: Failed subtask ID (must match
                ``log_nested_prompt``)
        """
        filepath = self._resolve_decisions_filepath(
            task_id, task_name,
            call_type=call_type,
            round_num=round_num,
            failed_subtask_id=failed_subtask_id,
        )

        content_parts = []
        content_parts.append(f"## Response\n\n")
        if isinstance(response, dict):
            import json
            response_str = json.dumps(response, indent=2, ensure_ascii=False)
            content_parts.append(f"```json\n{response_str}\n```\n\n")
        else:
            content_parts.append(f"{response}\n\n")

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
        failed_subtask_id: Optional[str] = None,
    ):
        """
        Log an AI decision call atomically (prompt + response).

        This is a convenience wrapper. Prefer ``log_nested_prompt`` +
        ``log_nested_response`` in new code for crash safety.
        """
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
    # Index file generation
    # ------------------------------------------------------------------

    def build_index_file(self, task_id: str):
        """
        Build or rebuild the index markdown file for a nested task.

        The index scans the subtask directory for per-round task files
        and per-type decision files, then generates a sorted link list.

        Args:
            task_id: Main task ID (e.g. "1")
        """
        if task_id not in self._nested_subtasks:
            return

        task_name = self._task_names.get(task_id, f"Task {task_id}")
        subtask_ids = self._nested_subtasks[task_id]
        filepath = os.path.join(self.session_dir, f"task_{task_id}.md")
        subtask_dir = os.path.join(self.session_dir, f"subtask_{task_id}")

        content_parts = []
        content_parts.append(f"# Task {task_id}: {task_name}\n\n")

        # --- Subtask logs (per-round files) ---
        content_parts.append(f"## Subtask Logs\n\n")
        for st_id in subtask_ids:
            # Collect round files for this subtask
            round_files = self._collect_round_files(subtask_dir, f"task_{st_id}_round_")
            if round_files:
                for rf in round_files:
                    rel = f"subtask_{task_id}/{rf}"
                    content_parts.append(f"- [Task {st_id} — {rf}]({rel})\n")
            else:
                # Legacy: check for single file
                legacy_file = f"task_{st_id}.md"
                legacy_path = os.path.join(subtask_dir, legacy_file)
                rel = f"subtask_{task_id}/{legacy_file}"
                if os.path.exists(legacy_path):
                    content_parts.append(f"- [Task {st_id}]({rel})\n")
                else:
                    content_parts.append(f"- Task {st_id} *(no log yet)*\n")

        # --- Decision files (failure_analysis, main_task_evaluation, etc.) ---
        decision_files = self._collect_decision_files(subtask_dir)
        if decision_files:
            content_parts.append(f"\n## AI Decisions\n\n")
            for df in decision_files:
                rel = f"subtask_{task_id}/{df}"
                label = df.replace(".md", "").replace("_", " ").title()
                content_parts.append(f"- [{label}]({rel})\n")

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Built index file: {filepath}")
        except Exception as e:
            logger.error(f"Failed to write index file {filepath}: {e}")

    @staticmethod
    def _collect_round_files(directory: str, prefix: str) -> list:
        """Collect and sort ``<prefix>N.md`` files in *directory*."""
        if not os.path.isdir(directory):
            return []
        files = [
            f for f in os.listdir(directory)
            if f.startswith(prefix) and f.endswith(".md")
        ]
        # Sort by round number extracted from filename
        def _sort_key(fname):
            m = re.search(r'_round_(\d+)', fname)
            return int(m.group(1)) if m else 0
        files.sort(key=_sort_key)
        return files

    @staticmethod
    def _collect_decision_files(directory: str) -> list:
        """Collect decision files (failure_analysis_*, main_task_evaluation_*, etc.)."""
        if not os.path.isdir(directory):
            return []
        prefixes = ("failure_analysis_", "looping_failure_analysis_", "main_task_evaluation_")
        files = [
            f for f in os.listdir(directory)
            if any(f.startswith(p) for p in prefixes) and f.endswith(".md")
        ]
        # Also include legacy _decisions.md if present
        if "_decisions.md" in os.listdir(directory):
            files.append("_decisions.md")
        # Sort: main_task_evaluation first, then failure_analysis, then by round
        def _sort_key(fname):
            order = 0
            if fname.startswith("failure_analysis_"):
                order = 1
            elif fname.startswith("looping_failure_analysis_"):
                order = 2
            elif fname.startswith("main_task_evaluation_"):
                order = 3
            elif fname == "_decisions.md":
                order = 9  # legacy at the end
            m = re.search(r'_round_(\d+)', fname)
            round_num = int(m.group(1)) if m else 0
            return (order, round_num)
        files.sort(key=_sort_key)
        return files

    # ------------------------------------------------------------------
    # Ideas processing logging (unchanged — single file)
    # ------------------------------------------------------------------

    def log_ideas_prompt(
        self,
        idea_title: str,
        idea_index: int,
        prompt: str,
    ):
        """
        Write the prompt section for an ideas decomposition call.

        All ideas decomposition logs are written to a single
        ``conversations/ideas.md`` file.

        Args:
            idea_title: Title of the idea being decomposed
            idea_index: 1-based index of the idea
            prompt: The prompt sent to AI
        """
        filepath = os.path.join(self.session_dir, "ideas.md")

        content_parts = []

        is_new_file = not os.path.exists(filepath)
        if is_new_file:
            content_parts.append("# Ideas Decomposition Log\n\n")

        content_parts.append(f"## Idea #{idea_index}: {idea_title}\n\n")
        content_parts.append(f"### Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged ideas prompt to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas prompt log to {filepath}: {e}")

    def log_ideas_response(
        self,
        response: str,
    ):
        """
        Append the response section for an ideas decomposition call.

        Must be called after ``log_ideas_prompt`` for the same idea.

        Args:
            response: The AI response (YAML task definitions)
        """
        filepath = os.path.join(self.session_dir, "ideas.md")

        content_parts = []
        content_parts.append(f"### Response\n\n")
        content_parts.append(f"```yaml\n{response}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged ideas response to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas response log to {filepath}: {e}")

    def log_ideas_review_prompt(
        self,
        review_round: int,
        prompt: str,
    ):
        """
        Write the prompt section for an ideas review call.

        Appended to the same ``conversations/ideas.md`` file, under the
        current idea section.

        Args:
            review_round: 1-based review round number
            prompt: The review prompt sent to AI
        """
        filepath = os.path.join(self.session_dir, "ideas.md")

        content_parts = []
        content_parts.append(f"### Review #{review_round} Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged ideas review prompt to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas review prompt log to {filepath}: {e}")

    def log_ideas_review_response(
        self,
        response: str,
    ):
        """
        Append the response section for an ideas review call.

        Must be called after ``log_ideas_review_prompt``.

        Args:
            response: The reviewer AI response
        """
        filepath = os.path.join(self.session_dir, "ideas.md")

        content_parts = []
        content_parts.append(f"### Review Response\n\n")
        content_parts.append(f"{response}\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged ideas review response to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas review response log to {filepath}: {e}")

    def log_ideas_revision_prompt(
        self,
        revision_round: int,
        prompt: str,
    ):
        """
        Write the prompt section for an ideas revision call (after review rejection).

        Args:
            revision_round: 1-based revision round number
            prompt: The revision prompt sent to the original AI
        """
        filepath = os.path.join(self.session_dir, "ideas.md")

        content_parts = []
        content_parts.append(f"### Revision #{revision_round} Prompt\n\n")
        content_parts.append(f"```\n{prompt}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged ideas revision prompt to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas revision prompt log to {filepath}: {e}")

    def log_ideas_revision_response(
        self,
        response: str,
    ):
        """
        Append the response section for an ideas revision call.

        Must be called after ``log_ideas_revision_prompt``.

        Args:
            response: The revised AI response (YAML task definitions)
        """
        filepath = os.path.join(self.session_dir, "ideas.md")

        content_parts = []
        content_parts.append(f"### Revision Response\n\n")
        content_parts.append(f"```yaml\n{response}\n```\n\n")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("".join(content_parts))
            logger.debug(f"Logged ideas revision response to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas revision response log to {filepath}: {e}")

    def log_ideas_section_end(self):
        """Write a separator to mark the end of an idea's processing section."""
        filepath = os.path.join(self.session_dir, "ideas.md")

        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write("---\n\n")
            logger.debug(f"Logged ideas section end to {filepath}")
        except Exception as e:
            logger.error(f"Failed to write ideas section end to {filepath}: {e}")

    def finalize(self):
        """
        Finalize all logs. Rebuild index files for nested tasks.
        Should be called at the end of orchestrator execution.
        """
        for task_id in self._nested_subtasks:
            self.build_index_file(task_id)
        logger.info(f"Conversation logs finalized in {self.session_dir}")
