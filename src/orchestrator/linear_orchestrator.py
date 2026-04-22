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
import time
import shutil
import logging
import yaml
from typing import Optional, List

from ai_client import AICallError
from ai_client.ai_providers import AIProvider, CodeBuddyProvider, MODEL_ROLES
from task_executor import (
    SimpleTaskExecutor,
    NestedTaskExecutor,
    LoopingTaskExecutor,
    SubtaskExecutor,
    ConfigError,
    ExecutionError,
)
from state_manager import StateManager
from logger import ConversationLogger
from ideas import IdeasWatcher
from orchestrator.orchestrator_common import (
    SessionHelper,
    create_ai_client,
    load_orchestrator_config,
)
from orchestrator.ai_orchestrator import AISchedulerMixin
from util.truncation_limits import limits
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)



class TodoOrchestrator(AISchedulerMixin):
    """
    Main orchestrator class that manages task loading, scheduling, and execution.
    
    Responsibilities:
    - Parse and validate todos.yaml configuration
    - Schedule task execution in order (linear mode) or via AI (AI mode)
    - Delegate to appropriate executors (SimpleTaskExecutor, NestedTaskExecutor)
    - Manage state persistence via StateManager
    - Create AIClient instances per main task for context isolation

    AI scheduling methods are provided by ``AISchedulerMixin``.
    Session management helpers are in ``orchestrator_common.SessionHelper``.
    """

    # ── Backward-compatible session management class attributes ────
    # These delegate to SessionHelper so that external code using
    # ``TodoOrchestrator._load_sessions_csv(...)`` etc. still works.

    SESSIONS_FILE = SessionHelper.SESSIONS_FILE


    # ── Session management (delegated to SessionHelper) ─────────

    _generate_session_name = staticmethod(SessionHelper.generate_session_name)
    _append_sessions_csv = staticmethod(SessionHelper.append_sessions_csv)
    _load_sessions_csv = staticmethod(SessionHelper.load_sessions_csv)
    _find_latest_session_for_workspace = staticmethod(SessionHelper.find_latest_session_for_workspace)
    _update_workspace_in_csv = staticmethod(SessionHelper.update_workspace_in_csv)
    _touch_session = staticmethod(SessionHelper.touch_session)
    resolve_session_dir = staticmethod(SessionHelper.resolve_session_dir)
    _cleanup_stale_sessions = staticmethod(SessionHelper.cleanup_stale_sessions)
    _get_session_status = staticmethod(SessionHelper.get_session_status)

    def __init__(
        self,
        todos_file: str = "todos.yaml",
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = None,
        bash_timeout: int = None,
        session_dir: str = None,
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = None,
        use_cli: bool = False,
        backoff_max_wait: int = None,
        model_roles: dict = None,
        default_max_attempts: int = None,
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
                ``sessions.csv`` lookup).
            ideas_file: Path to ideas.md file (None to disable ideas watching)
            idle_interval: Seconds between idle checks for new ideas (default: 30)
            use_cli: If True, use CLI subprocess instead of CodeBuddy Agent SDK
                     (only valid when provider is codebuddy)
            backoff_max_wait: Max wait time (seconds) for exponential backoff
                     when AI CLI calls fail repeatedly (default: 600)
            model_roles: Model role dict ({"plan": ..., "default": ..., "lite": ...}),
                     parsed by parse_model_spec(). None uses provider's default model.
            default_max_attempts: Global default for task/subtask max retry attempts.
                     Individual tasks can override via their own max_attempts field.
        """
        self.todos_file = todos_file
        self.workspace = os.path.abspath(workspace)
        self.timeout = timeout if timeout is not None else DEFAULTS['session_timeout']
        self.bash_timeout = bash_timeout if bash_timeout is not None else DEFAULTS['bash_timeout']
        self.idle_interval = idle_interval if idle_interval is not None else DEFAULTS['idle_interval']
        self.use_cli = use_cli
        self.backoff_max_wait = backoff_max_wait if backoff_max_wait is not None else DEFAULTS['backoff_max_wait']
        self.default_max_attempts = default_max_attempts if default_max_attempts is not None else DEFAULTS['default_max_attempts']

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
            # Fallback for tests and simple usage: look up sessions.csv
            if log_dir is None:
                log_dir = os.path.abspath(".autoagent")
            else:
                log_dir = os.path.abspath(log_dir)
            subdir = SessionHelper.find_latest_session_for_workspace(
                log_dir, self.workspace
            )
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
        self.simple_executor = SimpleTaskExecutor(session_dir=self.session_dir, default_max_attempts=self.default_max_attempts)
        self.nested_executor = NestedTaskExecutor(session_dir=self.session_dir, model_roles=self.model_roles, default_max_attempts=self.default_max_attempts)
        self.looping_executor = LoopingTaskExecutor(session_dir=self.session_dir, model_roles=self.model_roles, default_max_attempts=self.default_max_attempts)
        
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
            # Expand ${workspace} in last_result paths before validation
            self._expand_workspace_in_ai_orch(ai_orch)
            self.ai_orchestrator = self._validate_ai_orchestrator(ai_orch, tasks)
        else:
            self.ai_orchestrator = None

        # Validate each task
        # ── Validate top-level task ID ordering (linear mode only) ──
        # In AI scheduling mode, tasks can be executed in any order and
        # the user may intentionally define them out of sequence.
        if self.ai_orchestrator is None:
            prev_top_id: int | None = None
            for task in tasks:
                raw = task.get('id')
                if raw is not None:
                    str_id = str(raw)
                    if str_id.isdigit():
                        tid = int(str_id)
                        if prev_top_id is not None and tid <= prev_top_id:
                            raise ConfigError(
                                f"Top-level task IDs must be linearly increasing: "
                                f"ID {tid} is not greater than previous ID {prev_top_id}"
                            )
                        prev_top_id = tid

        for task in tasks:
            self._validate_task(task)

        # ── Validate model names against CodeBuddy supported list ──
        self._warn_unsupported_models(tasks)

        logger.info(f"Loaded {len(tasks)} tasks from {self.todos_file}")
        return tasks

    def _expand_workspace_in_ai_orch(self, ai_orch: dict):
        """Expand ``${workspace}`` in ai_orchestrator.last_result paths.

        Modifies the dict in-place so that subsequent validation sees
        absolute paths.
        """
        last_result = ai_orch.get('last_result')
        if not last_result or not isinstance(last_result, dict):
            return
        workspace = self.workspace.replace("\\", "/")
        for _tid, lr_config in last_result.items():
            if not isinstance(lr_config, dict):
                continue
            path = lr_config.get('path')
            if isinstance(path, str) and '${workspace}' in path:
                lr_config['path'] = path.replace('${workspace}', workspace)
            elif isinstance(path, list):
                lr_config['path'] = [
                    p.replace('${workspace}', workspace) if isinstance(p, str) and '${workspace}' in p else p
                    for p in path
                ]

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


    # ── _validate_ai_orchestrator → ai_orchestrator.AISchedulerMixin

    def _validate_task(self, task: dict, is_subtask: bool = False,
                       parent_id: str = None):
        """
        Validate a task configuration.
        
        Args:
            task: Task configuration dict
            is_subtask: Whether this is a subtask
            parent_id: The parent task's ID string (used to validate subtask
                ID prefix). ``None`` for top-level tasks.
            
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

        # ── Validate ID format ────────────────────────────────────
        raw_id = task.get('id')
        if raw_id is not None:
            str_id = str(raw_id)
            parts = str_id.split('.')
            if is_subtask:
                # Subtask ID must be X.Y (or deeper, e.g. X.Y.Z)
                if len(parts) < 2:
                    raise ConfigError(
                        f"Subtask ID '{str_id}' must use dot notation "
                        f"(e.g. '{parent_id}.1') but got a single-level ID"
                    )
                # Every component must be a positive integer
                for i, p in enumerate(parts):
                    if not p.isdigit() or int(p) < 1:
                        raise ConfigError(
                            f"Subtask ID '{str_id}': component '{p}' "
                            f"(position {i+1}) must be a positive integer"
                        )
                # Prefix must match parent_id
                if parent_id is not None:
                    expected_prefix = str(parent_id)
                    actual_prefix = '.'.join(parts[:-1])
                    if actual_prefix != expected_prefix:
                        raise ConfigError(
                            f"Subtask ID '{str_id}' must start with "
                            f"parent ID '{parent_id}.' but prefix is "
                            f"'{actual_prefix}'"
                        )
            else:
                # Top-level task ID must be a single positive integer
                if len(parts) != 1:
                    raise ConfigError(
                        f"Top-level task ID '{str_id}' must be a single "
                        f"integer (no dots), got '{str_id}'"
                    )
                elif not str_id.isdigit() or int(str_id) < 1:
                    raise ConfigError(
                        f"Top-level task ID '{str_id}' must be a positive integer"
                    )
        
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
            self._validate_subtask_ids(subtasks, str(task['id']))
            for subtask in subtasks:
                self._validate_task(subtask, is_subtask=True,
                                    parent_id=str(task['id']))
        
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
            self._validate_subtask_ids(subtasks, str(task['id']))
            for subtask in subtasks:
                self._validate_task(subtask, is_subtask=True,
                                    parent_id=str(task['id']))
        
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

    def _warn_unsupported_models(self, tasks: list):
        """Check model names against CodeBuddy's supported model list.

        Only runs when the provider is CodeBuddy.  Produces warnings (not
        errors) for model names that are not recognized role names and not
        in the supported model list extracted from ``codebuddy --help``.
        """
        if not isinstance(self.provider, CodeBuddyProvider):
            return

        supported = CodeBuddyProvider.get_supported_models(self.provider.executable)
        if supported is None:
            # Could not parse help text — skip validation silently
            return

        bad = []

        def _check_task(task: dict):
            model = task.get('model')
            if model and isinstance(model, str):
                model_lower = model.strip().lower()
                # Skip role names — they are resolved later
                if model_lower in MODEL_ROLES:
                    return
                if model_lower not in supported:
                    bad.append((task.get('id', '?'), model))
            # Recurse into subtasks
            for st in task.get('subtasks', []):
                _check_task(st)

        for task in tasks:
            _check_task(task)

        if bad:
            print("\n❌  Unsupported model(s) detected in todos.yaml:")
            for task_id, model in bad:
                print(f"      • Task {task_id} → model '{model}'")
            print(f"   Supported models: {', '.join(sorted(supported))}")
            print("   Fix the model name(s) and try again.")
            sys.exit(1)

    def _validate_subtask_ids(self, subtasks: list, parent_id: str):
        """Validate that subtask IDs are linearly increasing under *parent_id*.

        Each subtask ID must be ``parent_id.N`` where ``N`` is a positive
        integer.  The sequence of ``N`` values must be strictly increasing
        (gaps are allowed, e.g. 1, 3, 5).

        Raises:
            ConfigError: If subtask IDs are not linearly increasing.
        """
        prev_suffix: int | None = None
        for st in subtasks:
            raw = st.get('id')
            if raw is None:
                continue  # missing-id is caught elsewhere
            str_id = str(raw)
            parts = str_id.split('.')
            # Extract the last component as the ordering suffix
            suffix_str = parts[-1] if parts else ''
            if not suffix_str.isdigit():
                continue  # format error caught in _validate_task
            suffix = int(suffix_str)
            if prev_suffix is not None and suffix <= prev_suffix:
                raise ConfigError(
                    f"Subtask IDs under parent '{parent_id}' must be "
                    f"linearly increasing: ID '{str_id}' (suffix {suffix}) "
                    f"is not greater than previous suffix {prev_suffix}"
                )
            prev_suffix = suffix

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
            print(f"   Criteria: {task['completion_criteria'][:limits.get('log_promptlike_preview')]}...")
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


    # ── AI Orchestrator methods → ai_orchestrator.AISchedulerMixin
    # ── run_ai_scheduled, _get_scheduler_decision, _parse_scheduler_response,
    # ── _create_ai_client, _execute_scheduled_task, _build_scheduled_task,
    # ── _prefix_subtask_ids, _save_task_response_result

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
                    default_max_attempts=self.default_max_attempts,
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
        client = create_ai_client(
            provider=self.provider,
            workspace=self.workspace,
            timeout=self.timeout,
            bash_timeout=self.bash_timeout,
            context_id="ideas_processor",
            use_cli=self.use_cli,
            backoff_max_wait=self.backoff_max_wait,
            session_dir=self.session_dir,
        )
        review_client = create_ai_client(
            provider=self.provider,
            workspace=self.workspace,
            timeout=self.timeout,
            bash_timeout=self.bash_timeout,
            context_id="ideas_reviewer",
            use_cli=self.use_cli,
            backoff_max_wait=self.backoff_max_wait,
            session_dir=self.session_dir,
        )
        
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

