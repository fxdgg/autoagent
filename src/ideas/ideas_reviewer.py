"""Ideas Reviewer Mixin - handles AI review, validation, and human review of tasks.

This mixin provides the review-related methods which are mixed into
``IdeasWatcher``:
- ``_review_and_validate_loop``
- ``_review_tasks``
- ``_check_review_passed``
- ``_human_review_loop``

It relies on attributes and helper methods defined on the host class
(IdeasWatcher), such as ``_get_temp_tasks_path``, ``_cleanup_temp_file``,
``_start_temp_file_watcher``, ``_stop_temp_file_watcher``,
``_read_tasks_from_temp_file``, ``_extract_yaml_tasks``,
``_validate_tasks_schema``, ``max_review_rounds``, ``max_validation_retries``.
"""

import logging
import re
import yaml
from typing import Optional, List

from ai_client import AIClient, AICallError
from logger import ConversationLogger
from prompts.ideas_review import (
    build_ideas_review_prompt,
    build_revision_prompt,
)

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


class IdeasReviewerMixin:
    """Mixin that provides task review and validation logic.

    Must be mixed into a class that provides the following attributes/methods:
    - ``_get_temp_tasks_path() -> str``
    - ``_cleanup_temp_file()``
    - ``_start_temp_file_watcher()``
    - ``_stop_temp_file_watcher()``
    - ``_read_tasks_from_temp_file() -> Optional[dict]``
    - ``_extract_yaml_tasks(response: str) -> dict``
    - ``_validate_tasks_schema(parsed_data, next_id) -> tuple``
    - ``max_review_rounds: int``
    - ``max_validation_retries: int``
    """

    def _review_and_validate_loop(
        self,
        client: AIClient,
        review_client: AIClient,
        idea: dict,
        parsed_data: dict,
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
        next_id: int = 1,
        existing_todos_yaml: str = "",
    ) -> tuple:
        """Run the AI review loop followed by schema validation.

        After the AI reviewer approves (or is skipped), the tasks are
        validated against the schema.  If validation fails, the errors
        are fed back into the review loop as feedback so the AI can fix
        them.  This repeats up to ``MAX_VALIDATION_RETRIES`` times.

        Args:
            client: Original AIClient (with existing context)
            review_client: Optional AIClient for AI review
            idea: Original idea dict
            parsed_data: Current parsed data containing tasks and description
            raw_yaml_response: Raw response from the last AI call
            conv_logger: Optional ConversationLogger

        Returns:
            (parsed_data, raw_yaml_response) — the final validated data and
            the last raw AI response.
        """
        result = raw_yaml_response

        for validation_attempt in range(1, self.max_validation_retries + 2):
            # --- AI review loop ---
            if review_client and parsed_data and parsed_data.get('tasks'):
                last_feedback = ""
                for review_round in range(1, self.max_review_rounds + 1):
                    review_passed, review_feedback, revised_data = self._review_tasks(
                        review_client, idea, parsed_data, result,
                        conv_logger=conv_logger,
                        review_round=review_round,
                        last_feedback=last_feedback,
                        next_id=next_id,
                        existing_todos_yaml=existing_todos_yaml,
                    )
                    if review_passed:
                        print(f"   ✅ Review passed (round {review_round})")
                        break
                    else:
                        last_feedback = review_feedback
                        if revised_data:
                            print(f"   🔧 Reviewer directly revised tasks (round {review_round})")
                            parsed_data = revised_data
                        else:
                            print(f"   🔄 Review rejected (round {review_round}), but reviewer did not provide revised tasks.")
                            # Reviewer didn't write a corrected file — accept current tasks
                            # (the reviewer's feedback is lost since we don't send it to planner anymore)
                            break
                else:
                    print(
                        f"   ⚠️  Max review rounds ({self.max_review_rounds}) reached, "
                        f"accepting current tasks"
                    )

            # --- Schema validation ("compile") ---
            if not parsed_data or not parsed_data.get('tasks'):
                break

            valid, errors = self._validate_tasks_schema(parsed_data, next_id=next_id)
            if valid:
                print(f"   ✅ Schema validation passed")
                break
            else:
                error_text = '\n'.join(f"  - {e}" for e in errors)
                print(f"   ❌ Schema validation failed (attempt {validation_attempt}/{self.max_validation_retries + 1}):")
                for e in errors:
                    print(f"      • {e}")

                if validation_attempt > self.max_validation_retries:
                    print(f"   ⚠️  Max validation retries ({self.max_validation_retries}) exceeded, accepting current tasks")
                    break

                # Feed validation errors back as review feedback for the reviewer to fix
                validation_feedback = (
                    f"Schema validation failed with the following errors:\n"
                    f"{error_text}\n\n"
                    f"Please fix these issues. Every task must conform to the schema."
                )
                print(f"   🔄 Sending validation errors to reviewer for revision...")

                # Send to the reviewer (same session) to fix
                # NOTE: Do NOT delete the temp file here — the AI may try to
                # read it before writing.  It will be overwritten by the AI
                # and cleaned up after we read the result.
                temp_tasks_path = self._get_temp_tasks_path()
                revision_prompt = build_revision_prompt(
                    temp_tasks_path=temp_tasks_path,
                    human_feedback=validation_feedback,
                    next_id=next_id,
                )
                try:
                    if conv_logger:
                        conv_logger.log_ideas_revision_prompt(validation_attempt, revision_prompt)
                    self._start_temp_file_watcher()
                    revision_result = review_client.ask(revision_prompt)
                    if conv_logger:
                        conv_logger.log_ideas_revision_response(revision_result)
                    parsed_data = self._read_tasks_from_temp_file()
                    if parsed_data is None:
                        logger.info("Temp file not found after validation-retry revision, falling back to response text parsing")
                        parsed_data = self._extract_yaml_tasks(revision_result)
                    self._cleanup_temp_file()
                    result = revision_result
                except AICallError as e:
                    self._stop_temp_file_watcher()
                    logger.error(f"AI call failed during validation-retry revision: {e}")
                    break
                # Loop back to AI review + validation

        return parsed_data, result

    def _review_tasks(
        self,
        review_client: AIClient,
        idea: dict,
        parsed_data: dict,
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
        review_round: int = 1,
        last_feedback: str = "",
        next_id: int = 1,
        existing_todos_yaml: str = "",
    ) -> tuple:
        """
        Send generated tasks to a fresh-context reviewer AI for quality check.

        If the reviewer rejects the tasks, it is instructed to directly modify
        the temp YAML file with corrections. The caller can then read the
        revised tasks from the temp file, potentially skipping a separate
        revision round.

        Args:
            review_client: AIClient with fresh context
            idea: Original idea dict
            parsed_data: Parsed data containing tasks and description
            raw_yaml_response: Raw YAML response from the decomposition AI
            conv_logger: Optional ConversationLogger
            review_round: 1-based review round number
            last_feedback: Feedback from the previous review round (if any)

        Returns:
            tuple: (passed: bool, feedback: str, revised_data: Optional[dict])
                   passed=True if review approves, feedback contains reviewer comments,
                   revised_data contains reviewer's corrected data if it rejected and
                   directly modified the file (None otherwise).
        """
        # Reset reviewer session so each review round starts with a fresh context.
        # Without this, the reviewer AI would see the full conversation history
        # from previous review rounds, which pollutes its judgment.
        review_client.reset_session()

        tasks_yaml = yaml.dump(parsed_data, Dumper=_BlockStyleDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)

        temp_tasks_path = self._get_temp_tasks_path()
        # Write current tasks to temp file so reviewer can modify it in-place
        self._cleanup_temp_file()
        try:
            with open(temp_tasks_path, 'w', encoding='utf-8') as f:
                f.write(tasks_yaml)
        except OSError as e:
            logger.warning(f"Failed to write temp file for reviewer: {e}")

        review_prompt = build_ideas_review_prompt(
            idea_content=idea['content'],
            temp_tasks_path=temp_tasks_path,
            next_id=next_id,
            existing_todos_yaml=existing_todos_yaml,
            mode=self._detect_mode(),
        )

        try:
            if conv_logger:
                conv_logger.log_ideas_review_prompt(review_round, review_prompt)

            self._start_temp_file_watcher()
            review_result = review_client.ask(review_prompt)

            if conv_logger:
                conv_logger.log_ideas_review_response(review_result)

            passed = self._check_review_passed(review_result)

            revised_data = None
            if not passed:
                # Try to read reviewer's corrected tasks from temp file
                revised_data = self._read_tasks_from_temp_file()
                if revised_data and revised_data.get('tasks'):
                    logger.info(f"Reviewer directly revised {len(revised_data['tasks'])} task(s) in temp file")
            self._cleanup_temp_file()

            return passed, review_result, revised_data

        except AICallError as e:
            logger.error(f"AI call failed for idea review: {e}")
            self._cleanup_temp_file()
            # On review failure, accept the tasks to avoid blocking
            return True, "", None

    @staticmethod
    def _check_review_passed(review_response: str) -> bool:
        """
        Check if the reviewer AI approved the tasks.

        Uses the same three-layer detection strategy as SimpleTaskExecutor:
        1. Strict negative markers (highest priority)
        2. Strict positive markers
        3. Fuzzy positive matching (fallback)

        Args:
            review_response: The reviewer's response text

        Returns:
            bool: True if review passed
        """
        lower = review_response.lower()

        # Layer 1: Strict negative markers
        if '❌ not completed' in lower or '❌not completed' in lower:
            return False

        # Layer 2: Strict positive markers
        if '✅ completed' in lower or '✅completed' in lower:
            return True

        # Layer 3: Fuzzy matching
        if re.search(r'✅.*completed', lower):
            if not re.search(r'not\s+completed|fail|reject', lower):
                return True

        # Default: not passed
        return False

    def _human_review_loop(
        self,
        client: AIClient,
        review_client: AIClient,
        idea: dict,
        parsed_data: dict,
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
        next_id: int = 1,
    ) -> dict:
        """
        Pause for human approval of the generated tasks.

        Flow when human rejects:
        1. Human provides feedback and/or edits the temp YAML file
        2. Revision prompt is sent to the **same reviewer** (session preserved)
        3. Reviewer revises the tasks
        4. A **new reviewer** (fresh session) reviews the revised tasks
        5. Human reviews again

        Args:
            client: Original AIClient
            review_client: AIClient for AI review
            idea: Original idea dict
            parsed_data: Current parsed data containing tasks and description
            raw_yaml_response: Raw response from the last AI call
            conv_logger: Optional ConversationLogger

        Returns:
            dict: The final approved parsed data
        """
        while True:
            print(f"\n   👀 Human Review Required for idea: {idea['title']}")
            print(f"   The generated tasks have been saved to: {self._get_temp_tasks_path()}")
            print(f"   You can review and edit this file directly.")

            # Write current tasks to temp file for human to review/edit
            tasks_yaml = yaml.dump(parsed_data, Dumper=_BlockStyleDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)
            self._cleanup_temp_file()
            try:
                with open(self._get_temp_tasks_path(), 'w', encoding='utf-8') as f:
                    f.write(tasks_yaml)
            except OSError as e:
                logger.warning(f"Failed to write temp file for human review: {e}")

            print(f"\n   Options:")
            print(f"   [y] Accept tasks (and any edits you made to the file)")
            print(f"   [n] Reject and provide feedback for AI to revise")
            print(f"   [s] Skip this idea for now")

            choice = input("   Your choice [y/n/s]: ").strip().lower()

            if choice == 'y':
                # Check if human edited the temp file
                edited_data = self._read_tasks_from_temp_file()
                if edited_data is not None:
                    # Validate the human-edited tasks
                    valid, errors = self._validate_tasks_schema(edited_data, next_id=next_id)
                    if valid:
                        parsed_data = edited_data
                        print(f"   ✅ Human approved the tasks (loaded from temp file).")
                    else:
                        print(f"   ⚠️  Temp file has schema errors:")
                        for e in errors:
                            print(f"      • {e}")
                        print(f"   Please fix the errors and try again.")
                        continue
                else:
                    print(f"   ✅ Human approved the tasks.")
                break

            elif choice == 'n':
                # Get human text feedback
                print(f"   Please provide your feedback for AI reviewer (end with an empty line, or leave empty to skip):")
                feedback_lines = []
                try:
                    while True:
                        line = input("   > ")
                        if line.strip() == '':
                            break
                        feedback_lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    print("\n   ⚠️  Input interrupted, accepting current tasks.")
                    break

                human_feedback = '\n'.join(feedback_lines) if feedback_lines else ''

                if not human_feedback:
                    print(f"   ⚠️  No feedback provided, please try again.")
                    continue

                # Log human feedback
                if conv_logger:
                    conv_logger.log_ideas_revision_prompt(
                        1,
                        f"[Human Feedback]\n{human_feedback}",
                    )

                # Send revision prompt to the SAME reviewer
                # NOTE: Do NOT delete the temp file here — the AI may try to
                # read it before writing.  It will be overwritten by the AI
                # and cleaned up after we read the result.
                print(f"   🔄 Sending human feedback to reviewer for revision...")

                revision_prompt = build_revision_prompt(
                    temp_tasks_path=self._get_temp_tasks_path(),
                    human_feedback=human_feedback,
                    next_id=next_id,
                )
                try:
                    if conv_logger:
                        conv_logger.log_ideas_revision_prompt(1, revision_prompt)
                    self._start_temp_file_watcher()
                    revision_result = review_client.ask(revision_prompt)
                    if conv_logger:
                        conv_logger.log_ideas_revision_response(revision_result)

                    new_parsed_data = self._read_tasks_from_temp_file()
                    if new_parsed_data is None:
                        logger.info("Temp file not found after human-feedback revision, falling back to response text parsing")
                        new_parsed_data = self._extract_yaml_tasks(revision_result)
                    self._cleanup_temp_file()

                    if new_parsed_data and new_parsed_data.get('tasks'):
                        parsed_data = new_parsed_data
                        # Run validation on the new tasks
                        valid, errors = self._validate_tasks_schema(parsed_data, next_id=next_id)
                        if not valid:
                            print(f"   ⚠️  AI revision has schema errors:")
                            for e in errors:
                                print(f"      • {e}")
                            print(f"   You can fix these manually in the temp file.")
                    else:
                        print(f"   ❌ AI failed to generate valid tasks from feedback.")

                except AICallError as e:
                    self._stop_temp_file_watcher()
                    logger.error(f"AI call failed during human-feedback revision: {e}")
                    print(f"   ❌ AI call failed: {e}")

            elif choice == 's':
                print(f"   ⏭️  Skipping idea.")
                return {}
            else:
                print(f"   Invalid choice. Please enter y, n, or s.")

        return parsed_data
