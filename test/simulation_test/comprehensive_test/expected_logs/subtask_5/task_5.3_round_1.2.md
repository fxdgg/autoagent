# Task 5.3: Verify fallback output — Round 1.2

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
        Verify fallback output
    </task_name>

    <completion_criteria>
        Verification completed successfully.
    </completion_criteria>

    <initial_hint>
        Verify the transformed output.
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
        5.1. Prepare fallback scenario
          5.2. Run fragile transformation
        → 5.3. Verify fallback output

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result (5.2)>
        I corrected the normalization map and re-ran the transformation:
        - added region fallback = "unknown"
        - regenerated transformed_payload.json
        - validated 500/500 records against the target schema

        ✅ completed
    </previous_step_result>
</context>
```

## Response

Verification succeeded:
- transformed_payload.json matches the schema
- fallback_audit.log contains the 17 corrected records
- no unexpected null fields remain

✅ completed

