# Task 2.2: Process data — Round 1.2

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
        Process data
    </task_name>

    <completion_criteria>
        Data processed correctly.
    </completion_criteria>

    <initial_hint>
        Run the data processing step.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        Both iterations completed successfully with correct output.
    </subtask_goal>

    <workflow>
        2.1. Iteration setup
        → 2.2. Process data
          2.3. Verify output

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>
</context>

<guidance_from_previous_failure>
    Add null_handling='drop' parameter to the processing config, or add a preprocessing filter that removes records with null user_id before the main processing step.

    Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>
```

## Response

I added the null handling filter but a new error appeared:

Error: SchemaValidationError - field 'email' contains malformed
entries. 89 records have invalid email format after null filtering.

❌ not completed: Malformed email entries after null filtering

