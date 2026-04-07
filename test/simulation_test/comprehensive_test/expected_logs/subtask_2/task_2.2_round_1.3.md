# Task 2.2: Process data — Round 1.3

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
  "D:/silasshen/autoagent/autoagent/test/simulation_test/logs/comprehensive_test_jpzxj717/scripts/autoagent-exec.bat" "<your entire command>"
Always wrap your command in double quotes so that shell operators (&&, |, ;, etc.) are passed correctly. For example:
  "D:/silasshen/autoagent/autoagent/test/simulation_test/logs/comprehensive_test_jpzxj717/scripts/autoagent-exec.bat" "cd build && cmake .. && make -j8"
The launcher will auto-detach after the fast-run window and print "TASK SUBMITTED". When you see that, output: ⏳ LONG_RUNNING_IN_PROGRESS

## ⚠️ IMPORTANT
1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or end your response with prompts like "What would you like to do?" or "Should I proceed?" — just do the work.
2. You MUST always use autoagent-exec for long-running commands. Running them directly in Bash will cause the session to hang and be killed. Even if autoagent-exec fails, fix the command arguments and retry with autoagent-exec — NEVER fall back to running directly in Bash.
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
    </workflow>
</context>

<guidance_from_previous_failure>
    Add email validation regex to the preprocessing filter alongside the null handling. Use re.match(r'^[^@]+@[^@]+\.[^@]+$', email) and drop records that fail validation.

    Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>
```

## Response

I added both null handling and email validation:
- Filtered 342 null user_id records
- Filtered 89 malformed email records
- Processing completed on 4569 valid records

Output: iteration_1_results.csv with 4569 records.

✅ completed

