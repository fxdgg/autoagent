# Task 2: Looping comprehensive coverage — Looping Failure Analysis (subtask 2.2, round 1.1)

## Prompt

```
You are a failure analysis expert. Analyze the subtask failure below and decide the best retry strategy.

<failed_subtask>
    <task_name>
        Looping comprehensive coverage
    </task_name>

    <main_task_completion_criteria>
        Both iterations completed successfully with correct output.
    </main_task_completion_criteria>

    <workflow>
        2.1. Iteration setup (COMPLETED)
                Criteria:
                    Setup completed for this iteration.
                Summary:
                    ✅ completed
        → 2.2. Process data (FAILED)
                Criteria:
                    Data processed correctly.
          2.3. Verify output
    </workflow>
</failed_subtask>

<outputs>
    <previous_step_context (2.1)>
        I initialized the iteration environment:
        - Created working directory for iteration 1
        - Loaded configuration from config.yaml
        - Connected to data source

        ✅ completed
    </previous_step_context>

    <failed_subtask_output (2.2)>
        I attempted to process the data but encountered an error:

        Error: DataFormatError - input records contain null values in
        required field 'user_id'. 342 of 5000 records affected.

        The null values need to be handled before processing.

        ❌ not completed: Null values in required field 'user_id'
    </failed_subtask_output>

    <failed_subtask_attempt_history (2.2)>
        - Attempt 1: not_completed
            Detail: ❌ not completed: Null values in required field 'user_id'
    </failed_subtask_attempt_history>
</outputs>

<instructions>
    ⚠️ Do NOT suggest the same fix that was already tried. Try a fundamentally different approach.

    Respond with a JSON object:
    ```json
    {
        "analysis": "Why the failure occurred and why retry from the chosen subtask",
        "retry_from": "<subtask_id>",
        "suggested_fix": "Specific, actionable fix for the retried subtask"
    }
    ```

    - `retry_from`: The failed subtask itself, or an earlier one if the root cause is there.
    - `suggested_fix`: Will be shown to the AI executing the retry — be specific.
    - Available subtask IDs: ['2.1', '2.2', '2.3']
</instructions>
```

## Response

{
    "analysis": "Subtask 2.2 failed because the input data contains null values in the user_id field. This needs a preprocessing step to filter or impute null values.",
    "retry_from": "2.1",
    "reasoning": "Retrying from setup to add a null-handling configuration.",
    "suggested_fix": "Add null_handling='drop' parameter to the processing config, or add a preprocessing filter that removes records with null user_id before the main processing step.",
    "confidence": "high"
}

