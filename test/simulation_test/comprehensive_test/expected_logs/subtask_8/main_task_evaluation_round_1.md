# Task 8: Nested fatal analysis coverage — Main Task Evaluation (round 1)

## Prompt

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.
DO NOT modifying source code, tests, configs, data, generated files, etc.

<context>
    <project_description>
        Round-scoped description for task 7: validates that the orchestrator selects description@7 over the root-level description.
    </project_description>

    <main_task>
        Nested fatal analysis coverage
    </main_task>

    <completion_criteria>
        All subtasks completed after fatal recovery.
    </completion_criteria>
</context>

<workflow>
    8.1. Registry setup (✅ completed)
            Criteria:
                Registry credentials configured.
      8.2. Push container image (✅ completed)
            Criteria:
                Container image pushed to registry.
      8.3. Deploy container (✅ completed)
            Criteria:
                Container deployed and running.
</workflow>

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
    - `next_strategy`: Will be passed to the AI executing the next round - be specific and actionable.
    - Available subtask IDs: ['8.1', '8.2', '8.3']
</instructions>
```

## Response

{
    "main_task_completed": true,
    "analysis": "All subtasks completed. Registry credential issue was resolved by using service account tokens on retry. Container image pushed and deployed successfully."
}

