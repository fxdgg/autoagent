#!/usr/bin/env python3
"""
AutoAgent - Main entry point.

An intelligent task orchestration system that uses CodeBuddy AI to
automatically execute, evaluate, and iterate on tasks defined in YAML.

Usage:
    python orchestrator.py                     # Run all tasks
    python orchestrator.py --config my.yaml    # Use custom config file
    python orchestrator.py --task 2            # Run only task 2
    python orchestrator.py --reset             # Reset all state
"""

import os
import sys
import csv
import json
import time
import shutil
import string
import random
import argparse
import logging
import yaml
from typing import Optional, List

from codebuddy_client import AIClient, AIClientSDK, AIClientTest, AICallError
from ai_providers import get_provider, list_providers, AIProvider, TestProvider, parse_model_spec
from task_executor import (
    SimpleTaskExecutor,
    NestedTaskExecutor,
    LoopingTaskExecutor,
    SubtaskExecutor,
    ConfigError,
    ExecutionError,
)
from state_manager import StateManager
from conversation_logger import ConversationLogger
from ideas_watcher import IdeasWatcher
from prompts.scheduler import (
    build_scheduler_prompt,
    save_response_result,
    SCHEDULER_SYSTEM_PROMPT,
    _get_response_result_path,
)

logger = logging.getLogger(__name__)


class _ScheduleAwareConvLogger:
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


