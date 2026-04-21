"""Orchestrator common utilities and shared types.

Contains session management helpers, AI client factory, and config loading
that are shared between the linear orchestrator and the AI orchestrator.
"""

import os
import sys
import csv
import time
import string
import random
import logging
import yaml

from ai_client import AIClient, AIClientSDK, AIClientTest, AICallError
from ai_client.ai_providers import AIProvider, TestProvider
from task_executor.task_executor_common import ConfigError, ExecutionError
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)

__all__ = [
    "ConfigError",
    "ExecutionError",
    "SessionHelper",
    "create_ai_client",
    "load_orchestrator_config",
]


# ── Config loading ──────────────────────────────────────────────────

def load_orchestrator_config() -> dict:
    """Load config.yaml from the project root (two levels up from this file).

    Returns:
        dict: Configuration values. Empty dict if file not found.
    """
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.yaml"
    )
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            logger.debug(f"Loaded config from {config_path}: {config}")
            return config
        except Exception as e:
            logger.warning(f"Failed to load config.yaml: {e}")
    return {}


# ── AI client factory ───────────────────────────────────────────────

def create_ai_client(
    provider: AIProvider,
    workspace: str,
    timeout: int,
    bash_timeout: int,
    context_id: str,
    use_cli: bool = False,
    backoff_max_wait: int = None,
    session_dir: str = None,
):
    """Create an AI client instance for the given context.

    Centralises client creation logic used by both task execution
    and the AI scheduler.

    Args:
        provider: AI provider instance.
        workspace: Working directory for AI tool.
        timeout: Session timeout in seconds.
        bash_timeout: No-new-output timeout in seconds.
        context_id: Context identifier for the client.
        use_cli: If True, use CLI subprocess instead of SDK.
        backoff_max_wait: Max wait time for exponential backoff.
        session_dir: Session directory (used for TestProvider fallback paths).

    Returns:
        An AIClient, AIClientSDK, or AIClientTest instance.
    """
    if backoff_max_wait is None:
        backoff_max_wait = DEFAULTS['backoff_max_wait']

    if isinstance(provider, TestProvider):
        client = AIClientTest(
            provider=provider,
            workspace=workspace,
            timeout=timeout,
            bash_timeout=bash_timeout,
            context_id=context_id,
        )
        client._fallback_exec_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "util", "autoagent_exec.py"
        )
        client._fallback_log_dir = session_dir or ""
    elif use_cli:
        client = AIClient(
            provider=provider,
            workspace=workspace,
            timeout=timeout,
            bash_timeout=bash_timeout,
            context_id=context_id,
        )
        client._backoff_max = backoff_max_wait
    else:
        client = AIClientSDK(
            provider=provider,
            workspace=workspace,
            timeout=timeout,
            bash_timeout=bash_timeout,
            context_id=context_id,
        )
        client._backoff_max = backoff_max_wait
    return client


# ── Session management helpers ──────────────────────────────────────

