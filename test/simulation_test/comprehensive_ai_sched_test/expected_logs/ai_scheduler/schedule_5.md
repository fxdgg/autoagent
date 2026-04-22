# AI Scheduler — Round 5

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
    Current Round: 5 / 10

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
            Last Result: See logs/<SESSION>/task_results/result_1.txt
        - Task 2: Looping comprehensive coverage | Type: looping | Executed: 1 time(s)
            Description:
                Comprehensive looping task testing all prompt-building paths.
            Last Result: See logs/<SESSION>/task_results/result_2.txt
        - Task 3: Nested edge case coverage | Type: nested | Executed: 1 time(s)
            Description:
                Nested task testing edge cases with long_running subtasks.
            Last Result: See logs/<SESSION>/task_results/result_3.txt
        - Task 4: Looping max attempts exhaustion | Type: looping | Executed: 1 time(s)
            Description:
                Looping task testing max_attempts exhaustion with long_running subtask.
            Last Result: See logs/<SESSION>/task_results/result_4.txt
        - Task 5: Nested invalid JSON fallback coverage | Type: nested | Executed: 0 time(s)
            Description:
                Nested task testing invalid JSON fallback handling.
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

    <schedule_history> (last 10 rounds)
        ✅ 1. (Nested comprehensive coverage)
            Reasoning: Sequential execution order
        ✅ 2. (Looping comprehensive coverage)
            Reasoning: Sequential execution order
        ✅ 3. (Nested edge case coverage)
            Reasoning: Sequential execution order
        ❌ 4. (Looping max attempts exhaustion)
            Reasoning: Sequential execution order
    </schedule_history>

    NOTE: Only the last 10 rounds are shown above. For the complete scheduling history, read: logs/<SESSION>/schedule_history.txt
</context>
```

## Response

{"action": "execute", "task_id": 5, "reasoning": "Sequential execution order"}