class TodoOrchestrator:
    """
    Main orchestrator class that manages task loading, scheduling, and execution.
    
    Responsibilities:
    - Parse and validate todos.yaml configuration
    - Schedule task execution in order
    - Delegate to appropriate executors (SimpleTaskExecutor, NestedTaskExecutor)
    - Manage state persistence via StateManager
    - Create AIClient instances per main task for context isolation
    """

    # ── Session management helpers ──────────────────────────────────

    SESSIONS_FILE = "sessions.csv"

    @staticmethod
    def _generate_session_name(workspace: str) -> str:
        """Generate a new session directory name: ``<basename>_<random8>``."""
        basename = os.path.basename(os.path.abspath(workspace))
        rand_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        return f"{basename}_{rand_suffix}"

    @staticmethod
    def _read_marker(workspace: str) -> str:
        """Read the session subdir name from ``.autoagent_log``.

        Returns the name (e.g. ``cufftdx_optimization_4jvowsl3``)
        or empty string if the marker doesn't exist or is empty.
        """
        marker = os.path.join(workspace, ".autoagent_log")
        if os.path.exists(marker):
            try:
                with open(marker, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                pass
        return ""

    @staticmethod
    def _write_marker(workspace: str, subdir_name: str):
        """Write *subdir_name* into ``<workspace>/.autoagent_log``."""
        marker = os.path.join(workspace, ".autoagent_log")
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write(subdir_name + "\n")
        except Exception as e:
            logger.warning(f"Failed to write {marker}: {e}")

    @staticmethod
    def _append_sessions_csv(log_dir: str, subdir_name: str, workspace: str):
        """Append a row to ``<log_dir>/sessions.csv``."""
        csv_path = os.path.join(log_dir, TodoOrchestrator.SESSIONS_FILE)
        write_header = not os.path.exists(csv_path)
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(csv_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                if write_header:
                    writer.writerow(["session_id", "workspace", "created_at"])
                writer.writerow([
                    subdir_name,
                    workspace,
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                ])
        except Exception as e:
            logger.warning(f"Failed to append to {csv_path}: {e}")

    @staticmethod
    def _load_sessions_csv(log_dir: str) -> list:
        """Load all rows from ``sessions.csv``.

        Returns a list of dicts with keys ``session_id``, ``workspace``,
        ``created_at``.
        """
        csv_path = os.path.join(log_dir, TodoOrchestrator.SESSIONS_FILE)
        if not os.path.isfile(csv_path):
            return []
        rows = []
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    rows.append(row)
        except Exception as e:
            logger.warning(f"Failed to read {csv_path}: {e}")
        return rows

    @staticmethod
    def resolve_session_dir(
        log_dir: str,
        workspace: str,
        mode: str = "new",
        resume_id: str = None,
    ) -> str:
        """Resolve the session directory path.

        Args:
            log_dir: Absolute path to the log root (e.g. ``.autoagent``).
            workspace: Absolute path to the workspace.
            mode: One of ``"new"``, ``"continue"``, ``"resume"``.
            resume_id: Session suffix or full name (only for ``mode="resume"``).

        Returns:
            Absolute path to the session directory.

        Raises:
            SystemExit on error (no marker, session not found, etc.)
        """
        cls = TodoOrchestrator

        if mode == "continue":
            subdir = cls._read_marker(workspace)
            if not subdir:
                print("❌ No active session found (.autoagent_log missing or empty).")
                print("   Use --resume <session_id> or run without --continue to start fresh.")
                sys.exit(1)
            session_dir = os.path.join(log_dir, subdir)
            if not os.path.isdir(session_dir):
                print(f"❌ Session directory not found: {session_dir}")
                print(f"   The session '{subdir}' may have been deleted.")
                sys.exit(1)
            return session_dir

        if mode == "resume":
            if not resume_id:
                print("❌ --resume requires a session ID.")
                sys.exit(1)
            # Search sessions.csv
            rows = cls._load_sessions_csv(log_dir)
            matches = []
            for row in rows:
                sid = row.get("session_id", "")
                # Match by full name or by suffix (the random part)
                if sid == resume_id or sid.endswith(f"_{resume_id}"):
                    matches.append(sid)
            if not matches:
                # Also try scanning log_dir directly
                if os.path.isdir(log_dir):
                    for d in os.listdir(log_dir):
                        if d == resume_id or d.endswith(f"_{resume_id}"):
                            matches.append(d)
            if not matches:
                print(f"❌ Session '{resume_id}' not found.")
                print(f"   Use --list-sessions to see available sessions.")
                sys.exit(1)
            if len(matches) > 1:
                print(f"❌ Ambiguous session ID '{resume_id}', matches: {matches}")
                print(f"   Please use the full session ID.")
                sys.exit(1)
            subdir = matches[0]
            session_dir = os.path.join(log_dir, subdir)
            if not os.path.isdir(session_dir):
                print(f"❌ Session directory not found: {session_dir}")
                sys.exit(1)
            # Update .autoagent_log to point to this session
            cls._write_marker(workspace, subdir)
            return session_dir

        # mode == "new"
        subdir = cls._generate_session_name(workspace)
        cls._write_marker(workspace, subdir)
        cls._append_sessions_csv(log_dir, subdir, workspace)
        return os.path.join(log_dir, subdir)

    @staticmethod
    def _get_session_status(session_dir: str) -> str:
        """Read todos_state.yaml and return a brief status string.

        Examples: ``"1.2 (round 3/10)"``, ``"completed"``, ``"no state"``.
        """
        state_file = os.path.join(session_dir, "todos_state.yaml")
        if not os.path.isfile(state_file):
            return "no state"
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = yaml.safe_load(f)
        except Exception:
            return "error reading state"
        if not state or "tasks" not in state:
            return "empty"

        # Check for AI orchestrator state
        orch = state.get("orchestrator")
        if orch:
            orch_status = orch.get("status", "unknown")
            cr = orch.get("current_round", 0)
            mr = orch.get("max_rounds", "?")
            if orch_status in ("completed", "stopped"):
                return f"ai_sched: {orch_status} ({cr}/{mr} rounds)"
            return f"ai_sched: round {cr}/{mr}"

        tasks = state["tasks"]
        # Find the deepest in_progress task
        in_progress = None
        for key, val in tasks.items():
            if val.get("status") == "in_progress":
                # Prefer the one with the longest key (deepest subtask)
                if in_progress is None or len(key) > len(in_progress[0]):
                    in_progress = (key, val)

        if in_progress:
            key, val = in_progress
            # Strip round-scoped suffix for display
            display_id = key.split("@")[0] if "@" in key else key
            round_info = ""
            cr = val.get("current_round")
            mr = val.get("max_attempts") or val.get("repeat_count")
            if cr and mr:
                round_info = f" (round {cr}/{mr})"
            return f"{display_id}{round_info}"

        # Check if all top-level tasks are completed
        top_tasks = {k: v for k, v in tasks.items() if "@" not in k and "." not in k}
        if top_tasks and all(v.get("status") == "completed" for v in top_tasks.values()):
            return "completed"

        # Some tasks pending, none in progress
        return "pending"

    def __init__(
        self,
        todos_file: str = "todos.yaml",
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        bash_timeout: int = 300,
        session_dir: str = None,
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = 30,
        use_cli: bool = False,
        backoff_max_wait: int = 300,
        model_roles: dict = None,
    ):
        """
        Initialize the TodoOrchestrator.

        Args:
            todos_file: Path to the task configuration YAML
            provider: AI provider instance
            workspace: Working directory for AI tool
            timeout: Default session timeout for AI calls (hard cap on
                total session time).
            bash_timeout: No-new-output timeout for AI calls.  If the AI
                produces no new output for this many seconds, the session
                is killed and the next prompt includes long-running guidance.
            session_dir: Pre-resolved session directory (absolute path).
                If provided, ``log_dir`` is ignored.  Use
                ``resolve_session_dir()`` to compute this.
            log_dir: Root directory for all output files.  Only used when
                ``session_dir`` is None (fallback: resolve via
                ``.autoagent_log`` marker — for backward compat with tests).
            ideas_file: Path to ideas.md file (None to disable ideas watching)
            idle_interval: Seconds between idle checks for new ideas (default: 30)
            use_cli: If True, use CLI subprocess instead of CodeBuddy Agent SDK
                     (only valid when provider is codebuddy)
            backoff_max_wait: Max wait time (seconds) for exponential backoff
                     when AI CLI calls fail repeatedly (default: 300)
            model_roles: Model role dict ({"plan": ..., "default": ..., "lite": ...}),
                     parsed by parse_model_spec(). None uses provider's default model.
        """
        self.todos_file = todos_file
        self.workspace = os.path.abspath(workspace)
        self.timeout = timeout
        self.bash_timeout = bash_timeout
        self.idle_interval = idle_interval
        self.use_cli = use_cli
        self.backoff_max_wait = backoff_max_wait

        self.provider = provider

        self.model_roles = model_roles or {
            "plan": self.provider.model,
            "default": self.provider.model,
            "lite": self.provider.model,
            "evaluation": self.provider.model,
            "scheduler": self.provider.model,
        }

        # ── Resolve session log directory ──────────────────────────
        if session_dir:
            self.session_dir = session_dir
        else:
            # Fallback for tests and simple usage: read .autoagent_log
            if log_dir is None:
                log_dir = os.path.abspath(".autoagent")
            else:
                log_dir = os.path.abspath(log_dir)
            subdir = self._read_marker(self.workspace)
            if subdir:
                self.session_dir = os.path.join(log_dir, subdir)
            else:
                self.session_dir = self.resolve_session_dir(
                    log_dir, self.workspace, mode="new"
                )
        os.makedirs(self.session_dir, exist_ok=True)

        # Derived paths inside the session directory
        resolved_state_file = os.path.join(self.session_dir, "todos_state.yaml")
        resolved_plans_state = os.path.join(self.session_dir, "plans_state.yaml")

        self.state_manager = StateManager(resolved_state_file)
        self.conv_logger = ConversationLogger(self.session_dir)
        self.simple_executor = SimpleTaskExecutor(session_dir=self.session_dir)
        self.nested_executor = NestedTaskExecutor(session_dir=self.session_dir, model_roles=self.model_roles)
        self.looping_executor = LoopingTaskExecutor(session_dir=self.session_dir, model_roles=self.model_roles)
        
        # Ideas watcher (optional)
        if ideas_file:
            self.ideas_watcher = IdeasWatcher(
                ideas_file=ideas_file,
                todos_file=todos_file,
                plans_state_file=resolved_plans_state,
            )
        else:
            self.ideas_watcher = None

        self.project_description = ''
        self.scoped_descriptions = {}
        self.ai_orchestrator = None  # Populated by _load_todos if ai_orchestrator is present
        self.todos = self._load_todos(allow_empty=self.ideas_watcher is not None)

    def _load_todos(self, allow_empty: bool = False) -> list:
        """
        Load and validate task configuration from YAML file.

        Also extracts the optional root-level ``description`` field and
        stores it in ``self.project_description``.
        
        Args:
            allow_empty: If True, allow empty/missing config (for idle mode)
        
        Returns:
            list: List of task configurations
            
        Raises:
            ConfigError: If the file is invalid
        """
        if not os.path.exists(self.todos_file):
            if allow_empty:
                logger.info(f"Config file {self.todos_file} not found, starting with empty task list")
                return []
            raise ConfigError(f"Configuration file not found: {self.todos_file}")
        
        try:
            with open(self.todos_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML syntax error in {self.todos_file}: {e}")
        
        if not config or not isinstance(config, dict):
            if allow_empty:
                return []
            raise ConfigError(f"Invalid configuration format in {self.todos_file}")
        
        tasks = config.get('tasks', [])
        if not tasks:
            if allow_empty:
                return []
            raise ConfigError(f"No tasks defined in {self.todos_file}")

        # Extract optional root-level project description
        description = config.get('description', '')
        if description and not isinstance(description, str):
            raise ConfigError(f"'description' must be a string in {self.todos_file}")
        self.project_description = description or ''

        # Extract round-scoped descriptions (description@N)
        self.scoped_descriptions = {}
        for key, val in config.items():
            if key.startswith('description@'):
                if val and not isinstance(val, str):
                    raise ConfigError(f"'{key}' must be a string in {self.todos_file}")
                try:
                    scope_id = int(key.split('@')[1])
                    if val:
                        self.scoped_descriptions[scope_id] = val
                except (ValueError, IndexError):
                    raise ConfigError(f"Invalid round-scoped description key '{key}' in {self.todos_file}")

        # Extract optional ai_orchestrator configuration
        ai_orch = config.get('ai_orchestrator')
        if ai_orch is not None:
            self.ai_orchestrator = self._validate_ai_orchestrator(ai_orch, tasks)
        else:
            self.ai_orchestrator = None

        # Validate each task
        for task in tasks:
            self._validate_task(task)
        
        logger.info(f"Loaded {len(tasks)} tasks from {self.todos_file}")
        return tasks

    def reload_todos(self):
        """
        Reload task configuration from the YAML file.
        
        Used after new tasks have been appended (e.g. from ideas processing).
        """
        try:
            self.todos = self._load_todos(allow_empty=self.ideas_watcher is not None)
            logger.info(f"Reloaded {len(self.todos)} tasks from {self.todos_file}")
        except ConfigError as e:
            logger.error(f"Failed to reload todos: {e}")

    def _get_description_for_task(self, task_id) -> str:
        """Return the most relevant description for a given task ID.

        Finds the round-scoped description with the largest scope_id <= task_id.
        Falls back to root-level description if no scoped match exists.
        """
        if not self.scoped_descriptions:
            return self.project_description

        # Convert task_id to int for comparison (handles float IDs like 1.0)
        try:
            tid = int(task_id)
        except (ValueError, TypeError):
            return self.project_description

        best_scope = None
        for scope_id in sorted(self.scoped_descriptions.keys()):
            if scope_id <= tid:
                best_scope = scope_id

        if best_scope is not None:
            return self.scoped_descriptions[best_scope]
        return self.project_description

    def _get_latest_description(self) -> str:
        """Return the latest project description for AI scheduling mode.

        In AI scheduling mode, the description is always the latest
        scoped description (largest scope_id <= max defined task_id).
        Falls back to root-level description if no scoped match exists.
        """
        if not self.scoped_descriptions:
            return self.project_description

        # Find the maximum task_id defined in todos
        max_task_id = 0
        for task in self.todos:
            try:
                tid = int(task['id'])
                if tid > max_task_id:
                    max_task_id = tid
            except (ValueError, TypeError):
                pass

        best_scope = None
        for scope_id in sorted(self.scoped_descriptions.keys()):
            if scope_id <= max_task_id:
                best_scope = scope_id

        if best_scope is not None:
            return self.scoped_descriptions[best_scope]
        return self.project_description

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

        # Validate that all tasks have a description in AI scheduling mode
        for task in tasks:
            if not task.get('description'):
                raise ConfigError(
                    f"Task {task['id']} is missing required 'description' field "
                    f"(required in AI orchestrator mode)"
                )

        return {
            'strategy': strategy,
            'max_rounds': max_rounds,
            'stop_condition': stop_condition or '',
            'last_result': normalized_last_result,
        }

    def _validate_task(self, task: dict, is_subtask: bool = False):
        """
        Validate a task configuration.
        
        Args:
            task: Task configuration dict
            is_subtask: Whether this is a subtask
            
        Raises:
            ConfigError: If validation fails
        """
        # Required fields
        required_fields = ['id', 'name', 'type', 'completion_criteria']
        for field in required_fields:
            if field not in task:
                raise ConfigError(
                    f"Task {task.get('id', '?')} missing required field: {field}"
                )
        
        task_type = task['type']
        
        # Validate task type
        if is_subtask:
            valid_types = ['simple', 'long_running', 'simple_once', 'long_running_once',
                           'nested', 'looping']
        else:
            valid_types = ['simple', 'nested', 'looping', 'long_running']
        
        if task_type not in valid_types:
            raise ConfigError(
                f"Task {task['id']} has invalid type: {task_type}. "
                f"Valid types: {valid_types}"
            )
        
        # Validate nested tasks
        if task_type == 'nested':
            subtasks = task.get('subtasks', [])
            if not subtasks:
                raise ConfigError(
                    f"Nested task {task['id']} must have subtasks"
                )
            for subtask in subtasks:
                self._validate_task(subtask, is_subtask=True)
        
        # Validate looping tasks
        if task_type == 'looping':
            subtasks = task.get('subtasks', [])
            if not subtasks:
                raise ConfigError(
                    f"Looping task {task['id']} must have subtasks"
                )
            repeat_count = task.get('repeat_count')
            if repeat_count is None:
                raise ConfigError(
                    f"Looping task {task['id']} must have 'repeat_count' field"
                )
            if not isinstance(repeat_count, int) or repeat_count < 1:
                raise ConfigError(
                    f"Looping task {task['id']}: repeat_count must be a positive integer"
                )
            for subtask in subtasks:
                self._validate_task(subtask, is_subtask=True)
        
        # Validate long_running tasks
        # Note: long_running tasks no longer require a 'command' field.
        # The AI decides the command at runtime via autoagent-exec.

        # Validate optional model field
        model = task.get('model')
        if model is not None and not isinstance(model, str):
            raise ConfigError(
                f"Task {task['id']} has invalid model: '{model}'. "
                f"Must be a string: 'default', 'lite', or a direct model name"
            )

    def validate_config(self) -> bool:
        """
        Validate the loaded configuration.
        
        Returns:
            bool: True if valid
        """
        try:
            for task in self.todos:
                self._validate_task(task)
            return True
        except ConfigError as e:
            print(f"❌ Configuration error: {e}")
            return False

    def run(
        self,
        task_id: int = None,
    ) -> dict:
        """
        Run tasks from the configuration (linear mode).
        
        Args:
            task_id: Execute only this task (None = all tasks)
            
        Returns:
            dict: Execution results summary
        """
        # Check for mode conflict: linear mode with existing orchestrator state
        orch_state = self.state_manager.get_orchestrator_state()
        if orch_state:
            raise ConfigError(
                "Cannot run in linear mode: existing AI orchestrator state found. "
                "Use --reset to clear state before switching modes."
            )

        start_time = time.time()
        results = {}
        
        # Determine which tasks to run
        if task_id is not None:
            tasks_to_run = [t for t in self.todos if str(t['id']) == str(task_id)]
            if not tasks_to_run:
                print(f"❌ Task {task_id} not found")
                return {"total_tasks": 0, "successful_tasks": 0, "failed_tasks": 0, "results": {}}
        else:
            tasks_to_run = self.todos
        
        print(f"{'=' * 60}")
        print(f"  AutoAgent")
        print(f"  Tasks to execute: {len(tasks_to_run)}")
        print(f"  Config: {self.todos_file}")
        print(f"  Provider: {self.provider.name}")
        print(f"  Model: {self.provider.model}")
        print(f"{'=' * 60}")
        
        for task in tasks_to_run:
            tid = str(task['id'])
            
            # Check if task is already completed
            task_state = self.state_manager.get_task_state(tid)
            if task_state.get('status') == 'completed':
                print(f"\n⏭️  Task {tid}: {task['name']} (already completed, skipping)")
                results[tid] = True
                continue
            
            print(f"\n{'─' * 60}")
            print(f"📋 Task {tid}: {task['name']}")
            print(f"   Type: {task['type']}")
            print(f"   Criteria: {task['completion_criteria'][:100]}...")
            print(f"{'─' * 60}")
            
            try:
                success = self.execute_task(task)
                results[tid] = success
                
                if success:
                    print(f"\n✅ Task {tid} completed successfully!")
                else:
                    print(f"\n❌ Task {tid} failed!")
                    
            except Exception as e:
                logger.error(f"Unexpected error executing task {tid}: {e}", exc_info=True)
                print(f"\n❌ Task {tid} error: {e}")
                results[tid] = False
        
        duration = time.time() - start_time
        successful = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)
        
        print(f"\n{'=' * 60}")
        print(f"  Execution Summary")
        print(f"  Total: {len(results)} | ✅ Success: {successful} | ❌ Failed: {failed}")
        print(f"  Duration: {duration:.1f}s")
        print(f"{'=' * 60}")
        
        return {
            "total_tasks": len(results),
            "successful_tasks": successful,
            "failed_tasks": failed,
            "results": results,
            "duration": duration,
        }

    # ── AI Orchestrator scheduling loop ─────────────────────────────

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

        config = _load_config()
        scheduler_history_limit = config.get('scheduler_history_limit', 10)
        scheduler_decision_max_retries = config.get('scheduler_decision_max_retries', 3)

        strategy = ai_orch['strategy']
        max_rounds = ai_orch['max_rounds']
        stop_condition = ai_orch['stop_condition']
        last_result_config = ai_orch['last_result']

        start_time = time.time()

        # ── Initialize or restore orchestrator state ──────────────
        orch_state = self.state_manager.get_orchestrator_state()
        if not orch_state:
            # Fresh start
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
                        self.state_manager.save_orchestrator_state(orch_state)

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

        while current_round < max_rounds:
            current_round += 1
            orch_state['current_round'] = current_round
            self.state_manager.save_orchestrator_state(orch_state)

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
                orch_state=orch_state,
            )

            if decision is None:
                # Failed to get a valid decision after retries
                print(f"\n❌ Scheduler failed to produce a valid decision. Stopping.")
                orch_state['status'] = 'stopped'
                self.state_manager.save_orchestrator_state(orch_state)
                break

            action = decision.get('action')
            reasoning = decision.get('reasoning', '')

            if action == 'stop':
                print(f"\n🛑 Scheduler decided to stop: {reasoning}")
                schedule_history.append({
                    'round': current_round,
                    'task_id': None,
                    'task_name': None,
                    'result': 'stopped',
                    'reasoning': reasoning,
                    'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                orch_state['status'] = 'stopped'
                orch_state['schedule_history'] = schedule_history
                self.state_manager.save_orchestrator_state(orch_state)
                break

            # action == 'execute'
            selected_task_id = str(decision.get('task_id'))
            selected_task = next(
                (t for t in self.todos if str(t['id']) == selected_task_id), None
            )
            if not selected_task:
                print(f"\n❌ Scheduler selected non-existent task {selected_task_id}. Stopping.")
                orch_state['status'] = 'stopped'
                self.state_manager.save_orchestrator_state(orch_state)
                break

            print(f"\n📋 Scheduler selected: Task {selected_task_id} ({selected_task['name']})")
            print(f"   Reasoning: {reasoning}")

            # Record the scheduling decision (result=None until task completes)
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

            results[f"round_{current_round}"] = success

            if success:
                print(f"\n✅ Task {selected_task_id} completed successfully!")
            else:
                print(f"\n❌ Task {selected_task_id} failed!")

        else:
            # Reached max_rounds
            print(f"\n⚠️  Reached maximum scheduling rounds ({max_rounds})")
            orch_state['status'] = 'completed'
            self.state_manager.save_orchestrator_state(orch_state)

        duration = time.time() - start_time
        successful = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)

        print(f"\n{'=' * 60}")
        print(f"  AI Orchestrator Summary")
        print(f"  Rounds: {current_round}/{max_rounds}")
        print(f"  ✅ Success: {successful} | ❌ Failed: {failed}")
        print(f"  Duration: {duration:.1f}s")
        print(f"{'=' * 60}")

        return {
            "total_tasks": len(results),
            "successful_tasks": successful,
            "failed_tasks": failed,
            "results": results,
            "duration": duration,
        }

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
        orch_state: dict,
    ) -> dict | None:
        """Call the AI scheduler to get the next scheduling decision.

        Creates a fresh AI client for each scheduling round. Retries
        on invalid JSON or invalid task_id up to *max_retries* times.

        Args:
            current_round: Current round number.
            max_rounds: Maximum rounds.
            project_description: Project description text.
            strategy: Scheduling strategy text.
            stop_condition: Stop condition text.
            last_result_config: Last result configuration dict.
            task_execution_counts: Dict of task_id -> execution count.
            schedule_history: List of schedule history entries.
            scheduler_history_limit: Max history entries in prompt.
            max_retries: Max retries for invalid decisions.
            orch_state: Orchestrator state dict (for session_id persistence).

        Returns:
            Parsed decision dict, or None if all retries exhausted.
        """
        # Switch to scheduler model
        scheduler_model = self.model_roles.get('scheduler', self.model_roles['default'])
        original_model = self.provider.model
        self.provider.set_model(scheduler_model)

        # Create a fresh AI client for this scheduling round
        context_id = f"scheduler_round_{current_round}"
        client = self._create_ai_client(context_id)

        # Check if we should resume a previous scheduler session
        saved_session_id = orch_state.get('session_id', '')
        if saved_session_id:
            client.resume_session(saved_session_id)
            logger.info(f"Resuming scheduler session: {saved_session_id}")

        # Track session_id changes
        def on_session_id_changed(new_session_id: str):
            orch_state['session_id'] = new_session_id
            self.state_manager.save_orchestrator_state(orch_state)

        client._on_session_id_changed = on_session_id_changed

        # Build the scheduler prompt
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

        valid_task_ids = {str(t['id']) for t in self.todos}

        # Log the scheduler prompt
        if self.conv_logger:
            self.conv_logger.log_prompt(
                task_id="scheduler",
                task_name="AI Scheduler",
                prompt=prompt,
                attempt=str(current_round),
                system_prompt=SCHEDULER_SYSTEM_PROMPT,
            )

        decision = None
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
                    self.conv_logger.log_response(
                        task_id="scheduler",
                        response=response,
                        attempt=str(current_round),
                    )

                # Parse JSON from response
                decision = self._parse_scheduler_response(response)
                if decision is None:
                    error_msg = "Could not parse a valid JSON decision from your response."
                    logger.warning(f"Scheduler round {current_round}: invalid JSON (retry {retry})")
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

                # Valid decision
                break

            except AICallError as e:
                logger.error(f"Scheduler AI call failed: {e}")
                decision = None
                break

        # Clear scheduler session_id for next round (each round gets fresh session)
        orch_state['session_id'] = ''
        self.state_manager.save_orchestrator_state(orch_state)

        # Restore original model
        self.provider.set_model(original_model)

        return decision

    def _parse_scheduler_response(self, response: str) -> dict | None:
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
        import re
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

    def _create_ai_client(self, context_id: str):
        """Create an AI client instance for the given context.

        Centralizes client creation logic used by both task execution
        and scheduler.

        Args:
            context_id: Context identifier for the client.

        Returns:
            An AIClient, AIClientSDK, or AIClientTest instance.
        """
        if isinstance(self.provider, TestProvider):
            client = AIClientTest(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
            )
            client._fallback_exec_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "autoagent_exec.py"
            )
            client._fallback_log_dir = self.session_dir
        elif self.use_cli:
            client = AIClient(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
            )
            client._backoff_max = self.backoff_max_wait
        else:
            client = AIClientSDK(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
            )
            client._backoff_max = self.backoff_max_wait
        return client

    def _execute_scheduled_task(
        self,
        task: dict,
        schedule_round: int,
        task_execution_counts: dict,
    ) -> bool:
        """Execute a task within the AI scheduling context.

        Creates a fresh AI client (new session) for the task. Uses
        schedule-round-prefixed task IDs for state isolation.

        Args:
            task: Task configuration dict.
            schedule_round: Current schedule round number.
            task_execution_counts: Dict of task_id -> execution count.

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
        client = self._create_ai_client(context_id)

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
            sched_conv_logger = _ScheduleAwareConvLogger(
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

    def _build_scheduled_task(self, task: dict, schedule_round: int) -> dict:
        """Build a task dict with schedule-round-prefixed IDs.

        For simple tasks, the ID becomes ``{schedule_round}.{task_id}``.
        For nested/looping tasks, subtask IDs become
        ``{schedule_round}.{task_id}.{subtask_id_suffix}``.

        Args:
            task: Original task configuration dict.
            schedule_round: Current schedule round number.

        Returns:
            Modified task dict with prefixed IDs.
        """
        import copy
        scheduled = copy.deepcopy(task)
        original_id = str(task['id'])
        scheduled['id'] = f"{schedule_round}.{original_id}"

        # Prefix subtask IDs for nested/looping tasks
        if task['type'] in ('nested', 'looping'):
            subtasks = scheduled.get('subtasks', [])
            for st in subtasks:
                original_st_id = str(st['id'])
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
                    self._prefix_subtask_ids(st, schedule_round, original_id)

        return scheduled

    def _prefix_subtask_ids(self, task: dict, schedule_round: int, root_task_id: str):
        """Recursively prefix subtask IDs for deeply nested tasks.

        Args:
            task: Task/subtask dict to process.
            schedule_round: Current schedule round number.
            root_task_id: The root task ID for prefix construction.
        """
        subtasks = task.get('subtasks', [])
        for st in subtasks:
            original_st_id = str(st['id'])
            # Keep the relative structure but add schedule_round prefix
            parts = original_st_id.split('.', 1)
            if len(parts) == 2:
                st['id'] = f"{schedule_round}.{parts[0]}.{parts[1]}"
            if st.get('type') in ('nested', 'looping'):
                self._prefix_subtask_ids(st, schedule_round, root_task_id)

    def _save_task_response_result(self, task_id: str, task_type: str, success: bool):
        """Save the task's response to a result file if configured as type=response.

        Args:
            task_id: Original task ID (not schedule-prefixed).
            task_type: Task type string.
            success: Whether the task completed successfully.
        """
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
            subtask_exec = getattr(nested_exec, '_subtask_executor', None)
            if subtask_exec:
                simple_exec = getattr(subtask_exec, '_simple_executor', None)
                if simple_exec:
                    response_text = getattr(simple_exec, 'last_response_text', '')

        if response_text:
            from truncation_limits import limits
            save_response_result(
                task_id=task_id,
                response_text=response_text,
                session_dir=self.session_dir,
                max_length=limits.get('previous_subtask_summary'),
            )

    def execute_task(self, task: dict) -> bool:
        """
        Execute a single task, dispatching to the appropriate executor.
        
        Each main task gets its own AIClient for context isolation.
        
        Args:
            task: Task configuration dict
            
        Returns:
            bool: True if task completed successfully
        """
        task_id = str(task['id'])
        task_type = task['type']

        # Switch model based on task's model field (default/lite or direct model name)
        task_model_role = task.get('model', 'default')
        if task_model_role in self.model_roles:
            task_model = self.model_roles[task_model_role]
        else:
            # Treat as a direct model name
            task_model = task_model_role
        self.provider.set_model(task_model)
        
        # Create a new AIClient for this main task (context isolation)
        context_id = f"task_{task_id}"
        
        # Check if this task was interrupted and has a saved session_id
        task_state = self.state_manager.get_task_state(task_id)
        saved_session_id = task_state.get("session_id", "")
        
        if isinstance(self.provider, TestProvider):
            client = AIClientTest(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
            )
            # Set fallback paths so TestClient can execute autoagent-exec
            # even when the prompt doesn't contain them (e.g. simple tasks
            # where AI remembers the paths from context)
            client._fallback_exec_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "autoagent_exec.py"
            )
            client._fallback_log_dir = self.session_dir
        elif self.use_cli:
            client = AIClient(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
            )
            client._backoff_max = self.backoff_max_wait
        else:
            client = AIClientSDK(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id=context_id,
            )
            client._backoff_max = self.backoff_max_wait
        
        # Resume session if we have a saved session_id
        if saved_session_id:
            client.resume_session(saved_session_id)
            print(f"   🔄 Resuming session: {saved_session_id}")
        
        # Set up callback to save session_id when it changes
        def on_session_id_changed(new_session_id: str):
            self.state_manager.update_task_field(task_id, "session_id", new_session_id)
        
        client._on_session_id_changed = on_session_id_changed
        
        # Record context info in state
        self.state_manager.mark_task_status(
            task_id, "in_progress",
            context_id=context_id,
            context_created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        
        try:
            task_description = self._get_description_for_task(task_id)
            if task_type == 'simple':
                return self.simple_executor.execute(
                    task, client, self.state_manager, is_subtask=False,
                    conv_logger=self.conv_logger,
                    project_description=task_description,
                )
            elif task_type == 'nested':
                return self.nested_executor.execute(
                    task, client, self.state_manager,
                    conv_logger=self.conv_logger,
                    project_description=task_description,
                )
            elif task_type == 'looping':
                return self.looping_executor.execute(
                    task, client, self.state_manager,
                    conv_logger=self.conv_logger,
                    project_description=task_description,
                )
            elif task_type == 'long_running':
                lr_executor = SubtaskExecutor(
                    session_dir=self.session_dir,
                    model_roles=self.model_roles,
                )
                result = lr_executor._execute_long_running_subtask(
                    task, client, self.state_manager,
                    conv_logger=self.conv_logger,
                    parent_task_id=None,
                    parent_context={
                        'project_description': task_description,
                    },
                )
                return result.success
            else:
                raise ConfigError(f"Unknown task type: {task_type}")
                
        except KeyboardInterrupt:
            # Save session_id and mark interrupt so the next run can
            # continue in the same session with a lightweight follow-up
            # instead of resetting and replaying the full task prompt.
            if client.session_id:
                self.state_manager.update_task_field(
                    task_id, "session_id", client.session_id
                )
                self.state_manager.update_task_field(
                    task_id, "interrupt_pending", True
                )
                logger.info(
                    f"Saved session_id {client.session_id} for interrupted task {task_id} "
                    f"(interrupt_pending=True)"
                )
            raise
        except ConfigError as e:
            print(f"   ❌ Configuration error: {e}")
            self.state_manager.mark_task_status(task_id, "failed", error=str(e))
            return False
        except ExecutionError as e:
            print(f"   ❌ Execution error: {e}")
            self.state_manager.mark_task_status(task_id, "failed", error=str(e))
            return False
        except AICallError as e:
            print(f"   ❌ AI call error: {e}")
            self.state_manager.mark_task_status(task_id, "failed", error=str(e))
            return False

    def reset(self):
        """Reset all task states by removing the entire session directory."""
        import shutil

        # Close file handlers first to avoid "file in use" errors on Windows
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.close()
                root_logger.removeHandler(handler)

        # Remove the entire session directory
        if os.path.exists(self.session_dir):
            shutil.rmtree(self.session_dir)
            print(f"  Removed: {self.session_dir}")

        # Remove the .autoagent_log marker so a fresh session is created next run
        marker_file = os.path.join(self.workspace, ".autoagent_log")
        if os.path.exists(marker_file):
            os.remove(marker_file)
            print(f"  Removed: {marker_file}")

        print("✅ All task states have been reset.")

    def check_and_process_ideas(self, human_review: bool = False) -> int:
        """
        Check for new ideas in ideas.md and process them into TODO tasks.
        
        Args:
            human_review: If True, pause for human approval after AI review passes.
        
        Returns:
            int: Number of new ideas processed (0 if no watcher or no new ideas)
        """
        if not self.ideas_watcher:
            return 0
        
        if not self.ideas_watcher.has_new_ideas():
            return 0
        
        print(f"\n{'─' * 60}")
        print(f"💡 New ideas detected, processing...")
        print(f"{'─' * 60}")

        # Switch to plan model for ideas processing
        original_model = self.provider.model
        plan_model = self.model_roles.get("plan", original_model)
        self.provider.set_model(plan_model)
        
        # Create a client for ideas processing
        if isinstance(self.provider, TestProvider):
            client = AIClientTest(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id="ideas_processor",
            )
            # Review client uses the same TestProvider (shared rule sequence)
            review_client = AIClientTest(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id="ideas_reviewer",
            )
        elif self.use_cli:
            client = AIClient(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id="ideas_processor",
            )
            client._backoff_max = self.backoff_max_wait
            review_client = AIClient(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id="ideas_reviewer",
            )
            review_client._backoff_max = self.backoff_max_wait
        else:
            client = AIClientSDK(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id="ideas_processor",
            )
            client._backoff_max = self.backoff_max_wait
            review_client = AIClientSDK(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                bash_timeout=self.bash_timeout,
                context_id="ideas_reviewer",
            )
            review_client._backoff_max = self.backoff_max_wait
        
        count = self.ideas_watcher.process_new_ideas(
            client,
            review_client=review_client,
            conv_logger=self.conv_logger,
            human_review=human_review,
        )

        # Restore original model after ideas processing
        self.provider.set_model(original_model)
        
        if count > 0:
            print(f"\n   📝 Processed {count} new idea(s), reloading task list...")
            self.reload_todos()
        
        return count

    def run_with_idle(
        self,
        task_id: int = None,
    ):
        """
        Run tasks, then enter idle mode waiting for new ideas.
        
        This method:
        1. Processes any existing new ideas first
        2. Runs all pending tasks
        3. Enters idle loop: periodically checks ideas.md for new content
        4. When new ideas appear, converts them to tasks and executes them
        5. Repeats until interrupted by user (Ctrl+C)
        
        Args:
            task_id: Execute only this task (None = all tasks)
        """
        print(f"{'=' * 60}")
        print(f"  AutoAgent (Idle Mode)")
        print(f"  Config: {self.todos_file}")
        print(f"  Ideas: {self.ideas_watcher.ideas_file if self.ideas_watcher else 'disabled'}")
        print(f"  Provider: {self.provider.name}")
        print(f"  Model: {self.provider.model}")
        print(f"  Idle interval: {self.idle_interval}s")
        print(f"{'=' * 60}")
        
        while True:
            # Step 1: Check and process new ideas
            new_ideas_count = self.check_and_process_ideas()
            
            # Step 2: Run any pending tasks
            if self.ai_orchestrator:
                # AI orchestrator mode: use AI scheduling
                results = self.run_ai_scheduled()
            else:
                pending = self._get_pending_tasks(task_id)
                
                if pending:
                    print(f"\n📋 Found {len(pending)} pending task(s) to execute")
                    results = self.run(task_id=task_id)
                elif new_ideas_count == 0:
                    # No new ideas and no pending tasks - enter idle
                    pass
            
            # Step 3: Enter idle wait
            print(f"\n😴 Idle - waiting for new ideas in {self.ideas_watcher.ideas_file if self.ideas_watcher else 'N/A'}...")
            print(f"   (Press Ctrl+C to exit)")
            
            try:
                self._idle_wait()
            except KeyboardInterrupt:
                raise

    def _get_pending_tasks(self, task_id: int = None) -> list:
        """
        Get list of tasks that still need to be executed.
        
        Returns:
            list: Tasks that are pending or in_progress
        """
        if task_id is not None:
            candidates = [t for t in self.todos if str(t['id']) == str(task_id)]
        else:
            candidates = self.todos
        
        pending = []
        for task in candidates:
            tid = str(task['id'])
            state = self.state_manager.get_task_state(tid)
            if state.get('status') == 'completed':
                continue
            pending.append(task)
        
        return pending

    def _idle_wait(self):
        """
        Wait in idle mode until new ideas are detected.
        
        Polls ideas.md at the configured interval.
        Raises KeyboardInterrupt if user presses Ctrl+C.
        """
        while True:
            time.sleep(self.idle_interval)
            
            # Check for new ideas
            if self.ideas_watcher and self.ideas_watcher.has_new_ideas():
                print(f"\n🔔 New ideas detected!")
                return
            
            # Also check if todos.yaml was modified externally
            try:
                new_todos = self._load_todos(allow_empty=True)
                if len(new_todos) > len(self.todos):
                    self.todos = new_todos
                    print(f"\n🔔 New tasks detected in {self.todos_file}!")
                    return
            except Exception:
                pass


def setup_logging(verbose: bool = False, log_file: str = None):
    """Configure logging.
    
    Args:
        verbose: Enable debug-level logging.
        log_file: Path to orchestrator.log. If None, only logs to stdout.
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
    )




