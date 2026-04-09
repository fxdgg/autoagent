# Task 5: Nested invalid JSON fallback coverage — Failure Analysis (subtask 5.2, round 1.1)

## Prompt

```
You are a failure analysis expert. Analyze the subtask failure below and decide the best retry strategy.

<failed_subtask>
    <task_name>
        Nested invalid JSON fallback coverage
    </task_name>

    <main_task_completion_criteria>
        All subtasks completed and fallback handling validated.
    </main_task_completion_criteria>

    <workflow>
        5.1. Prepare fallback scenario (COMPLETED)
                Criteria:
                    Fallback test inputs prepared.
                Summary:
                    ✅ completed
        → 5.2. Run fragile transformation (FAILED)
                Criteria:
                    Transformation completed with validated output.
          5.3. Verify fallback output
    </workflow>
</failed_subtask>

<outputs>
    <previous_step_context (5.1)>
        I prepared the fallback scenario inputs:
        - generated fragile_input.json
        - recorded baseline schema expectations
        - enabled fallback audit logging

        ✅ completed
    </previous_step_context>

    <failed_subtask_output (5.2)>
        I ran the fragile transformation and it failed:

        Error: TransformSpecError - the normalization map omitted the "region"
        field for 17 records, so the output payload does not satisfy the target
        schema. The mapping logic needs a targeted correction.

        ❌ not completed: Missing region field in normalized payload
    </failed_subtask_output>

    <failed_subtask_attempt_history (5.2)>
        - Attempt 1: not_completed
            Detail: ❌ not completed: Missing region field in normalized payload
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
    - Available subtask IDs: ['5.1', '5.2', '5.3']
</instructions>
```

