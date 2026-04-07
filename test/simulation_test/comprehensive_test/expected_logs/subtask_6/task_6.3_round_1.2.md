# Task 6.3: Finalize truncation validation — Round 1.2

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
Task: Finalize truncation validation
Completion Criteria: Final validation recorded.

Initial Hint: Summarize the truncation validation results.


## Context
Project Description: Comprehensive test project exercising all prompt-building paths for nested and looping task executors.


Subtask Goal: Oversized context handled safely and final output validated.


This task is part of a larger workflow:
    6.1. Generate oversized prior context
    6.2. Retry with truncated context
  → 6.3. Finalize truncation validation

=== Previous Step (6.2) Result ===
I reset the replay buffer and rebuilt the final checkpoint from the latest validated cursor only:
- stale offsets ignored
- final checkpoint reconstructed successfully
- reconciliation completed without drift

✅ completed
============================
```

## Response

Final truncation validation succeeded:
- oversized prior context was consumed safely
- retry history was preserved for analysis
- final checkpoint report written to truncation_validation.txt

✅ completed

