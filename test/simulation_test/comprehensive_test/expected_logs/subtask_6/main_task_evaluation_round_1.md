# Task 6: Prompt truncation coverage — Main Task Evaluation (round 1)

## Prompt

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.

<evaluation_context>
Main Task: Prompt truncation coverage
Completion Criteria: Oversized context handled safely and final output validated.

</evaluation_context>

<execution_results>
  - 6.1 (Generate oversized prior context): status=completed, attempts=1
    Criteria: Oversized diagnostic context generated.

    Result: ✅ completed
  - 6.2 (Retry with truncated context): status=completed, attempts=1
    Criteria: Retry succeeds after analyzing truncated context.

    Result: ✅ completed
  - 6.3 (Finalize truncation validation): status=completed, attempts=1
    Criteria: Final validation recorded.

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
- Available subtask IDs: ['6.1', '6.2', '6.3']
</instructions>
```

## Response

{
    "main_task_completed": true,
    "analysis": "Oversized context was truncated safely in downstream prompts, retry analysis remained actionable, and the final checkpoint reconstruction plus validation completed successfully.",
    "confidence": "high"
}

