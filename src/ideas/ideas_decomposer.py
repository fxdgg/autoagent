"""Ideas Decomposer Mixin - handles decomposing ideas into structured TODO tasks.

This mixin provides the ``_decompose_idea_to_tasks`` method which is mixed into
``IdeasWatcher``.  It relies on attributes and helper methods defined on the
host class (IdeasWatcher), such as ``_load_existing_config``,
``_get_temp_tasks_path``, ``_cleanup_temp_file``, ``_start_temp_file_watcher``,
``_stop_temp_file_watcher``, ``_read_tasks_from_temp_file``,
``_extract_yaml_tasks``, ``_plans_state``, ``_record_idea_state``, etc.
"""

import logging
import yaml
from typing import TYPE_CHECKING

from ai_client import AIClient, AICallError
from logger import ConversationLogger
from prompts.ideas_decompose import build_ideas_decompose_prompt

if TYPE_CHECKING:
    pass  # IdeasWatcher would go here if needed for type hints

logger = logging.getLogger(__name__)


class _BlockStyleDumper(yaml.SafeDumper):
    """Custom YAML dumper that uses block scalar (|) style for multiline strings."""
    pass


def _str_representer(dumper, data):
    """Represent strings with block scalar style when they contain newlines."""
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


_BlockStyleDumper.add_representer(str, _str_representer)