def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8 to avoid GBK encoding errors on Windows."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)


def _load_config():
    """Load config.yaml from the same directory as this script.
    
    Returns:
        dict: Configuration values. Empty dict if file not found.
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            logger.debug(f"Loaded config from {config_path}: {config}")
            return config
        except Exception as e:
            logger.warning(f"Failed to load config.yaml: {e}")
    return {}


def _expand_workspace_vars(value, workspace):
    """Expand ${workspace} variable in configuration values.
    
    Args:
        value: The value to expand (string or other type)
        workspace: The workspace path to substitute
        
    Returns:
        Expanded value with ${workspace} replaced by actual path
    """
    if isinstance(value, str):
        return value.replace('${workspace}', workspace)
    return value


def _load_preset(config, preset_name, workspace):
    """Load preset configuration from config.
    
    Args:
        config: The loaded config dict
        preset_name: Name of the preset to load
        workspace: Current workspace path for variable expansion
        
    Returns:
        dict: Preset configuration values, empty dict if not found
    """
    presets = config.get('preset', [])
    
    # Convert list to dict for easier lookup
    preset_dict = {}
    for p in presets:
        if isinstance(p, dict) and 'name' in p:
            preset_dict[p['name']] = p
    
    if preset_name not in preset_dict:
        if preset_name != 'default':
            print(f"⚠️  Warning: Preset '{preset_name}' not found in config.yaml")
        return {}
    
    preset = preset_dict[preset_name].copy()
    preset.pop('name', None)  # Remove name field
    
    # Expand ${workspace} variables
    for key, value in preset.items():
        preset[key] = _expand_workspace_vars(value, workspace)
    
    logger.debug(f"Loaded preset '{preset_name}': {preset}")
    return preset


def _merge_preset_with_args(args, preset):
    """Merge preset values with command-line arguments.
    
    Command-line arguments take precedence over preset values.
    Only applies preset values when the arg wasn't explicitly set on CLI.
    
    Args:
        args: Parsed argparse Namespace
        preset: Preset configuration dict
        
    Returns:
        Updated args Namespace
    """
    # Map of preset keys to args attributes
    preset_to_arg_map = {
        'config': 'config',
        'ideas': 'ideas',
        'provider': 'provider',
        'model': 'model',
        'executable': 'executable',
        'workspace': 'workspace',
        'timeout': 'timeout',
        'log_dir': 'log_dir',
        'idle_interval': 'idle_interval',
        'include_directories': 'include_directories',
        'test_rules': 'test_rules',
        'verbose': 'verbose',
        'no_idle': 'no_idle',
        'use_cli': 'use_cli',
        'ideas_only': 'ideas_only',
        'human_review': 'human_review',
    }
    
    # Default values that indicate "not set by user"
    # For store_true args, the argparse default is False, so we need to
    # include them here so the preset can override them.
    defaults_not_set = {
        'config': 'todos.yaml',
        'provider': 'codebuddy',
        'workspace': '.',
        'idle_interval': 30,
        'verbose': False,
        'no_idle': False,
        'use_cli': False,
        'ideas_only': False,
        'human_review': False,
    }
    
    for preset_key, arg_key in preset_to_arg_map.items():
        if preset_key in preset:
            preset_value = preset[preset_key]
            current_value = getattr(args, arg_key)
            default_value = defaults_not_set.get(arg_key)
            
            # Apply preset if:
            # 1. Current value is None, or
            # 2. Current value equals the argparse default (meaning user didn't override)
            if current_value is None or (default_value is not None and current_value == default_value):
                setattr(args, arg_key, preset_value)
                logger.debug(f"Applied preset '{preset_key}': {preset_value}")
    
    return args


def _list_sessions(log_dir: str, workspace: str):
    """List all known sessions and their status."""
    rows = TodoOrchestrator._load_sessions_csv(log_dir)

    # Also scan log_dir for session dirs not in CSV (e.g. from before CSV existed)
    known_ids = {r["session_id"] for r in rows}
    if os.path.isdir(log_dir):
        for d in sorted(os.listdir(log_dir)):
            full = os.path.join(log_dir, d)
            if os.path.isdir(full) and d not in known_ids and d != "logs":
                # Check if it looks like a session dir (has todos_state.yaml or orchestrator.log)
                if os.path.exists(os.path.join(full, "orchestrator.log")) or \
                   os.path.exists(os.path.join(full, "todos_state.yaml")):
                    rows.append({
                        "session_id": d,
                        "workspace": "?",
                        "created_at": "?",
                    })

    if not rows:
        print(f"No sessions found in {log_dir}/")
        return

    # Determine active session for this workspace
    active_subdir = TodoOrchestrator._read_marker(workspace)

    print(f"\nSessions in {log_dir}/\n")
    print(f"{'Workspace':<50s} {'Session ID':<40s} {'Created':<22s} {'Status'}")
    print(f"{'-' * 50} {'-' * 40} {'-' * 22} {'-' * 30}")

    for row in rows:
        sid = row.get("session_id", "?")
        ws = row.get("workspace", "?")
        created = row.get("created_at", "?")
        # Truncate workspace for display
        ws_display = ws if len(ws) <= 48 else "..." + ws[-45:]

        # Get status from todos_state.yaml
        session_path = os.path.join(log_dir, sid)
        status = TodoOrchestrator._get_session_status(session_path)

        # Mark active session
        if sid == active_subdir:
            status += " (active)"

        print(f"{ws_display:<50s} {sid:<40s} {created:<22s} {status}")

    print()


def main():
    """CLI entry point."""
    _ensure_utf8_stdio()

    # Load config.yaml defaults
    config = _load_config()
    default_session_timeout = config.get('session_timeout', 3600)
    default_bash_timeout = config.get('bash_timeout', 300)

    parser = argparse.ArgumentParser(
        description="AI-driven task execution system (supports CodeBuddy, Claude Code, Gemini CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrator.py                                # Run all tasks (CodeBuddy default)
  python orchestrator.py --provider claude               # Use Claude Code
  python orchestrator.py --provider gemini --model gemini-3-flash  # Use Gemini CLI
  python orchestrator.py --config my_tasks.yaml          # Use custom config
  python orchestrator.py --task 2                        # Run only task 2
  python orchestrator.py --reset                         # Reset all state
  python orchestrator.py --verbose                       # Enable debug logging
  python orchestrator.py --ideas ideas.md                # Watch ideas.md for new ideas
python orchestrator.py --ideas ideas.md --ideas-only   # Process ideas only (no task execution)
    python orchestrator.py --ideas ideas.md --human-review  # Process ideas with human review
  python orchestrator.py --ideas ideas.md                 # Run tasks then idle for ideas (idle is default)
  python orchestrator.py --list-providers                # List available AI providers
        """,
    )
    
    parser.add_argument(
        '--config', '-c',
        default='todos.yaml',
        help='Path to task configuration file (default: todos.yaml)',
    )
    parser.add_argument(
        '--task', '-t',
        type=str,
        default=None,
        help='Execute only the specified task ID',
    )
    parser.add_argument(
        '--provider', '-P',
        default='codebuddy',
        help='AI provider to use: codebuddy (default), claude, gemini, opencode, test. '
             'Use --list-providers to see all available options.',
    )
    parser.add_argument(
        '--executable',
        default=None,
        help='Override the default executable path for the AI provider',
    )
    parser.add_argument(
        '--extra-args',
        default=None,
        help='Additional CLI arguments to pass to the AI tool',
    )
    parser.add_argument(
        '--list-providers',
        action='store_true',
        help='List available AI providers and exit',
    )
    parser.add_argument(
        '--continue', dest='continue_session',
        action='store_true',
        help='Continue from the current session (reads .autoagent_log)',
    )
    parser.add_argument(
        '--resume', dest='resume_session',
        default=None,
        help='Resume a specific session by ID (e.g. 4jvowsl3 or full name)',
    )
    parser.add_argument(
        '--list-sessions',
        action='store_true',
        help='List all sessions and exit',
    )
    parser.add_argument(
        '--model', '-m',
        default=None,
        help='AI model to use. Supports single model (e.g. "glm-5") or '
             'multi-role format: "plan:model1;default:model2;lite:model3;evaluation:model4;scheduler:model5". '
             'Roles: plan (idea decomposition), default (task execution), '
             'lite (lightweight tasks), evaluation (failure analysis & main task evaluation), '
             'scheduler (AI orchestrator scheduling decisions). '
             'Missing roles inherit from default.',
    )
    parser.add_argument(
        '--workspace', '-w',
        default='.',
        help='Working directory (default: current directory)',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=None,
        help=f'Session timeout for AI calls in seconds (default: {default_session_timeout}, from config.yaml session_timeout)',
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Reset all task states and exit',
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help='Validate configuration and exit',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose/debug logging',
    )
    parser.add_argument(
        '--log-dir',
        default=None,
        help='Root directory for all output files: conversation logs, state files, '
             'and orchestrator.log. Relative to CWD. (default: .autoagent)',
    )
    parser.add_argument(
        '--ideas',
        default=None,
        help='Path to ideas.md file. When set, new ideas will be processed into TODO tasks.',
    )
    parser.add_argument(
        '--ideas-only',
        action='store_true',
        help='Only process ideas.md, do not run the TODO task list. '
             'Requires --ideas to be set.',
    )
    parser.add_argument(
        '--human-review',
        action='store_true',
        help='Enable human review for ideas processing. After AI review passes, '
             'pauses for human approval. Enter y to accept and exit, or n to provide '
             'feedback for revision. (default: disabled)',
    )
    parser.add_argument(
        '--no-idle',
        action='store_true',
        help='Disable idle mode. By default, when --ideas is set, the orchestrator '
             'enters idle mode after completing tasks (waiting for new ideas). '
             'Use --no-idle to run once and exit.',
    )
    parser.add_argument(
        '--idle-interval',
        type=int,
        default=30,
        help='Seconds between idle checks for new ideas (default: 30)',
    )
    parser.add_argument(
        '--use-cli',
        action='store_true',
        help='Use CLI subprocess instead of CodeBuddy Agent SDK (default is SDK). '
             'Only works with --provider codebuddy.',
    )
    parser.add_argument(
        '--include-directories',
        default=None,
        help='Comma-separated list of additional directories the AI tool is allowed '
             'to access outside the workspace (Gemini only). '
             'Example: --include-directories /path/to/dir1,/path/to/dir2',
    )
    parser.add_argument(
        '--test-rules',
        default=None,
        help='Path to test rules file for --provider test. '
             'Each rule is separated by "---RULE---" delimiter. '
             'Rules are consumed in order, one per ask() call.',
    )
    parser.add_argument(
        '--preset',
        default='default',
        help='Preset configuration name from config.yaml (default: default). '
             'Preset values can be overridden by command-line arguments.',
    )
    
    args = parser.parse_args()
    
    # Resolve workspace early for preset loading
    _workspace_abs = os.path.abspath(args.workspace)
    
    # Load and apply preset configuration
    preset = _load_preset(config, args.preset, _workspace_abs)
    if preset:
        print(f"✓ Loaded preset: {args.preset}")
        args = _merge_preset_with_args(args, preset)
    
    # Resolve key file paths to absolute paths early, so all downstream
    # code (IdeasWatcher, TodoOrchestrator, empty-file creation, etc.)
    # works correctly regardless of CWD vs workspace differences.
    args.config = os.path.abspath(args.config)
    if args.ideas:
        args.ideas = os.path.abspath(args.ideas)
    
    # Ensure required files exist (create empty if not present)
    if args.ideas:
        if not os.path.exists(args.ideas):
            os.makedirs(os.path.dirname(args.ideas) or '.', exist_ok=True)
            with open(args.ideas, 'w', encoding='utf-8') as f:
                f.write('')  # Create empty file
            print(f"✓ Created empty ideas file: {args.ideas}")
    
    if not os.path.exists(args.config):
        os.makedirs(os.path.dirname(args.config) or '.', exist_ok=True)
        with open(args.config, 'w', encoding='utf-8') as f:
            f.write('')  # Create empty file
        print(f"✓ Created empty config file: {args.config}")
    
    # Resolve log_dir early so we can point orchestrator.log there too.
    _log_dir_raw = args.log_dir  # may be None
    _log_dir_abs = os.path.abspath(_log_dir_raw) if _log_dir_raw else os.path.abspath(".autoagent")
    _workspace_abs = os.path.abspath(args.workspace)

    # ── Handle --list-sessions early (before session resolution) ──
    if args.list_sessions:
        _list_sessions(_log_dir_abs, _workspace_abs)
        return

    # ── Validate mutually exclusive session flags ──
    if args.continue_session and args.resume_session:
        print("❌ Cannot use --continue and --resume together.")
        sys.exit(1)

    # ── Resolve session directory based on mode ──
    if args.continue_session:
        _session_dir = TodoOrchestrator.resolve_session_dir(
            _log_dir_abs, _workspace_abs, mode="continue"
        )
    elif args.resume_session:
        _session_dir = TodoOrchestrator.resolve_session_dir(
            _log_dir_abs, _workspace_abs, mode="resume",
            resume_id=args.resume_session,
        )
    else:
        # Default: fresh start
        _session_dir = TodoOrchestrator.resolve_session_dir(
            _log_dir_abs, _workspace_abs, mode="new"
        )
    os.makedirs(_session_dir, exist_ok=True)

    # Setup logging – orchestrator.log goes into the session directory
    setup_logging(
        verbose=args.verbose,
        log_file=os.path.join(_session_dir, "orchestrator.log"),
    )
    
    try:
        # Handle --list-providers
        if args.list_providers:
            providers = list_providers()
            print(f"\n{'=' * 50}")
            print(f"  Available AI Providers")
            print(f"{'=' * 50}")
            for name, info in providers.items():
                aliases = ", ".join(info['aliases']) if info['aliases'] else "(none)"
                print(f"\n  📌 {name}")
                print(f"     Executable: {info['default_executable']}")
                print(f"     Default model: {info['default_model']}")
                print(f"     Aliases: {aliases}")
            print(f"\n{'=' * 50}")
            return

        # Determine idle mode: enabled by default when --ideas is set
        idle_mode = bool(args.ideas) and not args.no_idle
        
        # Validate --ideas-only requires --ideas
        if args.ideas_only and not args.ideas:
            print("❌ --ideas-only mode requires --ideas to be set.")
            sys.exit(1)
        
        # Validate non-codebuddy providers always use CLI (SDK is codebuddy-only)
        if not args.use_cli:
            resolved_provider = args.provider.lower()
            # Resolve aliases
            from ai_providers import PROVIDER_ALIASES
            resolved_provider = PROVIDER_ALIASES.get(resolved_provider, resolved_provider)
            if resolved_provider not in ('codebuddy', 'test'):
                # Non-codebuddy providers don't support SDK, force CLI mode
                args.use_cli = True
        
        # Validate test provider requires --test-rules
        if args.provider.lower() == 'test' and not args.test_rules:
            print("❌ --provider test requires --test-rules <file> to be set.")
            sys.exit(1)
        
        # Create AI provider
        executable = args.executable

        # Parse model spec into role→model dict
        model_roles = parse_model_spec(args.model or "")

        # Use the 'default' role model for the provider
        provider_model = model_roles["default"] if model_roles["default"] else args.model
        
        # Parse --include-directories into a list
        include_dirs = None
        if args.include_directories:
            include_dirs = [d.strip() for d in args.include_directories.split(',') if d.strip()]
        
        # When using Gemini with ideas, auto-include the todos.yaml parent directory
        # so that Gemini's sandbox allows writing the temp tasks file there.
        resolved_provider_name = args.provider.lower()
        from ai_providers import PROVIDER_ALIASES
        resolved_provider_name = PROVIDER_ALIASES.get(resolved_provider_name, resolved_provider_name)
        if resolved_provider_name == 'gemini' and args.ideas:
            todos_parent = os.path.dirname(os.path.abspath(args.config))
            workspace_abs = os.path.abspath(args.workspace)
            if os.path.normcase(todos_parent) != os.path.normcase(workspace_abs):
                if include_dirs is None:
                    include_dirs = []
                if todos_parent not in include_dirs:
                    include_dirs.append(todos_parent)
                    logger.info(
                        f"Auto-added {todos_parent} to --include-directories "
                        f"for Gemini sandbox (todos.yaml parent != workspace)"
                    )
        
        provider = get_provider(
            name=args.provider,
            executable=executable,
            model=provider_model,
            extra_args=args.extra_args,
            test_rules_file=getattr(args, 'test_rules', None),
            include_directories=include_dirs,
        )
        
        logger.info(f"Using AI provider: {provider}")
        
        # Create orchestrator
        # Resolve timeout: CLI arg > config.yaml > fallback
        effective_session_timeout = args.timeout if args.timeout is not None else default_session_timeout
        effective_bash_timeout = default_bash_timeout
        backoff_max = config.get('backoff_max_wait', 300)

        orchestrator = TodoOrchestrator(
            todos_file=args.config,
            provider=provider,
            workspace=args.workspace,
            timeout=effective_session_timeout,
            bash_timeout=effective_bash_timeout,
            session_dir=_session_dir,
            ideas_file=args.ideas,
            idle_interval=args.idle_interval,
            use_cli=args.use_cli,
            backoff_max_wait=backoff_max,
            model_roles=model_roles,
        )
        
        # Handle special commands
        if args.validate:
            if orchestrator.validate_config():
                print("✅ Configuration is valid.")
            else:
                sys.exit(1)
            return
        
        if args.reset:
            orchestrator.reset()
            return
        
        
        # Process ideas before running tasks (if ideas file is configured)
        if orchestrator.ideas_watcher:
            orchestrator.check_and_process_ideas(
                human_review=args.human_review,
            )
        
        # --ideas-only mode: only process ideas, then exit
        if args.ideas_only:
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"📝 Conversation logs saved to: {orchestrator.session_dir}")
            print(f"\n✅ Ideas processing complete.")
            return

        # ── AI Orchestrator mode check ────────────────────────────
        if orchestrator.ai_orchestrator:
            # --task is not supported in AI orchestrator mode
            if args.task:
                print("❌ --task is not supported in AI orchestrator mode.")
                print("   The AI scheduler decides which tasks to execute.")
                sys.exit(1)

            # Check for mode conflict with existing state
            orch_state = orchestrator.state_manager.get_orchestrator_state()
            if orch_state is None:
                # Fresh start — check there's no linear-mode state
                existing_tasks = orchestrator.state_manager.state.get("tasks", {})
                if existing_tasks:
                    # There are task states but no orchestrator state — could be
                    # leftover from linear mode. Warn but allow (the user may
                    # have just added ai_orchestrator to an existing config).
                    logger.warning(
                        "Existing task states found without orchestrator state. "
                        "If switching from linear mode, consider --reset first."
                    )

            results = orchestrator.run_ai_scheduled()

            # Finalize conversation logs
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"📝 Conversation logs saved to: {orchestrator.session_dir}")

            if results['failed_tasks'] > 0:
                sys.exit(1)
            return

        if idle_mode:
            # Idle mode: run tasks then wait for new ideas
            orchestrator.run_with_idle(
                task_id=args.task,
            )
        else:
            # Normal mode: run tasks and exit
            results = orchestrator.run(
                task_id=args.task,
            )
            
            # Finalize conversation logs
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"📝 Conversation logs saved to: {orchestrator.session_dir}")
            
            # Exit with error code if any tasks failed
            if results['failed_tasks'] > 0:
                sys.exit(1)
            
    except ConfigError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        # Record interrupt for in-progress tasks before exiting
        if 'orchestrator' in dir() and orchestrator:
            in_progress = orchestrator.state_manager.get_in_progress_tasks()
            for tid in in_progress:
                orchestrator.state_manager.record_interrupt(tid)
            # Finalize conversation logs even on interrupt
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"\n📝 Conversation logs saved to: {orchestrator.session_dir}")
        print(f"\n\n⚠️  Interrupted by user. State has been saved.")
        print(f"    Run again to resume from where you left off.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
