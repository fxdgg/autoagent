"""
AI Providers - Abstracts differences between AI CLI tools.

This module loads provider configurations from providers.yaml and creates
provider instances dynamically. Each provider knows how to:
- Build the correct command-line arguments for its tool
- Handle tool-specific quirks (e.g. session continuation, permission flags)
- Parse stream-JSON output via pluggable parser scripts

Supported providers are defined in src/ai_client/providers.yaml.
"""

import os
import re
import sys
import logging
import subprocess
import importlib.util
from pathlib import Path
from typing import Optional, List, Set, Dict, Any
from dataclasses import dataclass

import yaml

from ai_client.ai_client_common import DEFAULT_MODEL

logger = logging.getLogger(__name__)

# Cache for loaded provider configs and parsers
_providers_config_cache: Optional[Dict[str, Any]] = None
_parser_cache: Dict[str, Any] = {}


@dataclass
class ProviderConfig:
    """Configuration for a CLI-based AI provider loaded from providers.yaml."""

    name: str
    default_executable: str
    model: str
    fixed_arguments: str = ""
    resume_argument: str = ""
    model_argument: str = ""
    system_prompt_argument: str = ""
    bypass_argument: str = ""
    stream_json: str = ""
    tool_names: Optional[Dict[str, str]] = None

    def __post_init__(self):
        if self.tool_names is None:
            self.tool_names = {}


