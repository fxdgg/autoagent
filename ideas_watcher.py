"""
Ideas Watcher - Monitors ideas.md for new ideas and converts them to TODO tasks.

This module provides:
- IdeasWatcher: Watches ideas.md for new content and uses AI to decompose
  ideas into structured TODO tasks that get appended to todos.yaml
"""

import os
import re
import time
import yaml
import hashlib
import logging
import tempfile
import threading
from typing import Optional, List


class _BlockStyleDumper(yaml.SafeDumper):
    """Custom YAML dumper that uses block scalar (|) style for multiline strings."""
    pass


def _str_representer(dumper, data):
    """Represent strings with block scalar style when they contain newlines."""
    if '\n' in data:
        # Strip trailing whitespace on each line to avoid YAML issues,
        # but preserve the overall structure.
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


_BlockStyleDumper.add_representer(str, _str_representer)

from codebuddy_client import AIClient, CodeBuddyClient, AICallError
from conversation_logger import ConversationLogger
from truncation_limits import limits
from prompts.ideas_decompose import build_ideas_decompose_prompt
from prompts.ideas_review import (
    build_ideas_review_prompt,
    build_revision_prompt,
)


def _load_ideas_config() -> dict:
    """Load ideas-related settings from config.yaml.

    Returns:
        dict with keys 'max_review_rounds' and 'max_validation_retries'.
    """
    defaults = {
        'max_review_rounds': 3,
        'max_validation_retries': 2,
    }
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            for key in defaults:
                val = config.get(key)
                if val is not None:
                    defaults[key] = int(val)
        except Exception as e:
            logger.warning(f"Failed to load ideas config from config.yaml: {e}")
    return defaults

logger = logging.getLogger(__name__)


