# Task 3: Nested edge case coverage — Failure Analysis (subtask 3.2, round 1.1)

## Prompt

```
You are a failure analysis expert. Analyze the subtask failure below and decide the best retry strategy.

<failed_subtask>
    <task_name>
        Nested edge case coverage
    </task_name>

    <main_task_completion_criteria>
        All subtasks completed with validated results.
    </main_task_completion_criteria>

    <workflow>
        3.1. Build artifacts (COMPLETED)
                Criteria:
                    Build artifacts generated successfully.
                Summary:
                    ✅ completed
        → 3.2. Run integration tests (FAILED)
                Criteria:
                    Integration tests passed.
          3.3. Deploy staging
          3.4. Smoke test staging
    </workflow>
</failed_subtask>

<outputs>
    <previous_step_context (3.1)>
        The build pipeline completed successfully.

        Artifacts generated:
        - app.wasm (12MB)
        - app.js (340KB)
        - sourcemaps/

        All compilation checks passed. Zero warnings.

        ✅ completed
    </previous_step_context>

    <failed_subtask_output (3.2)>
        I ran the integration tests but 3 of 47 tests failed:

        FAIL: test_auth_flow - Expected 200, got 401
        FAIL: test_data_sync - Timeout after 30s
        FAIL: test_webhook_delivery - Missing signature header

        ❌ not completed: 3 integration tests failed
    </failed_subtask_output>

    <failed_subtask_attempt_history (3.2)>
        - Attempt 1: not_completed
            Detail: ❌ not completed: 3 integration tests failed
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
    - Available subtask IDs: ['3.1', '3.2', '3.3', '3.4']
</instructions>
```

## Response

{
    "analysis": "Integration tests failed because the build artifacts were compiled without the auth module enabled. The build config needs AUTH_ENABLED=true.",
    "retry_from": "3.1",
    "reasoning": "The build step needs to be re-run with correct flags, then tests re-run.",
    "suggested_fix": "Re-run the build with AUTH_ENABLED=true in the build configuration and add a type coercion step for the auth token fields.",
    "confidence": "high"
}

