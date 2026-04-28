# Task 5.3: Verify fallback output — Round 2.1

## System Prompt

```
<instructions>
    1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.
    
    2. For any command that may run longer than a few minutes,
    you MUST use autoagent-exec instead of running it directly in Bash (which may cause **session timeout**):
      "<autoagent-exec>" "<your entire command>"
    Always wrap the command in double quotes so that shell operators are passed correctly.
    
    How does this work:
    You are not executing commands using autoagent-exec; instead you are SUBMITTING the command to the background by using it.
    So DO NOT manually wait for the command to finish.
    
    autoagent-exec has three possible outcomes:
      - "TASK SUBMITTED" → the command is submitted to background. Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
      - "[OK]" → the command finished quickly with exit code 0. Continue working — treat it as a normal completed command.
      - "[FAST-FAIL]" → the command failed quickly. Read the error output, fix the issue, and retry.
    
    ⚠️ CRITICAL — No Output Redirection:
    autoagent-exec already captures ALL stdout/stderr to a log file automatically.
    If you add output redirection (>, >>, 2>, &>, | tee, etc.), you may NOT see any of the three outcomes above.
    If the task hint's command already includes redirection, strip the redirection and use --stdout / --stderr instead:
      "<autoagent-exec>" --stdout build.log --stderr build_err.log "make"
    
    Pass --help to autoagent-exec for further troubleshooting.
    
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
        Verify fallback output
    </task_name>

    <completion_criteria>
        Verification completed successfully.
    </completion_criteria>

    <initial_hint>
        Verify the transformed output.
    </initial_hint>
</task>

<context>
    <project_description>
        Comprehensive test project exercising all prompt-building paths for nested and looping task executors.
    </project_description>

    <subtask_goal>
        All subtasks completed and fallback handling validated.
    </subtask_goal>

    <workflow>
        5.1. Prepare fallback scenario
          5.2. Run fragile transformation
        → 5.3. Verify fallback output

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result (5.2)>
        I re-ran the transformation with the corrected mapping:
        - region fallback applied correctly
        - transformed_payload_round2.json generated
        - all 500 records passed schema validation

        ✅ completed
    </previous_step_result>
</context>
```

## Response

Round 2 verification succeeded:
- transformed_payload_round2.json matches the schema
- fallback_audit.log contains only expected corrections
- regression checks all passed

✅ completed

