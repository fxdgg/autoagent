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
    Current Round: 6 / 10

    <project_description>
        Round-scoped description for task 5: validates that the AI scheduler correctly selects description@5 over the root-level description.
    </project_description>

    <scheduling_strategy>
        Analyze task dependencies and results to determine optimal execution order.
        Prioritize setup tasks first, then processing, then validation.
    </scheduling_strategy>

    <stop_condition>
        All critical tasks (1, 3, 4, 5) have been executed successfully.
    </stop_condition>

    <available_tasks>
        - Task 1: Initialize environment | Type: simple | Executed: 2 time(s)
            Description:
                Set up the project environment and install all dependencies.
            Last Result: See logs/<SESSION>/task_results/result_1.txt
        - Task 2: Run baseline benchmark | Type: simple | Executed: 1 time(s)
            Description:
                Execute the baseline performance benchmark.
            Last Result: See <PROJECT_ROOT>/result_files/result_2.txt (NOTFOUND)
        - Task 3: Optimize core algorithm | Type: simple | Executed: 1 time(s)
            Description:
                Apply optimization to the core algorithm based on benchmark results.
            Last Result: See <PROJECT_ROOT>/result_files/result_3.txt
        - Task 4: Integration validation | Type: nested | Executed: 1 time(s)
            Description:
                Run integration tests to validate the optimized algorithm.
        - Task 5: Generate final report | Type: simple | Executed: 0 time(s)
            Description:
                Generate the final optimization report with all results.

        IMPORTANT: If a result file is marked as NOTFOUND, it is probably
        due to task failures — the task may have crashed or errored out
        before it could write its result file. Consider re-running the
        task or running a diagnostic task to investigate.
    </available_tasks>

    <schedule_history> (last 10 rounds)
        ✅ 1. (Initialize environment)
            Reasoning: Start with environment setup as it is a prerequisite for all other tasks
        ❌ 2. (Run baseline benchmark)
            Reasoning: Run baseline benchmark now that environment is ready
        ✅ 3. (Optimize core algorithm)
            Reasoning: Task 2 failed but task 3 can proceed independently with synthetic data
        ✅ 4. (Integration validation)
            Reasoning: Run integration validation with the optimized algorithm
        ✅ 1. (Initialize environment)
            Reasoning: Re-run environment setup with updated config after optimization
    </schedule_history>

    NOTE: Only the last 10 rounds are shown above. For the complete scheduling history, read: logs/<SESSION>/schedule_history.txt
</context>
```

## Response

{"action": "execute", "task_id": 5, "reasoning": "Generate final report now that all critical tasks are done"}