class IdeasWatcher:
    """
    Watches an ideas.md file for new ideas and converts them into TODO tasks.
    
    Workflow:
    1. Read ideas.md and detect new (unprocessed) ideas
    2. Call AI to decompose each idea into structured TODO tasks
    3. Append the new tasks to todos.yaml
    4. Remove the processed idea from ideas.md
    5. Record the processed idea in plans_state.yaml
    
    Ideas in ideas.md are separated by horizontal rules (---). Each section
    between separators is treated as one idea.
    """

    # State file for tracking processed ideas (replaces .ideas_processed.md)
    PLANS_STATE_FILE = "plans_state.yaml"

    # Temporary file for AI to write generated YAML tasks into
    TEMP_TASKS_FILE = ".ideas_tasks_temp.yaml"

    def __init__(
        self,
        ideas_file: str = "ideas.md",
        todos_file: str = "todos.yaml",
        plans_state_file: str = None,
    ):
        """
        Initialize IdeasWatcher.
        
        Args:
            ideas_file: Path to the ideas markdown file
            todos_file: Path to the todos YAML configuration file
            plans_state_file: Path to the plans state YAML file
                (default: plans_state.yaml in the same directory)
        """
        self.ideas_file = ideas_file
        self.todos_file = todos_file
        self.plans_state_file = plans_state_file or self.PLANS_STATE_FILE
        self._lock = threading.Lock()
        self._plans_state = self._load_plans_state()
        self._last_mtime = 0.0

        # Load configurable review/validation limits from config.yaml
        ideas_cfg = _load_ideas_config()
        self.max_review_rounds = ideas_cfg['max_review_rounds']
        self.max_validation_retries = ideas_cfg['max_validation_retries']

    # ── Plans state management ──────────────────────────────────────────

    def _load_plans_state(self) -> dict:
        """Load plans state from YAML file."""
        try:
            if os.path.exists(self.plans_state_file):
                with open(self.plans_state_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and isinstance(data, dict):
                        logger.info(f"Loaded plans state from {self.plans_state_file}")
                        return data
        except Exception as e:
            logger.warning(f"Failed to load plans state file: {e}")
        return {"ideas": {}}

    def _save_plans_state(self):
        """Save current plans state to YAML file (thread-safe)."""
        with self._lock:
            try:
                with open(self.plans_state_file, 'w', encoding='utf-8') as f:
                    yaml.dump(
                        self._plans_state, f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                logger.debug(f"Plans state saved to {self.plans_state_file}")
            except Exception as e:
                logger.error(f"Failed to save plans state: {e}")

    def _is_idea_processed(self, idea_hash: str) -> bool:
        """Check whether an idea (by hash) has already been processed."""
        entry = self._plans_state.get("ideas", {}).get(idea_hash)
        if entry is None:
            return False
        return entry.get("status") in ("completed", "failed")

    def _record_idea_state(
        self,
        idea: dict,
        status: str,
        task_ids: Optional[List[int]] = None,
    ):
        """Record or update an idea's state in plans_state.yaml.

        Args:
            idea: Idea dict with 'hash', 'content', 'title' fields.
            status: One of 'in_progress', 'completed', 'failed'.
            task_ids: List of generated task IDs (for completed ideas).
        """
        idea_hash = idea['hash']
        if "ideas" not in self._plans_state:
            self._plans_state["ideas"] = {}

        entry = self._plans_state["ideas"].get(idea_hash, {})
        entry["status"] = status
        entry["display_title"] = idea['title']
        entry["content"] = idea['content']
        entry["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if status == "completed" and task_ids is not None:
            entry["task_ids"] = task_ids
        self._plans_state["ideas"][idea_hash] = entry
        self._save_plans_state()
        logger.debug(f"Recorded idea '{idea['title']}' as {status} in {self.plans_state_file}")

    def _remove_idea_from_file(self, idea: dict):
        """
        Remove a processed idea from ideas.md.

        Re-reads the file, splits by '---', removes the matching section,
        and writes back.
        """
        try:
            with open(self.ideas_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read ideas file for removal: {e}")
            return

        sections = re.split(r'\n---\n', content)
        remaining = []
        removed = False
        for section in sections:
            if not removed and section.strip() == idea['content'].strip():
                removed = True
                continue
            remaining.append(section)

        new_content = '\n---\n'.join(remaining).strip()
        # If there's still content, ensure it ends with a newline
        if new_content:
            new_content += '\n'

        try:
            with open(self.ideas_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            if removed:
                logger.debug(f"Removed idea '{idea['title']}' from {self.ideas_file}")
            else:
                logger.warning(f"Could not find idea '{idea['title']}' in {self.ideas_file} for removal")
        except Exception as e:
            logger.error(f"Failed to write ideas file after removal: {e}")

    def has_new_ideas(self) -> bool:
        """
        Check if ideas.md has been modified since last check.
        
        Returns:
            bool: True if the file exists and has been modified
        """
        if not os.path.exists(self.ideas_file):
            return False
        try:
            mtime = os.path.getmtime(self.ideas_file)
            if mtime > self._last_mtime:
                return True
        except OSError:
            pass
        return False

    @staticmethod
    def _make_display_title(content: str, max_len: int = 60) -> str:
        """Derive a short display title from free-form idea content.

        Takes the first non-empty line, strips leading ``#`` markers, and
        truncates to *max_len* characters so it can be used in log messages
        and console output.
        """
        for line in content.split('\n'):
            line = line.strip()
            if line:
                line = re.sub(r'^#+\s*', '', line)
                if len(line) > max_len:
                    return line[:max_len] + '…'
                return line
        return '(untitled)'

    def parse_ideas(self) -> List[dict]:
        """
        Parse ideas.md and extract individual ideas.
        
        Ideas are delimited by horizontal rules (``---``). Each section
        between separators is treated as one idea.  The format inside each
        section is completely free-form; no specific structure is assumed.
        
        Returns:
            List[dict]: List of ideas with 'title', 'content', and 'hash' fields.
                ``title`` is a short display string derived from the content
                (not stored persistently).
        """
        if not os.path.exists(self.ideas_file):
            return []

        try:
            with open(self.ideas_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read ideas file: {e}")
            return []

        # Update last modified time
        try:
            self._last_mtime = os.path.getmtime(self.ideas_file)
        except OSError:
            pass

        if not content.strip():
            return []

        # Split only by horizontal rules (---)
        sections = re.split(r'\n---\n', content)

        ideas = []
        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Compute hash of the idea content for deduplication
            idea_hash = hashlib.sha256(section.encode('utf-8')).hexdigest()[:16]

            ideas.append({
                'title': self._make_display_title(section),
                'content': section,
                'hash': idea_hash,
            })

        return ideas

    # Default maximum number of review rounds before accepting the tasks as-is
    _DEFAULT_MAX_REVIEW_ROUNDS = 3

    # Default maximum number of schema-validation retries before accepting as-is
    _DEFAULT_MAX_VALIDATION_RETRIES = 2

    def _get_temp_tasks_path(self) -> str:
        """Return the absolute path to the temporary tasks YAML file.

        The file is placed next to the todos.yaml file so that the AI
        tool can write to it in the project working directory.
        """
        return os.path.join(
            os.path.dirname(os.path.abspath(self.todos_file)) or os.getcwd(),
            self.TEMP_TASKS_FILE,
        )

    def _read_tasks_from_temp_file(self) -> Optional[List[dict]]:
        """Try to read and parse tasks from the temporary YAML file.

        Returns:
            List[dict] if the file exists and contains a valid YAML list,
            None otherwise.  The caller is responsible for cleaning up the
            temp file via ``_cleanup_temp_file()`` when appropriate.
        """
        temp_path = self._get_temp_tasks_path()
        if not os.path.exists(temp_path):
            return None
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                return None
            parsed = yaml.safe_load(content)
            if isinstance(parsed, list) and len(parsed) > 0:
                logger.info(f"Successfully read {len(parsed)} task(s) from temp file {temp_path}")
                return parsed
        except Exception as e:
            logger.warning(f"Failed to read/parse temp tasks file {temp_path}: {e}")
        return None

    def _cleanup_temp_file(self):
        """Remove the temporary tasks file if it exists."""
        temp_path = self._get_temp_tasks_path()
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError as e:
            logger.warning(f"Failed to remove temp file {temp_path}: {e}")

    @staticmethod
    def _validate_task_schema(task: dict, is_subtask: bool = False) -> List[str]:
        """Validate a single task's schema and return a list of error messages.

        This mirrors the validation logic in ``Orchestrator._validate_task`` so
        that schema problems are caught *before* tasks are written to todos.yaml.
        """
        errors: List[str] = []
        task_id = task.get('id', '?')

        # Required fields
        required_fields = ['id', 'name', 'type', 'completion_criteria']
        for field in required_fields:
            if field not in task:
                errors.append(f"Task {task_id} missing required field: '{field}'")

        task_type = task.get('type')
        if task_type is None:
            return errors  # cannot validate further without type

        # Validate task type
        if is_subtask:
            valid_types = ['simple', 'long_running', 'simple_once', 'long_running_once',
                           'nested', 'looping']
        else:
            valid_types = ['simple', 'nested', 'looping']
        if task_type not in valid_types:
            errors.append(
                f"Task {task_id} has invalid type: '{task_type}'. "
                f"Valid types for {'subtask' if is_subtask else 'top-level'}: {valid_types}"
            )

        # Validate nested tasks
        if task_type == 'nested':
            subtasks = task.get('subtasks', [])
            if not subtasks:
                errors.append(f"Nested task {task_id} must have 'subtasks'")
            else:
                for st in subtasks:
                    errors.extend(IdeasWatcher._validate_task_schema(st, is_subtask=True))

        # Validate looping tasks
        if task_type == 'looping':
            subtasks = task.get('subtasks', [])
            if not subtasks:
                errors.append(f"Looping task {task_id} must have 'subtasks'")
            else:
                for st in subtasks:
                    errors.extend(IdeasWatcher._validate_task_schema(st, is_subtask=True))
            repeat_count = task.get('repeat_count')
            if repeat_count is None:
                errors.append(f"Looping task {task_id} must have 'repeat_count' field")
            elif not isinstance(repeat_count, int) or repeat_count < 1:
                errors.append(f"Looping task {task_id}: 'repeat_count' must be a positive integer")

        # Validate optional model field
        model = task.get('model')
        if model is not None and not isinstance(model, str):
            errors.append(
                f"Task {task_id} has invalid model: '{model}'. "
                f"Must be a string: 'default', 'simple', or a direct model name"
            )

        return errors

    @staticmethod
    def _validate_tasks_schema(tasks: List[dict]) -> tuple:
        """Validate the schema of a list of tasks.

        Returns:
            (valid: bool, errors: List[str])
        """
        all_errors: List[str] = []
        for task in tasks:
            all_errors.extend(IdeasWatcher._validate_task_schema(task, is_subtask=False))
        return (len(all_errors) == 0, all_errors)

    def process_new_ideas(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient = None,
        conv_logger: ConversationLogger = None,
        human_review: bool = False,
    ) -> int:
        """
        Process all new ideas: parse, convert to TODOs via AI, and append to todos.yaml.
        
        Args:
            client: CodeBuddyClient instance to call AI for task decomposition
            review_client: Optional CodeBuddyClient with fresh context for reviewing
                           generated tasks. If None, review step is skipped.
            conv_logger: Optional ConversationLogger to record prompts/responses
            human_review: If True, after AI review passes, pause for human approval.
                          Human can accept (y) or reject with feedback (n) which
                          triggers another AI revision cycle.
            
        Returns:
            int: Number of new ideas processed
        """
        ideas = self.parse_ideas()
        if not ideas:
            return 0

        logger.info(f"Found {len(ideas)} new idea(s) to process")
        processed_count = 0

        for idea in ideas:
            # Skip already-processed ideas (deduplication by content hash)
            if self._is_idea_processed(idea['hash']):
                logger.info(f"Skipping already-processed idea '{idea['title']}' (hash={idea['hash']})")
                # Still remove from ideas.md in case it was re-added
                self._remove_idea_from_file(idea)
                continue

            print(f"\n   💡 Processing idea: {idea['title']}")
            self._record_idea_state(idea, "in_progress")
            try:
                new_tasks = self._decompose_idea_to_tasks(
                    client, idea,
                    review_client=review_client,
                    conv_logger=conv_logger,
                    idea_index=processed_count + 1,
                    human_review=human_review,
                )
                if new_tasks:
                    self._append_tasks_to_todos(new_tasks)
                    task_ids = [t.get('id') for t in new_tasks if t.get('id') is not None]
                    self._record_idea_state(idea, "completed", task_ids=task_ids)
                    print(f"   ✅ Added {len(new_tasks)} task(s) from idea: {idea['title']}")
                else:
                    self._record_idea_state(idea, "completed", task_ids=[])
                    print(f"   ⚠️  No tasks generated from idea: {idea['title']}")

                # Remove the processed idea from ideas.md
                self._remove_idea_from_file(idea)
                processed_count += 1

            except Exception as e:
                self._record_idea_state(idea, "failed")
                logger.error(f"Failed to process idea '{idea['title']}': {e}")
                print(f"   ❌ Failed to process idea: {idea['title']} - {e}")

        return processed_count

    def _decompose_idea_to_tasks(
        self,
        client: CodeBuddyClient,
        idea: dict,
        review_client: CodeBuddyClient = None,
        conv_logger: ConversationLogger = None,
        idea_index: int = 1,
        human_review: bool = False,
    ) -> List[dict]:
        """
        Call AI to decompose an idea into structured TODO tasks.
        
        If a review_client is provided, the generated tasks are sent to a
        fresh-context AI for review. If the review rejects the tasks, the
        feedback is sent back to the original AI for revision. This loop
        repeats up to MAX_REVIEW_ROUNDS times.
        
        When human_review is True, after AI review passes the program pauses
        for human approval. The human can accept (y) or provide feedback (n)
        which triggers another AI revision + review cycle.
        
        Args:
            client: CodeBuddyClient instance
            idea: Idea dict with 'title', 'content', 'hash' fields
            review_client: Optional CodeBuddyClient with fresh context for review
            conv_logger: Optional ConversationLogger to record prompts/responses
            idea_index: 1-based index of the idea (for logging)
            human_review: If True, pause for human approval after AI review passes
            
        Returns:
            List[dict]: List of task configurations compatible with todos.yaml format
        """
        # Load existing tasks to determine the next available task ID
        existing_tasks = self._load_existing_tasks()
        max_id = 0
        for task in existing_tasks:
            tid = task.get('id', 0)
            if isinstance(tid, (int, float)):
                max_id = max(max_id, int(tid))
        next_id = max_id + 1

        # Resolve paths for the prompt
        temp_tasks_path = self._get_temp_tasks_path()
        # Clean up any leftover temp file from a previous run
        self._cleanup_temp_file()

        prompt = build_ideas_decompose_prompt(
            idea_content=idea['content'],
            next_id=next_id,
            temp_tasks_path=temp_tasks_path,
        )

        try:
            # Log prompt before AI call (crash-safe)
            if conv_logger:
                conv_logger.log_ideas_prompt(idea['title'], idea_index, prompt)

            result = client.ask(prompt)

            # Log response after AI call
            if conv_logger:
                conv_logger.log_ideas_response(result)

            # Parse the YAML: prefer temp file, fall back to response text
            tasks = self._read_tasks_from_temp_file()
            if tasks is None:
                logger.info("Temp file not found or empty, falling back to response text parsing")
                tasks = self._extract_yaml_tasks(result)
            self._cleanup_temp_file()

            # Review + validation loop
            if tasks:
                tasks, result = self._review_and_validate_loop(
                    client, review_client, idea, tasks, result,
                    conv_logger=conv_logger,
                )

            # Human review loop: after AI review + validation passes, pause for human approval
            if human_review and tasks:
                tasks = self._human_review_loop(
                    client, review_client, idea, tasks, result,
                    conv_logger=conv_logger,
                )

            # Write section end separator
            if conv_logger:
                conv_logger.log_ideas_section_end()

            return tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea decomposition: {e}")
            raise

    def _review_and_validate_loop(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
    ) -> tuple:
        """Run the AI review loop followed by schema validation.

        After the AI reviewer approves (or is skipped), the tasks are
        validated against the schema.  If validation fails, the errors
        are fed back into the review loop as feedback so the AI can fix
        them.  This repeats up to ``MAX_VALIDATION_RETRIES`` times.

        Args:
            client: Original CodeBuddyClient (with existing context)
            review_client: Optional CodeBuddyClient for AI review
            idea: Original idea dict
            tasks: Current parsed task list
            raw_yaml_response: Raw response from the last AI call
            conv_logger: Optional ConversationLogger

        Returns:
            (tasks, raw_yaml_response) — the final validated task list and
            the last raw AI response.
        """
        result = raw_yaml_response

        for validation_attempt in range(1, self.max_validation_retries + 2):
            # --- AI review loop ---
            if review_client and tasks:
                last_feedback = ""
                for review_round in range(1, self.max_review_rounds + 1):
                    review_passed, review_feedback, revised_tasks = self._review_tasks(
                        review_client, idea, tasks, result,
                        conv_logger=conv_logger,
                        review_round=review_round,
                        last_feedback=last_feedback,
                    )
                    if review_passed:
                        print(f"   ✅ Review passed (round {review_round})")
                        break
                    else:
                        last_feedback = review_feedback
                        if revised_tasks:
                            print(f"   🔧 Reviewer directly revised tasks (round {review_round})")
                            tasks = revised_tasks
                        else:
                            print(f"   🔄 Review rejected (round {review_round}), but reviewer did not provide revised tasks.")
                            # Reviewer didn't write a corrected file — accept current tasks
                            # (the reviewer's feedback is lost since we don't send it to planner anymore)
                            break
                else:
                    print(
                        f"   ⚠️  Max review rounds ({self.max_review_rounds}) reached, "
                        f"accepting current tasks"
                    )

            # --- Schema validation ("compile") ---
            if not tasks:
                break

            valid, errors = self._validate_tasks_schema(tasks)
            if valid:
                print(f"   ✅ Schema validation passed")
                break
            else:
                error_text = '\n'.join(f"  - {e}" for e in errors)
                print(f"   ❌ Schema validation failed (attempt {validation_attempt}/{self.max_validation_retries + 1}):")
                for e in errors:
                    print(f"      • {e}")

                if validation_attempt > self.max_validation_retries:
                    print(f"   ⚠️  Max validation retries ({self.max_validation_retries}) exceeded, accepting current tasks")
                    break

                # Feed validation errors back as review feedback for the reviewer to fix
                validation_feedback = (
                    f"Schema validation failed with the following errors:\n"
                    f"{error_text}\n\n"
                    f"Please fix these issues. Every task must conform to the schema."
                )
                print(f"   🔄 Sending validation errors to reviewer for revision...")

                # Send to the reviewer (same session) to fix
                # NOTE: Do NOT delete the temp file here — the AI may try to
                # read it before writing.  It will be overwritten by the AI
                # and cleaned up after we read the result.
                temp_tasks_path = self._get_temp_tasks_path()
                revision_prompt = build_revision_prompt(
                    temp_tasks_path=temp_tasks_path,
                    human_feedback=validation_feedback,
                )
                try:
                    if conv_logger:
                        conv_logger.log_ideas_revision_prompt(validation_attempt, revision_prompt)
                    revision_result = review_client.ask(revision_prompt)
                    if conv_logger:
                        conv_logger.log_ideas_revision_response(revision_result)
                    tasks = self._read_tasks_from_temp_file()
                    if tasks is None:
                        logger.info("Temp file not found after validation-retry revision, falling back to response text parsing")
                        tasks = self._extract_yaml_tasks(revision_result)
                    self._cleanup_temp_file()
                    result = revision_result
                except AICallError as e:
                    logger.error(f"AI call failed during validation-retry revision: {e}")
                    break
                # Loop back to AI review + validation

        return tasks, result

    def _review_tasks(
        self,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
        review_round: int = 1,
        last_feedback: str = "",
    ) -> tuple:
        """
        Send generated tasks to a fresh-context reviewer AI for quality check.
        
        If the reviewer rejects the tasks, it is instructed to directly modify
        the temp YAML file with corrections. The caller can then read the
        revised tasks from the temp file, potentially skipping a separate
        revision round.
        
        Args:
            review_client: CodeBuddyClient with fresh context
            idea: Original idea dict
            tasks: Parsed task list
            raw_yaml_response: Raw YAML response from the decomposition AI
            conv_logger: Optional ConversationLogger
            review_round: 1-based review round number
            last_feedback: Feedback from the previous review round (if any)
            
        Returns:
            tuple: (passed: bool, feedback: str, revised_tasks: Optional[List[dict]])
                   passed=True if review approves, feedback contains reviewer comments,
                   revised_tasks contains reviewer's corrected tasks if it rejected and
                   directly modified the file (None otherwise).
        """
        # Reset reviewer session so each review round starts with a fresh context.
        # Without this, the reviewer AI would see the full conversation history
        # from previous review rounds, which pollutes its judgment.
        review_client.reset_session()

        tasks_yaml = yaml.dump(tasks, Dumper=_BlockStyleDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)

        temp_tasks_path = self._get_temp_tasks_path()
        # Write current tasks to temp file so reviewer can modify it in-place
        self._cleanup_temp_file()
        try:
            with open(temp_tasks_path, 'w', encoding='utf-8') as f:
                f.write(tasks_yaml)
        except OSError as e:
            logger.warning(f"Failed to write temp file for reviewer: {e}")

        review_prompt = build_ideas_review_prompt(
            idea_content=idea['content'],
            tasks_yaml=tasks_yaml,
            temp_tasks_path=temp_tasks_path,
        )

        try:
            if conv_logger:
                conv_logger.log_ideas_review_prompt(review_round, review_prompt)

            review_result = review_client.ask(review_prompt)

            if conv_logger:
                conv_logger.log_ideas_review_response(review_result)

            passed = self._check_review_passed(review_result)

            revised_tasks = None
            if not passed:
                # Try to read reviewer's corrected tasks from temp file
                revised_tasks = self._read_tasks_from_temp_file()
                if revised_tasks:
                    logger.info(f"Reviewer directly revised {len(revised_tasks)} task(s) in temp file")
            self._cleanup_temp_file()

            return passed, review_result, revised_tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea review: {e}")
            self._cleanup_temp_file()
            # On review failure, accept the tasks to avoid blocking
            return True, "", None

    @staticmethod
    def _check_review_passed(review_response: str) -> bool:
        """
        Check if the reviewer AI approved the tasks.
        
        Uses the same three-layer detection strategy as SimpleTaskExecutor:
        1. Strict negative markers (highest priority)
        2. Strict positive markers
        3. Fuzzy positive matching (fallback)
        
        Args:
            review_response: The reviewer's response text
            
        Returns:
            bool: True if review passed
        """
        lower = review_response.lower()

        # Layer 1: Strict negative markers
        if '❌ not completed' in lower or '❌not completed' in lower:
            return False

        # Layer 2: Strict positive markers
        if '✅ completed' in lower or '✅completed' in lower:
            return True

        # Layer 3: Fuzzy matching
        import re as _re
        if _re.search(r'✅.*completed', lower):
            if not _re.search(r'not\s+completed|fail|reject', lower):
                return True

        # Default: not passed
        return False

    def _human_review_loop(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
    ) -> List[dict]:
        """
        Pause for human review after AI review passes.
        
        Flow when human rejects:
        1. Human provides feedback and/or edits the temp YAML file
        2. Revision prompt is sent to the **same reviewer** (session preserved)
        3. Reviewer revises the tasks
        4. A **new reviewer** (fresh session) reviews the revised tasks
        5. Human reviews again
        
        Args:
            client: Original CodeBuddyClient (with existing context)
            review_client: CodeBuddyClient for AI review
            idea: Original idea dict
            tasks: Current parsed task list
            raw_yaml_response: Raw YAML response from the last AI call
            conv_logger: Optional ConversationLogger
            
        Returns:
            List[dict]: Final approved task list
        """
        revision_counter = 0
        result = raw_yaml_response
        temp_tasks_path = self._get_temp_tasks_path()

        while True:
            # Write current tasks to temp file so human can edit directly
            tasks_yaml = yaml.dump(
                tasks, Dumper=_BlockStyleDumper, default_flow_style=False,
                allow_unicode=True, sort_keys=False,
            )
            try:
                with open(temp_tasks_path, 'w', encoding='utf-8') as f:
                    f.write(tasks_yaml)
            except OSError as e:
                logger.warning(f"Failed to write temp file for human review: {e}")

            print(f"\n{'─' * 60}")
            print(f"   👤 Human Review Required")
            print(f"{'─' * 60}")
            print(f"   Idea: {idea['title']}")
            print(f"\n   Generated Tasks:")
            print(f"{'─' * 40}")
            for line in tasks_yaml.split('\n'):
                print(f"   {line}")
            print(f"{'─' * 40}")
            print(f"\n   📝 You can also edit the tasks directly in:")
            print(f"      {temp_tasks_path}")

            # Wait for human input
            try:
                choice = input("\n   Accept these tasks? (y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n   ⚠️  Input interrupted, accepting current tasks.")
                break

            if choice == 'y':
                # Check if human edited the temp file
                edited_tasks = self._read_tasks_from_temp_file()
                if edited_tasks is not None:
                    # Validate the human-edited tasks
                    valid, errors = self._validate_tasks_schema(edited_tasks)
                    if valid:
                        tasks = edited_tasks
                        print(f"   ✅ Human approved the tasks (loaded from temp file).")
                    else:
                        print(f"   ⚠️  Temp file has schema errors:")
                        for e in errors:
                            print(f"      • {e}")
                        print(f"   Please fix the errors and try again.")
                        continue
                else:
                    print(f"   ✅ Human approved the tasks.")
                break
            elif choice == 'n':
                # Check if human already edited the temp file
                edited_tasks = self._read_tasks_from_temp_file()
                human_edited_yaml = ""
                if edited_tasks is not None:
                    # Human edited the file — validate it
                    valid, errors = self._validate_tasks_schema(edited_tasks)
                    if valid:
                        tasks = edited_tasks
                        human_edited_yaml = yaml.dump(
                            tasks, Dumper=_BlockStyleDumper, default_flow_style=False,
                            allow_unicode=True, sort_keys=False,
                        )
                        print(f"   📝 Loaded human-edited tasks from temp file.")
                    else:
                        print(f"   ⚠️  Temp file has schema errors:")
                        for e in errors:
                            print(f"      • {e}")
                        print(f"   Please fix the errors and try again, or provide text feedback below.")

                # Get human text feedback
                print(f"   Please provide your feedback for AI reviewer (end with an empty line, or leave empty to skip):")
                feedback_lines = []
                try:
                    while True:
                        line = input("   > ")
                        if line.strip() == '':
                            break
                        feedback_lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    print("\n   ⚠️  Input interrupted, accepting current tasks.")
                    break

                human_feedback = '\n'.join(feedback_lines) if feedback_lines else ''

                if not human_feedback and not human_edited_yaml:
                    print(f"   ⚠️  No feedback provided and no file edits detected, please try again.")
                    continue

                revision_counter += 1

                # Log human feedback
                if conv_logger:
                    log_parts = []
                    if human_edited_yaml:
                        log_parts.append(f"[Human edited YAML]")
                    if human_feedback:
                        log_parts.append(f"[Human Feedback]\n{human_feedback}")
                    conv_logger.log_ideas_revision_prompt(
                        revision_counter,
                        '\n'.join(log_parts),
                    )

                # Step 3-4: Send revision prompt to the SAME reviewer
                # NOTE: Do NOT delete the temp file here — the AI may try to
                # read it before writing.  It will be overwritten by the AI
                # and cleaned up after we read the result.
                print(f"   🔄 Sending human feedback to reviewer for revision...")

                revision_prompt = build_revision_prompt(
                    temp_tasks_path=temp_tasks_path,
                    human_feedback=human_feedback,
                    current_tasks_yaml=human_edited_yaml,
                )
                try:
                    result = review_client.ask(revision_prompt)

                    if conv_logger:
                        conv_logger.log_ideas_revision_response(result)

                    tasks = self._read_tasks_from_temp_file()
                    if tasks is None:
                        logger.info("Temp file not found after reviewer revision, falling back to response text parsing")
                        tasks = self._extract_yaml_tasks(result)
                    self._cleanup_temp_file()

                    if not tasks:
                        print(f"   ⚠️  Reviewer revision produced no valid tasks, keeping previous version.")
                        continue

                except AICallError as e:
                    logger.error(f"AI call failed during reviewer revision: {e}")
                    print(f"   ❌ Reviewer revision failed: {e}")
                    print(f"   Keeping previous version.")
                    continue

                # Step 5: New reviewer reviews the revised tasks
                tasks, result = self._review_and_validate_loop(
                    client, review_client, idea, tasks, result,
                    conv_logger=conv_logger,
                )

                # Loop back to human review with updated tasks
            else:
                print(f"   ⚠️  Invalid input. Please enter 'y' or 'n'.")

        # Clean up temp file when leaving the human review loop
        self._cleanup_temp_file()
        return tasks

    def _extract_yaml_tasks(self, response: str) -> List[dict]:
        """
        Extract YAML task definitions from AI response.
        
        Args:
            response: Raw AI response text
            
        Returns:
            List[dict]: Parsed task list
        """
        # Strategy 1: Try parsing the entire response as YAML
        try:
            parsed = yaml.safe_load(response)
            if isinstance(parsed, list):
                return parsed
        except yaml.YAMLError:
            pass

        # Strategy 2: Extract YAML from code block
        yaml_patterns = [
            r'```ya?ml\s*\n(.*?)\n\s*```',
            r'```\s*\n(.*?)\n\s*```',
        ]
        for pattern in yaml_patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                try:
                    parsed = yaml.safe_load(match.group(1))
                    if isinstance(parsed, list):
                        return parsed
                except yaml.YAMLError:
                    continue

        # Strategy 3: Find lines that look like YAML list items
        lines = response.split('\n')
        yaml_lines = []
        in_yaml = False
        for line in lines:
            if re.match(r'^- id:', line):
                in_yaml = True
            if in_yaml:
                yaml_lines.append(line)
                # Stop at empty line after content or at non-YAML content
                if line.strip() == '' and yaml_lines and yaml_lines[-2].strip() == '':
                    break

        if yaml_lines:
            try:
                parsed = yaml.safe_load('\n'.join(yaml_lines))
                if isinstance(parsed, list):
                    return parsed
            except yaml.YAMLError:
                pass

        logger.warning(f"Failed to extract YAML tasks from AI response: {response[:500]}")
        return []

    def _load_existing_tasks(self) -> list:
        """Load existing tasks from todos.yaml."""
        if not os.path.exists(self.todos_file):
            return []
        try:
            with open(self.todos_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            if config and isinstance(config, dict):
                return config.get('tasks', [])
        except Exception as e:
            logger.error(f"Failed to load todos file: {e}")
        return []

    def _append_tasks_to_todos(self, new_tasks: List[dict]):
        """
        Append new tasks to todos.yaml.
        
        If the file doesn't exist, creates it with proper structure.
        If it exists, reads existing tasks and appends new ones.
        
        Args:
            new_tasks: List of task configurations to append
        """
        if not new_tasks:
            return

        # Load existing config or create new one
        config = {'tasks': []}
        if os.path.exists(self.todos_file):
            try:
                with open(self.todos_file, 'r', encoding='utf-8') as f:
                    existing = yaml.safe_load(f)
                if existing and isinstance(existing, dict):
                    config = existing
                    if 'tasks' not in config:
                        config['tasks'] = []
            except Exception as e:
                logger.error(f"Failed to read existing todos: {e}")
                # Don't overwrite - just append after current content
                raise

        # Append new tasks
        config['tasks'].extend(new_tasks)

        # Write back
        try:
            with open(self.todos_file, 'w', encoding='utf-8') as f:
                yaml.dump(
                    config, f,
                    Dumper=_BlockStyleDumper,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )
            logger.info(f"Appended {len(new_tasks)} new task(s) to {self.todos_file}")
        except Exception as e:
            logger.error(f"Failed to write todos file: {e}")
            raise

    def mark_all_processed(self):
        """Mark all current ideas as processed without generating tasks."""
        ideas = self.parse_ideas()
        for idea in ideas:
            self._record_idea_state(idea, "completed", task_ids=[])
        # Clear the ideas file
        try:
            with open(self.ideas_file, 'w', encoding='utf-8') as f:
                f.write('')
        except Exception as e:
            logger.error(f"Failed to clear ideas file: {e}")

    def reset(self):
        """Reset all processed state."""
        self._last_mtime = 0.0
        self._plans_state = {"ideas": {}}
        self._save_plans_state()
        logger.info("Plans state reset")
