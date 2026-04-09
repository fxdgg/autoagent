# Task 2.3: Verify output — Round 1.3

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
        Verify output
    </task_name>

    <completion_criteria>
        Output verified and saved.
    </completion_criteria>

    <initial_hint>
        Run verification on the output.
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
          2.2. Process data
        → 2.3. Verify output

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result (2.2)>
        I added both null handling and email validation:
        - Filtered 342 null user_id records
        - Filtered 89 malformed email records
        - Processing completed on 4569 valid records

        Output: iteration_1_results.csv with 4569 records.

        ✅ completed
    </previous_step_result>
</context>
```

## Response

Verification of iteration 1 output:
- Record count: 4569 (matches processed count)
- Data integrity: all checksums valid
- Output format: correct schema
- No duplicate records found

Iteration 1 complete.

✅ completed

