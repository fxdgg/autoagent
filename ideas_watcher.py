"""
Ideas Watcher - Monitors ideas.md for new ideas and converts them to TODO tasks.

This module provides:
- IdeasWatcher: Watches ideas.md for new content and uses AI to decompose
  ideas into structured TODO tasks that get appended to todos.yaml
"""

import os
import re
import time
import yaml
import hashlib
import logging
import tempfile
from typing import Optional, List

from codebuddy_client import AIClient, CodeBuddyClient, AICallError
from conversation_logger import ConversationLogger

logger = logging.getLogger(__name__)


class IdeasWatcher:
    """
    Watches an ideas.md file for new ideas and converts them into TODO tasks.
    
    Workflow:
    1. Read ideas.md and detect new (unprocessed) ideas
    2. Call AI to decompose each idea into structured TODO tasks
    3. Append the new tasks to todos.yaml
    4. Remove the processed idea from ideas.md
    5. Archive the processed idea text into .ideas_processed.md
    
    Ideas in ideas.md are separated by horizontal rules (---). Each section
    between separators is treated as one idea.
    """

    # File to archive processed ideas
    PROCESSED_STATE_FILE = ".ideas_processed.md"

    # Temporary file for AI to write generated YAML tasks into
    TEMP_TASKS_FILE = ".ideas_tasks_temp.yaml"

    def __init__(
        self,
        ideas_file: str = "ideas.md",
        todos_file: str = "todos.yaml",
        processed_state_file: str = None,
    ):
        """
        Initialize IdeasWatcher.
        
        Args:
            ideas_file: Path to the ideas markdown file
            todos_file: Path to the todos YAML configuration file
        processed_state_file: Path to track processed ideas (default: .ideas_processed.md)
        """
        self.ideas_file = ideas_file
        self.todos_file = todos_file
        self.processed_state_file = processed_state_file or self.PROCESSED_STATE_FILE
        self._last_mtime = 0.0

    def _archive_idea(self, idea: dict):
        """Archive a processed idea by appending its original text to .ideas_processed.md."""
        try:
            is_new = not os.path.exists(self.processed_state_file)
            with open(self.processed_state_file, 'a', encoding='utf-8') as f:
                if is_new:
                    f.write("# Processed Ideas Archive\n\n")
                f.write(idea['content'])
                f.write("\n\n---\n\n")
            logger.debug(f"Archived idea '{idea['title']}' to {self.processed_state_file}")
        except Exception as e:
            logger.error(f"Failed to archive idea: {e}")

    def _remove_idea_from_file(self, idea: dict):
        """
        Remove a processed idea from ideas.md.

        Re-reads the file, splits by '---', removes the matching section,
        and writes back.
        """
        try:
            with open(self.ideas_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read ideas file for removal: {e}")
            return

        sections = re.split(r'\n---\n', content)
        remaining = []
        removed = False
        for section in sections:
            if not removed and section.strip() == idea['content'].strip():
                removed = True
                continue
            remaining.append(section)

        new_content = '\n---\n'.join(remaining).strip()
        # If there's still content, ensure it ends with a newline
        if new_content:
            new_content += '\n'

        try:
            with open(self.ideas_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            if removed:
                logger.debug(f"Removed idea '{idea['title']}' from {self.ideas_file}")
            else:
                logger.warning(f"Could not find idea '{idea['title']}' in {self.ideas_file} for removal")
        except Exception as e:
            logger.error(f"Failed to write ideas file after removal: {e}")

    def has_new_ideas(self) -> bool:
        """
        Check if ideas.md has been modified since last check.
        
        Returns:
            bool: True if the file exists and has been modified
        """
        if not os.path.exists(self.ideas_file):
            return False
        try:
            mtime = os.path.getmtime(self.ideas_file)
            if mtime > self._last_mtime:
                return True
        except OSError:
            pass
        return False

    def parse_ideas(self) -> List[dict]:
        """
        Parse ideas.md and extract individual ideas.
        
        Ideas are delimited by horizontal rules (``---``). Each section
        between separators is treated as one idea.
        
        Returns:
            List[dict]: List of ideas with 'title', 'content', 'body', and 'hash' fields.
        """
        if not os.path.exists(self.ideas_file):
            return []

        try:
            with open(self.ideas_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read ideas file: {e}")
            return []

        # Update last modified time
        try:
            self._last_mtime = os.path.getmtime(self.ideas_file)
        except OSError:
            pass

        if not content.strip():
            return []

        # Split only by horizontal rules (---)
        sections = re.split(r'\n---\n', content)

        ideas = []
        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Use first line as title, rest as body
            lines = section.split('\n', 1)
            title = lines[0].strip()
            # Strip leading '#' characters from title for display
            display_title = re.sub(r'^#+\s*', '', title)
            body = lines[1].strip() if len(lines) > 1 else ""

            # Compute hash of the idea content for deduplication
            idea_hash = hashlib.sha256(section.encode('utf-8')).hexdigest()[:16]

            ideas.append({
                'title': display_title,
                'content': section,
                'body': body,
                'hash': idea_hash,
            })

        return ideas

    # Maximum number of review rounds before accepting the tasks as-is
    MAX_REVIEW_ROUNDS = 3

    # Maximum number of schema-validation retries before accepting as-is
    MAX_VALIDATION_RETRIES = 2

    def _get_temp_tasks_path(self) -> str:
        """Return the absolute path to the temporary tasks YAML file.

        The file is placed next to the todos.yaml file so that the AI
        tool can write to it in the project working directory.
        """
        return os.path.join(
            os.path.dirname(os.path.abspath(self.todos_file)) or os.getcwd(),
            self.TEMP_TASKS_FILE,
        )

    def _read_tasks_from_temp_file(self) -> Optional[List[dict]]:
        """Try to read and parse tasks from the temporary YAML file.

        Returns:
            List[dict] if the file exists and contains a valid YAML list,
            None otherwise.  The temp file is deleted after a successful read.
        """
        temp_path = self._get_temp_tasks_path()
        if not os.path.exists(temp_path):
            return None
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if not content.strip():
                return None
            parsed = yaml.safe_load(content)
            if isinstance(parsed, list) and len(parsed) > 0:
                logger.info(f"Successfully read {len(parsed)} task(s) from temp file {temp_path}")
                return parsed
        except Exception as e:
            logger.warning(f"Failed to read/parse temp tasks file {temp_path}: {e}")
        return None

    def _cleanup_temp_file(self):
        """Remove the temporary tasks file if it exists."""
        temp_path = self._get_temp_tasks_path()
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError as e:
            logger.warning(f"Failed to remove temp file {temp_path}: {e}")

    @staticmethod
    def _validate_task_schema(task: dict, is_subtask: bool = False) -> List[str]:
        """Validate a single task's schema and return a list of error messages.

        This mirrors the validation logic in ``Orchestrator._validate_task`` so
        that schema problems are caught *before* tasks are written to todos.yaml.
        """
        errors: List[str] = []
        task_id = task.get('id', '?')

        # Required fields
        required_fields = ['id', 'name', 'type', 'completion_criteria']
        for field in required_fields:
            if field not in task:
                errors.append(f"Task {task_id} missing required field: '{field}'")

        task_type = task.get('type')
        if task_type is None:
            return errors  # cannot validate further without type

        # Validate task type
        if is_subtask:
            valid_types = ['simple', 'long_running']
        else:
            valid_types = ['simple', 'nested', 'looping']
        if task_type not in valid_types:
            errors.append(
                f"Task {task_id} has invalid type: '{task_type}'. "
                f"Valid types for {'subtask' if is_subtask else 'top-level'}: {valid_types}"
            )

        # Validate nested tasks
        if task_type == 'nested':
            subtasks = task.get('subtasks', [])
            if not subtasks:
                errors.append(f"Nested task {task_id} must have 'subtasks'")
            else:
                for st in subtasks:
                    errors.extend(IdeasWatcher._validate_task_schema(st, is_subtask=True))

        # Validate looping tasks
        if task_type == 'looping':
            subtasks = task.get('subtasks', [])
            if not subtasks:
                errors.append(f"Looping task {task_id} must have 'subtasks'")
            else:
                for st in subtasks:
                    errors.extend(IdeasWatcher._validate_task_schema(st, is_subtask=True))
            repeat_count = task.get('repeat_count')
            if repeat_count is None:
                errors.append(f"Looping task {task_id} must have 'repeat_count' field")
            elif not isinstance(repeat_count, int) or repeat_count < 1:
                errors.append(f"Looping task {task_id}: 'repeat_count' must be a positive integer")

        return errors

    @staticmethod
    def _validate_tasks_schema(tasks: List[dict]) -> tuple:
        """Validate the schema of a list of tasks.

        Returns:
            (valid: bool, errors: List[str])
        """
        all_errors: List[str] = []
        for task in tasks:
            all_errors.extend(IdeasWatcher._validate_task_schema(task, is_subtask=False))
        return (len(all_errors) == 0, all_errors)

    def process_new_ideas(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient = None,
        conv_logger: ConversationLogger = None,
        human_review: bool = False,
    ) -> int:
        """
        Process all new ideas: parse, convert to TODOs via AI, and append to todos.yaml.
        
        Args:
            client: CodeBuddyClient instance to call AI for task decomposition
            review_client: Optional CodeBuddyClient with fresh context for reviewing
                           generated tasks. If None, review step is skipped.
            conv_logger: Optional ConversationLogger to record prompts/responses
            human_review: If True, after AI review passes, pause for human approval.
                          Human can accept (y) or reject with feedback (n) which
                          triggers another AI revision cycle.
            
        Returns:
            int: Number of new ideas processed
        """
        ideas = self.parse_ideas()
        if not ideas:
            return 0

        logger.info(f"Found {len(ideas)} new idea(s) to process")
        processed_count = 0

        for idea in ideas:
            print(f"\n   💡 Processing idea: {idea['title']}")
            try:
                new_tasks = self._decompose_idea_to_tasks(
                    client, idea,
                    review_client=review_client,
                    conv_logger=conv_logger,
                    idea_index=processed_count + 1,
                    human_review=human_review,
                )
                if new_tasks:
                    self._append_tasks_to_todos(new_tasks)
                    print(f"   ✅ Added {len(new_tasks)} task(s) from idea: {idea['title']}")
                else:
                    print(f"   ⚠️  No tasks generated from idea: {idea['title']}")

                # Archive the idea and remove it from ideas.md
                self._archive_idea(idea)
                self._remove_idea_from_file(idea)
                processed_count += 1

            except Exception as e:
                logger.error(f"Failed to process idea '{idea['title']}': {e}")
                print(f"   ❌ Failed to process idea: {idea['title']} - {e}")

        return processed_count

    def _decompose_idea_to_tasks(
        self,
        client: CodeBuddyClient,
        idea: dict,
        review_client: CodeBuddyClient = None,
        conv_logger: ConversationLogger = None,
        idea_index: int = 1,
        human_review: bool = False,
    ) -> List[dict]:
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
            client: CodeBuddyClient instance
            idea: Idea dict with 'title', 'content', 'body' fields
            review_client: Optional CodeBuddyClient with fresh context for review
            conv_logger: Optional ConversationLogger to record prompts/responses
            idea_index: 1-based index of the idea (for logging)
            human_review: If True, pause for human approval after AI review passes
            
        Returns:
            List[dict]: List of task configurations compatible with todos.yaml format
        """
        # Load existing tasks to determine the next available task ID
        existing_tasks = self._load_existing_tasks()
        max_id = 0
        for task in existing_tasks:
            tid = task.get('id', 0)
            if isinstance(tid, (int, float)):
                max_id = max(max_id, int(tid))
        next_id = max_id + 1

        # Resolve paths for the prompt
        temp_tasks_path = self._get_temp_tasks_path()
        # Clean up any leftover temp file from a previous run
        self._cleanup_temp_file()

        prompt = f"""You are a task planner. Your job is to decompose a given idea into concrete, actionable
TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

## Idea

{idea['content']}

## Task Types

There are 4 task types. Choose the most appropriate one for each task:

1. **simple** — A single-step task the AI agent completes autonomously (code changes, running
   commands, analysis, etc.). Can be a top-level task or a subtask.
2. **nested** — A multi-step task containing ordered subtasks. After all subtasks finish, the
   AI evaluates whether the overall completion criteria are met. Top-level only.
3. **looping** — An iterative task that repeats all its subtasks for a fixed number of cycles
   (e.g., profile → optimize → benchmark → commit). No completion evaluation between cycles.
   Top-level only.
4. **long_running** — A task that runs in the background via nohup to avoid timeouts (e.g.,
   model training, large data processing). Subtask only (inside nested or looping).

**Hierarchy rules:**
- Top-level tasks can be: simple, nested, or looping.
- Subtasks (inside nested/looping) can only be: simple or long_running.

**When to use which:**
- If the idea can be done in one step → use a single **simple** task.
- If the idea requires multiple ordered steps and the AI should evaluate overall success
  after all steps → use **nested**.
- If the idea involves repeating an optimize-test cycle N times → use **looping** with
  repeat_count.
- If a subtask runs a long-running process (training, heavy computation) → use **long_running**.

## Task Schema

Common fields (all types):
- id: integer for top-level tasks (starting from {next_id}), dot notation for subtasks (e.g., {next_id}.1)
- name: string — concise task name
- type: "simple" | "nested" | "looping" | "long_running"
- completion_criteria: string — clear, specific, and measurable

Type-specific fields:
- simple: initial_hint (optional — helpful context for the AI executor)
- nested: subtasks (list), max_attempts (optional, default 20)
- looping: subtasks (list), repeat_count (required, positive integer), max_attempts_per_loop (optional, default 20)
- long_running: (no extra required fields)

## Constraints

1. Do NOT over-decompose. If the idea is simple, a single "simple" task is perfectly fine.
   Prefer fewer, well-scoped tasks over many trivial ones.
2. Do NOT write vague completion_criteria. Each criterion must be objectively verifiable.
   ✅ Good: "All unit tests pass with 0 failures"
   ✅ Good: "Response time < 200ms on the /api/users endpoint"
   ❌ Bad: "Code is optimized"
   ❌ Bad: "Performance is improved"
3. Do NOT use "long_running" or "simple" as a top-level task type when the idea clearly
   requires multiple coordinated steps — use "nested" or "looping" instead.
4. Do NOT use "nested" or "looping" as subtask types.

## Output Format

Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
The file content must be a YAML list of task objects. Below are examples covering all task types:

### simple (top-level)

- id: {next_id}
  name: "Refactor logging module"
  type: simple
  completion_criteria: |
    1. All log calls use the new structured format.
    2. No references to the old logging helper remain.
  initial_hint: |
    The old helper is in utils/legacy_logger.py.

### nested (with simple and long_running subtasks)

- id: {next_id}
  name: "Add user authentication"
  type: nested
  max_attempts: 10
  completion_criteria: |
    1. Login and registration endpoints return correct status codes.
    2. All auth-related unit tests pass.
  subtasks:
    - id: {next_id}.1
      name: "Implement auth endpoints"
      type: simple
      completion_criteria: |
        POST /login and POST /register are functional.
    - id: {next_id}.2
      name: "Train fraud-detection model"
      type: long_running
      completion_criteria: |
        Model checkpoint saved to checkpoints/ with accuracy > 0.95.

### looping

- id: {next_id}
  name: "Iterative kernel optimization"
  type: looping
  repeat_count: 5
  max_attempts_per_loop: 10
  completion_criteria: |
    Kernel execution time reduced by at least 30%.
  subtasks:
    - id: {next_id}.1
      name: "Profile and optimize"
      type: simple
      completion_criteria: |
        At least one optimization applied and benchmarked.
    - id: {next_id}.2
      name: "Run full benchmark suite"
      type: long_running
      completion_criteria: |
        Benchmark results saved to results/bench_latest.json.
"""

        try:
            # Log prompt before AI call (crash-safe)
            if conv_logger:
                conv_logger.log_ideas_prompt(idea['title'], idea_index, prompt)

            result = client.ask(prompt, continue_session=True)

            # Log response after AI call
            if conv_logger:
                conv_logger.log_ideas_response(result)

            # Parse the YAML: prefer temp file, fall back to response text
            tasks = self._read_tasks_from_temp_file()
            if tasks is None:
                logger.info("Temp file not found or empty, falling back to response text parsing")
                tasks = self._extract_yaml_tasks(result)
            self._cleanup_temp_file()

            # Review + validation loop
            if tasks:
                tasks, result = self._review_and_validate_loop(
                    client, review_client, idea, tasks, result,
                    conv_logger=conv_logger,
                )

            # Human review loop: after AI review + validation passes, pause for human approval
            if human_review and tasks:
                tasks = self._human_review_loop(
                    client, review_client, idea, tasks, result,
                    conv_logger=conv_logger,
                )

            # Write section end separator
            if conv_logger:
                conv_logger.log_ideas_section_end()

            return tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea decomposition: {e}")
            raise

    def _review_and_validate_loop(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
    ) -> tuple:
        """Run the AI review loop followed by schema validation.

        After the AI reviewer approves (or is skipped), the tasks are
        validated against the schema.  If validation fails, the errors
        are fed back into the review loop as feedback so the AI can fix
        them.  This repeats up to ``MAX_VALIDATION_RETRIES`` times.

        Args:
            client: Original CodeBuddyClient (with existing context)
            review_client: Optional CodeBuddyClient for AI review
            idea: Original idea dict
            tasks: Current parsed task list
            raw_yaml_response: Raw response from the last AI call
            conv_logger: Optional ConversationLogger

        Returns:
            (tasks, raw_yaml_response) — the final validated task list and
            the last raw AI response.
        """
        result = raw_yaml_response

        for validation_attempt in range(1, self.MAX_VALIDATION_RETRIES + 2):
            # --- AI review loop ---
            if review_client and tasks:
                last_feedback = ""
                for review_round in range(1, self.MAX_REVIEW_ROUNDS + 1):
                    review_passed, review_feedback, revised_tasks = self._review_tasks(
                        review_client, idea, tasks, result,
                        conv_logger=conv_logger,
                        review_round=review_round,
                        last_feedback=last_feedback,
                    )
                    if review_passed:
                        print(f"   ✅ Review passed (round {review_round})")
                        break
                    else:
                        last_feedback = review_feedback
                        if revised_tasks:
                            print(f"   🔧 Reviewer directly revised tasks (round {review_round})")
                            tasks = revised_tasks
                        else:
                            print(f"   🔄 Review rejected (round {review_round}), requesting revision...")
                            result, tasks = self._revise_tasks(
                                client, idea, review_feedback,
                                conv_logger=conv_logger,
                                revision_round=review_round,
                            )
                            if not tasks:
                                logger.warning(f"Revision round {review_round} produced no tasks")
                                break
                else:
                    print(
                        f"   ⚠️  Max review rounds ({self.MAX_REVIEW_ROUNDS}) reached, "
                        f"accepting current tasks"
                    )

            # --- Schema validation ("compile") ---
            if not tasks:
                break

            valid, errors = self._validate_tasks_schema(tasks)
            if valid:
                print(f"   ✅ Schema validation passed")
                break
            else:
                error_text = '\n'.join(f"  - {e}" for e in errors)
                print(f"   ❌ Schema validation failed (attempt {validation_attempt}/{self.MAX_VALIDATION_RETRIES + 1}):")
                for e in errors:
                    print(f"      • {e}")

                if validation_attempt > self.MAX_VALIDATION_RETRIES:
                    print(f"   ⚠️  Max validation retries ({self.MAX_VALIDATION_RETRIES}) exceeded, accepting current tasks")
                    break

                # Feed validation errors back as review feedback
                validation_feedback = (
                    f"Schema validation failed with the following errors:\n"
                    f"{error_text}\n\n"
                    f"Please fix these issues. Every task must conform to the schema."
                )
                print(f"   🔄 Sending validation errors to AI for revision...")
                result, tasks = self._revise_tasks(
                    client, idea, validation_feedback,
                    conv_logger=conv_logger,
                    revision_round=validation_attempt,
                )
                if not tasks:
                    logger.warning(f"Validation-retry revision produced no tasks")
                    break
                # Loop back to AI review + validation

        return tasks, result

    def _review_tasks(
        self,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
        review_round: int = 1,
        last_feedback: str = "",
    ) -> tuple:
        """
        Send generated tasks to a fresh-context reviewer AI for quality check.
        
        If the reviewer rejects the tasks, it is instructed to directly modify
        the temp YAML file with corrections. The caller can then read the
        revised tasks from the temp file, potentially skipping a separate
        revision round.
        
        Args:
            review_client: CodeBuddyClient with fresh context
            idea: Original idea dict
            tasks: Parsed task list
            raw_yaml_response: Raw YAML response from the decomposition AI
            conv_logger: Optional ConversationLogger
            review_round: 1-based review round number
            last_feedback: Feedback from the previous review round (if any)
            
        Returns:
            tuple: (passed: bool, feedback: str, revised_tasks: Optional[List[dict]])
                   passed=True if review approves, feedback contains reviewer comments,
                   revised_tasks contains reviewer's corrected tasks if it rejected and
                   directly modified the file (None otherwise).
        """
        tasks_yaml = yaml.dump(tasks, default_flow_style=False, allow_unicode=True, sort_keys=False)

        temp_tasks_path = self._get_temp_tasks_path()
        # Write current tasks to temp file so reviewer can modify it in-place
        self._cleanup_temp_file()
        try:
            with open(temp_tasks_path, 'w', encoding='utf-8') as f:
                f.write(tasks_yaml)
        except OSError as e:
            logger.warning(f"Failed to write temp file for reviewer: {e}")

        last_feedback_section = ""
        if last_feedback:
            last_feedback_section = f"""## Last Feedback

The following feedback was provided in the previous review round. Check whether
the issues have been addressed:

{last_feedback}

"""

        review_prompt = f"""You are a task review expert. Review the following TODO task decomposition
for quality, completeness, and correctness.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs.

## Original Idea

{idea['content']}

## Generated Tasks (YAML)

```yaml
{tasks_yaml}```

{last_feedback_section}## Task Types

There are 4 task types:

1. **simple** — A single-step task. Can be top-level or subtask.
2. **nested** — A multi-step task with ordered subtasks. Top-level only.
3. **looping** — An iterative task repeating subtasks for N cycles. Top-level only.
4. **long_running** — A background task via nohup. Subtask only.

**Hierarchy rules:**
- Top-level: simple, nested, or looping.
- Subtasks (inside nested/looping): simple or long_running only.

## Task Schema

Common fields (all types): id, name, type, completion_criteria

Type-specific fields:
- simple: initial_hint (optional)
- nested: subtasks (list), max_attempts (optional, default 20)
- looping: subtasks (list), repeat_count (required), max_attempts_per_loop (optional, default 20)
- long_running: (no extra required fields)

## Review Criteria

1. **Schema correctness**: Does every task have the required fields for its type?
   (e.g., nested/looping must have subtasks; looping must have repeat_count)
2. **ID consistency**: Are task IDs sequential integers and subtask IDs use correct
   dot notation (e.g., 2.1, 2.2)?
3. **Type appropriateness**: Are task types chosen correctly?
   - Multi-step ideas should use nested/looping, not a single simple task.
   - Iterative optimize-test cycles should use looping, not nested.
   - long_running is only used as a subtask, never top-level.
   - nested/looping are never used as subtask types.
4. **Completion criteria quality**: Is every completion_criteria specific, measurable,
   and objectively verifiable by an AI agent?
   ✅ Good: "All unit tests pass with 0 failures"
   ❌ Bad: "Code is optimized" or "Performance is improved"
5. **Decomposition granularity**: Does the decomposition fully cover the idea without
   over-decomposing into trivial subtasks or leaving gaps?
6. **YAML validity**: Is the YAML structure well-formed and parseable?

## Instructions

If the tasks pass ALL criteria, respond with EXACTLY:
✅ completed

If the tasks need improvement:
1. Respond with: ❌ not completed
2. Briefly explain what needs to be fixed.
3. Then DIRECTLY modify the YAML file at:
     {temp_tasks_path}
   Write the corrected full task list into that file.
   Do NOT include markdown code fences or any extra text in the file.
"""

        try:
            if conv_logger:
                conv_logger.log_ideas_review_prompt(review_round, review_prompt)

            review_result = review_client.ask(review_prompt, continue_session=False)

            if conv_logger:
                conv_logger.log_ideas_review_response(review_result)

            passed = self._check_review_passed(review_result)

            revised_tasks = None
            if not passed:
                # Try to read reviewer's corrected tasks from temp file
                revised_tasks = self._read_tasks_from_temp_file()
                if revised_tasks:
                    logger.info(f"Reviewer directly revised {len(revised_tasks)} task(s) in temp file")
            self._cleanup_temp_file()

            return passed, review_result, revised_tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea review: {e}")
            self._cleanup_temp_file()
            # On review failure, accept the tasks to avoid blocking
            return True, "", None

    def _revise_tasks(
        self,
        client: CodeBuddyClient,
        idea: dict,
        review_feedback: str,
        conv_logger: ConversationLogger = None,
        revision_round: int = 1,
    ) -> tuple:
        """
        Send review feedback back to the original AI for task revision.
        
        Args:
            client: Original CodeBuddyClient (with existing context)
            idea: Original idea dict
            review_feedback: Feedback from the reviewer AI
            conv_logger: Optional ConversationLogger
            revision_round: 1-based revision round number
            
        Returns:
            tuple: (raw_response: str, tasks: List[dict])
        """
        temp_tasks_path = self._get_temp_tasks_path()
        self._cleanup_temp_file()

        revision_prompt = f"""Your previous task decomposition was reviewed and needs revision.

## Reviewer Feedback

{review_feedback}

## Instructions

Please revise the task decomposition based on the feedback above.
Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
"""

        try:
            if conv_logger:
                conv_logger.log_ideas_revision_prompt(revision_round, revision_prompt)

            result = client.ask(revision_prompt, continue_session=True)

            if conv_logger:
                conv_logger.log_ideas_revision_response(result)

            tasks = self._read_tasks_from_temp_file()
            if tasks is None:
                logger.info("Temp file not found or empty after revision, falling back to response text parsing")
                tasks = self._extract_yaml_tasks(result)
            self._cleanup_temp_file()
            return result, tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea revision: {e}")
            raise

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
        import re as _re
        if _re.search(r'✅.*completed', lower):
            if not _re.search(r'not\s+completed|fail|reject', lower):
                return True

        # Default: not passed
        return False

    def _human_review_loop(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
    ) -> List[dict]:
        """
        Pause for human review after AI review passes.
        
        Displays the generated tasks and waits for human input:
        - 'y': Accept the tasks and continue
        - 'n': Human provides feedback, AI revises, AI re-reviews, then
               pauses for human review again
        
        Args:
            client: Original CodeBuddyClient (with existing context)
            review_client: CodeBuddyClient for AI review (fresh context)
            idea: Original idea dict
            tasks: Current parsed task list
            raw_yaml_response: Raw YAML response from the last AI call
            conv_logger: Optional ConversationLogger
            
        Returns:
            List[dict]: Final approved task list
        """
        revision_counter = 0
        result = raw_yaml_response

        while True:
            # Display current tasks for human review
            tasks_yaml = yaml.dump(
                tasks, default_flow_style=False,
                allow_unicode=True, sort_keys=False,
            )
            print(f"\n{'─' * 60}")
            print(f"   👤 Human Review Required")
            print(f"{'─' * 60}")
            print(f"   Idea: {idea['title']}")
            print(f"\n   Generated Tasks:")
            print(f"{'─' * 40}")
            for line in tasks_yaml.split('\n'):
                print(f"   {line}")
            print(f"{'─' * 40}")

            # Wait for human input
            try:
                choice = input("\n   Accept these tasks? (y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n   ⚠️  Input interrupted, accepting current tasks.")
                break

            if choice == 'y':
                print(f"   ✅ Human approved the tasks.")
                break
            elif choice == 'n':
                # Get human feedback
                print(f"   Please provide your feedback (end with an empty line):")
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

                if not feedback_lines:
                    print(f"   ⚠️  No feedback provided, please try again.")
                    continue

                human_feedback = '\n'.join(feedback_lines)
                revision_counter += 1

                # Log human feedback
                if conv_logger:
                    conv_logger.log_ideas_revision_prompt(
                        revision_counter,
                        f"[Human Feedback]\n{human_feedback}",
                    )

                print(f"   🔄 Sending human feedback to AI for revision...")

                # Send human feedback to AI for revision
                temp_tasks_path = self._get_temp_tasks_path()
                self._cleanup_temp_file()

                revision_prompt = f"""Your task decomposition needs revision based on human feedback.

## Human Feedback

{human_feedback}

## Instructions

Please revise the task decomposition based on the feedback above.
Write ONLY valid YAML (a list of tasks) into the following file:
  {temp_tasks_path}

Do NOT include markdown code fences or any extra text in the file.
"""
                try:
                    result = client.ask(revision_prompt, continue_session=True)

                    if conv_logger:
                        conv_logger.log_ideas_revision_response(result)

                    tasks = self._read_tasks_from_temp_file()
                    if tasks is None:
                        logger.info("Temp file not found after human-feedback revision, falling back to response text parsing")
                        tasks = self._extract_yaml_tasks(result)
                    self._cleanup_temp_file()
                    if not tasks:
                        print(f"   ⚠️  AI revision produced no valid tasks, keeping previous version.")
                        continue

                    # Re-run AI review + schema validation on the revised tasks
                    if tasks:
                        tasks, result = self._review_and_validate_loop(
                            client, review_client, idea, tasks, result,
                            conv_logger=conv_logger,
                        )

                    # Loop back to human review with updated tasks

                except AICallError as e:
                    logger.error(f"AI call failed during human-feedback revision: {e}")
                    print(f"   ❌ AI revision failed: {e}")
                    print(f"   Keeping previous version.")
            else:
                print(f"   ⚠️  Invalid input. Please enter 'y' or 'n'.")

        return tasks

    def _extract_yaml_tasks(self, response: str) -> List[dict]:
        """
        Extract YAML task definitions from AI response.
        
        Args:
            response: Raw AI response text
            
        Returns:
            List[dict]: Parsed task list
        """
        # Strategy 1: Try parsing the entire response as YAML
        try:
            parsed = yaml.safe_load(response)
            if isinstance(parsed, list):
                return parsed
        except yaml.YAMLError:
            pass

        # Strategy 2: Extract YAML from code block
        yaml_patterns = [
            r'```ya?ml\s*\n(.*?)\n\s*```',
            r'```\s*\n(.*?)\n\s*```',
        ]
        for pattern in yaml_patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                try:
                    parsed = yaml.safe_load(match.group(1))
                    if isinstance(parsed, list):
                        return parsed
                except yaml.YAMLError:
                    continue

        # Strategy 3: Find lines that look like YAML list items
        lines = response.split('\n')
        yaml_lines = []
        in_yaml = False
        for line in lines:
            if re.match(r'^- id:', line):
                in_yaml = True
            if in_yaml:
                yaml_lines.append(line)
                # Stop at empty line after content or at non-YAML content
                if line.strip() == '' and yaml_lines and yaml_lines[-2].strip() == '':
                    break

        if yaml_lines:
            try:
                parsed = yaml.safe_load('\n'.join(yaml_lines))
                if isinstance(parsed, list):
                    return parsed
            except yaml.YAMLError:
                pass

        logger.warning(f"Failed to extract YAML tasks from AI response: {response[:500]}")
        return []

    def _load_existing_tasks(self) -> list:
        """Load existing tasks from todos.yaml."""
        if not os.path.exists(self.todos_file):
            return []
        try:
            with open(self.todos_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            if config and isinstance(config, dict):
                return config.get('tasks', [])
        except Exception as e:
            logger.error(f"Failed to load todos file: {e}")
        return []

    def _append_tasks_to_todos(self, new_tasks: List[dict]):
        """
        Append new tasks to todos.yaml.
        
        If the file doesn't exist, creates it with proper structure.
        If it exists, reads existing tasks and appends new ones.
        
        Args:
            new_tasks: List of task configurations to append
        """
        if not new_tasks:
            return

        # Load existing config or create new one
        config = {'tasks': []}
        if os.path.exists(self.todos_file):
            try:
                with open(self.todos_file, 'r', encoding='utf-8') as f:
                    existing = yaml.safe_load(f)
                if existing and isinstance(existing, dict):
                    config = existing
                    if 'tasks' not in config:
                        config['tasks'] = []
            except Exception as e:
                logger.error(f"Failed to read existing todos: {e}")
                # Don't overwrite - just append after current content
                raise

        # Append new tasks
        config['tasks'].extend(new_tasks)

        # Write back
        try:
            with open(self.todos_file, 'w', encoding='utf-8') as f:
                yaml.dump(
                    config, f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )
            logger.info(f"Appended {len(new_tasks)} new task(s) to {self.todos_file}")
        except Exception as e:
            logger.error(f"Failed to write todos file: {e}")
            raise

    def mark_all_processed(self):
        """Mark all current ideas as processed without generating tasks."""
        ideas = self.parse_ideas()
        for idea in ideas:
            self._archive_idea(idea)
        # Clear the ideas file
        try:
            with open(self.ideas_file, 'w', encoding='utf-8') as f:
                f.write('')
        except Exception as e:
            logger.error(f"Failed to clear ideas file: {e}")

    def reset(self):
        """Reset all processed state (remove the archive file)."""
        self._last_mtime = 0.0
        if os.path.exists(self.processed_state_file):
            os.remove(self.processed_state_file)
        logger.info("Ideas processed state reset")
