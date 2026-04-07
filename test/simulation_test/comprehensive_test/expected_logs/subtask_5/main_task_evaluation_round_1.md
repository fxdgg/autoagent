# Task 5: Nested invalid JSON fallback coverage — Main Task Evaluation (round 1)

## Prompt

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.

<evaluation_context>
Main Task: Nested invalid JSON fallback coverage
Completion Criteria: All subtasks completed and fallback handling validated.

</evaluation_context>

<execution_results>
  - 5.1 (Prepare fallback scenario): status=completed, attempts=1
    Criteria: Fallback test inputs prepared.

    Result: ✅ completed
  - 5.2 (Run fragile transformation): status=completed, attempts=1
    Criteria: Transformation completed with validated output.

    Result: ✅ completed
  - 5.3 (Verify fallback output): status=completed, attempts=1
    Criteria: Verification completed successfully.

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
- Available subtask IDs: ['5.1', '5.2', '5.3']
</instructions>
```

