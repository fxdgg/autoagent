# Task 4.2: Validate report — Round 1.2

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes,
    you MUST use autoagent-exec instead of running it directly in Bash (which may cause **session timeout**):
      "<autoagent-exec>" "<your entire command>"
    Always wrap the command in double quotes so that shell operators are passed correctly.
    
    How does this work:
    You are SUBMITTING the command to the background, instead of executing commands using autoagent-exec.
    So DO NOT manually wait for the command to finish —— Just output ⏳ LONG_RUNNING_IN_PROGRESS after it shows "TASK SUBMITTED".
    
    autoagent-exec has three possible outcomes:
      - "TASK SUBMITTED" → the command is submitted to background. Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
      - "[OK]" → the command finished quickly with exit code 0. Continue working — treat it as a normal completed command.
      - "[FAST-FAIL]" → the command failed quickly. Read the error output, fix the issue, and retry.
    
    ⚠️ CRITICAL — No Output Redirection:
    autoagent-exec automatically captures ALL stdout/stderr to a log file.
    If you add output redirection (>, >>, 2>, &>, | tee, etc.), you may NOT see any of the three outcomes above.
    If commands in `initial_hint` already includes redirection, strip the redirection and use --stdout / --stderr instead:
      "<autoagent-exec>" --stdout build.log --stderr build_err.log "make"
    
    ⚠️ If you can't see autoagent-exec's any of the three outcomes:
    The output may have been already redirected. DO NOT run autoagent-exec again before checking the process by PID.
    Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately if it's still running.
    Check the command outputs in redirected files or "logs/<SESSION>/lr_tasks/lr_4.2_output.log" and continue working if it has already finished.
    DO NOT use `sleep` or any wait command in your session.
    
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
    Current task ID: 4.2

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

