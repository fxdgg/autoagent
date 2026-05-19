# Task 8: Nested fatal analysis coverage — Fatal Analysis (subtask 8.2, round 1.1)

## Prompt

```
You are an AI coding agent. You can read/write files, run shell commands, and analyze outputs. Complete the following task.

<task>
    <task_name>
        Fatal Analysis
    </task_name>

    <completion_criteria>
        Analyze the fatal failure and decide retry strategy.
    </completion_criteria>
</task>

<context>
    <project_description>
        Round-scoped description for task 7: validates that the orchestrator selects description@7 over the root-level description.
    </project_description>

    <workflow>
        1. Nested comprehensive coverage (✅ completed)
            Criteria:
                All subtasks completed with optimized performance.
                Processing pipeline produces correct output.
        2. Looping comprehensive coverage (✅ completed)
            Criteria:
                Both iterations completed successfully with correct output.
        3. Nested edge case coverage (✅ completed)
            Criteria:
                All subtasks completed with validated results.
        4. Looping max attempts exhaustion (❌ not completed)
            Criteria:
                Both iterations completed with passing validation.
        5. Nested invalid JSON fallback coverage (✅ completed)
            Criteria:
                All subtasks completed and fallback handling validated.
        6. Prompt truncation coverage (✅ completed)
            Criteria:
                Oversized context handled safely and final output validated.
        7. Round-scoped description validation (✅ completed)
            Criteria:
                Round-scoped description verified in prompt context.
        8. Nested fatal analysis coverage
            8.1. Registry setup (✅ completed)
                Criteria:
                    Registry credentials configured.
            8.2. Push container image (❌ FATAL: registry credentials expired, cannot push image)
                Criteria:
                    Container image pushed to registry.
            8.3. Deploy container
                Criteria:
                    Container deployed and running.
    </workflow>
</context>

<outputs>
    <failed_task_output (8.2)>
        Attempted to push container image but registry returned
        HTTP 401 Unauthorized. The registry credentials have expired
        and cannot be refreshed automatically.

        ❌ FATAL: registry credentials expired, cannot push image
    </failed_task_output>
</outputs>

<instructions>
    1. You should analyze the prerequisite failure, apply only fixes that are within this task's authority, and decide where AutoAgent should retry from.

    2. Respond with a JSON object:
    ```json
    {
        "analysis": "Why the failure occurred and why retry from the chosen task",
        "retry_from": "<task_id>",
        "suggested_fix": "Specific, actionable fix for the retried task, or empty if retry_from is `stop`"
    }
    ```

    - `retry_from`: The failed task itself, or an earlier one if the root cause is there.
      ⚠️ Choosing `stop` will end the whole AutoAgent system. Proceed with this choice
      ONLY if these failures are external blockers that cannot be resolved, or outside the user-allowed fix scope.
    - `suggested_fix`: Will be shown to the AI executing the retry - be specific.
    - Available `retry_from` IDs: ['1', '2', '3', '4', '5', '6', '7', '8.1', '8.2', '8.3', 'stop'].
</instructions>
```

## Response

{
    "analysis": "Subtask 8.2 failed because the registry credentials expired. The credentials were configured in 8.1 but have a short TTL. Retrying 8.2 with refreshed credentials should resolve the issue.",
    "retry_from": "8.2",
    "suggested_fix": "Refresh the registry credentials before pushing. Use a longer-lived token or service account credentials instead of short-lived user tokens."
}

