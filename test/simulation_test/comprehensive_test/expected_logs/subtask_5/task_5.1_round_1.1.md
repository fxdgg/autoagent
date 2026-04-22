# Task 5.1: Prepare fallback scenario — Round 1.1

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes,
    you MUST use autoagent-exec instead of running it directly in Bash:
      "<autoagent-exec>" "<your entire command>"
    Directly running in Bash may cause **session timeout**, wasting time or leaving the project in broken state.
    Always wrap the command in double quotes so that shell operators are passed correctly.
    
    autoagent-exec has three possible outcomes:
      - "TASK SUBMITTED" → the command is running in the background. Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
      - "[OK]" → the command finished quickly with exit code 0. Continue working — treat it as a normal completed command.
      - "[FAST-FAIL]" → the command failed quickly. Read the error output, fix the issue, and retry.
    
    ⚠️ CRITICAL — No Output Redirection:
    autoagent-exec already captures ALL stdout/stderr to a log file automatically.
    If you add output redirection (>, >>, 2>, &>, | tee, etc.) to the command, you may NOT see any of the three outcomes above.
    If the task hint's command already includes redirection, strip the redirection and use --stdout / --stderr instead:
      "<autoagent-exec>" --stdout build.log --stderr build_err.log "make"
    
    ⚠️ If you can't see autoagent-exec's any of the three outcomes:
    The most likely reason is that its output has been already redirected.
    DO NOT run autoagent-exec again before checking if the process is still running by PID.
    Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately if it's still running.
    Check the command outputs and continue working if it has already finished.
    DO NOT use `sleep` or any wait command.
    
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
        Prepare fallback scenario
    </task_name>

    <completion_criteria>
        Fallback test inputs prepared.
    </completion_criteria>

    <initial_hint>
        Prepare the fallback validation scenario.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        All subtasks completed and fallback handling validated.
    </subtask_goal>

    <workflow>
        → 5.1. Prepare fallback scenario
          5.2. Run fragile transformation
          5.3. Verify fallback output

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>
</context>
```

## Response

I prepared the fallback scenario inputs:
- generated fragile_input.json
- recorded baseline schema expectations
- enabled fallback audit logging

✅ completed

