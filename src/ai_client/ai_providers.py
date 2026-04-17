"""
AI Providers - Abstracts differences between AI CLI tools.

Supported providers:
- codebuddy: CodeBuddy CLI (default)
- claude: Claude Code CLI
- gemini: Gemini Cli
- opencode: OpenCode CLI
- test: Test Provider (reads pre-defined responses from a rules file)

Each provider knows how to:
- Build the correct command-line arguments for its tool
- Handle tool-specific quirks (e.g. session continuation, permission flags)
"""

import os
import logging
from typing import Optional, List

import yaml

from ai_client.ai_client_common import DEFAULT_MODEL
from util.default_value import DEFAULTS

logger = logging.getLogger(__name__)

class AIProvider:
    """
    Base class for AI CLI tool providers.

    Subclasses must implement:
    - build_command(): Construct the CLI command string
    - get_stdin_command(): Build the full command with stdin piping

    The stream-json output format is assumed to be compatible across
    all providers (CodeBuddy, Claude Code, Gemini CLI all support it).
    """

    # Provider name (used for display and config)
    name: str = "base"

    # Default executable name
    default_executable: str = "ai-tool"

    # Default model
    default_model: str = ""

    # Whether this provider supports --append-system-prompt CLI parameter.
    # If True, system_prompt is passed via CLI; otherwise it must be
    # prepended to the user prompt by the caller.
    supports_system_prompt: bool = False

    def __init__(
        self,
        executable: str = None,
        model: str = None,
        extra_args: Optional[str] = None,
    ):
        """
        Initialize provider.

        Args:
            executable: Path to the CLI executable (None = use default)
            model: AI model to use (None = use provider default)
            extra_args: Additional CLI arguments to append
        """
        self.executable = executable or self.default_executable
        self.model = model or self.default_model
        self.extra_args = extra_args

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        """
        Build the CLI command string (without prompt).

        The prompt is always passed via stdin pipe.

        Args:
            session_id: Session ID to resume. If provided, the CLI will
                continue an existing conversation. If None, starts a new session.
            system_prompt: Optional system prompt to append via
                ``--append-system-prompt``.  Ignored by providers that
                do not support it (``supports_system_prompt = False``).

        Returns:
            str: The command string
        """
        raise NotImplementedError

    def get_stdin_command(self, prompt_file_path: str, cmd_args: str) -> str:
        """
        Build the full command that pipes a prompt file to the CLI tool.

        Args:
            prompt_file_path: Path to the temp file containing the prompt
            cmd_args: The command args from build_command()

        Returns:
            str: Full command string with stdin piping
        """
        if os.name == "nt":
            return f'type "{prompt_file_path}" | {cmd_args}'
        else:
            return f'cat "{prompt_file_path}" | {cmd_args}'

    def __repr__(self):
        return f"{self.__class__.__name__}(executable={self.executable!r}, model={self.model!r})"

    def set_model(self, model_name: str):
        """
        Switch the model used by this provider.

        Since task execution is single-threaded, mutating self.model
        in-place is safe.

        Args:
            model_name: New model name to use
        """
        if model_name and model_name != self.model:
            logger.info(f"[{self.name}] Switching model: {self.model} → {model_name}")
            self.model = model_name


class CodeBuddyProvider(AIProvider):
    """
    Provider for CodeBuddy CLI.

    Command pattern:
        type prompt.txt | codebuddy --debug --verbose --print
            --output-format stream-json [--resume <session_id>] --model <model> -y -
    """

    name = "codebuddy"
    default_executable = "codebuddy"
    default_model = DEFAULT_MODEL
    supports_system_prompt = True

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        parts = [self.executable]

        parts.append("--debug --verbose --print")
        parts.extend(["--output-format", "stream-json"])

        if session_id:
            parts.extend(["--resume", session_id])

        parts.extend(["--model", self.model])

        if system_prompt:
            # Escape double quotes for shell safety
            escaped = system_prompt.replace('"', '\\"')
            parts.extend(["--append-system-prompt", f'"{escaped}"'])

        if self.extra_args:
            parts.append(self.extra_args)

        # -y - means: accept all, read prompt from stdin
        parts.extend(["-y", "-"])

        return " ".join(parts)


