# Task 1.3: Core processing — Round 1.1

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
  "<autoagent-exec>" "<your entire command>"
Always wrap your command in double quotes so that shell operators (&&, |, ;, etc.) are passed correctly. For example:
  "<autoagent-exec>" "cd build && cmake .. && make -j8"
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
        Core processing
    </task_name>

    <completion_criteria>
        Processing completed with correct output.
    </completion_criteria>

    <initial_hint>
        Run the core processing pipeline.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        All subtasks completed with optimized performance.
        Processing pipeline produces correct output.
    </subtask_goal>

    <workflow>
        1.1. One-time environment setup
          1.2. One-time data preparation
        → 1.3. Core processing
          1.4. Benchmark and validate
          1.5. Commit results
    </workflow>

    <previous_step_result (1.2)>
        The data preparation pipeline completed successfully.

        Output files generated:
        - prepared_data.parquet (800MB)
        - feature_index.json
        - schema_metadata.yaml

        All data quality checks passed. 15,000 records processed.

        ✅ completed
    </previous_step_result>
</context>
```

## Response

I attempted to run the core processing pipeline but hit an error:

Error: ConfigurationError - processing parameters do not match
the prepared data schema. Field 'timestamp' expected datetime64
but got string type.

The config file needs to be updated to match the new data format.

❌ not completed: Configuration mismatch with prepared data schema

