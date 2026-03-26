#!/usr/bin/env python3
"""
CodeBuddy Todo Orchestrator - Main entry point.

An intelligent task orchestration system that uses CodeBuddy AI to
automatically execute, evaluate, and iterate on tasks defined in YAML.

Usage:
    python orchestrator.py                     # Run all tasks
    python orchestrator.py --config my.yaml    # Use custom config file
    python orchestrator.py --task 2            # Run only task 2
    python orchestrator.py --reset             # Reset all state
    python orchestrator.py --status            # Show current status
"""

import os
import sys
import time
import string
import random
import argparse
import logging
import yaml
from typing import Optional, List

from codebuddy_client import AIClient, AIClientSDK, AIClientTest, CodeBuddyClient, AICallError
from ai_providers import get_provider, list_providers, AIProvider, TestProvider
from task_executor import (
    SimpleTaskExecutor,
    NestedTaskExecutor,
    LoopingTaskExecutor,
    ConfigError,
    ExecutionError,
)
from state_manager import StateManager
from conversation_logger import ConversationLogger
from ideas_watcher import IdeasWatcher

logger = logging.getLogger(__name__)


class TodoOrchestrator:
    """
    Main orchestrator class that manages task loading, scheduling, and execution.
    
    Responsibilities:
    - Parse and validate todos.yaml configuration
    - Schedule task execution in order
    - Delegate to appropriate executors (SimpleTaskExecutor, NestedTaskExecutor)
    - Manage state persistence via StateManager
    - Create CodeBuddyClient instances per main task for context isolation
    """

    @staticmethod
    def _resolve_log_session_dir(log_dir: str, workspace: str) -> str:
        """
        Resolve the final log session directory by reading or generating
        a project-specific subdirectory name stored in .autoagent_log.

        The .autoagent_log file lives in the *workspace* (project) directory
        and contains a single line like ``cufftdx_optimization_ko53bi1b``.
        The returned path is ``<log_dir>/<that_line>``.

        If the file does not yet exist it is created with a freshly
        generated name of the form ``<dirname>_<random8chars>``.

        Args:
            log_dir: Root log directory (absolute path)
            workspace: Project / workspace directory (absolute path)

        Returns:
            str: Absolute path to the project-specific session directory.
        """
        marker_file = os.path.join(workspace, ".autoagent_log")

        # Try to read an existing marker
        if os.path.exists(marker_file):
            try:
                with open(marker_file, "r", encoding="utf-8") as f:
                    subdir_name = f.read().strip()
                if subdir_name:
                    return os.path.join(log_dir, subdir_name)
            except Exception:
                pass  # Fall through to generate a new one

        # Generate a new subdirectory name: <basename>_<random8>
        basename = os.path.basename(os.path.abspath(workspace))
        rand_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        subdir_name = f"{basename}_{rand_suffix}"

        # Persist it so that subsequent runs reuse the same directory
        try:
            with open(marker_file, "w", encoding="utf-8") as f:
                f.write(subdir_name + "\n")
        except Exception as e:
            logger.warning(f"Failed to write {marker_file}: {e}")

        return os.path.join(log_dir, subdir_name)

    def __init__(
        self,
        todos_file: str = "todos.yaml",
        state_file: str = None,
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = 30,
        use_cli: bool = False,
        # Legacy parameters for backward compatibility
        codebuddy_path: str = None,
        model: str = None,
    ):
        """
        Initialize the TodoOrchestrator.
        
        Args:
            todos_file: Path to the task configuration YAML
            state_file: (Deprecated, ignored) State file path is now derived
                        from log_dir automatically.
            provider: AI provider instance (takes precedence over legacy params)
            workspace: Working directory for AI tool
            timeout: Default timeout for AI calls
            log_dir: Root directory for all output files (conversation logs,
                     state files, orchestrator.log).  Defaults to ".autoagent"
                     relative to the current working directory.
            ideas_file: Path to ideas.md file (None to disable ideas watching)
            idle_interval: Seconds between idle checks for new ideas (default: 30)
            use_cli: If True, use CLI subprocess instead of CodeBuddy Agent SDK
                     (only valid when provider is codebuddy)
            codebuddy_path: (Legacy) Path to CodeBuddy executable
            model: (Legacy) AI model to use
        """
        self.todos_file = todos_file
        self.workspace = os.path.abspath(workspace)
        self.timeout = timeout
        self.idle_interval = idle_interval
        self.use_cli = use_cli
        
        # Store provider (or create from legacy params)
        if provider is not None:
            self.provider = provider
        elif codebuddy_path or model:
            from ai_providers import CodeBuddyProvider
            self.provider = CodeBuddyProvider(
                executable=codebuddy_path or "codebuddy",
                model=model or "glm-5.0-ioa",
            )
        else:
            from ai_providers import CodeBuddyProvider
            self.provider = CodeBuddyProvider()
        
        # ── Resolve session log directory ──────────────────────────
        # log_dir defaults to ".autoagent" relative to CWD.
        if log_dir is None:
            log_dir = os.path.abspath(".autoagent")
        else:
            log_dir = os.path.abspath(log_dir)

        self.session_dir = self._resolve_log_session_dir(log_dir, self.workspace)
        os.makedirs(self.session_dir, exist_ok=True)

        # Derived paths inside the session directory
        resolved_state_file = os.path.join(self.session_dir, "todos_state.yaml")
        resolved_ideas_processed = os.path.join(self.session_dir, ".ideas_processed.yaml")

        self.state_manager = StateManager(resolved_state_file)
        self.conv_logger = ConversationLogger(self.session_dir)
        self.simple_executor = SimpleTaskExecutor()
        self.nested_executor = NestedTaskExecutor(session_dir=self.session_dir)
        self.looping_executor = LoopingTaskExecutor(session_dir=self.session_dir)
        
        # Ideas watcher (optional)
        if ideas_file:
            self.ideas_watcher = IdeasWatcher(
                ideas_file=ideas_file,
                todos_file=todos_file,
                processed_state_file=resolved_ideas_processed,
            )
        else:
            self.ideas_watcher = None
        
        self.todos = self._load_todos(allow_empty=self.ideas_watcher is not None)

    def _load_todos(self, allow_empty: bool = False) -> list:
        """
        Load and validate task configuration from YAML file.
        
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
            valid_types = ['simple', 'long_running']
        else:
            valid_types = ['simple', 'nested', 'looping']
        
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
        skip_completed: bool = True,
    ) -> dict:
        """
        Run tasks from the configuration.
        
        Args:
            task_id: Execute only this task (None = all tasks)
            skip_completed: Whether to skip already completed tasks
            
        Returns:
            dict: Execution results summary
        """
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
        print(f"  CodeBuddy Todo Orchestrator")
        print(f"  Tasks to execute: {len(tasks_to_run)}")
        print(f"  Config: {self.todos_file}")
        print(f"  Provider: {self.provider.name}")
        print(f"  Model: {self.provider.model}")
        print(f"{'=' * 60}")
        
        for task in tasks_to_run:
            tid = str(task['id'])
            
            # Check if task is already completed
            if skip_completed:
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

    def execute_task(self, task: dict) -> bool:
        """
        Execute a single task, dispatching to the appropriate executor.
        
        Each main task gets its own CodeBuddyClient for context isolation.
        
        Args:
            task: Task configuration dict
            
        Returns:
            bool: True if task completed successfully
        """
        task_id = str(task['id'])
        task_type = task['type']
        
        # Create a new CodeBuddyClient for this main task (context isolation)
        context_id = f"task_{task_id}"
        if isinstance(self.provider, TestProvider):
            client = AIClientTest(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                context_id=context_id,
            )
        elif self.use_cli:
            client = AIClient(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                context_id=context_id,
            )
        else:
            client = AIClientSDK(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                context_id=context_id,
            )
        
        # Record context info in state
        self.state_manager.mark_task_status(
            task_id, "in_progress",
            context_id=context_id,
            context_created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        
        try:
            if task_type == 'simple':
                return self.simple_executor.execute(
                    task, client, self.state_manager, is_subtask=False,
                    conv_logger=self.conv_logger,
                )
            elif task_type == 'nested':
                return self.nested_executor.execute(
                    task, client, self.state_manager,
                    conv_logger=self.conv_logger,
                )
            elif task_type == 'looping':
                return self.looping_executor.execute(
                    task, client, self.state_manager,
                    conv_logger=self.conv_logger,
                )
            else:
                raise ConfigError(f"Unknown task type: {task_type}")
                
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

    def get_status(self) -> dict:
        """
        Get current execution status.
        
        Returns:
            dict: Status summary of all tasks
        """
        status = {"tasks": []}
        
        for task in self.todos:
            tid = str(task['id'])
            state = self.state_manager.get_task_state(tid)
            
            task_status = {
                "id": tid,
                "name": task['name'],
                "type": task['type'],
                "status": state.get('status', 'pending'),
                "attempts": state.get('attempts', 0),
            }
            
            # Add subtask info for nested/looping tasks
            if task['type'] in ('nested', 'looping') and 'subtasks' in task:
                task_status["subtasks"] = []
                for st in task['subtasks']:
                    st_id = str(st['id'])
                    st_state = self.state_manager.get_task_state(st_id)
                    task_status["subtasks"].append({
                        "id": st_id,
                        "name": st['name'],
                        "type": st['type'],
                        "status": st_state.get('status', 'pending'),
                        "attempts": st_state.get('attempts', 0),
                    })
            
            status["tasks"].append(task_status)
        
        return status

    def reset(self):
        """Reset all task states."""
        self.state_manager.reset()
        if self.ideas_watcher:
            self.ideas_watcher.reset()
        print("✅ All task states have been reset.")

    def check_and_process_ideas(self) -> int:
        """
        Check for new ideas in ideas.md and process them into TODO tasks.
        
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
        
        # Create a client for ideas processing
        if isinstance(self.provider, TestProvider):
            client = AIClientTest(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                context_id="ideas_processor",
            )
        elif self.use_cli:
            client = AIClient(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                context_id="ideas_processor",
            )
        else:
            client = AIClientSDK(
                provider=self.provider,
                workspace=self.workspace,
                timeout=self.timeout,
                context_id="ideas_processor",
            )
        
        count = self.ideas_watcher.process_new_ideas(client)
        
        if count > 0:
            print(f"\n   📝 Processed {count} new idea(s), reloading task list...")
            self.reload_todos()
        
        return count

    def run_with_idle(
        self,
        task_id: int = None,
        skip_completed: bool = True,
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
            skip_completed: Whether to skip already completed tasks
        """
        print(f"{'=' * 60}")
        print(f"  CodeBuddy Todo Orchestrator (Idle Mode)")
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
            pending = self._get_pending_tasks(task_id, skip_completed)
            
            if pending:
                print(f"\n📋 Found {len(pending)} pending task(s) to execute")
                results = self.run(task_id=task_id, skip_completed=skip_completed)
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

    def _get_pending_tasks(self, task_id: int = None, skip_completed: bool = True) -> list:
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
            if skip_completed:
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


def print_status(orchestrator: TodoOrchestrator):
    """Print current task status in a formatted way."""
    status = orchestrator.get_status()
    
    print(f"\n{'=' * 60}")
    print(f"  Task Status")
    print(f"{'=' * 60}")
    
    for task in status['tasks']:
        status_icon = {
            'pending': '⏳',
            'in_progress': '🔄',
            'completed': '✅',
            'failed': '❌',
        }.get(task['status'], '❓')
        
        print(f"\n{status_icon} Task {task['id']}: {task['name']}")
        print(f"   Type: {task['type']} | Status: {task['status']} | Attempts: {task['attempts']}")
        
        if 'subtasks' in task:
            for st in task['subtasks']:
                st_icon = {
                    'pending': '  ⏳',
                    'in_progress': '  🔄',
                    'completed': '  ✅',
                    'failed': '  ❌',
                }.get(st['status'], '  ❓')
                
                print(f"   {st_icon} Subtask {st['id']}: {st['name']}")
                print(f"      Type: {st['type']} | Status: {st['status']} | Attempts: {st['attempts']}")
    
    print(f"\n{'=' * 60}")


def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8 to avoid GBK encoding errors on Windows."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)


def main():
    """CLI entry point."""
    _ensure_utf8_stdio()

    parser = argparse.ArgumentParser(
        description="AI-driven task execution system (supports CodeBuddy, Claude Code, Gemini CLI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrator.py                                # Run all tasks (CodeBuddy default)
  python orchestrator.py --provider claude               # Use Claude Code Internal
  python orchestrator.py --provider gemini --model gemini-2.5-pro  # Use Gemini CLI
  python orchestrator.py --config my_tasks.yaml          # Use custom config
  python orchestrator.py --task 2                        # Run only task 2
  python orchestrator.py --status                        # Show current status
  python orchestrator.py --reset                         # Reset all state
  python orchestrator.py --verbose                       # Enable debug logging
  python orchestrator.py --ideas ideas.md                # Watch ideas.md for new ideas
  python orchestrator.py --idle --ideas ideas.md         # Run tasks then idle for ideas
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
        help='AI provider to use: codebuddy (default), claude, gemini. '
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
        '--codebuddy-path',
        default=None,
        help='(Legacy) Path to CodeBuddy executable. Prefer --provider + --executable.',
    )
    parser.add_argument(
        '--model', '-m',
        default=None,
        help='AI model to use (default depends on provider: '
             'codebuddy=glm-5.0-ioa, claude=claude-sonnet-4-6, gemini=gemini-2.5-pro)',
    )
    parser.add_argument(
        '--workspace', '-w',
        default='.',
        help='Working directory (default: current directory)',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=3600,
        help='Timeout for AI calls in seconds (default: 3600)',
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current task status and exit',
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Reset all task states and exit',
    )
    parser.add_argument(
        '--no-skip',
        action='store_true',
        help='Do not skip completed tasks',
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
        '--idle',
        action='store_true',
        help='Enter idle mode after completing tasks. Waits for new ideas in ideas.md. '
             'Requires --ideas to be set.',
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
        '--test-rules',
        default=None,
        help='Path to test rules file for --provider test. '
             'Each rule is separated by "---RULE---" delimiter. '
             'Rules are consumed in order, one per ask() call.',
    )
    
    args = parser.parse_args()
    
    # Resolve log_dir early so we can point orchestrator.log there too.
    # The actual session sub-directory is determined later by the
    # orchestrator (via .autoagent_log), but we need log_dir itself
    # for the orchestrator.log file handler.
    _log_dir_raw = args.log_dir  # may be None
    _log_dir_abs = os.path.abspath(_log_dir_raw) if _log_dir_raw else os.path.abspath(".autoagent")

    # Resolve session dir for orchestrator.log placement
    _workspace_abs = os.path.abspath(args.workspace)
    _session_dir = TodoOrchestrator._resolve_log_session_dir(_log_dir_abs, _workspace_abs)
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

        # Validate idle mode requires ideas file
        if args.idle and not args.ideas:
            print("❌ --idle mode requires --ideas to be set.")
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
        # Legacy support: --codebuddy-path overrides executable for codebuddy provider
        executable = args.executable
        if args.codebuddy_path and not executable:
            executable = args.codebuddy_path
            if args.provider == 'codebuddy':
                pass  # Use codebuddy_path as executable
            else:
                logger.warning(
                    "--codebuddy-path is deprecated when using --provider. "
                    "Use --executable instead."
                )
        
        provider = get_provider(
            name=args.provider,
            executable=executable,
            model=args.model,
            extra_args=args.extra_args,
            test_rules_file=getattr(args, 'test_rules', None),
        )
        
        logger.info(f"Using AI provider: {provider}")
        
        # Create orchestrator
        orchestrator = TodoOrchestrator(
            todos_file=args.config,
            provider=provider,
            workspace=args.workspace,
            timeout=args.timeout,
            log_dir=_log_dir_raw,
            ideas_file=args.ideas,
            idle_interval=args.idle_interval,
            use_cli=args.use_cli,
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
        
        if args.status:
            print_status(orchestrator)
            return
        
        # Process ideas before running tasks (if ideas file is configured)
        if orchestrator.ideas_watcher:
            orchestrator.check_and_process_ideas()
        
        if args.idle:
            # Idle mode: run tasks then wait for new ideas
            orchestrator.run_with_idle(
                task_id=args.task,
                skip_completed=not args.no_skip,
            )
        else:
            # Normal mode: run tasks and exit
            results = orchestrator.run(
                task_id=args.task,
                skip_completed=not args.no_skip,
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
        # Finalize conversation logs even on interrupt
        if 'orchestrator' in dir() and orchestrator.conv_logger:
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
