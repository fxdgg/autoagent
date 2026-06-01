# Task 3.2: Run integration tests — Round 1.1

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes,
    you MUST use autoagent-exec instead of running it directly in Bash (which may cause **session timeout**):
      "<autoagent-exec>" "<your entire command>"
    Always wrap the command in double quotes so that shell operators are passed correctly.
    
    How does this work:
    You are SUBMITTING the command to the background, instead of executing commands using autoagent-exec.
    So DO NOT manually wait for the command to finish —— Just output ⏳ LONG_RUNNING_IN_PROGRESS after it shows "TASK SUBMITTED".
    
    autoagent-exec has three possible outcomes:
      - "TASK SUBMITTED" → the command is submitted to background. Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
      - "[OK]" → the command finished quickly with exit code 0. Continue working — treat it as a normal completed command.
      - "[FAST-FAIL]" → the command failed quickly. Read the error output, fix the issue, and retry.
    
    ⚠️ CRITICAL — No Output Redirection:
    autoagent-exec automatically captures ALL stdout/stderr to a log file.
    If you add output redirection (>, >>, 2>, &>, | tee, etc.), you may NOT see any of the three outcomes above.
    If commands in `initial_hint` already includes redirection, strip the redirection and use --stdout / --stderr instead:
      "<autoagent-exec>" --stdout build.log --stderr build_err.log "make"
    
    ⚠️ If you can't see autoagent-exec's any of the three outcomes:
    The output may have been already redirected. DO NOT run autoagent-exec again before checking the process by PID.
    Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately if it's still running.
    Check the command outputs in redirected files or "logs/<SESSION>/lr_tasks/lr_3.3.2_output.log" and continue working if it has already finished.
    DO NOT use `sleep` or any wait command in your session.
    
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
    Current task ID: 3.2

    <task_name>
        Run integration tests
    </task_name>

    <completion_criteria>
        Integration tests passed.
    </completion_criteria>

    <initial_hint>
        Execute the integration test suite.
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
        → 3.2. Run integration tests
          3.3. Deploy staging
          3.4. Smoke test staging

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result (3.1)>
        The build pipeline completed successfully.

        Artifacts generated:
        - app.wasm (12MB)
        - app.js (340KB)
        - sourcemaps/

        All compilation checks passed. Zero warnings.

        ✅ completed
    </previous_step_result>
</context>
```

## Response

I ran the integration tests but 3 of 47 tests failed:

FAIL: test_auth_flow - Expected 200, got 401
FAIL: test_data_sync - Timeout after 30s
FAIL: test_webhook_delivery - Missing signature header

❌ not completed: 3 integration tests failed

