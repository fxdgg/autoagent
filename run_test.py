#!/usr/bin/env python3
"""
AutoAgent Test Script - cuFFTDx DCT3D Kernel Optimization

This script tests the AutoAgent system by running an AI-driven optimization
task on a cuFFTDx-based 3D DCT kernel implementation.

Test objectives:
  1. AI can build, run, and benchmark CUDA code autonomously
  2. AI can use ncu (NVIDIA Nsight Compute) to profile kernel performance
  3. AI commits effective optimizations and reverts ineffective ones via git
  4. AI iterates until achieving >= 20% overall speedup

Usage:
    python run_test.py                                # Run with defaults (CodeBuddy)
    python run_test.py --provider claude              # Use Claude Code Internal
    python run_test.py --provider gemini              # Use Gemini CLI Internal
    python run_test.py --dry-run                      # Validate config only
    python run_test.py --status                       # Check current status
    python run_test.py --reset                        # Reset and start over
    python run_test.py --model glm-5.0-ioa            # Override model
    python run_test.py --project-root /path/to        # Override project root
    python run_test.py --autoagent-dir /path/to       # Override autoagent dir
    python run_test.py --list-providers               # List available AI providers
    python run_test.py --ideas ideas.md               # Process ideas.md into TODOs
    python run_test.py --idle --ideas ideas.md        # Run then idle for new ideas
"""

import os
import sys
import argparse
import subprocess
import shutil


def get_default_project_root():
    """Get the default project root (directory containing this script)."""
    return os.path.dirname(os.path.abspath(__file__))


def get_default_autoagent_dir(project_root):
    """Get the default autoagent/ directory relative to project root."""
    return os.path.normpath(os.path.join(project_root, "..", "..", "autoagent"))