def _load_providers_yaml() -> Dict[str, Any]:
    """Load and cache the providers.yaml configuration file.

    Returns:
        Dict with keys: 'codebuddy_sdk_default_model', 'providers'
    """
    global _providers_config_cache

    if _providers_config_cache is not None:
        return _providers_config_cache

    # Look for providers.yaml in the same directory as this module
    providers_yaml_path = Path(__file__).parent / "providers.yaml"

    if not providers_yaml_path.exists():
        raise FileNotFoundError(
            f"providers.yaml not found at {providers_yaml_path}. "
            "This file is required to configure AI providers."
        )

    with open(providers_yaml_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("providers.yaml must contain a YAML dictionary")

    _providers_config_cache = config
    logger.debug(f"Loaded providers.yaml from {providers_yaml_path}")
    return config


def _get_provider_config(name: str) -> Optional[ProviderConfig]:
    """Get provider configuration by name from providers.yaml.

    Args:
        name: Provider name (e.g., "codebuddy", "claude", "gemini")

    Returns:
        ProviderConfig instance, or None if not found
    """
    config = _load_providers_yaml()
    providers_list = config.get("providers", [])

    for provider_dict in providers_list:
        if provider_dict.get("name") == name:
            return ProviderConfig(
                name=provider_dict["name"],
                default_executable=provider_dict.get("default_executable", ""),
                model=provider_dict.get("model", ""),
                fixed_arguments=provider_dict.get("fixed_arguments", ""),
                resume_argument=provider_dict.get("resume_argument", ""),
                model_argument=provider_dict.get("model_argument", ""),
                system_prompt_argument=provider_dict.get("system_prompt_argument", ""),
                bypass_argument=provider_dict.get("bypass_argument", ""),
                stream_json=provider_dict.get("stream_json", ""),
                tool_names=provider_dict.get("tool_names"),
            )

    return None


def _load_stream_parser(script_name: str):
    """Dynamically load a Parser class from providers/<script_name>.

    Args:
        script_name: Filename of the parser script (e.g., "codebuddy.py")

    Returns:
        Parser instance
    """
    if script_name in _parser_cache:
        return _parser_cache[script_name]

    provider_dir = Path(__file__).parent / "providers"
    script_path = provider_dir / script_name

    if not script_path.is_file():
        raise RuntimeError(
            f"Stream-JSON parser script not found: {script_path}"
        )

    module_name = f"ai_client_provider_{script_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(script_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parser_cls = getattr(module, "Parser", None)
    if parser_cls is None:
        raise RuntimeError(
            f"Parser script {script_name} does not export a 'Parser' class"
        )

    parser = parser_cls()
    _parser_cache[script_name] = parser
    logger.debug(f"Loaded stream-JSON parser from {script_path}")
    return parser


class AIProvider:
    """
    Base class for AI CLI tool providers.

    This class uses configuration loaded from providers.yaml to build
    command-line invocations for different AI CLI tools.
    """

    def __init__(
        self,
        config: ProviderConfig,
        executable: str = None,
        model: str = None,
        extra_args: Optional[str] = None,
    ):
        """
        Initialize provider from configuration.

        Args:
            config: Provider configuration from providers.yaml
            executable: Path to the CLI executable (None = use default)
            model: AI model to use (None = use provider default)
            extra_args: Additional CLI arguments to append
        """
        self.config = config
        self.name = config.name
        self.default_executable = config.default_executable
        self.default_model = config.model
        self.executable = executable or config.default_executable
        self.model = model or config.model
        self.extra_args = extra_args

        # Whether this provider supports --append-system-prompt CLI parameter
        self.supports_system_prompt = bool(config.system_prompt_argument)

        # Load stream-JSON parser if specified
        self.parser = None
        if config.stream_json:
            try:
                self.parser = _load_stream_parser(config.stream_json)
            except RuntimeError as e:
                logger.warning(f"Failed to load parser for {self.name}: {e}")

    def build_command(self, session_id: str = None, system_prompt: str = None) -> str:
        """
        Build the CLI command string (without prompt).

        The prompt is always passed via stdin pipe.

        Args:
            session_id: Session ID to resume. If provided, the CLI will
                continue an existing conversation. If None, starts a new session.
            system_prompt: Optional system prompt to append via CLI flag.
                Ignored by providers that do not support it.

        Returns:
            str: The command string
        """
        parts = [self.executable]

        # Add fixed arguments
        if self.config.fixed_arguments:
            parts.extend(self.config.fixed_arguments.split())

        # Add session resume argument
        if session_id and self.config.resume_argument:
            parts.extend([self.config.resume_argument, session_id])

        # Add model argument
        if self.model and self.config.model_argument:
            parts.extend([self.config.model_argument, self.model])

        # Add system prompt argument
        if system_prompt and self.config.system_prompt_argument:
            # Escape double quotes for shell safety
            escaped = system_prompt.replace('"', '\\"')
            parts.extend([self.config.system_prompt_argument, f'"{escaped}"'])

        # Add bypass/auto-approve argument
        if self.config.bypass_argument:
            parts.append(self.config.bypass_argument)

        # Add extra arguments
        if self.extra_args:
            parts.append(self.extra_args)

        return " ".join(parts)

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

    def __repr__(self):
        return f"AIProvider(name={self.name!r}, executable={self.executable!r}, model={self.model!r})"


class CodeBuddyProvider(AIProvider):
    """
    Provider for CodeBuddy CLI with model validation support.

    This is a specialized subclass that adds model validation via --help parsing.
    """

    _supported_models_cache: dict = {}  # executable -> set[str] | None

    @classmethod
    def get_supported_models(cls, executable: str = None) -> Optional[Set[str]]:
        """Extract supported model names from ``<executable> --help``.

        Parses the ``--model <model>`` line in the help output to find the
        parenthesized list of supported model IDs.

        Results are cached per executable path so the subprocess is only
        invoked once per session.

        Returns:
            A set of lowercase model name strings, or ``None`` if the
            help text could not be parsed (e.g. executable not found).
        """
        exe = executable or "codebuddy"
        if exe in cls._supported_models_cache:
            return cls._supported_models_cache[exe]

        try:
            # On Windows, npm-installed tools live as .cmd scripts;
            # shell=True is needed so subprocess can resolve them via PATHEXT.
            result = subprocess.run(
                [exe, "--help"],
                capture_output=True,
                text=True,
                timeout=15,
                shell=(sys.platform == "win32"),
            )
            help_text = result.stdout or ""
        except Exception:
            cls._supported_models_cache[exe] = None
            return None

        # The --model section in help text may span multiple lines, e.g.:
        #   --model <model>  Model for AI processing.
        #                    Currently supported: (model1, model2, ...)
        # We collect all lines from "--model" until the next CLI option
        # (a line starting with '-') to form the full --model description.
        lines = help_text.splitlines()
        model_section = None
        for i, line in enumerate(lines):
            if "--model" in line:
                # Collect this line and continuation lines until next option
                section_lines = [line]
                for j in range(i + 1, len(lines)):
                    stripped = lines[j].lstrip()
                    # A new option starts with '-' (e.g. --foo or -x)
                    if stripped.startswith("-"):
                        break
                    section_lines.append(lines[j])
                model_section = " ".join(section_lines)
                break

        if not model_section:
            cls._supported_models_cache[exe] = None
            return None

        # Extract the parenthesized list after "Currently supported:"
        match = re.search(
            r"Currently supported:\s*\(([^)]+)\)",
            model_section,
            re.IGNORECASE,
        )
        if not match:
            cls._supported_models_cache[exe] = None
            return None

        raw = match.group(1)
        models = {m.strip().lower() for m in raw.split(",") if m.strip()}
        if not models:
            cls._supported_models_cache[exe] = None
            return None

        cls._supported_models_cache[exe] = models
        logger.debug("CodeBuddy supported models (%s): %s", exe, models)
        return models


class TestProvider(AIProvider):
    """
    Test provider that reads pre-defined responses from a rules file.

    This provider does NOT call any real AI tool. Instead, it reads
    responses sequentially from a test_rules file. This is useful for
    testing the orchestration logic without incurring AI costs.

    The rules file format uses '---RULE---' as a delimiter between
    consecutive responses. Each section between delimiters is returned
    verbatim as the AI response for one ask() call.
    """

    def __init__(
        self,
        test_rules_file: str = None,
        executable: str = None,
        model: str = None,
        extra_args: str = None,
        ai_strategy: str = None,
    ):
        # Create a dummy config for TestProvider
        dummy_config = ProviderConfig(
            name="test",
            default_executable="test",
            model="test",
        )
        super().__init__(dummy_config, executable=executable, model=model, extra_args=extra_args)

        self.test_rules_file = test_rules_file
        self._rules = []
        self._rule_index = 0
        # AI scheduling strategy for test mode
        self.ai_strategy = ai_strategy
        # Populated by the orchestrator after loading todos.yaml
        self.ai_task_ids: list[str] = []
        # Internal counter: which task in ai_task_ids to schedule next
        self._ai_sched_index = 0
        if test_rules_file:
            self._load_rules(test_rules_file)

    def _load_rules(self, filepath: str):
        """Load test rules from file, split by '---RULE---' delimiter."""
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

        # Clean up each section
        for section in sections:
            stripped = section.strip()
            if not stripped:
                continue
            # Remove leading comment lines and blank lines
            result_lines = []
            past_leading = False
            for line in stripped.split("\n"):
                sline = line.strip()
                if not past_leading and (sline.startswith("#") or sline == ""):
                    continue
                past_leading = True
                result_lines.append(line)
            cleaned = "\n".join(result_lines).strip()
            if cleaned:
                self._rules.append(cleaned)

        logger.info(f"Loaded {len(self._rules)} test rules from {filepath}")

    def get_next_response(self) -> str:
        """Get the next pre-defined response."""
        if not self._rules:
            return "❌ not completed: No test rules loaded"

        if self._rule_index >= len(self._rules):
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
        """Auto-generate a scheduler decision for sequential AI strategy."""
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
        return "echo test-provider"

    def __repr__(self):
        return (
            f"TestProvider(rules_file={self.test_rules_file!r}, "
            f"rules={len(self._rules)}, index={self._rule_index})"
        )


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
        name: Provider name (e.g. "codebuddy", "claude", "gemini", "test")
        executable: Override the default executable path
        model: Override the default model
        extra_args: Additional CLI arguments
        test_rules_file: Path to test rules file (only for "test" provider)
        include_directories: List of additional directories (reserved for future use)
        ai_strategy: AI scheduling strategy for test mode ("sequential" or None)

    Returns:
        AIProvider: Configured provider instance

    Raises:
        ValueError: If the provider name is unknown
    """
    # Handle test provider specially
    if name.lower() == "test":
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

    # Load provider config from providers.yaml
    config = _get_provider_config(name.lower())
    if config is None:
        # List available providers
        all_config = _load_providers_yaml()
        available = [p["name"] for p in all_config.get("providers", [])]
        raise ValueError(
            f"Unknown AI provider: {name!r}. "
            f"Available providers in providers.yaml: {', '.join(available)}"
        )

    # Create provider instance based on name
    if name.lower() == "codebuddy":
        return CodeBuddyProvider(
            config=config,
            executable=executable,
            model=model,
            extra_args=extra_args,
        )
    else:
        return AIProvider(
            config=config,
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
    config = _load_providers_yaml()
    providers_list = config.get("providers", [])

    result = {}
    for provider_dict in providers_list:
        name = provider_dict.get("name", "")
        if name:
            result[name] = {
                "name": name,
                "default_executable": provider_dict.get("default_executable", ""),
                "default_model": provider_dict.get("model", ""),
                "stream_json": provider_dict.get("stream_json", ""),
            }

    # Add test provider
    result["test"] = {
        "name": "test",
        "default_executable": "test",
        "default_model": "test",
        "stream_json": "",
    }

    return result


def get_codebuddy_sdk_default_model() -> str:
    """Get the default model for CodeBuddy SDK mode from providers.yaml."""
    config = _load_providers_yaml()
    return config.get("codebuddy_sdk_default_model", DEFAULT_MODEL)


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
