# Task 4.2: Validate report — Round 1.2

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
Task: Validate report
Completion Criteria: Report validation passed.

Initial Hint: Validate the generated report.

</task>

<context>
Project Description: Comprehensive test project exercising all prompt-building paths for nested and looping task executors.


Subtask Goal: Both iterations completed with passing validation.


This task is part of a larger workflow:
    4.1. Generate report
  → 4.2. Validate report

=== Previous Step (4.1) Result ===
Report regenerated with correct precision:

- report_q1.pdf (45 pages, updated)
- report_data.json (raw data with decimal values)
- charts/ (12 PNG files, updated)

Revenue total now shows $1,234,567.89 (correct).

✅ completed
============================
</context>
```

## Response

I re-validated the report with decimal precision:

Revenue figures now match ($1,234,567.89), but a new issue:

Error: Chart 7 (quarterly comparison) shows negative growth for Q4
but the raw data shows positive growth. The chart generation script
has a sign error in the YoY comparison formula.

❌ not completed: Chart 7 YoY comparison has sign error

