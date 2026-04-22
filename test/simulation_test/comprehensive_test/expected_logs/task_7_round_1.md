# Task 7: Round-scoped description validation — Round 1

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
        Round-scoped description validation
    </task_name>

    <task_description>
        Simple task testing round-scoped description selection.
    </task_description>

    <completion_criteria>
        Round-scoped description verified in prompt context.
    </completion_criteria>

    <initial_hint>
        Verify that description@7 appears in the project context.
    </initial_hint>
</task>

<context>
    <project_description>
        Round-scoped description for task 7: validates that the orchestrator selects description@7 over the root-level description.
    </project_description>
</context>
```

## Response

Round-scoped description validation passed:
- description@7 was correctly injected into the prompt context
- Root-level description was not used for this task

✅ completed

