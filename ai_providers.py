"""
AI Providers - Abstracts differences between AI CLI tools.

Supported providers:
- codebuddy: CodeBuddy CLI (default)
- claude: Claude Code CLI
- gemini: Gemini Cli

Each provider knows how to:
- Build the correct command-line arguments for its tool
- Handle tool-specific quirks (e.g. session continuation, permission flags)
"""

import os
import logging
from typing import Optional, List

import yaml

logger = logging.getLogger(__name__)


def _load_default_model():
    """Load default model from config.yaml."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return config.get('default_model', 'deepseek-v3.2')
        except Exception:
            pass
    return 'deepseek-v3.2'


# Default model loaded from config.yaml, fallback to deepseek-v3.2
DEFAULT_MODEL = _load_default_model()


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

    def build_command(self, session_id: str = None) -> str:
        """
        Build the CLI command string (without prompt).

        The prompt is always passed via stdin pipe.

        Args:
            session_id: Session ID to resume. If provided, the CLI will
                continue an existing conversation. If None, starts a new session.

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
        if os.name == 'nt':
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
        type prompt.txt | codebuddy --debug --verbose --max-turns 500 --print
            --output-format stream-json [--resume <session_id>] --model <model> -y -
    """

    name = "codebuddy"
    default_executable = "codebuddy"
    default_model = DEFAULT_MODEL

    def build_command(self, session_id: str = None) -> str:
        parts = [self.executable]

        parts.append("--debug --verbose --print")
        parts.extend(["--output-format", "stream-json"])

        if session_id:
            parts.extend(["--resume", session_id])

        parts.extend(["--model", self.model])

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
    default_model = "claude-sonnet-4-6"

    def build_command(self, session_id: str = None) -> str:
        parts = [self.executable]

        parts.append("--verbose --print")
        parts.extend(["--output-format", "stream-json"])

        if session_id:
            parts.extend(["--resume", session_id])

        parts.extend(["--model", self.model])
        parts.append("--dangerously-skip-permissions")
        
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
    default_model = "gemini-2.5-pro"

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

    def build_command(self, session_id: str = None) -> str:
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
        
        # -p - means: non-interactive mode, read prompt from stdin
        parts.extend(["-p", "-"])
        
        return " ".join(parts)


class OpenCodeProvider(AIProvider):
    """
    Provider for OpenCode CLI (https://opencode.ai).

    OpenCode is a terminal-based AI coding agent that supports multiple
    AI backends (Claude, GPT, Gemini, etc.) through its own configuration.

    Command pattern (new session):
        opencode run --format json -m <model> "prompt text"

    Command pattern (continue session):
        opencode run --format json -m <model> -s <session_id> "prompt text"

    Key differences from other providers:
    - Prompt is passed as a positional argument, NOT via stdin
    - Session continuation uses -s <session_id>
    - The session ID is extracted from the first JSON event
    - Output format uses line-delimited JSON with types:
      step_start, text, tool_call, tool_result, step_finish
    - The --format json flag is required for machine-readable output
    """

    name = "opencode"
    default_executable = "opencode"
    default_model = ""  # Uses opencode's configured default

    def build_command(self, session_id: str = None) -> str:
        parts = [self.executable, "run"]

        parts.extend(["--format", "json"])

        if self.model:
            parts.extend(["-m", self.model])

        if session_id:
            parts.extend(["-s", session_id])

        if self.extra_args:
            parts.append(self.extra_args)

        return " ".join(parts)

    def get_stdin_command(self, prompt_file_path: str, cmd_args: str) -> str:
        """
        OpenCode supports stdin pipe for the message, just like other providers.
        """
        if os.name == 'nt':
            return f'type "{prompt_file_path}" | {cmd_args}'
        else:
            return f'cat "{prompt_file_path}" | {cmd_args}'


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
    ):
        super().__init__(executable=executable, model=model, extra_args=extra_args)
        self.test_rules_file = test_rules_file
        self._rules = []
        self._rule_index = 0
        if test_rules_file:
            self._load_rules(test_rules_file)

    def _load_rules(self, filepath: str):
        """Load test rules from file, split by '---RULE---' delimiter.
        
        The delimiter must appear on its own line (leading/trailing whitespace
        is ignored). Lines starting with '#' at the beginning of a rule
        section are treated as comments and stripped.
        """
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Split into sections by '---RULE---' lines
        sections = []
        current_section = []
        for line in lines:
            if line.strip() == '---RULE---':
                if current_section:
                    sections.append(''.join(current_section))
                    current_section = []
            else:
                current_section.append(line)
        # Don't forget the last section
        if current_section:
            sections.append(''.join(current_section))
        
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
            for line in stripped.split('\n'):
                sline = line.strip()
                if not past_leading and (sline.startswith('#') or sline == ''):
                    continue  # Skip leading comments and blank lines
                past_leading = True
                result_lines.append(line)
            cleaned = '\n'.join(result_lines).strip()
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
        logger.info(f"TestProvider: returning rule {self._rule_index}/{len(self._rules)}")
        return response

    def peek_remaining(self) -> int:
        """Return the number of remaining unused rules."""
        return max(0, len(self._rules) - self._rule_index)

    def build_command(self, session_id: str = None) -> str:
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
}


def get_provider(
    name: str,
    executable: str = None,
    model: str = None,
    extra_args: str = None,
    test_rules_file: str = None,
    include_directories: List[str] = None,
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
        
    Returns:
        AIProvider: Configured provider instance
        
    Raises:
        ValueError: If the provider name is unknown
    """
    # Resolve aliases
    resolved = PROVIDER_ALIASES.get(name.lower(), name.lower())
    
    provider_class = PROVIDERS.get(resolved)
    if not provider_class:
        available = ", ".join(sorted(set(list(PROVIDERS.keys()) + list(PROVIDER_ALIASES.keys()))))
        raise ValueError(
            f"Unknown AI provider: {name!r}. "
            f"Available: {available}"
        )
    
    if resolved == 'test':
        if not test_rules_file:
            raise ValueError(
                "TestProvider requires --test-rules <file> to specify the rules file."
            )
        return TestProvider(
            test_rules_file=test_rules_file,
            executable=executable,
            model=model,
            extra_args=extra_args,
        )
    
    if resolved == 'gemini':
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
MODEL_ROLES = ("plan", "default", "simple")


def parse_model_spec(model_str: str) -> dict:
    """
    Parse a model specification string into a role→model dict.

    Supports two formats:
    1. Single model: "glm-5" → all three roles use the same model
    2. Multi-role: "plan:glm-4-flash;default:glm-5;simple:glm-4-flash"
       - Separator is ';', key-value separator is ':'
       - Only 'plan', 'default', 'simple' keys are allowed
       - Missing roles are filled with the 'default' value

    Args:
        model_str: Model specification string

    Returns:
        dict: {"plan": "...", "default": "...", "simple": "..."}

    Raises:
        ValueError: If the spec contains invalid role names
    """
    if not model_str:
        return {"plan": "", "default": "", "simple": ""}

    # Check if it's a multi-role spec (contains both ';' and ':' with a valid role prefix)
    if ';' in model_str or any(model_str.startswith(f"{role}:") for role in MODEL_ROLES):
        roles = {}
        for part in model_str.split(';'):
            part = part.strip()
            if not part:
                continue
            if ':' not in part:
                raise ValueError(
                    f"Invalid model spec segment: {part!r}. "
                    f"Expected 'role:model' format (roles: {', '.join(MODEL_ROLES)})"
                )
            role, model = part.split(':', 1)
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
                "Multi-role model spec must include 'default'. "
                f"Got: {model_str!r}"
            )

        # Fill missing roles with 'default' value
        default_model = roles["default"]
        for role in MODEL_ROLES:
            if role not in roles:
                roles[role] = default_model

        return roles
    else:
        # Single model string — all roles use the same model
        return {"plan": model_str, "default": model_str, "simple": model_str}
