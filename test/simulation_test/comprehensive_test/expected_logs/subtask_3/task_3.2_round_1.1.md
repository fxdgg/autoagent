# Task 3.2: Run integration tests — Round 1.1

## System Prompt

```
# Instructions

## Status Markers
When you finish a task, you MUST end your response with EXACTLY one of these status lines (on its own line):
  ✅ completed
  ❌ not completed: <reason>

If a task requires a long-running command (e.g. compilation, benchmarking), use the `autoagent-exec` launcher instead of running it directly in Bash. When the launcher prints "TASK SUBMITTED", output:
  ⏳ LONG_RUNNING_IN_PROGRESS

These markers are MANDATORY. Your response MUST end with one of them.

## Note on long-running commands
If a Bash command may take more than a few minutes (e.g. compilation, benchmarking, profiling), do NOT run it directly in Bash. Instead use the `autoagent-exec` launcher:
  "<autoagent-exec>" "<your entire command>"
Always wrap your command in double quotes so that shell operators (&&, |, ;, etc.) are passed correctly. For example:
  "<autoagent-exec>" "cd build && cmake .. && make -j8"
The launcher will auto-detach after the fast-run window and print "TASK SUBMITTED". When you see that, output: ⏳ LONG_RUNNING_IN_PROGRESS

## ⚠️ IMPORTANT
1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or end your response with prompts like "What would you like to do?" or "Should I proceed?" — just do the work.
2. You MUST always use autoagent-exec for long-running commands. Running them directly in Bash will cause the session to hang and be killed. Even if autoagent-exec fails, fix the command arguments and retry with autoagent-exec — NEVER fall back to running directly in Bash.
```

## Prompt

```
You are an AI coding agent. You can read/write files, run shell commands, and analyze outputs. Complete the following task.


## Task
Task: Run integration tests
Completion Criteria: Integration tests passed.

Initial Hint: Execute the integration test suite.


## Context
Project Description: Comprehensive test project exercising all prompt-building paths for nested and looping task executors.


Subtask Goal: All subtasks completed with validated results.


This task is part of a larger workflow:
    3.1. Build artifacts
  → 3.2. Run integration tests
    3.3. Deploy staging
    3.4. Smoke test staging

=== Previous Step (3.1) Result ===
The build pipeline completed successfully.

Artifacts generated:
- app.wasm (12MB)
- app.js (340KB)
- sourcemaps/

All compilation checks passed. Zero warnings.

✅ completed
============================
```

## Response

I ran the integration tests but 3 of 47 tests failed:

FAIL: test_auth_flow - Expected 200, got 401
FAIL: test_data_sync - Timeout after 30s
FAIL: test_webhook_delivery - Missing signature header

❌ not completed: 3 integration tests failed

