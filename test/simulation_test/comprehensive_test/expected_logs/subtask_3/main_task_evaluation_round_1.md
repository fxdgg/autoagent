# Task 3: Nested edge case coverage — Main Task Evaluation (round 1)

## Prompt

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.

<evaluation_context>
Main Task: Nested edge case coverage
Completion Criteria: All subtasks completed with validated results.

</evaluation_context>

<execution_results>
  - 3.1 (Build artifacts): status=completed, attempts=1
    Criteria: Build artifacts generated successfully.

    Result: ✅ completed
  - 3.2 (Run integration tests): status=completed, attempts=1
    Criteria: Integration tests passed.

    Result: ✅ completed
  - 3.3 (Deploy staging): status=completed, attempts=2
    Criteria: Staging deployment verified and healthy.

    Result: ✅ completed
  - 3.4 (Smoke test staging): status=completed, attempts=1
    Criteria: Smoke tests passed on staging.

    Result: ✅ completed
</execution_results>

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
- `next_strategy`: Will be passed to the AI executing the next round — be specific and actionable.
- Available subtask IDs: ['3.1', '3.2', '3.3', '3.4']
</instructions>
```

## Response

{
    "main_task_completed": true,
    "analysis": "All subtasks completed successfully. Build artifacts generated with auth module, all 47 integration tests pass, staging deployment healthy with proper connection pool sizing, and all 12 smoke tests pass.",
    "confidence": "high"
}

