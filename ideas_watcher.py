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
            processed_state_file: Path to track processed ideas (default: .ideas_processed.yaml)
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

    def process_new_ideas(
        self,
        client: CodeBuddyClient,
        review_client: CodeBuddyClient = None,
        conv_logger: ConversationLogger = None,
    ) -> int:
        """
        Process all new ideas: parse, convert to TODOs via AI, and append to todos.yaml.
        
        Args:
            client: CodeBuddyClient instance to call AI for task decomposition
            review_client: Optional CodeBuddyClient with fresh context for reviewing
                           generated tasks. If None, review step is skipped.
            conv_logger: Optional ConversationLogger to record prompts/responses
            
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
    ) -> List[dict]:
        """
        Call AI to decompose an idea into structured TODO tasks.
        
        If a review_client is provided, the generated tasks are sent to a
        fresh-context AI for review. If the review rejects the tasks, the
        feedback is sent back to the original AI for revision. This loop
        repeats up to MAX_REVIEW_ROUNDS times.
        
        Args:
            client: CodeBuddyClient instance
            idea: Idea dict with 'title', 'content', 'body' fields
            review_client: Optional CodeBuddyClient with fresh context for review
            conv_logger: Optional ConversationLogger to record prompts/responses
            idea_index: 1-based index of the idea (for logging)
            
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

        prompt = f"""You are a task planner. Given the following idea, decompose it into one or more
concrete, actionable TODO tasks in YAML format.

## Idea Title
{idea['title']}

## Idea Content
{idea['content']}

## Instructions

1. Each task should have: id, name, type, completion_criteria
2. Task IDs should start from {next_id}
3. Task types can be: "simple" (for standalone tasks) or "nested" (for complex tasks with subtasks)
4. For nested tasks, include a "subtasks" list where each subtask has: id, name, type, completion_criteria
5. Subtask IDs should use dot notation (e.g., {next_id}.1, {next_id}.2)
6. Subtask types can only be: "simple" or "long_running"
7. For long_running subtasks, include a "command" field
8. Write clear, measurable completion_criteria
9. Include "initial_hint" for tasks where helpful context can guide the AI executor

## Output Format

Respond with ONLY valid YAML (no markdown code fences, no extra text).
The output should be a list of tasks, for example:

- id: {next_id}
  name: "Task name"
  type: simple
  completion_criteria: |
    1. First criterion
    2. Second criterion
  initial_hint: |
    Helpful context for the AI executor.

Or for a nested task:

- id: {next_id}
  name: "Complex task name"
  type: nested
  max_attempts: 10
  completion_criteria: |
    Overall completion criteria.
  subtasks:
    - id: {next_id}.1
      name: "First subtask"
      type: simple
      completion_criteria: |
        Subtask criteria.
"""

        try:
            # Log prompt before AI call (crash-safe)
            if conv_logger:
                conv_logger.log_ideas_prompt(idea['title'], idea_index, prompt)

            result = client.ask(prompt, continue_session=True)

            # Log response after AI call
            if conv_logger:
                conv_logger.log_ideas_response(result)

            # Parse the YAML from the AI response
            tasks = self._extract_yaml_tasks(result)

            # Review loop: send tasks to a fresh-context reviewer AI
            if review_client and tasks:
                for review_round in range(1, self.MAX_REVIEW_ROUNDS + 1):
                    review_passed, review_feedback = self._review_tasks(
                        review_client, idea, tasks, result,
                        conv_logger=conv_logger,
                        review_round=review_round,
                    )
                    if review_passed:
                        print(f"   ✅ Review passed (round {review_round})")
                        break
                    else:
                        print(f"   🔄 Review rejected (round {review_round}), requesting revision...")
                        # Send feedback back to original AI for revision
                        result, tasks = self._revise_tasks(
                            client, idea, review_feedback,
                            conv_logger=conv_logger,
                            revision_round=review_round,
                        )
                        if not tasks:
                            logger.warning(
                                f"Revision round {review_round} produced no tasks"
                            )
                            break
                else:
                    # Exhausted all review rounds — accept last version
                    print(
                        f"   ⚠️  Max review rounds ({self.MAX_REVIEW_ROUNDS}) reached, "
                        f"accepting current tasks"
                    )

            # Write section end separator
            if conv_logger:
                conv_logger.log_ideas_section_end()

            return tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea decomposition: {e}")
            raise

    def _review_tasks(
        self,
        review_client: CodeBuddyClient,
        idea: dict,
        tasks: List[dict],
        raw_yaml_response: str,
        conv_logger: ConversationLogger = None,
        review_round: int = 1,
    ) -> tuple:
        """
        Send generated tasks to a fresh-context reviewer AI for quality check.
        
        Args:
            review_client: CodeBuddyClient with fresh context
            idea: Original idea dict
            tasks: Parsed task list
            raw_yaml_response: Raw YAML response from the decomposition AI
            conv_logger: Optional ConversationLogger
            review_round: 1-based review round number
            
        Returns:
            tuple: (passed: bool, feedback: str)
                   passed=True if review approves, feedback contains reviewer comments
        """
        tasks_yaml = yaml.dump(tasks, default_flow_style=False, allow_unicode=True, sort_keys=False)

        review_prompt = f"""You are a task review expert. Review the following TODO task decomposition
for quality, completeness, and correctness.

## Original Idea

### Title
{idea['title']}

### Content
{idea['content']}

## Generated Tasks (YAML)

```yaml
{tasks_yaml}```

## Review Criteria

1. Are the task IDs correct and consistent (including subtask dot notation)?
2. Are the task types appropriate (simple vs nested, simple vs long_running for subtasks)?
3. Are the completion_criteria clear, specific, and measurable?
4. Does the decomposition fully cover the original idea?
5. Are there any missing or redundant tasks?
6. Is the YAML structure valid and well-formed?

## Instructions

If the tasks pass all criteria, respond with EXACTLY:
✅ completed

If the tasks need improvement, respond with:
❌ not completed

Followed by specific feedback on what needs to be fixed.
"""

        try:
            if conv_logger:
                conv_logger.log_ideas_review_prompt(review_round, review_prompt)

            review_result = review_client.ask(review_prompt, continue_session=False)

            if conv_logger:
                conv_logger.log_ideas_review_response(review_result)

            passed = self._check_review_passed(review_result)
            return passed, review_result

        except AICallError as e:
            logger.error(f"AI call failed for idea review: {e}")
            # On review failure, accept the tasks to avoid blocking
            return True, ""

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
        revision_prompt = f"""Your previous task decomposition was reviewed and needs revision.

## Reviewer Feedback

{review_feedback}

## Instructions

Please revise the task decomposition based on the feedback above.
Respond with ONLY valid YAML (no markdown code fences, no extra text).
"""

        try:
            if conv_logger:
                conv_logger.log_ideas_revision_prompt(revision_round, revision_prompt)

            result = client.ask(revision_prompt, continue_session=True)

            if conv_logger:
                conv_logger.log_ideas_revision_response(result)

            tasks = self._extract_yaml_tasks(result)
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
