# Task 4: Looping max attempts exhaustion — Looping Failure Analysis (subtask 4.2, round 1.1)

## Prompt

```
You are a failure analysis expert. Analyze the subtask failure below and decide the best retry strategy.
DO NOT modifying source code, tests, configs, data, generated files, etc.

<failed_subtask>
    <task_name>
        Looping max attempts exhaustion
    </task_name>

    <main_task_completion_criteria>
        Both iterations completed with passing validation.
    </main_task_completion_criteria>

    <workflow>
        4.1. Generate report (✅ completed)
                Criteria:
                    Report generated with correct data.
        → 4.2. Validate report (❌ not completed)
                Criteria:
                    Report validation passed.
    </workflow>
</failed_subtask>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>
</context>

<outputs>
    <previous_step_context (4.1)>
        Report generation completed:

        - report_q1.pdf (45 pages)
        - report_data.json (raw data)
        - charts/ (12 PNG files)

        All data sources queried successfully. 50,000 records processed.

        ✅ completed
    </previous_step_context>

    <failed_subtask_output (4.2)>
        I validated the report but found discrepancies:

        Error: Revenue figures in Section 3 don't match the raw data.
        Expected total: $1,234,567 but report shows $1,234,000.
        The rounding in the aggregation query is dropping cents.

        ❌ not completed: Revenue figures mismatch due to rounding error
    </failed_subtask_output>

    <failed_subtask_attempt_history (4.2)>
        - Attempt 1: not_completed
            Detail: ❌ not completed: Revenue figures mismatch due to rounding error
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
    - `suggested_fix`: Will be shown to the AI executing the retry - be specific.
    - Available subtask IDs: ['4.1', '4.2']
</instructions>
```

## Response

{
    "analysis": "Report validation failed because the revenue aggregation query rounds to nearest thousand instead of keeping cent precision. The report generation needs to use DECIMAL type instead of INTEGER for monetary values.",
    "retry_from": "4.1",
    "reasoning": "The report generation step needs to be re-run with correct precision settings.",
    "suggested_fix": "Update the SQL aggregation to use CAST(SUM(amount) AS DECIMAL(12,2)) instead of CAST(SUM(amount) AS INTEGER) in the revenue report query."
}