class ClaudeCodeProvider(AIProvider):
    """
    Provider for Claude Code CLI.

    Command pattern:
        type prompt.txt | claude --print --output-format stream-json
            [--resume <session_id>] --model <model> --dangerously-skip-permissions -

    Key differences from CodeBuddy:
    - Uses --dangerously-skip-permissions instead of -y
    - The stdin sentinel is also '-'
    - Supports --debug with optional filter and --verbose flags
    """

    name = "claude"
    default_executable = "claude"
    default_model = DEFAULTS['default_model_provider']['claude']
    supports_system_prompt = True

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        parts = [self.executable]

        parts.append("--verbose --print")
        parts.extend(["--output-format", "stream-json"])

        if session_id:
            parts.extend(["--resume", session_id])

        parts.extend(["--model", self.model])
        parts.append("--dangerously-skip-permissions")

        if system_prompt:
            # Escape double quotes for shell safety
            escaped = system_prompt.replace('"', '\\"')
            parts.extend(["--append-system-prompt", f'"{escaped}"'])

        if self.extra_args:
            parts.append(self.extra_args)

        # '-' reads prompt from stdin
        parts.append("-")

        return " ".join(parts)


class GeminiCLIProvider(AIProvider):
    """
    Provider for Gemini Cli.

    Command pattern:
        type prompt.txt | gemini --output-format stream-json
            -p - [--resume latest] --model <model> --yolo
            [--include-directories <dir1>,<dir2>,...]

    Key differences from CodeBuddy:
    - Uses -p (--prompt) for non-interactive mode instead of --print
    - Uses --yolo or -y instead of -y for auto-accept
    - Uses --resume <session_id> for session continuation
    - Prompt is passed via -p with '-' to read from stdin
    - Supports --include-directories to allow access to directories outside workspace
    """

    name = "gemini"
    default_executable = "gemini"
    default_model = DEFAULTS['default_model_provider']['gemini']

    def __init__(
        self,
        executable: str = None,
        model: str = None,
        extra_args: Optional[str] = None,
        include_directories: Optional[List[str]] = None,
    ):
        """
        Initialize Gemini CLI provider.

        Args:
            executable: Path to the CLI executable (None = use default)
            model: AI model to use (None = use provider default)
            extra_args: Additional CLI arguments to append
            include_directories: List of additional directories Gemini is
                allowed to read/write outside the workspace sandbox.
        """
        super().__init__(executable=executable, model=model, extra_args=extra_args)
        self.include_directories = include_directories or []

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        parts = [self.executable]

        parts.extend(["--output-format", "stream-json"])

        if session_id:
            parts.extend(["--resume", session_id])

        parts.extend(["--model", self.model])
        parts.append("--yolo")

        # Add --include-directories if specified
        if self.include_directories:
            dirs_str = ",".join(self.include_directories)
            parts.extend(["--include-directories", dirs_str])

        if self.extra_args:
            parts.append(self.extra_args)

        # system_prompt is ignored — Gemini CLI does not support it

        # -p - means: non-interactive mode, read prompt from stdin
        parts.extend(["-p", "-"])

        return " ".join(parts)


class OpenCodeProvider(AIProvider):
    """
    Provider for OpenCode CLI (https://opencode.ai).

    OpenCode is a terminal-based AI coding agent that supports multiple
    AI backends (Claude, GPT, Gemini, etc.) through its own configuration.

    Command pattern (new session):
        type prompt.txt | opencode run --format json [-m <model>]

    Command pattern (continue session):
        type prompt.txt | opencode run --format json [-m <model>] -s <session_id>

    Key differences from other providers:
    - Session continuation uses -s <session_id>
    - The session ID is extracted from the first JSON event
    - Output format uses line-delimited JSON with types:
      step_start, text, tool_call, tool_result, step_finish
    - The --format json flag is required for machine-readable output
    - Does not set a default model; uses opencode's own configuration
    """

    name = "opencode"
    default_executable = "opencode"
    default_model = ""  # Uses opencode's configured default

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        parts = [self.executable, "run"]

        parts.extend(["--format", "json"])

        if self.model:
            parts.extend(["-m", self.model])

        if session_id:
            parts.extend(["-s", session_id])

        if self.extra_args:
            parts.append(self.extra_args)

        # system_prompt is ignored — OpenCode does not support it

        return " ".join(parts)

    def get_stdin_command(self, prompt_file_path: str, cmd_args: str) -> str:
        """
        OpenCode supports stdin pipe for the message, just like other providers.
        """
        if os.name == "nt":
            return f'type "{prompt_file_path}" | {cmd_args}'
        else:
            return f'cat "{prompt_file_path}" | {cmd_args}'

