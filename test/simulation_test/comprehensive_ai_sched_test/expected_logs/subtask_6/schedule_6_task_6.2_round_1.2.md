# Task 6.2: Retry with truncated context — Round 1.2

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes (compilation, benchmarking, profiling, training, etc.), 
    you MUST use autoagent-exec instead of running it directly in Bash:
      "<autoagent-exec>" "<your entire command>"
    Always wrap the command in double quotes so that shell operators are passed correctly.
    autoagent-exec has three possible outcomes:
      - "TASK SUBMITTED" → the command is running in the background. Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
      - "[OK]" → the command finished quickly with exit code 0. Continue working — treat it as a normal completed command.
      - "[FAST-FAIL]" → the command failed quickly. Read the error output, fix the issue, and retry.
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
        Retry with truncated context
    </task_name>

    <completion_criteria>
        Retry succeeds after analyzing truncated context.
    </completion_criteria>

    <initial_hint>
        Use the oversized context to debug and complete the task.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        Oversized context handled safely and final output validated.
    </subtask_goal>

    <workflow>
        6.1. Generate oversized prior context
        → 6.2. Retry with truncated context
          6.3. Finalize truncation validation

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>
</context>

<guidance_from_previous_failure>
    Reset the replay buffer before reconstructing the final checkpoint, then rebuild the checkpoint exclusively from the latest validated cursor snapshot instead of mixing in stale offsets.

    Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>
```

## Response

I reset the replay buffer and rebuilt the final checkpoint from the latest validated cursor only:
- stale offsets ignored
- final checkpoint reconstructed successfully
- reconciliation completed without drift

✅ completed

