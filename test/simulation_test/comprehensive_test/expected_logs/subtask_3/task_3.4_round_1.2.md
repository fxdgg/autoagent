# Task 3.4: Smoke test staging — Round 1.2

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes (compilation, benchmarking, profiling, training, etc.), 
    you MUST use autoagent-exec instead of running it directly in Bash:
      "<autoagent-exec>" "<your entire command>"
    Always wrap the command in double quotes so that shell operators are passed correctly.
    When autoagent-exec prints "TASK SUBMITTED", output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
    NEVER run long commands directly in Bash — the session may be killed due to timeout, wasting time or leaving the project in broken state.
    
    3. When you are done, end your response with EXACTLY one of:
      ✅ completed
      ❌ not completed: <reason>
      ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED")
</instructions>
```

## Prompt

```
You are an AI coding agent. You can read/write files, run shell commands, and analyze outputs. Complete the following task.


<task>
    <task_name>
        Smoke test staging
    </task_name>

    <completion_criteria>
        Smoke tests passed on staging.
    </completion_criteria>

    <initial_hint>
        Run smoke tests against the staging deployment.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        All subtasks completed with validated results.
    </subtask_goal>

    <workflow>
        3.1. Build artifacts
          3.2. Run integration tests
          3.3. Deploy staging
        → 3.4. Smoke test staging

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result (3.3)>
        Redeployment completed and health checks pass:

        - All 5 pods running
        - Health endpoint: 200 OK
        - Average response time: 45ms
        - Database connections: 12/50 active

        Staging environment is healthy.

        ✅ completed
    </previous_step_result>
</context>
```

## Response

I ran the smoke tests against staging:

All 12 smoke tests passed:
- Login flow: PASS
- Data CRUD operations: PASS
- File upload/download: PASS
- Search functionality: PASS
- Webhook integration: PASS

Staging environment fully validated.

✅ completed

