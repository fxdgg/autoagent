# Task 4.2: Validate report — Round 1.1

## System Prompt

```
# Instructions

## Status Markers
When you finish a task, you MUST end your response with EXACTLY one of these status lines (on its own line):
  ✅ completed
  ❌ not completed: <reason>

If a task requires a long-running command (e.g. compilation, benchmarking), use the `autoagent-exec` launcher instead of running it directly in Bash. When the launcher prints "TASK SUBMITTED", output:
  ⏳ LONG_RUNNING_IN_PROGRESS and END YOUR SESSION immediately.

These markers are MANDATORY. Your response MUST end with one of them.

## Note on long-running commands
If a Bash command may take more than a few minutes (e.g. compilation, benchmarking, profiling), do NOT run it directly in Bash. Instead use the `autoagent-exec` launcher:
  "<autoagent-exec>" "<your entire command>"
Always wrap your command in double quotes so that shell operators (&&, |, ;, etc.) are passed correctly. For example:
  "<autoagent-exec>" "cd build && cmake .. && make -j8"
The launcher will auto-detach after the fast-run window and print "TASK SUBMITTED". When you see that, output: ⏳ LONG_RUNNING_IN_PROGRESS and END YOUR SESSION immediately.

## ⚠️ IMPORTANT
1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or end your response with prompts like "What would you like to do?" or "Should I proceed?" — just do the work.
2. You MUST always use autoagent-exec for long-running commands. Running them directly in Bash will cause the session to hang and be killed. Even if autoagent-exec fails, fix the command arguments and retry with autoagent-exec — NEVER fall back to running directly in Bash.
```

## Prompt

```
You are an AI coding agent. You can read/write files, run shell commands, and analyze outputs. Complete the following task.


<task>
    <task_name>
        Validate report
    </task_name>

    <completion_criteria>
        Report validation passed.
    </completion_criteria>

    <initial_hint>
        Validate the generated report.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        Both iterations completed with passing validation.
    </subtask_goal>

    <workflow>
        4.1. Generate report
        → 4.2. Validate report

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result (4.1)>
        Report generation completed:

        - report_q1.pdf (45 pages)
        - report_data.json (raw data)
        - charts/ (12 PNG files)

        All data sources queried successfully. 50,000 records processed.

        ✅ completed
    </previous_step_result>
</context>
```

## Response

I validated the report but found discrepancies:

Error: Revenue figures in Section 3 don't match the raw data.
Expected total: $1,234,567 but report shows $1,234,000.
The rounding in the aggregation query is dropping cents.

❌ not completed: Revenue figures mismatch due to rounding error