class IdeasDecomposerMixin:
    """Mixin that provides idea-to-task decomposition logic.

    Must be mixed into a class that provides the following attributes/methods:
    - ``_load_existing_config() -> dict``
    - ``_get_temp_tasks_path() -> str``
    - ``_cleanup_temp_file()``
    - ``_start_temp_file_watcher()``
    - ``_stop_temp_file_watcher()``
    - ``_read_tasks_from_temp_file() -> Optional[dict]``
    - ``_extract_yaml_tasks(response: str) -> dict``
    - ``_plans_state: dict``
    - ``_record_idea_state(idea, status, **kwargs)``
    - ``max_plan_retries: int``
    - ``_review_and_validate_loop(...)``  (from IdeasReviewerMixin)
    - ``_human_review_loop(...)``  (from IdeasReviewerMixin)
    """

    def _decompose_idea_to_tasks(
        self,
        client: AIClient,
        idea: dict,
        review_client: AIClient = None,
        conv_logger: ConversationLogger = None,
        idea_index: int = 1,
        human_review: bool = False,
    ) -> tuple:
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
            client: AIClient instance
            idea: Idea dict with 'title', 'content', 'hash' fields
            review_client: Optional AIClient with fresh context for review
            conv_logger: Optional ConversationLogger to record prompts/responses
            idea_index: 1-based index of the idea (for logging)
            human_review: If True, pause for human approval after AI review passes

        Returns:
            tuple: (parsed_data, next_id) where parsed_data is a dict containing
                'tasks' and optionally description fields, and next_id is the
                starting task ID used for this batch.
        """
        # Load existing config to determine the next available task ID
        # and to provide existing todos context to the decomposition AI
        existing_config = self._load_existing_config()
        existing_tasks = existing_config.get('tasks', [])
        max_id = 0
        for task in existing_tasks:
            tid = task.get('id', 0)
            if isinstance(tid, (int, float)):
                max_id = max(max_id, int(tid))
        next_id = max_id + 1

        # Serialize existing todos for the decomposition prompt (read-only context)
        existing_todos_yaml = ""
        if existing_tasks:
            # Build a config snapshot with descriptions + tasks for context
            snapshot = {}
            desc = existing_config.get('description', '')
            if desc:
                snapshot['description'] = desc
            # Include any round-scoped descriptions (description@N)
            for key, val in existing_config.items():
                if key.startswith('description@') and isinstance(val, str):
                    snapshot[key] = val
            snapshot['tasks'] = existing_tasks
            existing_todos_yaml = yaml.dump(
                snapshot, Dumper=_BlockStyleDumper,
                default_flow_style=False, allow_unicode=True,
                sort_keys=False, width=120,
            )

        # Resolve paths for the prompt
        temp_tasks_path = self._get_temp_tasks_path()
        # Clean up any leftover temp file from a previous run
        self._cleanup_temp_file()

        # ── Resume checkpoint: skip plan phase if tasks already generated ──
        saved_plan = self._plans_state.get("ideas", {}).get(idea['hash'], {}).get("plan_data")
        if not saved_plan:
            # Fallback to legacy plan_tasks
            legacy_plan = self._plans_state.get("ideas", {}).get(idea['hash'], {}).get("plan_tasks")
            if legacy_plan and isinstance(legacy_plan, list) and len(legacy_plan) > 0:
                saved_plan = {"tasks": legacy_plan, "description": ""}

        if saved_plan and isinstance(saved_plan, dict) and saved_plan.get('tasks'):
            print(f"   ♻️  Resuming from saved plan (skipping decomposition phase)")
            logger.info(f"Resuming idea '{idea['title']}' from saved plan_data ({len(saved_plan['tasks'])} tasks)")
            parsed_data = saved_plan
            result = yaml.dump(parsed_data, Dumper=_BlockStyleDumper, default_flow_style=False,
                               allow_unicode=True, sort_keys=False)
        else:
            # ── Plan phase with retry loop ──
            # Each attempt uses a fresh AI session (reset_session) to avoid
            # issues carried over from a previous failed session.
            parsed_data = None
            result = ""
            mode = self._detect_mode()
            for plan_attempt in range(1, self.max_plan_retries + 1):
                prompt = build_ideas_decompose_prompt(
                    idea_content=idea['content'],
                    next_id=next_id,
                    temp_tasks_path=temp_tasks_path,
                    existing_todos_yaml=existing_todos_yaml,
                    mode=mode,
                )

                try:
                    # Fresh session for each plan attempt
                    if plan_attempt > 1:
                        client.reset_session()
                        print(f"   🔄 Plan retry {plan_attempt}/{self.max_plan_retries} (new session)")

                    # Log prompt before AI call (crash-safe)
                    if conv_logger:
                        conv_logger.log_ideas_prompt(idea['title'], idea_index, prompt)

                    self._start_temp_file_watcher()
                    result = client.ask(prompt)

                    # Log response after AI call
                    if conv_logger:
                        conv_logger.log_ideas_response(result)

                    # Parse the YAML: prefer temp file, fall back to response text
                    parsed_data = self._read_tasks_from_temp_file()
                    if parsed_data is None:
                        logger.info("Temp file yielded no valid tasks, falling back to response text parsing")
                        parsed_data = self._extract_yaml_tasks(result)
                    self._cleanup_temp_file()

                except AICallError as e:
                    self._stop_temp_file_watcher()
                    logger.error(f"AI call failed for idea decomposition (attempt {plan_attempt}): {e}")
                    if plan_attempt >= self.max_plan_retries:
                        raise
                    print(f"   ❌ Plan attempt {plan_attempt} failed: {e}")
                    continue

                if parsed_data and parsed_data.get('tasks'):
                    if plan_attempt > 1:
                        print(f"   ✅ Plan succeeded on attempt {plan_attempt}")
                    break
                else:
                    logger.warning(f"Plan attempt {plan_attempt} produced no valid tasks")
                    if plan_attempt < self.max_plan_retries:
                        print(f"   ❌ Plan attempt {plan_attempt} produced no valid tasks, retrying...")
                    else:
                        print(f"   ❌ Plan failed after {self.max_plan_retries} attempts, skipping idea")

            # Save plan output as checkpoint so a resumed run can skip to review
            if parsed_data and parsed_data.get('tasks'):
                self._record_idea_state(idea, "in_progress", plan_data=parsed_data)

        # Review + validation loop
        if parsed_data and parsed_data.get('tasks'):
            parsed_data, result = self._review_and_validate_loop(
                client, review_client, idea, parsed_data, result,
                conv_logger=conv_logger,
                next_id=next_id,
                existing_todos_yaml=existing_todos_yaml,
            )

        # Human review loop: after AI review + validation passes, pause for human approval
        if human_review and parsed_data and parsed_data.get('tasks'):
            parsed_data = self._human_review_loop(
                client, review_client, idea, parsed_data, result,
                conv_logger=conv_logger,
                next_id=next_id,
            )

        # Write section end separator
        if conv_logger:
            conv_logger.log_ideas_section_end()

        return (parsed_data or {}, next_id)