class SessionHelper:
    """Static helper methods for session directory management.

    These were originally ``@staticmethod`` methods on ``TodoOrchestrator``.
    They are grouped here so both the linear and AI orchestrators can
    share them without duplicating code.
    """

    SESSIONS_FILE = "sessions.csv"

    @staticmethod
    def generate_session_name(workspace: str) -> str:
        """Generate a new session directory name: ``<basename>_<random8>``."""
        basename = os.path.basename(os.path.abspath(workspace))
        rand_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        return f"{basename}_{rand_suffix}"

    @staticmethod
    def append_sessions_csv(log_dir: str, subdir_name: str, workspace: str):
        """Append a row to ``<log_dir>/sessions.csv``."""
        csv_path = os.path.join(log_dir, SessionHelper.SESSIONS_FILE)
        write_header = not os.path.exists(csv_path)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(csv_path, "a", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                if write_header:
                    writer.writerow(["session_id", "workspace", "created_at", "last_accessed_at"])
                writer.writerow([
                    subdir_name,
                    workspace,
                    now,
                    now,
                ])
        except Exception as e:
            logger.warning(f"Failed to append to {csv_path}: {e}")

    @staticmethod
    def load_sessions_csv(log_dir: str) -> list:
        """Load all rows from ``sessions.csv``.

        Returns a list of dicts with keys ``session_id``, ``workspace``,
        ``created_at``, and ``last_accessed_at``.

        For backward compatibility, if ``last_accessed_at`` is missing
        from a row, it falls back to ``created_at``.
        """
        csv_path = os.path.join(log_dir, SessionHelper.SESSIONS_FILE)
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
    def find_latest_session_for_workspace(log_dir: str, workspace: str) -> str:
        """Find the most recently *accessed* session for *workspace*.

        Looks up ``sessions.csv`` and returns the ``session_id`` with the
        largest ``last_accessed_at`` value among rows matching *workspace*.
        Falls back to ``created_at`` for rows that lack the column (backward
        compatibility with older CSV files).

        Returns the ``session_id`` string, or empty string if none found.
        """
        rows = SessionHelper.load_sessions_csv(log_dir)
        norm_ws = os.path.normcase(os.path.normpath(workspace))
        best = ""
        best_ts = ""
        for row in rows:
            row_ws = os.path.normcase(os.path.normpath(row.get("workspace", "")))
            if row_ws == norm_ws:
                ts = row.get("last_accessed_at") or row.get("created_at", "")
                if ts >= best_ts:
                    best_ts = ts
                    best = row.get("session_id", "")
        return best

    @staticmethod
    def touch_session(log_dir: str, session_id: str):
        """Update ``last_accessed_at`` for *session_id* in ``sessions.csv``.

        If the CSV does not yet have a ``last_accessed_at`` column (old
        format), the column is added transparently.
        """
        csv_path = os.path.join(log_dir, SessionHelper.SESSIONS_FILE)
        if not os.path.isfile(csv_path):
            return
        rows = SessionHelper.load_sessions_csv(log_dir)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        found = False
        for row in rows:
            if row.get("session_id") == session_id:
                row["last_accessed_at"] = now
                found = True
                break
        if not found:
            return
        try:
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter="\t")
                writer.writerow(["session_id", "workspace", "created_at", "last_accessed_at"])
                for row in rows:
                    writer.writerow([
                        row.get("session_id", ""),
                        row.get("workspace", ""),
                        row.get("created_at", ""),
                        row.get("last_accessed_at", row.get("created_at", "")),
                    ])
        except Exception as e:
            logger.warning(f"Failed to update {csv_path}: {e}")

    @staticmethod
    def update_workspace_in_csv(
        log_dir: str, old_workspace: str, new_workspace: str,
    ) -> int:
        """Replace *old_workspace* with *new_workspace* in ``sessions.csv``.

        Returns the number of rows updated.
        """
        csv_path = os.path.join(log_dir, SessionHelper.SESSIONS_FILE)
        if not os.path.isfile(csv_path):
            return 0
        rows = SessionHelper.load_sessions_csv(log_dir)
        norm_old = os.path.normcase(os.path.normpath(old_workspace))
        count = 0
        for row in rows:
            row_ws = os.path.normcase(os.path.normpath(row.get("workspace", "")))
            if row_ws == norm_old:
                row["workspace"] = os.path.normpath(new_workspace)
                count += 1
        if count:
            try:
                with open(csv_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f, delimiter="\t")
                    writer.writerow(["session_id", "workspace", "created_at", "last_accessed_at"])
                    for row in rows:
                        writer.writerow([
                            row.get("session_id", ""),
                            row.get("workspace", ""),
                            row.get("created_at", ""),
                            row.get("last_accessed_at", row.get("created_at", "")),
                        ])
            except Exception as e:
                logger.warning(f"Failed to update {csv_path}: {e}")
                return 0
        return count

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
        sh = SessionHelper

        if mode == "continue":
            # Look up the latest session for this workspace from sessions.csv
            subdir = sh.find_latest_session_for_workspace(log_dir, workspace)
            if not subdir:
                # Workspace not found – maybe the folder was moved.
                # Ask the user whether to supply the old path so we can
                # update sessions.csv, or just start fresh.
                print("⚠️  No session found for this workspace in sessions.csv.")
                print(f"   Current workspace: {workspace}")
                print()
                print("   The workspace folder may have been moved or renamed.")
                print("   If you know the OLD path that was used when the session")
                print("   was created, enter it below and sessions.csv will be updated.")
                print("   Otherwise, press Enter to exit.")
                print()
                try:
                    old_path = input("   Old workspace path (or Enter to exit): ").strip()
                except (EOFError, KeyboardInterrupt):
                    old_path = ""
                if old_path:
                    old_path = os.path.abspath(old_path)
                    count = sh.update_workspace_in_csv(log_dir, old_path, workspace)
                    if count:
                        print(f"   ✅ Updated {count} session(s): {old_path} → {workspace}")
                        # Retry lookup after the update
                        subdir = sh.find_latest_session_for_workspace(log_dir, workspace)
                    else:
                        print(f"   ⚠️  No sessions matched the old path: {old_path}")
                if not subdir:
                    print("❌ Still no session found for this workspace.")
                    print("   Use --resume <session_id> or run without --continue to start fresh.")
                    sys.exit(1)
            session_dir = os.path.join(log_dir, subdir)
            if not os.path.isdir(session_dir):
                print(f"❌ Session directory not found: {session_dir}")
                print(f"   The session '{subdir}' may have been deleted.")
                sys.exit(1)
            sh.touch_session(log_dir, subdir)
            return session_dir

        if mode == "resume":
            if not resume_id:
                print("❌ --resume requires a session ID.")
                sys.exit(1)
            # Search sessions.csv
            rows = sh.load_sessions_csv(log_dir)
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
                print(f"   Please check the session ID, or use --list-sessions to see available sessions.")
                print(f"   You can also remove the --resume flag to start a fresh session.")
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
            sh.touch_session(log_dir, subdir)
            return session_dir

        # mode == "new"
        subdir = sh.generate_session_name(workspace)
        sh.append_sessions_csv(log_dir, subdir, workspace)
        return os.path.join(log_dir, subdir)

    @staticmethod
    def get_session_status(session_dir: str) -> str:
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
