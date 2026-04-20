
#!/usr/bin/env python3
"""
AutoAgent Orchestrator - Main entry point.

AI-driven task execution system that supports multiple AI providers
(CodeBuddy, Claude Code, Gemini CLI, Codex, OpenCode).
"""

import os
import sys
import json
import logging
import argparse

import yaml

from orchestrator.linear_orchestrator import TodoOrchestrator
from ai_client.ai_providers import (
    get_provider,
    list_providers,
    parse_model_spec,
    PROVIDER_ALIASES,
)
from task_executor import ConfigError
from util.default_value import generate_default_config, DEFAULTS

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False, log_file: str = None):
    """Configure logging.
    
    Args:
        verbose: Enable debug-level logging.
        log_file: Path to orchestrator.log. If None, only logs to stdout.
    """
    level = logging.DEBUG if verbose else logging.INFO
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers,
    )




def _ensure_utf8_stdio():
    """Reconfigure stdout/stderr to UTF-8 to avoid GBK encoding errors on Windows."""
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)
    if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
        sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", errors="replace", closefd=False)


def _load_config():
    """Load config.yaml from the same directory as this script.
    
    Returns:
        dict: Configuration values. Empty dict if file not found.
    """
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml")
    if os.path.isfile(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            logger.debug(f"Loaded config from {config_path}: {config}")
            return config
        except Exception as e:
            logger.warning(f"Failed to load config.yaml: {e}")
    return {}


def _expand_workspace_vars(value, workspace):
    """Expand ${workspace} variable in configuration values.
    
    Args:
        value: The value to expand (string or other type)
        workspace: The workspace path to substitute
        
    Returns:
        Expanded value with ${workspace} replaced by actual path
    """
    if isinstance(value, str):
        return value.replace('${workspace}', workspace)
    return value


def _load_preset(config, preset_name, workspace):
    """Load preset configuration from config.
    
    Args:
        config: The loaded config dict
        preset_name: Name of the preset to load
        workspace: Current workspace path for variable expansion
        
    Returns:
        dict: Preset configuration values, empty dict if not found
    """
    presets = config.get('preset', [])
    
    # Convert list to dict for easier lookup
    preset_dict = {}
    for p in presets:
        if isinstance(p, dict) and 'name' in p:
            preset_dict[p['name']] = p
    
    if preset_name not in preset_dict:
        if preset_name != 'default':
            print(f"⚠️  Warning: Preset '{preset_name}' not found in config.yaml")
        return {}
    
    preset = preset_dict[preset_name].copy()
    preset.pop('name', None)  # Remove name field
    
    # Expand ${workspace} variables
    for key, value in preset.items():
        preset[key] = _expand_workspace_vars(value, workspace)
    
    logger.debug(f"Loaded preset '{preset_name}': {preset}")
    return preset


def _merge_preset_with_args(args, preset):
    """Merge preset values with command-line arguments.
    
    Command-line arguments take precedence over preset values.
    Only applies preset values when the arg wasn't explicitly set on CLI.
    
    Args:
        args: Parsed argparse Namespace
        preset: Preset configuration dict
        
    Returns:
        Updated args Namespace
    """
    # Map of preset keys to args attributes
    preset_to_arg_map = {
        'config': 'config',
        'ideas': 'ideas',
        'provider': 'provider',
        'model': 'model',
        'executable': 'executable',
        'workspace': 'workspace',
        'log_dir': 'log_dir',
        'include_directories': 'include_directories',
        'test_schema': 'test_schema',
        'use_test': 'use_test',
        'verbose': 'verbose',
        'no_idle': 'no_idle',
        'use_cli': 'use_cli',
        'ideas_only': 'ideas_only',
        'human_review': 'human_review',
        'mode': 'mode',
    }
    
    # Default values that indicate "not set by user"
    # For store_true args, the argparse default is False, so we need to
    # include them here so the preset can override them.
    defaults_not_set = {
        'config': 'todos.yaml',
        'provider': 'codebuddy',
        'workspace': '.',
        'verbose': False,
        'no_idle': False,
        'use_cli': False,
        'ideas_only': False,
        'human_review': False,
    }
    
    for preset_key, arg_key in preset_to_arg_map.items():
        if preset_key in preset:
            preset_value = preset[preset_key]
            current_value = getattr(args, arg_key)
            default_value = defaults_not_set.get(arg_key)
            
            # Apply preset if:
            # 1. Current value is None, or
            # 2. Current value equals the argparse default (meaning user didn't override)
            if current_value is None or (default_value is not None and current_value == default_value):
                setattr(args, arg_key, preset_value)
                logger.debug(f"Applied preset '{preset_key}': {preset_value}")
    
    return args


def _list_sessions(log_dir: str, workspace: str):
    """List all known sessions and their status."""
    rows = TodoOrchestrator._load_sessions_csv(log_dir)

    # Also scan log_dir for session dirs not in CSV (e.g. from before CSV existed)
    known_ids = {r["session_id"] for r in rows}
    if os.path.isdir(log_dir):
        for d in sorted(os.listdir(log_dir)):
            full = os.path.join(log_dir, d)
            if os.path.isdir(full) and d not in known_ids and d != "logs":
                # Check if it looks like a session dir (has todos_state.yaml or orchestrator.log)
                if os.path.exists(os.path.join(full, "orchestrator.log")) or \
                   os.path.exists(os.path.join(full, "todos_state.yaml")):
                    rows.append({
                        "session_id": d,
                        "workspace": "?",
                        "created_at": "?",
                    })

    if not rows:
        print(f"No sessions found in {log_dir}/")
        return

    # Determine active session for this workspace
    active_subdir = TodoOrchestrator._read_marker(workspace)

    print(f"\nSessions in {log_dir}/\n")
    print(f"{'Workspace':<50s} {'Session ID':<40s} {'Created':<22s} {'Status'}")
    print(f"{'-' * 50} {'-' * 40} {'-' * 22} {'-' * 30}")

    for row in rows:
        sid = row.get("session_id", "?")
        ws = row.get("workspace", "?")
        created = row.get("created_at", "?")
        # Truncate workspace for display
        ws_display = ws if len(ws) <= 48 else "..." + ws[-45:]

        # Get status from todos_state.yaml
        session_path = os.path.join(log_dir, sid)
        status = TodoOrchestrator._get_session_status(session_path)

        # Mark active session
        if sid == active_subdir:
            status += " (active)"

        print(f"{ws_display:<50s} {sid:<40s} {created:<22s} {status}")

    print()




def main():
    """CLI entry point."""
    _ensure_utf8_stdio()

    # Load config.yaml defaults
    config = _load_config()
    default_session_timeout = config.get('session_timeout', DEFAULTS['session_timeout'])
    default_bash_timeout = config.get('bash_timeout', DEFAULTS['bash_timeout'])
    default_idle_interval = config.get('idle_interval', DEFAULTS['idle_interval'])
    default_max_attempts = config.get('default_max_attempts', DEFAULTS['default_max_attempts'])

    parser = argparse.ArgumentParser(
        description="AI-driven task execution system (supports CodeBuddy, Claude Code, Gemini CLI, Codex, OpenCode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python orchestrator.py                                  # Run all tasks (CodeBuddy default)
  python orchestrator.py --provider claude                 # Use Claude Code
  python orchestrator.py --provider gemini --model gemini-3-flash  # Use Gemini CLI
  python orchestrator.py --config my_tasks.yaml            # Use custom config
  python orchestrator.py --task 2                          # Run only task 2
  python orchestrator.py --reset                           # Reset all state
  python orchestrator.py --verbose                         # Enable debug logging
  python orchestrator.py --ideas ideas.md                  # Watch ideas.md for new ideas
  python orchestrator.py --ideas ideas.md --ideas-only     # Process ideas only (no task execution)
  python orchestrator.py --ideas ideas.md --human-review   # Process ideas with human review
  python orchestrator.py --mode ai                         # Force AI orchestrator mode
  python orchestrator.py --mode linear                     # Force linear mode (default)
  python orchestrator.py --list-providers                  # List available AI providers
        """,
    )

    # ── General ───────────────────────────────────────
    general = parser.add_argument_group('General')
    general.add_argument(
        '--config', '-c',
        default='todos.yaml',
        help='Path to task configuration file (default: todos.yaml)',
    )
    general.add_argument(
        '--workspace', '-w',
        default='.',
        help='Working directory (default: current directory)',
    )
    general.add_argument(
        '--mode',
        choices=['linear', 'ai'],
        default=None,
        help='Execution mode: "linear" (sequential) or "ai" (AI-driven scheduling). '
             'Default: auto-detect from todos.yaml (ai if ai_orchestrator field is present, '
             'otherwise linear). If todos.yaml has no ai_orchestrator field, only "linear" is allowed.',
    )
    general.add_argument(
        '--task', '-t',
        type=str,
        default=None,
        help='Execute only the specified task ID (not available in AI orchestrator mode)',
    )

    # ── Idea ──────────────────────────────────────────
    idea = parser.add_argument_group('Idea')
    idea.add_argument(
        '--ideas',
        default=None,
        help='Path to ideas.md file. When set, new ideas will be processed into TODO tasks.',
    )
    idea.add_argument(
        '--ideas-only',
        action='store_true',
        help='Only process ideas.md, do not run the TODO task list. '
             'Requires --ideas to be set.',
    )
    idea.add_argument(
        '--human-review',
        action='store_true',
        help='Enable human review for ideas processing. After AI review passes, '
             'pauses for human approval. Enter y to accept and exit, or n to provide '
             'feedback for revision. (default: disabled)',
    )
    idea.add_argument(
        '--no-idle',
        action='store_true',
        help='Disable idle mode. By default, when --ideas is set, the orchestrator '
             'enters idle mode after completing tasks (waiting for new ideas). '
             'Use --no-idle to run once and exit.',
    )

    # ── Session Management ────────────────────────────
    session = parser.add_argument_group('Session Management')
    session.add_argument(
        '--continue', dest='continue_session',
        action='store_true',
        help='Continue from the current session (reads .autoagent_log)',
    )
    session.add_argument(
        '--resume', dest='resume_session',
        default=None,
        help='Resume a specific session by ID (e.g. 4jvowsl3 or full name)',
    )
    session.add_argument(
        '--list-sessions',
        action='store_true',
        help='List all sessions and exit',
    )

    # ── Provider & Model ──────────────────────────────
    provider_group = parser.add_argument_group('Provider & Model')
    provider_group.add_argument(
        '--provider', '-P',
        default='codebuddy',
        help='AI provider to use: codebuddy (default), claude, gemini, codex, opencode, test (for testing only). '
             'Use --list-providers to see all available options.',
    )
    provider_group.add_argument(
        '--list-providers',
        action='store_true',
        help='List available AI providers and exit',
    )
    provider_group.add_argument(
        '--model', '-m',
        default=None,
        help='AI model to use. Supports single model (e.g. "glm-5") or '
             'multi-role format: "plan:model1;default:model2;lite:model3;evaluation:model4;scheduler:model5". '
             'Roles: plan (idea decomposition), default (task execution), '
             'lite (lightweight tasks), evaluation (failure analysis & main task evaluation), '
             'scheduler (AI orchestrator scheduling decisions). '
             'Missing roles inherit from default.',
    )
    provider_group.add_argument(
        '--executable',
        default=None,
        help='Override the default executable path for the AI provider',
    )
    provider_group.add_argument(
        '--extra-args',
        default=None,
        help='Additional CLI arguments to pass to the AI tool',
    )
    provider_group.add_argument(
        '--use-cli',
        action='store_true',
        help='Use CLI subprocess instead of CodeBuddy Agent SDK (default is SDK). '
             'Only works with --provider codebuddy.',
    )
    provider_group.add_argument(
        '--include-directories',
        default=None,
        help='Comma-separated list of additional directories the AI tool is allowed '
             'to access outside the workspace (Gemini only). '
             'Example: --include-directories /path/to/dir1,/path/to/dir2',
    )

    # ── Preset & Config ───────────────────────────────
    preset_group = parser.add_argument_group('Preset & Config')
    preset_group.add_argument(
        '--preset',
        default='default',
        help='Preset configuration name from config.yaml (default: default). '
             'Preset values can be overridden by command-line arguments.',
    )
    preset_group.add_argument(
        '--generate-default-config',
        action='store_true',
        help='Overwrite config.yaml with the built-in defaults and exit. '
             'The file is written to the same directory as orchestrator.py.',
    )

    # ── Utility ───────────────────────────────────────
    utility = parser.add_argument_group('Utility')
    utility.add_argument(
        '--validate',
        action='store_true',
        help='Validate configuration and exit',
    )
    utility.add_argument(
        '--reset',
        action='store_true',
        help='Reset all task states and exit',
    )
    utility.add_argument(
        '--log-dir',
        default=None,
        help='Root directory for all output files: conversation logs, state files, '
             'and orchestrator.log. Relative to CWD. (default: .autoagent)',
    )
    utility.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose/debug logging',
    )

    # ── Testing ───────────────────────────────────────
    testing = parser.add_argument_group('Testing')
    testing.add_argument(
        '--test-schema',
        default=None,
        help='Path to test schema JSON file (internal testing only). '
             'Used together with --use-test to select a test case. '
             'The schema defines test_rules, ai_strategy, and other test parameters.',
    )
    testing.add_argument(
        '--use-test',
        type=int,
        default=None,
        help='Test case ID (1-based index) to run from --test-schema. '
             'Automatically resolves test_rules and ai_strategy from the schema.',
    )
    
    args = parser.parse_args()

    # ── Handle --generate-default-config early (no other setup needed) ──
    if args.generate_default_config:
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "config.yaml"
        )
        written = generate_default_config(config_path)
        print(f"✅ Default config.yaml written to: {written}")
        return

    # Resolve workspace early for preset loading
    _workspace_abs = os.path.abspath(args.workspace)
    
    # Load and apply preset configuration
    preset = _load_preset(config, args.preset, _workspace_abs)
    if preset:
        print(f"✓ Loaded preset: {args.preset}")
        args = _merge_preset_with_args(args, preset)
    
    # Resolve key file paths to absolute paths early, so all downstream
    # code (IdeasWatcher, TodoOrchestrator, empty-file creation, etc.)
    # works correctly regardless of CWD vs workspace differences.
    args.config = os.path.abspath(args.config)
    if args.ideas:
        args.ideas = os.path.abspath(args.ideas)
    
    # Ensure required files exist (create empty if not present)
    if args.ideas:
        if not os.path.exists(args.ideas):
            os.makedirs(os.path.dirname(args.ideas) or '.', exist_ok=True)
            with open(args.ideas, 'w', encoding='utf-8') as f:
                f.write('')  # Create empty file
            print(f"✓ Created empty ideas file: {args.ideas}")
    
    if not os.path.exists(args.config):
        os.makedirs(os.path.dirname(args.config) or '.', exist_ok=True)
        with open(args.config, 'w', encoding='utf-8') as f:
            f.write('')  # Create empty file
        print(f"✓ Created empty config file: {args.config}")
    
    # Resolve log_dir early so we can point orchestrator.log there too.
    _log_dir_raw = args.log_dir  # may be None
    _log_dir_abs = os.path.abspath(_log_dir_raw) if _log_dir_raw else os.path.abspath(".autoagent")
    _workspace_abs = os.path.abspath(args.workspace)

    # ── Handle --list-sessions early (before session resolution) ──
    if args.list_sessions:
        _list_sessions(_log_dir_abs, _workspace_abs)
        return

    # ── Validate mutually exclusive session flags ──
    if args.continue_session and args.resume_session:
        print("❌ Cannot use --continue and --resume together.")
        sys.exit(1)

    # ── Resolve session directory based on mode ──
    if args.continue_session:
        _session_dir = TodoOrchestrator.resolve_session_dir(
            _log_dir_abs, _workspace_abs, mode="continue"
        )
    elif args.resume_session:
        _session_dir = TodoOrchestrator.resolve_session_dir(
            _log_dir_abs, _workspace_abs, mode="resume",
            resume_id=args.resume_session,
        )
    else:
        # Default: fresh start
        _session_dir = TodoOrchestrator.resolve_session_dir(
            _log_dir_abs, _workspace_abs, mode="new"
        )
    os.makedirs(_session_dir, exist_ok=True)

    # Setup logging – orchestrator.log goes into the session directory
    setup_logging(
        verbose=args.verbose,
        log_file=os.path.join(_session_dir, "orchestrator.log"),
    )
    
    try:
        # Handle --list-providers
        if args.list_providers:
            providers = list_providers()
            print(f"\n{'=' * 50}")
            print(f"  Available AI Providers")
            print(f"{'=' * 50}")
            for name, info in providers.items():
                aliases = ", ".join(info['aliases']) if info['aliases'] else "(none)"
                print(f"\n  📌 {name}")
                print(f"     Executable: {info['default_executable']}")
                print(f"     Default model: {info['default_model']}")
                print(f"     Aliases: {aliases}")
            print(f"\n{'=' * 50}")
            return

        # Determine idle mode: enabled by default when --ideas is set
        idle_mode = bool(args.ideas) and not args.no_idle
        
        # Validate --ideas-only requires --ideas
        if args.ideas_only and not args.ideas:
            print("❌ --ideas-only mode requires --ideas to be set.")
            sys.exit(1)
        
        # Validate non-codebuddy providers always use CLI (SDK is codebuddy-only)
        if not args.use_cli:
            resolved_provider = args.provider.lower()
            # Resolve aliases
            resolved_provider = PROVIDER_ALIASES.get(resolved_provider, resolved_provider)
            if resolved_provider not in ('codebuddy', 'test'):
                # Non-codebuddy providers don't support SDK, force CLI mode
                args.use_cli = True
        
        # ── Resolve --test-schema + --use-test into test_rules / ai_strategy ──
        test_rules_file = None
        ai_strategy = None

        if getattr(args, 'test_schema', None) and getattr(args, 'use_test', None) is not None:
            schema_path = os.path.abspath(args.test_schema)
            if not os.path.isfile(schema_path):
                print(f"❌ --test-schema file not found: {schema_path}")
                sys.exit(1)
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            test_idx = args.use_test - 1  # 1-based → 0-based
            if test_idx < 0 or test_idx >= len(schema):
                print(f"❌ --use-test {args.use_test} out of range (1-{len(schema)}).")
                sys.exit(1)
            tc = schema[test_idx]
            # Resolve test_rules path relative to the schema file's directory
            schema_dir = os.path.dirname(schema_path)
            test_rules_file = os.path.join(schema_dir, tc['test_rules'])
            if not os.path.isfile(test_rules_file):
                print(f"❌ test_rules file not found: {test_rules_file}")
                sys.exit(1)
            ai_strategy = tc.get('ai_strategy', None)
            logger.info(
                f"Resolved test case #{args.use_test}: "
                f"rules={tc['test_rules']}, ai_strategy={ai_strategy}"
            )
        elif getattr(args, 'test_schema', None) or getattr(args, 'use_test', None) is not None:
            print("❌ --test-schema and --use-test must be used together.")
            sys.exit(1)

        # Validate test provider requires --test-schema + --use-test
        if args.provider.lower() == 'test' and not test_rules_file:
            print("❌ --provider test requires --test-schema and --use-test to be set.")
            sys.exit(1)
        
        # Create AI provider
        executable = args.executable

        # Parse model spec into role→model dict
        model_roles = parse_model_spec(args.model or "")

        # Use the 'default' role model for the provider
        provider_model = model_roles["default"] if model_roles["default"] else args.model
        
        # Parse --include-directories into a list
        include_dirs = None
        if args.include_directories:
            include_dirs = [d.strip() for d in args.include_directories.split(',') if d.strip()]
        
        # When using Gemini with ideas, auto-include the todos.yaml parent directory
        # so that Gemini's sandbox allows writing the temp tasks file there.
        resolved_provider_name = args.provider.lower()
        resolved_provider_name = PROVIDER_ALIASES.get(resolved_provider_name, resolved_provider_name)
        if resolved_provider_name == 'gemini' and args.ideas:
            todos_parent = os.path.dirname(os.path.abspath(args.config))
            workspace_abs = os.path.abspath(args.workspace)
            if os.path.normcase(todos_parent) != os.path.normcase(workspace_abs):
                if include_dirs is None:
                    include_dirs = []
                if todos_parent not in include_dirs:
                    include_dirs.append(todos_parent)
                    logger.info(
                        f"Auto-added {todos_parent} to --include-directories "
                        f"for Gemini sandbox (todos.yaml parent != workspace)"
                    )
        
        provider = get_provider(
            name=args.provider,
            executable=executable,
            model=provider_model,
            extra_args=args.extra_args,
            test_rules_file=test_rules_file,
            include_directories=include_dirs,
            ai_strategy=ai_strategy,
        )
        
        logger.info(f"Using AI provider: {provider}")
        
        # Create orchestrator
        # Timeout and idle_interval are now solely from config.yaml
        effective_session_timeout = default_session_timeout
        effective_bash_timeout = default_bash_timeout
        effective_idle_interval = default_idle_interval
        backoff_max = config.get('backoff_max_wait', DEFAULTS['backoff_max_wait'])

        orchestrator = TodoOrchestrator(
            todos_file=args.config,
            provider=provider,
            workspace=args.workspace,
            timeout=effective_session_timeout,
            bash_timeout=effective_bash_timeout,
            session_dir=_session_dir,
            ideas_file=args.ideas,
            idle_interval=effective_idle_interval,
            use_cli=args.use_cli,
            backoff_max_wait=backoff_max,
            model_roles=model_roles,
            default_max_attempts=default_max_attempts,
        )
        
        # Handle special commands
        if args.validate:
            if orchestrator.validate_config():
                print("✅ Configuration is valid.")
            else:
                sys.exit(1)
            return
        
        if args.reset:
            orchestrator.reset()
            return
        
        
        # Process ideas before running tasks (if ideas file is configured)
        if orchestrator.ideas_watcher:
            orchestrator.check_and_process_ideas(
                human_review=args.human_review,
            )
        
        # --ideas-only mode: only process ideas, then exit
        if args.ideas_only:
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"📝 Conversation logs saved to: {orchestrator.session_dir}")
            print(f"\n✅ Ideas processing complete.")
            return

        # ── Determine execution mode ─────────────────────────────
        has_ai_orchestrator = orchestrator.ai_orchestrator is not None
        requested_mode = args.mode  # None, 'linear', or 'ai'

        if requested_mode == 'ai' and not has_ai_orchestrator:
            print("❌ --mode ai requires 'ai_orchestrator' field in todos.yaml.")
            print("   Add an ai_orchestrator section to your config or use --mode linear.")
            sys.exit(1)

        # Resolve effective mode: explicit > auto-detect
        if requested_mode is not None:
            effective_mode = requested_mode
        else:
            effective_mode = 'ai' if has_ai_orchestrator else 'linear'

        # When --mode linear is forced on a config that has ai_orchestrator,
        # clear it so all downstream code (run_with_idle, etc.) treats this
        # as a pure linear run.
        if effective_mode == 'linear' and has_ai_orchestrator:
            orchestrator.ai_orchestrator = None

        if effective_mode == 'ai':
            # --task is not supported in AI orchestrator mode
            if args.task:
                print("❌ --task is not supported in AI orchestrator mode.")
                print("   The AI scheduler decides which tasks to execute.")
                sys.exit(1)

            if idle_mode:
                # AI orchestrator + idle mode: run_with_idle handles both
                orchestrator.run_with_idle()
            else:
                results = orchestrator.run_ai_scheduled()

                # Finalize conversation logs
                if orchestrator.conv_logger:
                    orchestrator.conv_logger.finalize()
                    print(f"📝 Conversation logs saved to: {orchestrator.session_dir}")

                if results['failed_tasks'] > 0:
                    sys.exit(1)
            return

        # effective_mode == 'linear'
        if idle_mode:
            # Idle mode: run tasks then wait for new ideas
            orchestrator.run_with_idle(
                task_id=args.task,
            )
        else:
            # Normal mode: run tasks and exit
            results = orchestrator.run(
                task_id=args.task,
            )
            
            # Finalize conversation logs
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"📝 Conversation logs saved to: {orchestrator.session_dir}")
            
            # Exit with error code if any tasks failed
            if results['failed_tasks'] > 0:
                sys.exit(1)
            
    except ConfigError as e:
        print(f"❌ Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        # Record interrupt for in-progress tasks before exiting
        if 'orchestrator' in dir() and orchestrator:
            in_progress = orchestrator.state_manager.get_in_progress_tasks()
            for tid in in_progress:
                orchestrator.state_manager.record_interrupt(tid)
            # Finalize conversation logs even on interrupt
            if orchestrator.conv_logger:
                orchestrator.conv_logger.finalize()
                print(f"\n📝 Conversation logs saved to: {orchestrator.session_dir}")
        print(f"\n\n⚠️  Interrupted by user. State has been saved.")
        print(f"    Run again to resume from where you left off.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
