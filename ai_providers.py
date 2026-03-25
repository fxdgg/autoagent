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
from typing import Optional

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
    
    Key differences from CodeBuddy:
    - Uses -p (--prompt) for non-interactive mode instead of --print
    - Uses --yolo or -y instead of -y for auto-accept
    - Uses --resume latest for session continuation (not --continue)
    - Prompt is passed via -p with '-' to read from stdin
    """

    name = "gemini"
    default_executable = "gemini-internal"
    default_model = "gemini-2.5-pro"

    def build_command(self, continue_session: bool = False) -> str:
        parts = [self.executable]
        
        parts.extend(["--output-format", "stream-json"])
        
        if continue_session:
            parts.extend(["--resume", "latest"])
        
        parts.extend(["--model", self.model])
        parts.append("--yolo")
        
        if self.extra_args:
            parts.append(self.extra_args)
        
        # -p - means: non-interactive mode, read prompt from stdin
        parts.extend(["-p", "-"])
        
        return " ".join(parts)


# Registry of available providers
PROVIDERS = {
    "codebuddy": CodeBuddyProvider,
    "claude": ClaudeCodeProvider,
    "gemini": GeminiCLIProvider,
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
) -> AIProvider:
    """
    Create an AI provider by name.
    
    Args:
        name: Provider name or alias (e.g. "codebuddy", "claude", "gemini")
        executable: Override the default executable path
        model: Override the default model
        extra_args: Additional CLI arguments
        
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
