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
import argparse
import logging
import yaml
from typing import Optional, List

from codebuddy_client import CodeBuddyClient, AICallError
from task_executor import (
    SimpleTaskExecutor,
    NestedTaskExecutor,
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

    def __init__(
        self,
        todos_file: str = "todos.yaml",
        state_file: str = "todos_state.yaml",
        codebuddy_path: str = "codebuddy",
        model: str = "glm-5.0-ioa",
        workspace: str = ".",
        timeout: int = 3600,
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = 30,
    ):
        """
        Initialize the TodoOrchestrator.
        
        Args:
            todos_file: Path to the task configuration YAML
            state_file: Path to the state persistence file
            codebuddy_path: Path to CodeBuddy executable
            model: AI model to use
            workspace: Working directory for CodeBuddy
            timeout: Default timeout for AI calls
            log_dir: Root directory for conversation logs (None to disable)
            ideas_file: Path to ideas.md file (None to disable ideas watching)
            idle_interval: Seconds between idle checks for new ideas (default: 30)
        """
        self.todos_file = todos_file
        self.codebuddy_path = codebuddy_path
        self.model = model
        self.workspace = workspace
        self.timeout = timeout
        self.idle_interval = idle_interval
        
        self.state_manager = StateManager(state_file)
        self.conv_logger = ConversationLogger(log_dir) if log_dir else None
        self.simple_executor = SimpleTaskExecutor()
        self.nested_executor = NestedTaskExecutor()
        
        # Ideas watcher (optional)
        if ideas_file:
            processed_state = os.path.join(
                os.path.dirname(state_file) or '.', '.ideas_processed.yaml'
            )
            self.ideas_watcher = IdeasWatcher(
                ideas_file=ideas_file,
                todos_file=todos_file,
                processed_state_file=processed_state,
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
            valid_types = ['simple', 'nested']
        
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
        
        # Validate long_running tasks
        if task_type == 'long_running':
            if 'command' not in task:
                raise ConfigError(
                    f"Long-running task {task['id']} must have a 'command' field"
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
        print(f"  Model: {self.model}")
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
        client = CodeBuddyClient(
            codebuddy_path=self.codebuddy_path,
            model=self.model,
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
            
            # Add subtask info for nested tasks
            if task['type'] == 'nested' and 'subtasks' in task:
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
        client = CodeBuddyClient(
            codebuddy_path=self.codebuddy_path,
            model=self.model,
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
        print(f"  Model: {self.model}")
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


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('orchestrator.log', encoding='utf-8'),
        ],
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


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CodeBuddy Todo Orchestrator - AI-driven task execution system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrator.py                          # Run all tasks
  python orchestrator.py --config my_tasks.yaml   # Use custom config
  python orchestrator.py --task 2                  # Run only task 2
  python orchestrator.py --status                  # Show current status
  python orchestrator.py --reset                   # Reset all state
  python orchestrator.py --verbose                 # Enable debug logging
  python orchestrator.py --ideas ideas.md          # Watch ideas.md for new ideas
  python orchestrator.py --idle --ideas ideas.md   # Run tasks then idle for ideas
        """,
    )
    
    parser.add_argument(
        '--config', '-c',
        default='todos.yaml',
        help='Path to task configuration file (default: todos.yaml)',
    )
    parser.add_argument(
        '--state', '-s',
        default='todos_state.yaml',
        help='Path to state file (default: todos_state.yaml)',
    )
    parser.add_argument(
        '--task', '-t',
        type=str,
        default=None,
        help='Execute only the specified task ID',
    )
    parser.add_argument(
        '--codebuddy-path',
        default='codebuddy',
        help='Path to CodeBuddy executable (default: codebuddy)',
    )
    parser.add_argument(
        '--model', '-m',
        default='glm-5.0-ioa',
        help='AI model to use (default: glm-5.0-ioa)',
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
        help='Root directory for conversation logs (e.g. logs). Disabled if not set.',
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
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(verbose=args.verbose)
    
    try:
        # Validate idle mode requires ideas file
        if args.idle and not args.ideas:
            print("❌ --idle mode requires --ideas to be set.")
            sys.exit(1)
        
        # Create orchestrator
        orchestrator = TodoOrchestrator(
            todos_file=args.config,
            state_file=args.state,
            codebuddy_path=args.codebuddy_path,
            model=args.model,
            workspace=args.workspace,
            timeout=args.timeout,
            log_dir=args.log_dir,
            ideas_file=args.ideas,
            idle_interval=args.idle_interval,
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
                print(f"📝 Conversation logs saved to: {orchestrator.conv_logger.get_session_dir()}")
            
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
            print(f"\n📝 Conversation logs saved to: {orchestrator.conv_logger.get_session_dir()}")
        print(f"\n\n⚠️  Interrupted by user. State has been saved.")
        print(f"    Run again to resume from where you left off.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
