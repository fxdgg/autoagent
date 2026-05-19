# Task 5: Nested invalid JSON fallback coverage — Main Task Evaluation (round 1)

## Prompt

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.
DO NOT modifying source code, tests, configs, data, generated files, etc.

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <main_task>
        Nested invalid JSON fallback coverage
    </main_task>

    <completion_criteria>
        All subtasks completed and fallback handling validated.
    </completion_criteria>
</context>

<workflow>
    5.1. Prepare fallback scenario (✅ completed)
            Criteria:
                Fallback test inputs prepared.
      5.2. Run fragile transformation (✅ completed)
            Criteria:
                Transformation completed with validated output.
      5.3. Verify fallback output (✅ completed)
            Criteria:
                Verification completed successfully.
</workflow>

<instructions>
    Evaluate whether ALL completion criteria are met based on the execution results above.

    Respond with a JSON object:
    ```json
    {
        "main_task_completed": true/false,
        "analysis": "Detailed analysis of results vs each criterion",
        "retry_from": "<subtask_id>",
        "next_strategy": "What to do differently in the next round"
    }
    ```

    - `retry_from` and `next_strategy`: Only required when `main_task_completed` is false.
    - `next_strategy`: Will be passed to the AI executing the next round - be specific and actionable.
    - Available subtask IDs: ['5.1', '5.2', '5.3']
</instructions>
```