class CodexProvider(AIProvider):
    """
    Provider for OpenAI Codex CLI.

    Command pattern:
        type prompt.txt | codex exec --json --dangerously-bypass-approvals-and-sandbox
            -s danger-full-access [-m <model>] -

    Key features:
    - Uses `codex exec` subcommand for non-interactive mode
    - Uses --json for JSONL output
    - Uses --dangerously-bypass-approvals-and-sandbox for auto-accept
    - Uses -s danger-full-access to disable sandbox
    - '-' reads prompt from stdin
    - Does not support --append-system-prompt (system_prompt prepended to user prompt)
    """

    name = "codex"
    default_executable = "codex"
    default_model = DEFAULTS['default_model_provider']['codex']
    supports_system_prompt = False

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        parts = [self.executable, "exec"]

        parts.append("--json")
        parts.append("--dangerously-bypass-approvals-and-sandbox")
        parts.extend(["-s", "danger-full-access"])

        if session_id:
            parts.extend(["-c", f'session_id="{session_id}"'])

        if self.model:
            parts.extend(["-m", self.model])

        if self.extra_args:
            parts.append(self.extra_args)

        # system_prompt is not supported natively — caller prepends to user prompt

        # '-' reads prompt from stdin
        parts.append("-")

        return " ".join(parts)


class TestProvider(AIProvider):
    """
    Test provider that reads pre-defined responses from a rules file.

    This provider does NOT call any real AI tool. Instead, it reads
    responses sequentially from a test_rules file. This is useful for
    testing the orchestration logic without incurring AI costs.

    The rules file format uses '---RULE---' as a delimiter between
    consecutive responses. Each section between delimiters is returned
    verbatim as the AI response for one ask() call.

    Example test_rules.txt:
    ```
    I have completed the task successfully.

    ✅ completed
    ---RULE---
    {"analysis": "Build failed", "retry_from": "1.1", "reasoning": "...", "suggested_fix": "...", "confidence": "high"}
    ---RULE---
    ❌ not completed: build error in line 42
    ```

    For long_running tasks, the AI response should instruct the system
    to run a command. You can use 'sleep 15' for testing.
    """

    name = "test"
    default_executable = "test"
    default_model = "test"

    def __init__(
        self,
        test_rules_file: str = None,
        executable: str = None,
        model: str = None,
        extra_args: str = None,
        ai_strategy: str = None,
    ):
        super().__init__(executable=executable, model=model, extra_args=extra_args)
        self.test_rules_file = test_rules_file
        self._rules = []
        self._rule_index = 0
        # AI scheduling strategy for test mode.
        # When set to "sequential", the provider auto-generates scheduler
        # decisions (execute tasks in order, then stop) so that the same
        # test_rules file can be reused for AI-mode tests.
        self.ai_strategy = ai_strategy
        # Populated by the orchestrator after loading todos.yaml:
        # list of top-level task ID strings in order, e.g. ["1", "2", "3"]
        self.ai_task_ids: list[str] = []
        # Internal counter: which task in ai_task_ids to schedule next
        self._ai_sched_index = 0
        if test_rules_file:
            self._load_rules(test_rules_file)

    def _load_rules(self, filepath: str):
        """Load test rules from file, split by '---RULE---' delimiter.

        The delimiter must appear on its own line (leading/trailing whitespace
        is ignored). Lines starting with '#' at the beginning of a rule
        section are treated as comments and stripped.
        """
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Split into sections by '---RULE---' lines
        sections = []
        current_section = []
        for line in lines:
            if line.strip() == "---RULE---":
                if current_section:
                    sections.append("".join(current_section))
                    current_section = []
            else:
                current_section.append(line)
        # Don't forget the last section
        if current_section:
            sections.append("".join(current_section))

        # Clean up each section: strip leading/trailing whitespace,
        # and remove leading comment lines (lines starting with #) and blank lines
        for section in sections:
            # Strip the section
            stripped = section.strip()
            if not stripped:
                continue
            # Remove leading comment lines and blank lines
            result_lines = []
            past_leading = False
            for line in stripped.split("\n"):
                sline = line.strip()
                if not past_leading and (sline.startswith("#") or sline == ""):
                    continue  # Skip leading comments and blank lines
                past_leading = True
                result_lines.append(line)
            cleaned = "\n".join(result_lines).strip()
            if cleaned:
                self._rules.append(cleaned)

        logger.info(f"Loaded {len(self._rules)} test rules from {filepath}")

    def get_next_response(self) -> str:
        """
        Get the next pre-defined response.

        Returns responses in order. If all rules are exhausted,
        cycles back to the last rule (to avoid index errors in
        long-running tests).

        Returns:
            str: The next test response
        """
        if not self._rules:
            return "❌ not completed: No test rules loaded"

        if self._rule_index >= len(self._rules):
            # Cycle on the last rule to avoid crashes
            logger.warning(
                f"Test rules exhausted (used {self._rule_index}/{len(self._rules)}). "
                f"Repeating last rule."
            )
            return self._rules[-1]

        response = self._rules[self._rule_index]
        self._rule_index += 1
        logger.info(
            f"TestProvider: returning rule {self._rule_index}/{len(self._rules)}"
        )
        return response

    def get_scheduler_decision(self) -> str | None:
        """Auto-generate a scheduler decision for sequential AI strategy.

        When ``ai_strategy == "sequential"``, this method returns the next
        sequential scheduling decision JSON string.  It walks through
        ``ai_task_ids`` in order, returning an ``execute`` action for each,
        then a ``stop`` action when all tasks have been scheduled.

        Returns:
            JSON string for the scheduler decision, or None if
            ``ai_strategy`` is not set.
        """
        if self.ai_strategy != 'sequential' or not self.ai_task_ids:
            return None

        if self._ai_sched_index >= len(self.ai_task_ids):
            logger.info("TestProvider: sequential scheduler → stop")
            return '{"action": "stop", "reasoning": "All tasks executed sequentially"}'

        task_id = self.ai_task_ids[self._ai_sched_index]
        self._ai_sched_index += 1
        logger.info(f"TestProvider: sequential scheduler → execute task {task_id}")
        return ('{"action": "execute", "task_id": ' + task_id +
                ', "reasoning": "Sequential execution order"}')

    def peek_remaining(self) -> int:
        """Return the number of remaining unused rules."""
        return max(0, len(self._rules) - self._rule_index)

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        # Not used for test provider
        return "echo test-provider"

    def __repr__(self):
        return (
            f"TestProvider(rules_file={self.test_rules_file!r}, "
            f"rules={len(self._rules)}, index={self._rule_index})"
        )


