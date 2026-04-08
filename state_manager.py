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
            "1.1@2.1": {"status": "completed", ...},  # round-scoped subtask
            ...
        }
    }

    Round-scoped keys use the format ``task_id@round_label`` (e.g.,
    ``"1.2@3.1"``).  These are internal bookkeeping entries for subtask
    state within a specific round and are excluded from summary counts
    and in-progress queries.
    """

    # Separator used in round-scoped state keys.
    ROUND_SEP = "@"

    @staticmethod
    def round_key(task_id: str, round_label: str | None) -> str:
        """Build a round-scoped state key.

        Returns ``"task_id@round_label"`` when *round_label* is given,
        or the plain ``task_id`` string otherwise.
        """
        task_id = str(task_id)
        if round_label:
            return f"{task_id}{StateManager.ROUND_SEP}{round_label}"
        return task_id

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
        """Save current state to file (thread-safe, crash-safe).

        Uses write-to-temp + flush + fsync + atomic rename so the state
        file is never left empty or half-written after a crash or
        interrupt.
        """
        with self._lock:
            temp_file = self.state_file + ".tmp"
            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    yaml.dump(
                        self.state, f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                    f.flush()
                    os.fsync(f.fileno())
                # Atomic replace — on Windows os.replace is atomic
                # for same-volume files.
                os.replace(temp_file, self.state_file)
                logger.debug(f"State saved to {self.state_file}")
            except Exception as e:
                logger.error(f"Failed to save state: {e}")
                # Clean up temp file on failure
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
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

        Round-scoped keys (containing ``@``) are excluded from counts.

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
            if self.ROUND_SEP in task_id:
                continue
            summary["total"] += 1
            status = task_state.get("status", "pending")
            if status in summary:
                summary[status] += 1

        return summary

    def get_in_progress_tasks(self) -> list:
        """
        Get list of task IDs that are currently in_progress.

        Round-scoped keys (containing ``@``) are excluded.

        Returns:
            list: List of task_id strings with status 'in_progress'
        """
        in_progress = []
        for task_id, task_state in self.state["tasks"].items():
            if self.ROUND_SEP in task_id:
                continue
            if task_state.get("status") == "in_progress":
                in_progress.append(task_id)
        return in_progress

    def record_interrupt(self, task_id: str, attempt: int = 0):
        """
        Record an interruption (e.g., Ctrl+C) in the task's history.

        Also records the interrupt on any round-scoped subtask keys
        (``id@round``) that are currently ``in_progress``, so the
        information is visible to the prompt builder on resume.

        Args:
            task_id: Task identifier
            attempt: Current attempt number (uses existing if not provided)
        """
        task_id = str(task_id)

        # Collect keys to record: the task itself + any in-progress
        # round-scoped subtasks that belong to it (e.g. "1.2@3.1" for
        # parent task "1").
        keys_to_record = []
        if task_id in self.state["tasks"]:
            keys_to_record.append(task_id)
        # Find in-progress round-scoped keys whose base subtask id starts
        # with the parent task id (e.g. "1." matches "1.2@3.1").
        prefix = task_id + "."
        for key, st in self.state["tasks"].items():
            if self.ROUND_SEP not in key:
                continue
            base_id = key.split(self.ROUND_SEP)[0]
            if (base_id == task_id or base_id.startswith(prefix)) and st.get("status") == "in_progress":
                keys_to_record.append(key)

        for key in keys_to_record:
            task_state = self.state["tasks"][key]
            current_attempt = task_state.get("attempts", 0)
            a = attempt if attempt else current_attempt

            entry = {
                "attempt": a,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "result": "interrupted",
                "summary": "Interrupted by user (Ctrl+C)",
            }

            if "history" not in self.state["tasks"][key]:
                self.state["tasks"][key]["history"] = []
            self.state["tasks"][key]["history"].append(entry)

        if keys_to_record:
            self.save_state()
            logger.info(f"Recorded interrupt for {keys_to_record}")
