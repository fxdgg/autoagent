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

from ai_client import AIClient, AICallError
from logger import ConversationLogger
from util.truncation_limits import limits
from ideas.ideas_decomposer import IdeasDecomposerMixin
from ideas.ideas_reviewer import IdeasReviewerMixin


def _load_ideas_config() -> dict:
    """Load ideas-related settings from config.yaml.

    Returns:
        dict with keys 'max_review_rounds', 'max_validation_retries',
        and 'max_plan_retries'.
    """
    defaults = {
        'max_review_rounds': 3,
        'max_validation_retries': 2,
        'max_plan_retries': 3,
    }
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"
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


class IdeasWatcher(IdeasDecomposerMixin, IdeasReviewerMixin):
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
        self.max_plan_retries = ideas_cfg['max_plan_retries']

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
        return entry.get("status") == "completed"

    def _record_idea_state(
        self,
        idea: dict,
        status: str,
        task_ids: Optional[List[int]] = None,
        plan_data: Optional[dict] = None,
    ):
        """Record or update an idea's state in plans_state.yaml.

        Args:
            idea: Idea dict with 'hash', 'content', 'title' fields.
            status: One of 'in_progress', 'completed'.
            task_ids: List of generated task IDs (for completed ideas).
            plan_data: Intermediate plan output (dict with tasks and description) saved after
                the plan phase completes so that a resumed run can skip
                directly to the review phase.
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
        if plan_data is not None:
            entry["plan_data"] = plan_data
        # Clear plan_data when the idea reaches a terminal state
        if status in ("completed", "failed") and "plan_data" in entry:
            del entry["plan_data"]
        # Also clear legacy plan_tasks
        if status in ("completed", "failed") and "plan_tasks" in entry:
            del entry["plan_tasks"]
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

        The file is placed next to the plans_state.yaml file (in the
        session log directory) so that it survives across runs for
        checkpoint/resume, and avoids issues with AI CLI tools that
        clean up files relative to the workspace.
        """
        return os.path.join(
            os.path.dirname(os.path.abspath(self.plans_state_file)) or os.getcwd(),
            self.TEMP_TASKS_FILE,
        )

    # ── Temp file watcher ─────────────────────────────────────────────
    #
    # Some AI CLI tools (e.g. Claude Code ``--print`` mode) clean up files
    # they created when the session ends.  The temp YAML file written by
    # the AI may therefore vanish before ``_read_tasks_from_temp_file()``
    # is called.  To work around this we poll the file in a background
    # thread while the AI session is running and cache the latest content
    # in memory.

    def _start_temp_file_watcher(self):
        """Start a background thread that polls the temp file for changes.

        While the AI session is running, this thread checks the temp file
        every 0.5 s.  Whenever the file is found with non-empty content
        that differs from the previous snapshot, the content is cached in
        ``self._temp_file_cache``.  This way, even if the AI CLI removes
        the file on session exit, we still have the last good content.
        """
        self._temp_file_cache: Optional[str] = None
        self._watcher_stop = threading.Event()
        temp_path = self._get_temp_tasks_path()

        def _poll():
            last_mtime = 0.0
            while not self._watcher_stop.is_set():
                try:
                    if os.path.exists(temp_path):
                        mtime = os.path.getmtime(temp_path)
                        if mtime != last_mtime:
                            with open(temp_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            if content.strip():
                                self._temp_file_cache = content
                                last_mtime = mtime
                                logger.debug(
                                    f"Temp file watcher: cached {len(content)} chars "
                                    f"from {temp_path}"
                                )
                except Exception:
                    pass  # file may be mid-write; ignore transient errors
                self._watcher_stop.wait(0.2)

        self._watcher_thread = threading.Thread(target=_poll, daemon=True)
        self._watcher_thread.start()

    def _stop_temp_file_watcher(self):
        """Stop the background watcher thread."""
        if hasattr(self, '_watcher_stop'):
            self._watcher_stop.set()
            self._watcher_thread.join(timeout=2)

    def _read_tasks_from_temp_file(self) -> Optional[dict]:
        """Try to read and parse tasks from the temporary YAML file.

        First stops the watcher thread (joining it ensures the cache is
        visible to the calling thread).  Then checks the live file on
        disk.  If the file is missing or empty (which can happen when
        the AI CLI cleans up on session exit), falls back to the
        in-memory cache populated by the background watcher thread.

        Returns:
            dict containing 'tasks' and 'description' if valid YAML is found, None otherwise.
            The caller is responsible for cleaning up the temp file via
            ``_cleanup_temp_file()`` when appropriate.
        """
        # Stop the watcher first — join() guarantees the cached content
        # written by the watcher thread is visible in this thread.
        self._stop_temp_file_watcher()

        temp_path = self._get_temp_tasks_path()

        # Try reading the live file first
        content = None
        if os.path.exists(temp_path):
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if not content.strip():
                    content = None
                else:
                    logger.info(f"Read {len(content)} chars from temp file on disk")
            except Exception as e:
                logger.warning(f"Failed to read temp tasks file {temp_path}: {e}")
        else:
            logger.info(f"Temp file not found on disk: {temp_path}")

        # Fall back to watcher cache
        if content is None:
            cache = getattr(self, '_temp_file_cache', None)
            if cache:
                logger.info(
                    f"Using cached content from watcher ({len(cache)} chars)"
                )
                content = cache
            else:
                logger.warning(
                    "Temp file missing on disk AND watcher cache is empty — "
                    "AI may have deleted the file before watcher could cache it"
                )

        if content is None:
            return None

        try:
            parsed = yaml.safe_load(content)
            if isinstance(parsed, list) and len(parsed) > 0:
                logger.info(f"Successfully read {len(parsed)} task(s) from temp file {temp_path}")
                return {"tasks": parsed, "description": ""}
            # AI might have written a dict with a "tasks" key
            if isinstance(parsed, dict) and isinstance(parsed.get('tasks'), list):
                tasks_list = parsed['tasks']
                if tasks_list:
                    logger.info(f"Extracted {len(tasks_list)} task(s) from dict wrapper in temp file")
                    return {"tasks": tasks_list, "description": parsed.get("description", "")}
            logger.warning(
                f"Temp file YAML parsed but not a valid task list: "
                f"type={type(parsed).__name__}, "
                f"preview={str(parsed)[:limits.get('idea_yaml_preview')]}"
            )
        except Exception as e:
            logger.warning(f"Failed to parse temp tasks YAML: {e}")

        # Last resort: try stripping markdown code fences and re-parse
        stripped = content.strip()
        if stripped.startswith("```"):
            # Remove leading ```yaml / ``` and trailing ```
            lines = stripped.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            stripped = "\n".join(lines)
            try:
                parsed = yaml.safe_load(stripped)
                if isinstance(parsed, list) and len(parsed) > 0:
                    logger.info(f"Successfully read {len(parsed)} task(s) after stripping code fences")
                    return {"tasks": parsed, "description": ""}
                if isinstance(parsed, dict) and isinstance(parsed.get('tasks'), list):
                    tasks_list = parsed['tasks']
                    if tasks_list:
                        logger.info(f"Extracted {len(tasks_list)} task(s) from dict wrapper after stripping code fences")
                        return {"tasks": tasks_list, "description": parsed.get("description", "")}
            except Exception:
                pass
        return None

    def _cleanup_temp_file(self):
        """Remove the temporary tasks file if it exists and clear the cache."""
        self._stop_temp_file_watcher()
        self._temp_file_cache = None
        temp_path = self._get_temp_tasks_path()
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                logger.debug(f"Cleaned up temp file: {temp_path}")
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
            valid_types = ['simple', 'nested', 'looping', 'long_running']
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
                f"Must be a string: 'default', 'lite', or a direct model name"
            )

        return errors

    @staticmethod
    def _validate_tasks_schema(parsed_data: dict, next_id: int = 1) -> tuple:
        """Validate the schema of the parsed YAML data (tasks and description).

        Args:
            parsed_data: Parsed YAML data containing tasks and description.
            next_id: Starting ID for new tasks. When 1, root-level ``description``
                is required. When > 1, ``description@{next_id}`` is optional.

        Returns:
            (valid: bool, errors: List[str])
        """
        all_errors: List[str] = []

        if next_id == 1:
            # First batch: root-level description is required
            description = parsed_data.get('description')
            if description is None or not str(description).strip():
                all_errors.append("Root-level 'description' field is missing or empty")
            elif not isinstance(description, str):
                all_errors.append("'description' must be a string")
        else:
            # Later batches: description@{next_id} is optional
            scoped_key = f'description@{next_id}'
            scoped_desc = parsed_data.get(scoped_key)
            if scoped_desc is not None and not isinstance(scoped_desc, str):
                all_errors.append(f"'{scoped_key}' must be a string")

        tasks = parsed_data.get('tasks', [])
        if not tasks:
            all_errors.append("No tasks found")
            
        for task in tasks:
            all_errors.extend(IdeasWatcher._validate_task_schema(task, is_subtask=False))
            
        return (len(all_errors) == 0, all_errors)

    def process_new_ideas(
        self,
        client: AIClient,
        review_client: AIClient = None,
        conv_logger: ConversationLogger = None,
        human_review: bool = False,
    ) -> int:
        """
        Process all new ideas: parse, convert to TODOs via AI, and append to todos.yaml.
        
        Args:
            client: AIClient instance to call AI for task decomposition
            review_client: Optional AIClient with fresh context for reviewing
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
                parsed_data, next_id = self._decompose_idea_to_tasks(
                    client, idea,
                    review_client=review_client,
                    conv_logger=conv_logger,
                    idea_index=processed_count + 1,
                    human_review=human_review,
                )
                if parsed_data and parsed_data.get('tasks'):
                    new_tasks = parsed_data['tasks']
                    self._append_tasks_to_todos(parsed_data, next_id=next_id)
                    task_ids = [t.get('id') for t in new_tasks if t.get('id') is not None]
                    self._record_idea_state(idea, "completed", task_ids=task_ids)
                    print(f"   ✅ Added {len(new_tasks)} task(s) from idea: {idea['title']}")
                    # Remove the processed idea from ideas.md
                    self._remove_idea_from_file(idea)
                    processed_count += 1
                else:
                    # Do NOT mark as completed — keep in_progress so the
                    # next run will retry this idea.
                    print(f"   ⚠️  No tasks generated from idea: {idea['title']}, will retry next run")

            except Exception as e:
                # Do NOT record as "failed" — leave the idea in_progress so
                # the next run will retry it (resuming from plan checkpoint
                # if available).
                logger.error(f"Failed to process idea '{idea['title']}': {e}")
                print(f"   ❌ Failed to process idea: {idea['title']} - {e}")

        return processed_count

    # ── _decompose_idea_to_tasks  → ideas_decomposer.IdeasDecomposerMixin
    # ── _review_and_validate_loop → ideas_reviewer.IdeasReviewerMixin
    # ── _review_tasks             → ideas_reviewer.IdeasReviewerMixin
    # ── _check_review_passed      → ideas_reviewer.IdeasReviewerMixin
    # ── _human_review_loop        → ideas_reviewer.IdeasReviewerMixin

    def _extract_yaml_tasks(self, response: str) -> dict:
        """
        Extract YAML task definitions from AI response.
        
        Args:
            response: Raw AI response text
            
        Returns:
            dict: Parsed task list and description
        """
        # Strategy 1: Try parsing the entire response as YAML
        try:
            parsed = yaml.safe_load(response)
            if isinstance(parsed, list):
                return {"tasks": parsed, "description": ""}
            if isinstance(parsed, dict) and isinstance(parsed.get('tasks'), list):
                return {"tasks": parsed['tasks'], "description": parsed.get("description", "")}
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
                        return {"tasks": parsed, "description": ""}
                    if isinstance(parsed, dict) and isinstance(parsed.get('tasks'), list):
                        return {"tasks": parsed['tasks'], "description": parsed.get("description", "")}
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
                    return {"tasks": parsed, "description": ""}
            except yaml.YAMLError:
                pass

        logger.warning(f"Failed to extract YAML tasks from AI response: {response[:limits.get('previous_subtask_summary')]}")
        return {}

    def _load_existing_tasks(self) -> list:
        """Load existing tasks from todos.yaml."""
        config = self._load_existing_config()
        return config.get('tasks', [])

    def _load_existing_config(self) -> dict:
        """Load full existing config (tasks + descriptions) from todos.yaml."""
        if not os.path.exists(self.todos_file):
            return {}
        try:
            with open(self.todos_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            if config and isinstance(config, dict):
                return config
        except Exception as e:
            logger.error(f"Failed to load todos file: {e}")
        return {}

    def _append_tasks_to_todos(self, parsed_data: dict, next_id: int = 1):
        """
        Append new tasks to todos.yaml.
        
        If the file doesn't exist, creates it with proper structure.
        If it exists, reads existing tasks and appends new ones.
        
        For the first batch (next_id == 1), the root-level ``description``
        field is written.  For later batches, a round-scoped
        ``description@{next_id}`` field is used instead.
        
        Args:
            parsed_data: dict containing 'tasks' and optionally
                'description' or 'description@{next_id}'
            next_id: Starting task ID for this batch (used for
                round-scoped description key)
        """
        new_tasks = parsed_data.get('tasks', [])
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
        
        # Handle description: first batch uses root-level, later batches use round-scoped
        # DEFENSIVE: Never overwrite existing descriptions to preserve user context
        if next_id == 1:
            new_description = parsed_data.get('description', '')
            if new_description:
                if 'description' not in config:
                    config['description'] = new_description
                else:
                    logger.warning(
                        f"Root 'description' already exists in {self.todos_file}; "
                        f"skipping overwrite (next_id={next_id}). Existing description preserved."
                    )
        else:
            scoped_key = f'description@{next_id}'
            new_description = parsed_data.get(scoped_key, '')
            if new_description:
                if scoped_key not in config:
                    config[scoped_key] = new_description
                else:
                    logger.warning(
                        f"Description field '{scoped_key}' already exists in {self.todos_file}; "
                        f"skipping overwrite to preserve existing context. "
                        f"Use a different next_id to add new descriptions."
                    )

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
