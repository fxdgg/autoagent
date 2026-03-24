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
        """
        self.todos_file = todos_file
        self.codebuddy_path = codebuddy_path
        self.model = model
        self.workspace = workspace
        self.timeout = timeout
        
        self.state_manager = StateManager(state_file)
        self.simple_executor = SimpleTaskExecutor()
        self.nested_executor = NestedTaskExecutor()
        
        self.todos = self._load_todos()

    def _load_todos(self) -> list:
        """
        Load and validate task configuration from YAML file.
        
        Returns:
            list: List of task configurations
            
        Raises:
            ConfigError: If the file is invalid
        """
        if not os.path.exists(self.todos_file):
            raise ConfigError(f"Configuration file not found: {self.todos_file}")
        
        try:
            with open(self.todos_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML syntax error in {self.todos_file}: {e}")
        
        if not config or not isinstance(config, dict):
            raise ConfigError(f"Invalid configuration format in {self.todos_file}")
        
        tasks = config.get('tasks', [])
        if not tasks:
            raise ConfigError(f"No tasks defined in {self.todos_file}")
        
        # Validate each task
        for task in tasks:
            self._validate_task(task)
        
        logger.info(f"Loaded {len(tasks)} tasks from {self.todos_file}")
        return tasks

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
                    task, client, self.state_manager, is_subtask=False
                )
            elif task_type == 'nested':
                return self.nested_executor.execute(
                    task, client, self.state_manager
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
        print("✅ All task states have been reset.")


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
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(verbose=args.verbose)
    
    try:
        # Create orchestrator
        orchestrator = TodoOrchestrator(
            todos_file=args.config,
            state_file=args.state,
            codebuddy_path=args.codebuddy_path,
            model=args.model,
            workspace=args.workspace,
            timeout=args.timeout,
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
        
        # Run tasks
        results = orchestrator.run(
            task_id=args.task,
            skip_completed=not args.no_skip,
        )
        
        # Exit with error code if any tasks failed
        if results['failed_tasks'] > 0:
            sys.exit(1)
            
    except ConfigError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n\n⚠️  Interrupted by user. State has been saved.")
        print(f"    Run again to resume from where you left off.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
