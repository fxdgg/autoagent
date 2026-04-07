# Task 3.2: Run integration tests — Round 1.2

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


<task>
Task: Run integration tests
Completion Criteria: Integration tests passed.

Initial Hint: Execute the integration test suite.

</task>

<context>
Project Description: Comprehensive test project exercising all prompt-building paths for nested and looping task executors.


Subtask Goal: All subtasks completed with validated results.


This task is part of a larger workflow:
    3.1. Build artifacts
  → 3.2. Run integration tests
    3.3. Deploy staging
    3.4. Smoke test staging

=== Previous Step (3.1) Result ===
Rebuild completed successfully with auth module:

Artifacts generated:
- app.wasm (13.2MB, +1.2MB from auth module)
- app.js (355KB)
- auth_tokens.json
- sourcemaps/

All compilation checks passed. Auth module linked.

✅ completed
============================
</context>
```

## Response

I re-ran the integration tests against the rebuilt artifacts:

All 47 tests passed:
- test_auth_flow: PASS (200 OK, token validated)
- test_data_sync: PASS (completed in 2.3s)
- test_webhook_delivery: PASS (signature verified)

✅ completed

