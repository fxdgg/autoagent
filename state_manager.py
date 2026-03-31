"""
State Manager - Handles task state persistence and management.

This module manages:
- Loading and saving state to todos_state.yaml
- Task status tracking
- Execution history recording
- AI decision recording
"""

import os
import time
import yaml
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class StateManager:
    """
    Manages task execution state with YAML persistence.
    
    State structure:
    {
        "tasks": {
            "1": {"status": "pending", "attempts": 0, ...},
            "2": {"status": "in_progress", ...},
            ...
        }
    }
    """

    def __init__(self, state_file: str = "todos_state.yaml"):
        """
        Initialize StateManager.
        
        Args:
            state_file: Path to the state persistence file
        """
        self.state_file = state_file
        self._lock = threading.Lock()
        self.state = self._load_state()

    def _load_state(self) -> dict:
        """Load state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and isinstance(data, dict):
                        logger.info(f"Loaded state from {self.state_file}")
                        return data
        except Exception as e:
            logger.warning(f"Failed to load state file: {e}")
        
        return {"tasks": {}}

    def save_state(self):
        """Save current state to file (thread-safe)."""
        with self._lock:
            try:
                with open(self.state_file, 'w', encoding='utf-8') as f:
                    yaml.dump(
                        self.state, f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                logger.debug(f"State saved to {self.state_file}")
            except Exception as e:
                logger.error(f"Failed to save state: {e}")
                raise

    def get_task_state(self, task_id: str) -> dict:
        """
        Get the state of a specific task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            dict: Task state (empty dict with status=pending if not found)
        """
        task_id = str(task_id)
        return self.state["tasks"].get(task_id, {"status": "pending", "attempts": 0})

    def mark_task_status(self, task_id: str, status: str, **kwargs):
        """
        Update task status and additional fields.
        
        Args:
            task_id: Task identifier
            status: New status value
            **kwargs: Additional fields to update
        """
        task_id = str(task_id)
        if task_id not in self.state["tasks"]:
            self.state["tasks"][task_id] = {}
        
        self.state["tasks"][task_id]["status"] = status
        self.state["tasks"][task_id].update(kwargs)
        self.save_state()

    def update_task_field(self, task_id: str, field: str, value):
        """
        Update a single field in a task's state.
        
        Args:
            task_id: Task identifier
            field: Field name to update
            value: New value for the field
        """
        task_id = str(task_id)
        if task_id not in self.state["tasks"]:
            self.state["tasks"][task_id] = {}
        
        self.state["tasks"][task_id][field] = value
        self.save_state()

    def add_task_history(self, task_id: str, entry: dict):
        """
        Add an entry to task's execution history.
        
        Args:
            task_id: Task identifier
            entry: History entry dict
        """
        task_id = str(task_id)
        if task_id not in self.state["tasks"]:
            self.state["tasks"][task_id] = {}
        
        if "history" not in self.state["tasks"][task_id]:
            self.state["tasks"][task_id]["history"] = []
        
        self.state["tasks"][task_id]["history"].append(entry)
        self.save_state()

    def add_ai_decision(self, task_id: str, decision: dict):
        """
        Record an AI decision for a task.
        
        Args:
            task_id: Task identifier
            decision: AI decision dict
        """
        task_id = str(task_id)
        if task_id not in self.state["tasks"]:
            self.state["tasks"][task_id] = {}
        
        if "ai_decisions" not in self.state["tasks"][task_id]:
            self.state["tasks"][task_id]["ai_decisions"] = []
        
        self.state["tasks"][task_id]["ai_decisions"].append(decision)
        self.save_state()

    def add_main_task_evaluation(self, task_id: str, evaluation: dict):
        """
        Record a main task evaluation result.
        
        Args:
            task_id: Task identifier  
            evaluation: Evaluation result dict
        """
        task_id = str(task_id)
        if task_id not in self.state["tasks"]:
            self.state["tasks"][task_id] = {}
        
        if "main_task_evaluations" not in self.state["tasks"][task_id]:
            self.state["tasks"][task_id]["main_task_evaluations"] = []
        
        self.state["tasks"][task_id]["main_task_evaluations"].append(evaluation)
        self.save_state()

    def reset(self):
        """Reset all state."""
        self.state = {"tasks": {}}
        self.save_state()
        logger.info("State reset")

    def get_summary(self) -> dict:
        """
        Get a summary of all task states.
        
        Returns:
            dict: Summary with counts by status
        """
        summary = {
            "total": 0,
            "pending": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
        }
        
        for task_id, task_state in self.state["tasks"].items():
            summary["total"] += 1
            status = task_state.get("status", "pending")
            if status in summary:
                summary[status] += 1
        
        return summary

    def get_in_progress_tasks(self) -> list:
        """
        Get list of task IDs that are currently in_progress.
        
        Returns:
            list: List of task_id strings with status 'in_progress'
        """
        in_progress = []
        for task_id, task_state in self.state["tasks"].items():
            if task_state.get("status") == "in_progress":
                in_progress.append(task_id)
        return in_progress

    def record_interrupt(self, task_id: str, attempt: int = 0):
        """
        Record an interruption (e.g., Ctrl+C) in the task's history.
        
        Args:
            task_id: Task identifier
            attempt: Current attempt number (uses existing if not provided)
        """
        task_id = str(task_id)
        if task_id not in self.state["tasks"]:
            return
        
        task_state = self.state["tasks"][task_id]
        current_attempt = task_state.get("attempts", 0)
        if attempt == 0:
            attempt = current_attempt
        
        entry = {
            "attempt": attempt,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "result": "interrupted",
            "summary": "Interrupted by user (Ctrl+C)",
        }
        
        if "history" not in self.state["tasks"][task_id]:
            self.state["tasks"][task_id]["history"] = []
        
        self.state["tasks"][task_id]["history"].append(entry)
        self.save_state()
        logger.info(f"Recorded interrupt for task {task_id}")
