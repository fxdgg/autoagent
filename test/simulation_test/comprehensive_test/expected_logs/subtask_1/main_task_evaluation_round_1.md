# Task 1: Nested comprehensive coverage — Main Task Evaluation (round 1)

## Prompt

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.

<evaluation_context>
Main Task: Nested comprehensive coverage
Completion Criteria: All subtasks completed with optimized performance.
Processing pipeline produces correct output.

</evaluation_context>

<execution_results>
  - 1.1 (One-time environment setup): status=completed, attempts=1
    Criteria: Environment configured and dependencies installed.

    Result: ✅ completed
  - 1.2 (One-time data preparation): status=completed, attempts=1
    Criteria: Data pipeline executed, output files generated.

    Result: ✅ completed
  - 1.3 (Core processing): status=completed, attempts=1
    Criteria: Processing completed with correct output.

    Result: ✅ completed
  - 1.4 (Benchmark and validate): status=completed, attempts=1
    Criteria: Benchmark results recorded and correctness validated.

    Result: ✅ completed
  - 1.5 (Commit results): status=completed, attempts=1
    Criteria: Results committed to git.

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
- Available subtask IDs: ['1.1', '1.2', '1.3', '1.4', '1.5']
</instructions>
```

## Response

{
    "main_task_completed": false,
    "analysis": "All subtasks completed but the throughput improvement of 50% may not be reliable. The benchmark was run only once and results may vary. Need to run at least 3 iterations and report the median.",
    "retry_from": "1.3",
    "next_strategy": "Re-run processing with 3 benchmark iterations and report median throughput. Also add p95 latency metric.",
    "suggested_improvements": ["Run 3 benchmark iterations", "Add p95 latency metric"],
    "confidence": "medium"
}