# Registry of available providers
PROVIDERS = {
    "codebuddy": CodeBuddyProvider,
    "claude": ClaudeCodeProvider,
    "gemini": GeminiCLIProvider,
    "opencode": OpenCodeProvider,
    "codex": CodexProvider,
    "test": TestProvider,
}

# Aliases for convenience
PROVIDER_ALIASES = {
    "cb": "codebuddy",
    "claude-code": "claude",
    "claude": "claude",
    "gemini-cli": "gemini",
    "gemini": "gemini",
    "oc": "opencode",
    "codex": "codex",
}


def get_provider(
    name: str,
    executable: str = None,
    model: str = None,
    extra_args: str = None,
    test_rules_file: str = None,
    include_directories: List[str] = None,
    ai_strategy: str = None,
) -> AIProvider:
    """
    Create an AI provider by name.

    Args:
        name: Provider name or alias (e.g. "codebuddy", "claude", "gemini", "test")
        executable: Override the default executable path
        model: Override the default model
        extra_args: Additional CLI arguments
        test_rules_file: Path to test rules file (only for "test" provider)
        include_directories: List of additional directories for Gemini sandbox
        ai_strategy: AI scheduling strategy for test mode ("sequential" or None)

    Returns:
        AIProvider: Configured provider instance

    Raises:
        ValueError: If the provider name is unknown
    """
    # Resolve aliases
    resolved = PROVIDER_ALIASES.get(name.lower(), name.lower())

    provider_class = PROVIDERS.get(resolved)
    if not provider_class:
        available = ", ".join(
            sorted(set(list(PROVIDERS.keys()) + list(PROVIDER_ALIASES.keys())))
        )
        raise ValueError(f"Unknown AI provider: {name!r}. Available: {available}")

    if resolved == "test":
        if not test_rules_file:
            raise ValueError(
                "TestProvider requires --test-schema and --use-test to specify the test case."
            )
        return TestProvider(
            test_rules_file=test_rules_file,
            executable=executable,
            model=model,
            extra_args=extra_args,
            ai_strategy=ai_strategy,
        )

    if resolved == "gemini":
        return GeminiCLIProvider(
            executable=executable,
            model=model,
            extra_args=extra_args,
            include_directories=include_directories,
        )

    return provider_class(
        executable=executable,
        model=model,
        extra_args=extra_args,
    )


