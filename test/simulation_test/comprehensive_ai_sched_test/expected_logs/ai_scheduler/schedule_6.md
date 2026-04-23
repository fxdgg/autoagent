# AI Scheduler — Round 6

## System Prompt

```
You are an AI task scheduler. Your job is to decide which task to execute next, or whether to stop execution.

You must respond with a JSON object in one of these formats:
1. Execute a task: {"action": "execute", "task_id": <id>, "reasoning": "<why>"}
2. Stop execution: {"action": "stop", "reasoning": "<why>"}

You must choose exactly ONE task per round.
```

## Prompt

```
<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <scheduling_strategy>
        Execute tasks sequentially.
    </scheduling_strategy>

    <stop_condition>
        All tasks completed.
    </stop_condition>

    <available_tasks>
        - Task 1: Nested comprehensive coverage | Type: nested | Executed: 1 time(s)
            Description:
                Comprehensive nested task testing all prompt-building paths.
            Last Result:
                1. logs/<SESSION>/task_results/result_1.txt
                Preview:
                    git commit -m "perf: optimize pipeline - 43.75% throughput, 57.1% latency gain (median of 3 runs)"
                    
                    Results committed successfully.
                    
                    ✅ completed
        - Task 2: Looping comprehensive coverage | Type: looping | Executed: 1 time(s)
            Description:
                Comprehensive looping task testing all prompt-building paths.
            Last Result:
                1. logs/<SESSION>/task_results/result_2.txt
                Preview:
                    - No duplicate records found
                    
                    Both iterations completed successfully.
                    
                    ✅ completed
        - Task 3: Nested edge case coverage | Type: nested | Executed: 1 time(s)
            Description:
                Nested task testing edge cases with long_running subtasks.
            Last Result:
                1. logs/<SESSION>/task_results/result_3.txt
                Preview:
                    - Webhook integration: PASS
                    
                    Staging environment fully validated.
                    
                    ✅ completed
        - Task 4: Looping max attempts exhaustion | Type: looping | Executed: 1 time(s)
            Description:
                Looping task testing max_attempts exhaustion with long_running subtask.
            Last Result:
                1. logs/<SESSION>/task_results/result_4.txt
                Preview:
                    Error: Chart 7 (quarterly comparison) shows negative growth for Q4
                    but the raw data shows positive growth. The chart generation script
                    has a sign error in the YoY comparison formula.
                    
                    ❌ not completed: Chart 7 YoY comparison has sign error
        - Task 5: Nested invalid JSON fallback coverage | Type: nested | Executed: 1 time(s)
            Description:
                Nested task testing invalid JSON fallback handling.
            Last Result:
                1. logs/<SESSION>/task_results/result_5.txt
                Preview:
                    - transformed_payload_round2.json matches the schema
                    - fallback_audit.log contains only expected corrections
                    - regression checks all passed
                    
                    ✅ completed
        - Task 6: Prompt truncation coverage | Type: nested | Executed: 0 time(s)
            Description:
                Nested task testing prompt truncation with oversized context.
        - Task 7: Round-scoped description validation | Type: simple | Executed: 0 time(s)
            Description:
                Simple task testing round-scoped description selection.

        IMPORTANT: If a result file is marked as NOTFOUND, it is probably
        due to task failures — the task may have crashed or errored out
        before it could write its result file. Consider re-running the
        task or running a diagnostic task to investigate.
    </available_tasks>

    <schedule_history> (last 10 rounds, most recent call last)
        Task 1 | Nested comprehensive coverage | COMPLETED
        Task 2 | Looping comprehensive coverage | COMPLETED
        Task 3 | Nested edge case coverage | COMPLETED
        Task 4 | Looping max attempts exhaustion | FAILED
        Task 5 | Nested invalid JSON fallback coverage | COMPLETED
    </schedule_history>
</context>
```

## Response

{"action": "execute", "task_id": 6, "reasoning": "Sequential execution order"}

