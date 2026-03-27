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
    4. Mark processed ideas so they are not re-processed
    
    Ideas in ideas.md are separated by markdown headings (## or ###) or
    horizontal rules (---). Each section is treated as one idea.
    """

    # File to track which ideas have been processed
    PROCESSED_STATE_FILE = ".ideas_processed.yaml"

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
        self._processed_hashes = self._load_processed_state()
        self._last_mtime = 0.0

    def _load_processed_state(self) -> set:
        """Load the set of already-processed idea hashes."""
        if not os.path.exists(self.processed_state_file):
            return set()
        try:
            with open(self.processed_state_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if data and isinstance(data, dict):
                return set(data.get('processed_hashes', []))
        except Exception as e:
            logger.warning(f"Failed to load processed state: {e}")
        return set()

    def _save_processed_state(self):
        """Save the set of processed idea hashes."""
        try:
            data = {'processed_hashes': sorted(self._processed_hashes)}
            with open(self.processed_state_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
        except Exception as e:
            logger.error(f"Failed to save processed state: {e}")

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
        
        Each idea is delimited by:
        - Markdown headings (## or ###)
        - Horizontal rules (---)
        - Or treated as a single block if no delimiters found
        
        Returns:
            List[dict]: List of ideas with 'title', 'content', and 'hash' fields.
                        Only includes ideas not yet processed.
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

        # Split by headings or horizontal rules
        # Pattern matches: ## heading, ### heading, or --- (horizontal rule)
        sections = re.split(r'\n(?=#{2,3}\s)|(?<=\n)---+\n', content)

        ideas = []
        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Extract title from heading if present
            heading_match = re.match(r'^(#{2,3})\s+(.+?)(?:\n|$)', section)
            if heading_match:
                title = heading_match.group(2).strip()
                body = section[heading_match.end():].strip()
            else:
                # Use first line as title, rest as body
                lines = section.split('\n', 1)
                title = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ""

            # Compute hash of the idea content for deduplication
            idea_hash = hashlib.sha256(section.encode('utf-8')).hexdigest()[:16]

            if idea_hash not in self._processed_hashes:
                ideas.append({
                    'title': title,
                    'content': section,
                    'body': body,
                    'hash': idea_hash,
                })

        return ideas

    def process_new_ideas(
        self,
        client: CodeBuddyClient,
        conv_logger: ConversationLogger = None,
    ) -> int:
        """
        Process all new ideas: parse, convert to TODOs via AI, and append to todos.yaml.
        
        Args:
            client: CodeBuddyClient instance to call AI for task decomposition
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
                    conv_logger=conv_logger,
                    idea_index=processed_count + 1,
                )
                if new_tasks:
                    self._append_tasks_to_todos(new_tasks)
                    print(f"   ✅ Added {len(new_tasks)} task(s) from idea: {idea['title']}")
                else:
                    print(f"   ⚠️  No tasks generated from idea: {idea['title']}")

                # Mark as processed regardless of whether tasks were generated
                self._processed_hashes.add(idea['hash'])
                self._save_processed_state()
                processed_count += 1

            except Exception as e:
                logger.error(f"Failed to process idea '{idea['title']}': {e}")
                print(f"   ❌ Failed to process idea: {idea['title']} - {e}")

        return processed_count

    def _decompose_idea_to_tasks(
        self,
        client: CodeBuddyClient,
        idea: dict,
        conv_logger: ConversationLogger = None,
        idea_index: int = 1,
    ) -> List[dict]:
        """
        Call AI to decompose an idea into structured TODO tasks.
        
        Args:
            client: CodeBuddyClient instance
            idea: Idea dict with 'title', 'content', 'body' fields
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
            return tasks

        except AICallError as e:
            logger.error(f"AI call failed for idea decomposition: {e}")
            raise

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
            self._processed_hashes.add(idea['hash'])
        self._save_processed_state()

    def reset(self):
        """Reset all processed state, allowing all ideas to be re-processed."""
        self._processed_hashes = set()
        self._last_mtime = 0.0
        if os.path.exists(self.processed_state_file):
            os.remove(self.processed_state_file)
        logger.info("Ideas processed state reset")