def list_providers() -> dict:
    """
    List all available providers with their info.

    Returns:
        dict: Provider name -> info dict
    """
    result = {}
    for name, cls in PROVIDERS.items():
        result[name] = {
            "name": cls.name,
            "default_executable": cls.default_executable,
            "default_model": cls.default_model,
            "aliases": [k for k, v in PROVIDER_ALIASES.items() if v == name],
        }
    return result


# Valid model roles for multimodel support
MODEL_ROLES = ("plan", "default", "lite", "evaluation", "scheduler")


def parse_model_spec(model_spec) -> dict:
    """
    Parse a model specification into a role→model dict.

    Supports three formats:

    1. **Single model string**: ``"glm-5"``
       → all roles use the same model

    2. **Multi-role string** (CLI-friendly):
       ``"plan:claude-opus-4.6;default:glm-5;lite:glm-4-flash"``
       - Separator: ``;``   Key-value separator: ``:``
       - Only role names from ``MODEL_ROLES`` are allowed
       - Missing roles inherit from ``default``

    3. **Dict** (config.yaml-friendly)::

           model:
             plan: claude-opus-4.6
             default: glm-5
             lite: glm-4-flash
             evaluation: claude-opus-4.6

       Same validation as format 2.

    Args:
        model_spec: Model specification — ``str`` or ``dict``.

    Returns:
        dict with at least ``plan``, ``default``, ``lite`` keys.
        ``evaluation`` is included when explicitly specified, otherwise
        falls back to ``default``.

    Raises:
        ValueError: If the spec contains invalid role names or is
            missing the ``default`` role.
    """
    empty = {role: "" for role in MODEL_ROLES}

    if not model_spec:
        return empty

    # ── Format 3: dict (from config.yaml) ────────────────────────
    if isinstance(model_spec, dict):
        roles = {}
        for role, model in model_spec.items():
            role = str(role).strip()
            if role not in MODEL_ROLES:
                raise ValueError(
                    f"Unknown model role: {role!r}. "
                    f"Allowed roles: {', '.join(MODEL_ROLES)}"
                )
            roles[role] = str(model).strip()

        if "default" not in roles:
            raise ValueError(
                f"Model spec dict must include 'default'. Got: {model_spec!r}"
            )

        default_model = roles["default"]
        for role in MODEL_ROLES:
            if role not in roles:
                roles[role] = default_model
        return roles

    # ── Format 1 & 2: string ─────────────────────────────────────
    model_str = str(model_spec)

    # Check if it's a multi-role spec (contains ';' or starts with a valid role prefix)
    if ";" in model_str or any(
        model_str.startswith(f"{role}:") for role in MODEL_ROLES
    ):
        roles = {}
        for part in model_str.split(";"):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise ValueError(
                    f"Invalid model spec segment: {part!r}. "
                    f"Expected 'role:model' format (roles: {', '.join(MODEL_ROLES)})"
                )
            role, model = part.split(":", 1)
            role = role.strip()
            model = model.strip()
            if role not in MODEL_ROLES:
                raise ValueError(
                    f"Unknown model role: {role!r}. "
                    f"Allowed roles: {', '.join(MODEL_ROLES)}"
                )
            roles[role] = model

        # 'default' must be present if any role is specified
        if "default" not in roles:
            raise ValueError(
                f"Multi-role model spec must include 'default'. Got: {model_str!r}"
            )

        # Fill missing roles with 'default' value
        default_model = roles["default"]
        for role in MODEL_ROLES:
            if role not in roles:
                roles[role] = default_model

        return roles
    else:
        # Single model string — all roles use the same model
        return {role: model_str for role in MODEL_ROLES}
