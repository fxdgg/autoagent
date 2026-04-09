# Task 4.2: Validate report — Round 1.2

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes (compilation, benchmarking, profiling, training, etc.), 
    you MUST use autoagent-exec instead of running it directly in Bash:
      "<autoagent-exec>" "<your entire command>"
    Always wrap the command in double quotes so that shell operators are passed correctly.
    When autoagent-exec prints "TASK SUBMITTED", output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
    NEVER run long commands directly in Bash — the session may be killed due to timeout, wasting time or leaving the project in broken state.
    
    3. When you are done, end your response with EXACTLY one of:
      ✅ completed
      ❌ not completed: <reason>
      ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED")
</instructions>
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
        Report regenerated with correct precision:

        - report_q1.pdf (45 pages, updated)
        - report_data.json (raw data with decimal values)
        - charts/ (12 PNG files, updated)

        Revenue total now shows $1,234,567.89 (correct).

        ✅ completed
    </previous_step_result>
</context>
```

## Response

I re-validated the report with decimal precision:

Revenue figures now match ($1,234,567.89), but a new issue:

Error: Chart 7 (quarterly comparison) shows negative growth for Q4
but the raw data shows positive growth. The chart generation script
has a sign error in the YoY comparison formula.

❌ not completed: Chart 7 YoY comparison has sign error

