"""
AI Providers - Abstracts differences between AI CLI tools.

Supported providers:
- codebuddy: CodeBuddy CLI (default)
- claude: Claude Code Internal CLI
- gemini: Gemini CLI Internal

Each provider knows how to:
- Build the correct command-line arguments for its tool
- Handle tool-specific quirks (e.g. session continuation, permission flags)
"""

import os
import logging
from typing import Optional, List

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

    def build_command(self, continue_session: bool = False) -> str:
        """
        Build the CLI command string (without prompt).
        
        The prompt is always passed via stdin pipe.
        
        Args:
            continue_session: Whether to continue an existing session
            
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


class CodeBuddyProvider(AIProvider):
    """
    Provider for CodeBuddy CLI.
    
    Command pattern:
        type prompt.txt | codebuddy --debug --verbose --max-turns 500 --print
            --output-format stream-json [--continue] --model <model> -y -
    """

    name = "codebuddy"
    default_executable = "codebuddy"
    default_model = "glm-5.0-ioa"

    def build_command(self, continue_session: bool = False) -> str:
        parts = [self.executable]
        
        parts.append("--debug --verbose --print")
        parts.extend(["--output-format", "stream-json"])
        
        if continue_session:
            parts.append("--continue")
        
        parts.extend(["--model", self.model])
        
        if self.extra_args:
            parts.append(self.extra_args)
        
        # -y - means: accept all, read prompt from stdin
        parts.extend(["-y", "-"])
        
        return " ".join(parts)


class ClaudeCodeProvider(AIProvider):
    """
    Provider for Claude Code Internal CLI.
    
    Command pattern:
        type prompt.txt | claude-internal --print --output-format stream-json
            [--continue] --model <model> --dangerously-skip-permissions -
    
    Key differences from CodeBuddy:
    - Uses --dangerously-skip-permissions instead of -y
    - The stdin sentinel is also '-'
    - Supports --debug with optional filter and --verbose flags
    """

    name = "claude"
    default_executable = "claude-internal"
    default_model = "claude-sonnet-4-6"

    def build_command(self, continue_session: bool = False) -> str:
        parts = [self.executable]
        
        parts.append("--verbose --print")
        parts.extend(["--output-format", "stream-json"])
        
        if continue_session:
            parts.append("--continue")
        
        parts.extend(["--model", self.model])
        parts.append("--dangerously-skip-permissions")
        
        if self.extra_args:
            parts.append(self.extra_args)
        
        # '-' reads prompt from stdin
        parts.append("-")
        
        return " ".join(parts)


class GeminiCLIProvider(AIProvider):
    """
    Provider for Gemini CLI Internal.
    
    Command pattern:
        type prompt.txt | gemini-internal --output-format stream-json
            -p - [--resume latest] --model <model> --yolo
            [--include-directories <dir1>,<dir2>,...]
    
    Key differences from CodeBuddy:
    - Uses -p (--prompt) for non-interactive mode instead of --print
    - Uses --yolo or -y instead of -y for auto-accept
    - Uses --resume latest for session continuation (not --continue)
    - Prompt is passed via -p with '-' to read from stdin
    - Supports --include-directories to allow access to directories outside workspace
    """

    name = "gemini"
    default_executable = "gemini-internal"
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

    def build_command(self, continue_session: bool = False) -> str:
        parts = [self.executable]
        
        parts.extend(["--output-format", "stream-json"])
        
        if continue_session:
            parts.extend(["--resume", "latest"])
        
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

    def build_command(self, continue_session: bool = False) -> str:
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
    "test": TestProvider,
}

# Aliases for convenience
PROVIDER_ALIASES = {
    "cb": "codebuddy",
    "claude-code": "claude",
    "claude-internal": "claude",
    "gemini-cli": "gemini",
    "gemini-internal": "gemini",
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