def check_prerequisites(project_root, autoagent_dir, **kwargs):
    """Check that all prerequisites are met before running.
    
    Args:
        project_root: Path to the test project directory
        autoagent_dir: Path to the autoagent directory
        **kwargs: Additional options:
            - provider_name: AI provider name (default: 'codebuddy')
            - executable: Override executable path for the AI tool
    """
    errors = []

    # Check autoagent files exist
    required_autoagent_files = [
        "orchestrator.py",
        "codebuddy_client.py",
        "ai_providers.py",
        "task_executor.py",
        "state_manager.py",
    ]
    for f in required_autoagent_files:
        path = os.path.join(autoagent_dir, f)
        if not os.path.exists(path):
            errors.append(f"Missing autoagent file: {path}")

    # Check test project files
    required_test_files = [
        "CMakeLists.txt",
        "cufftdx_dct3d.cuh",
        "cufftdx_dct3d_dispatch.cu",
        "main.cpp",
        "todos.yaml",
    ]
    for f in required_test_files:
        path = os.path.join(project_root, f)
        if not os.path.exists(path):
            errors.append(f"Missing test file: {path}")

    # Check Python dependencies
    try:
        import yaml
    except ImportError:
        errors.append("Missing Python package: pyyaml (pip install pyyaml)")

    # Check AI tool availability based on provider
    provider_name = kwargs.get("provider_name", "codebuddy")
    executable = kwargs.get("executable", None)
    
    # Map provider to its default executable
    provider_executables = {
        "codebuddy": "codebuddy",
        "claude": "claude-internal",
        "gemini": "gemini-internal",
    }
    check_exe = executable or provider_executables.get(provider_name, provider_name)
    
    try:
        result = subprocess.run(
            f"{check_exe} --version",
            shell=True, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            errors.append(
                f"AI tool '{check_exe}' not found or not working. "
                f"Make sure '{check_exe}' is in your PATH."
            )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        errors.append(
            f"AI tool '{check_exe}' not found. "
            f"Make sure '{check_exe}' is in your PATH."
        )

    # Check git repo
    result = subprocess.run(
        "git status",
        shell=True, capture_output=True, text=True,
        cwd=project_root,
    )
    if result.returncode != 0:
        errors.append(
            "Not a git repository. Please initialize git:\n"
            f"  cd {project_root}\n"
            "  git init && git add -A && git commit -m 'initial'"
        )

    return errors


def ensure_git_initialized(project_root):
    """Ensure the test directory has a proper git state for the AI to work with."""
    result = subprocess.run(
        "git status --porcelain",
        shell=True, capture_output=True, text=True,
        cwd=project_root,
    )
    if result.returncode != 0:
        print("⚠️  Initializing git repository...")
        subprocess.run("git init", shell=True, cwd=project_root)
        subprocess.run("git add -A", shell=True, cwd=project_root)
        subprocess.run(
            'git commit -m "initial: cuFFTDx DCT3D baseline"',
            shell=True, cwd=project_root,
        )
        print("✅ Git repository initialized with baseline commit.")


def clean_log_dirs(project_root, log_dir=None):
    """Clean up the log session directory recorded in .autoagent_log.

    The .autoagent_log marker file (inside *project_root*) stores a single
    subdirectory name such as ``cufftdx_optimization_ko53bi1b``.  This
    function reads that name, joins it with *log_dir* to form the full
    session path, removes that directory, and finally removes the marker.

    Args:
        project_root: Path to the test project directory.
        log_dir: Root log directory (absolute path).  When *None* the
                 default ``.autoagent`` under CWD is used, mirroring
                 the orchestrator default.
    """
    if log_dir is None:
        log_dir = os.path.join(os.getcwd(), ".autoagent")

    marker = os.path.join(project_root, ".autoagent_log")
    if os.path.exists(marker):
        try:
            with open(marker, "r", encoding="utf-8") as f:
                subdir_name = f.read().strip()
        except Exception:
            subdir_name = ""

        if subdir_name:
            session_dir = os.path.join(log_dir, subdir_name)
            if os.path.exists(session_dir):
                shutil.rmtree(session_dir)
                print(f"  Removed session dir: {session_dir}")

        os.remove(marker)
        print(f"  Removed: .autoagent_log")
    else:
        print(f"  No .autoagent_log found; nothing to clean.")

    # Also clean any leftover long-running output files in project root
    for pattern_dir in ["monitors", "logs"]:
        target = os.path.join(project_root, pattern_dir)
        if os.path.exists(target):
            shutil.rmtree(target)
            print(f"  Removed: {pattern_dir}/")


def run_orchestrator(
    project_root,
    autoagent_dir,
    provider_name="codebuddy",
    model=None,
    executable=None,
    extra_provider_args=None,
    extra_args=None,
):
    """
    Run the AutoAgent orchestrator on the test task.
    
    Args:
        project_root: Path to test/cufftdx_optimization
        autoagent_dir: Path to autoagent/
        provider_name: AI provider name (codebuddy, claude, gemini)
        model: AI model to use (None = use provider default)
        executable: Override the default executable for the provider
        extra_provider_args: Additional CLI arguments for the AI tool
        extra_args: Additional CLI arguments for the orchestrator
    """
    todos_yaml = os.path.join(project_root, "todos.yaml")
    orchestrator_py = os.path.join(autoagent_dir, "orchestrator.py")

    cmd_parts = [
        sys.executable,
        orchestrator_py,
        "--config", todos_yaml,
        "--provider", provider_name,
        "--workspace", project_root,
        # "--verbose",
    ]

    if model:
        cmd_parts.extend(["--model", model])
    if executable:
        cmd_parts.extend(["--executable", executable])
    if extra_provider_args:
        cmd_parts.extend(["--extra-args", extra_provider_args])

    if extra_args:
        cmd_parts.extend(extra_args)

    cmd = " ".join(f'"{p}"' if " " in p else p for p in cmd_parts)

    # Resolve display model
    provider_default_models = {
        "codebuddy": "glm-5.0-ioa",
        "claude": "claude-sonnet-4-6",
        "gemini": "gemini-2.5-pro",
    }
    display_model = model or provider_default_models.get(provider_name, "(default)")

    print(f"\n{'=' * 70}")
    print(f"  AutoAgent Test: cuFFTDx DCT3D Kernel Optimization")
    print(f"{'=' * 70}")
    print(f"  Working directory : {project_root}")
    print(f"  Config            : {todos_yaml}")
    print(f"  Provider          : {provider_name}")
    print(f"  Model             : {display_model}")
    print(f"  AutoAgent         : {autoagent_dir}")
    print(f"{'=' * 70}")
    print(f"\n  Command: {cmd}\n")

    # Set PYTHONPATH so orchestrator can import its modules
    env = os.environ.copy()
    existing_pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = autoagent_dir + (os.pathsep + existing_pypath if existing_pypath else "")

    # Run the orchestrator
    try:
        result = subprocess.run(
            cmd_parts,
            cwd=project_root,
            env=env,
        )
        return result.returncode
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user.")
        print("    Run again to resume, or use --reset to start over.")
        return 130


def show_results(project_root):
    """Display test results if available."""
    print(f"\n{'=' * 70}")
    print(f"  Test Results")
    print(f"{'=' * 70}")

    # Show optimization result
    result_file = os.path.join(project_root, "optimization_result.txt")
    if os.path.exists(result_file):
        with open(result_file, 'r') as f:
            print(f"\n📊 Optimization Result:")
            print(f.read())
    else:
        print("\n📊 No optimization result file found yet.")

    # Show baseline
    baseline_file = os.path.join(project_root, "baseline_timing.txt")
    if os.path.exists(baseline_file):
        with open(baseline_file, 'r') as f:
            print(f"\n⏱️  Baseline Timing:")
            print(f.read())

    # Show git log
    print(f"\n📝 Git Log (recent commits):")
    subprocess.run(
        "git log --oneline -10",
        shell=True, cwd=project_root,
    )

    # Show ncu analysis
    analysis_file = os.path.join(project_root, "ncu_analysis.txt")
    if os.path.exists(analysis_file):
        with open(analysis_file, 'r') as f:
            content = f.read()
            print(f"\n🔍 NCU Analysis (first 1000 chars):")
            print(content[:1000])
            if len(content) > 1000:
                print("... (truncated)")

    print(f"\n{'=' * 70}")


def main():
    parser = argparse.ArgumentParser(
        description="AutoAgent Test: cuFFTDx DCT3D Kernel Optimization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Flow:
  1. Build project & record baseline performance
  2. Profile kernels with ncu (NVIDIA Nsight Compute)
  3. AI modifies CUDA code based on profiling results
  4. Rebuild, benchmark, verify correctness (Score: 100/100)
  5. Git commit if improved, git reset if not
  6. Repeat until >= 20% cumulative speedup is achieved

Supported AI Providers:
  codebuddy  - CodeBuddy CLI (default, model: glm-5.0-ioa)
  claude     - Claude Code Internal (model: claude-sonnet-4-6)
  gemini     - Gemini CLI Internal (model: gemini-2.5-pro)

Examples:
  python run_test.py                              # Run full test (CodeBuddy)
  python run_test.py --provider claude             # Use Claude Code Internal
  python run_test.py --provider gemini             # Use Gemini CLI Internal
  python run_test.py --dry-run                     # Validate config only
  python run_test.py --status                      # Show current progress
  python run_test.py --reset                       # Reset and start fresh
  python run_test.py --model glm-5.0-ioa           # Use specific model
  python run_test.py --project-root /path/to/project  # Custom project root
  python run_test.py --autoagent-dir /path/to/agent   # Custom autoagent dir
  python run_test.py --results                     # Show results summary
  python run_test.py --list-providers              # List available AI providers
  python run_test.py --ideas ideas.md              # Process ideas.md into TODOs
  python run_test.py --idle --ideas ideas.md       # Run then idle for new ideas
        """,
    )

    parser.add_argument(
        "--provider", "-P",
        default="codebuddy",
        help="AI provider to use: codebuddy (default), claude, gemini. "
             "Use --list-providers to see all available options.",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="AI model to use (default depends on provider: "
             "codebuddy=glm-5.0-ioa, claude=claude-sonnet-4-6, gemini=gemini-2.5-pro)",
    )
    parser.add_argument(
        "--executable",
        default=None,
        help="Override the default executable path for the AI provider",
    )
    parser.add_argument(
        "--extra-provider-args",
        default=None,
        help="Additional CLI arguments to pass to the AI tool",
    )
    parser.add_argument(
        "--list-providers",
        action="store_true",
        help="List available AI providers and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only validate configuration, don't execute",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current task status",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset all state and clean artifacts",
    )
    parser.add_argument(
        "--results",
        action="store_true",
        help="Show test results summary",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="Path to the test project directory (default: directory containing this script)",
    )
    parser.add_argument(
        "--autoagent-dir",
        default=None,
        help="Path to the autoagent/ directory (default: inferred from project root)",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip prerequisite checks",
    )
    parser.add_argument(
        "--task", "-t",
        type=str,
        default=None,
        help="Run only the specified task ID",
    )
    parser.add_argument(
        "--log-dir",
        default=None,
        help="Root directory for all output files: conversation logs, state files, "
             "and orchestrator.log (default: .autoagent under CWD)",
    )
    parser.add_argument(
        "--ideas",
        default=None,
        help="Path to ideas.md file. When set, new ideas will be processed into TODO tasks.",
    )
    parser.add_argument(
        "--idle",
        action="store_true",
        help="Enter idle mode after completing tasks. Waits for new ideas. Requires --ideas.",
    )
    parser.add_argument(
        "--idle-interval",
        type=int,
        default=30,
        help="Seconds between idle checks for new ideas (default: 30)",
    )
    parser.add_argument(
        "--use-cli",
        action="store_true",
        help="Use CLI subprocess instead of CodeBuddy Agent SDK (default is SDK). "
             "Only works with --provider codebuddy.",
    )
    parser.add_argument(
        "--test-rules",
        default=None,
        help="Path to test rules file for --provider test. "
             "Each rule is separated by '---RULE---' delimiter.",
    )

    args = parser.parse_args()

    project_root = os.path.abspath(args.project_root) if args.project_root else get_default_project_root()
    autoagent_dir = os.path.abspath(args.autoagent_dir) if args.autoagent_dir else get_default_autoagent_dir(project_root)

    print(f"🚀 AutoAgent Test: cuFFTDx DCT3D Kernel Optimization")
    print(f"   Project:  {project_root}")
    print(f"   Agent:    {autoagent_dir}")
    print(f"   Provider: {args.provider}")

    # List providers mode
    if args.list_providers:
        # Import from autoagent dir
        if autoagent_dir not in sys.path:
            sys.path.insert(0, autoagent_dir)
        from ai_providers import list_providers as _list_providers
        providers = _list_providers()
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

    # Results mode
    if args.results:
        show_results(project_root)
        return

    # Prerequisite checks
    if not args.skip_checks:
        print(f"\n🔍 Checking prerequisites...")
        errors = check_prerequisites(
            project_root, autoagent_dir,
            provider_name=args.provider,
            executable=args.executable,
        )
        if errors:
            print(f"\n❌ Prerequisite check failed:")
            for err in errors:
                print(f"   • {err}")
            print(f"\nFix the issues above and try again, or use --skip-checks to bypass.")
            sys.exit(1)
        print(f"   ✅ All prerequisites met.")

    # Reset mode
    if args.reset:
        print(f"\n🔄 Resetting test state...")
        # 1. Git reset: restore all tracked files and remove untracked ones
        subprocess.run("git checkout -- .", shell=True, cwd=project_root)
        subprocess.run("git clean -fd", shell=True, cwd=project_root)
        print(f"   ✅ Git: all files restored to HEAD, untracked files removed.")
        # 2. Remove log session directory (reads .autoagent_log to find it)
        log_dir = os.path.abspath(args.log_dir) if args.log_dir else None
        clean_log_dirs(project_root, log_dir=log_dir)
        print(f"   ✅ Log directories cleaned.")
        return

    # Status mode
    if args.status:
        extra = ["--status"]
        run_orchestrator(
            project_root, autoagent_dir,
            provider_name=args.provider, model=args.model,
            executable=args.executable, extra_provider_args=args.extra_provider_args,
            extra_args=extra,
        )
        show_results(project_root)
        return

    # Dry-run mode
    if args.dry_run:
        extra = ["--validate"]
        ret = run_orchestrator(
            project_root, autoagent_dir,
            provider_name=args.provider, model=args.model,
            executable=args.executable, extra_provider_args=args.extra_provider_args,
            extra_args=extra,
        )
        if ret == 0:
            print("\n✅ Configuration is valid. Ready to run.")
        else:
            print("\n❌ Configuration validation failed.")
        sys.exit(ret)

    # Ensure git state
    ensure_git_initialized(project_root)

    # Build extra args
    extra = []
    if args.task:
        extra.extend(["--task", args.task])
    if args.log_dir:
        # log_dir is relative to the console's current working directory, not project_root
        log_dir = os.path.abspath(args.log_dir)
        extra.extend(["--log-dir", log_dir])
    # Note: when --log-dir is not specified, orchestrator defaults to .autoagent (CWD-relative)
    if args.ideas:
        ideas_path = os.path.abspath(os.path.join(project_root, args.ideas))
        extra.extend(["--ideas", ideas_path])
    if args.idle:
        if not args.ideas:
            print("\n❌ --idle mode requires --ideas to be set.")
            sys.exit(1)
        extra.append("--idle")
        extra.extend(["--idle-interval", str(args.idle_interval)])
    if args.use_cli:
        extra.append("--use-cli")
    if args.test_rules:
        extra.extend(["--test-rules", os.path.abspath(args.test_rules)])

    # Run the test
    print(f"\n🏁 Starting AutoAgent test...")
    ret = run_orchestrator(
        project_root, autoagent_dir,
        provider_name=args.provider, model=args.model,
        executable=args.executable, extra_provider_args=args.extra_provider_args,
        extra_args=extra,
    )

    # Show results
    show_results(project_root)

    if ret == 0:
        print(f"\n🎉 Test completed successfully!")
    else:
        print(f"\n⚠️  Test finished with exit code {ret}")

    sys.exit(ret)


if __name__ == "__main__":
    main()
