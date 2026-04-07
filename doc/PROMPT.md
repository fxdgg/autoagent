# AutoAgent 提示词构建文档 (PROMPT.md)

本文档总结了 AutoAgent 中使用的所有核心提示词（Prompt）的构建方式。提示词中的可变部分使用 `<xxx>` 标识。

## 1. 共享组件 (Shared Components)

### 1.1 系统提示词前缀 (System Prompt Prefix)
用户可以在 `config.yaml` 或任务定义中配置 `system_prompt_prefix`，用于自定义 AI 的角色或添加特定指令。
如果配置了该前缀，它会被放置在用户提示词的最前面：
```
<system_prompt_prefix>

<user_prompt>
```

### 1.2 编码代理系统指令 (Coding Agent System Instructions)
对于执行代码任务的 AI，会附加以下状态标记和长任务执行指令（如果模型不支持原生 system prompt，则作为普通 prompt 附加）：
```
## Status Markers
When you finish a task, you MUST end your response with EXACTLY one of these status lines (on its own line):
  ✅ completed
  ❌ not completed: <reason>

If a task requires a long-running command (e.g. compilation, benchmarking), use the `autoagent-exec` launcher instead of running it directly in Bash. When the launcher prints "TASK SUBMITTED", output:
  ⏳ LONG_RUNNING_IN_PROGRESS

These markers are MANDATORY. Your response MUST end with one of them.

## Note on long-running commands
If a Bash command may take more than a few minutes (e.g. compilation, benchmarking, profiling), do NOT run it directly in Bash. Instead use the `autoagent-exec` launcher:
  "<exec_script_path>" "<your entire command>"
Always wrap your command in double quotes so that shell operators (&&, |, ;, etc.) are passed correctly. For example:
  "<exec_script_path>" "cd build && cmake .. && make -j8"
The launcher will auto-detach after the fast-run window and print "TASK SUBMITTED". When you see that, output: ⏳ LONG_RUNNING_IN_PROGRESS

## ⚠️ IMPORTANT
1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or end your response with prompts like "What would you like to do?" or "Should I proceed?" — just do the work.
2. You MUST always use autoagent-exec for long-running commands. Running them directly in Bash will cause the session to hang and be killed. Even if autoagent-exec fails, fix the command arguments and retry with autoagent-exec — NEVER fall back to running directly in Bash.
```

## 2. 任务执行提示词 (Task Execution Prompts)

### 2.1 简单任务执行 (Simple Task)
用于 `simple` 和 `simple_once` 任务的执行。

```
<system_prompt_prefix>

<task>
Task: <task_name>
Completion Criteria: <completion_criteria>
Initial Hint: <initial_hint>
</task>

<context>
Project Description: <project_description>

Subtask Goal: <main_task_criteria>

This task is part of a larger workflow:
  <sibling_subtasks_list>

<previous_step_id_context>
<previous_subtask_summary>
</previous_step_id_context>
</context>

<previous_attempts>
<previous_attempt_output>
<previous_attempt_output_text>
</previous_attempt_output>

Previous Attempts:
  - Attempt <attempt_num>: <result_str>
    <Error/Summary>: <error_or_summary_text>

Please analyze what went wrong and try a different approach.
</previous_attempts>

<guidance_from_previous_failure>
**AI Analysis from previous failure:**
<suggested_fix>

Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>

<constraints>
**⏰ TIMEOUT WARNING:** The previous session was terminated because no new output was produced for an extended period. If your task involves a long-running command, remember to use `autoagent-exec` (see system instructions).
</constraints>
```
*(注：Context、Previous Attempts、Guidance、Constraints 等部分根据实际情况条件渲染)*

### 2.2 长时间任务启动 (Long Running Task Launch)
用于 `long_running` 和 `long_running_once` 任务的启动。

```
<system_prompt_prefix>

<task>
Task: <task_name>
Completion Criteria: <completion_criteria>
Initial Hint: <initial_hint>
</task>

<context>
Project Description: <project_description>

Subtask Goal: <main_task_criteria>

This task is part of a larger workflow:
  <sibling_subtasks_list>

<previous_step_id_context>
<previous_subtask_summary>
</previous_step_id_context>
</context>

<previous_attempts>
Previous Attempts:
  - Attempt <attempt_num>: <result_str>
    <Error/Summary>: <error_or_summary_text>

The previous attempt failed. Please analyze what went wrong and adjust your command or approach.
</previous_attempts>

<guidance_from_previous_failure>
**AI Analysis from previous failure:**
<suggested_fix>

Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>

<constraints>
**⚠️ Long-Running Task:** You MUST use `autoagent-exec` to run your command. Do NOT run it directly in Bash. Example:
  "<exec_script_path>" "cd build && cmake .. && make -j8"
See system instructions for full details.
</constraints>
```

### 2.3 长时间任务结果分析 (Long Running Task Analysis)
当长时间任务完成后，让 AI 分析日志输出。

```
<system_prompt_prefix>

You previously launched this task using autoagent-exec:
  <command_line>
The task has now finished. Output has been saved to:
  <output_log_display>
```

## 3. 任务评估与分析提示词 (Evaluation & Analysis Prompts)

### 3.1 子任务失败分析 (Failure Analysis)
用于 `nested` 和 `looping` 任务中子任务失败时的分析。

```
You are a failure analysis expert. Analyze the subtask failure below and decide the best retry strategy.

<failed_subtask>
Main Task: <main_task_name>
Completion Criteria: <main_task_completion_criteria>
Loop Progress: iteration <loop_idx>/<repeat_count>

Failed Subtask:
  ID: <failed_id>
  Name: <failed_subtask_name>
  Type: <failed_subtask_type>
  Completion Criteria: <failed_subtask_completion_criteria>
</failed_subtask>

<previous_step_id_context>
<previous_context>
</previous_step_id_context>

<failed_subtask_output>
<error_text>
</failed_subtask_output>

<failed_subtask_attempt_history>
<failed_subtask_history>
</failed_subtask_attempt_history>

<all_subtasks_status>
<task_history_text>
</all_subtasks_status>

<previous_failure_analyses>
<prev_decisions_text>
</previous_failure_analyses>

<instructions>
⚠️ Do NOT suggest the same fix that was already tried. Try a fundamentally different approach.

Respond with a JSON object:
{
    "analysis": "Why the failure occurred and why retry from the chosen subtask",
    "retry_from": "<subtask_id>",
    "suggested_fix": "Specific, actionable fix for the retried subtask"
}

- `retry_from`: The failed subtask itself, or an earlier one if the root cause is there.
- `suggested_fix`: Will be shown to the AI executing the retry — be specific.
- Available subtask IDs: [<available_ids>]
</instructions>
```

### 3.2 主任务完成评估 (Main Task Evaluation)
在所有子任务完成后，评估主任务是否达成。

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.

<evaluation_context>
Main Task: <main_task_name>
Completion Criteria: <main_task_completion_criteria>
</evaluation_context>

<execution_results>
<execution_results_text>
</execution_results>

<previous_evaluations>
<prev_eval_section>
</previous_evaluations>

<instructions>
Evaluate whether ALL completion criteria are met based on the execution results above.

Respond with a JSON object:
{
    "main_task_completed": true/false,
    "analysis": "Detailed analysis of results vs each criterion",
    "retry_from": "<subtask_id>",
    "next_strategy": "What to do differently in the next round"
}

- `retry_from` and `next_strategy`: Only required when `main_task_completed` is false.
- `next_strategy`: Will be passed to the AI executing the next round — be specific and actionable.
- Available subtask IDs: [<available_ids>]
</instructions>
```

## 4. 任务分解与审查提示词 (Ideas Decomposition & Review Prompts)

### 4.1 想法分解 (Ideas Decompose)
将 `ideas.md` 中的想法分解为 YAML 任务。

```
You are a task planner. Your job is to decompose a given idea into concrete, actionable
TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

<idea>
<idea_content>
</idea>

The following guide describes how AutoAgent executes tasks at runtime. Understanding
this is essential for designing effective tasks. Read it carefully before generating
your task decomposition.

<task_design_guide>
<task_design_guide_content>
</task_design_guide>

<output_instructions>
- Task IDs start from **<next_id>** (integer for top-level, dot notation for subtasks,
  e.g., <next_id>.1, <next_id>.2).
- Write ONLY valid YAML into the following file:
    <temp_tasks_path>
- Do NOT include markdown code fences or any extra text in the file.
- The file content must be a YAML dictionary containing a `description` string and a `tasks` list.

### Output Examples
... (示例内容)
</output_instructions>
```

### 4.2 任务审查 (Ideas Review)
审查生成的 YAML 任务。

```
You are a task review expert. Review the following TODO task decomposition
for quality, completeness, and correctness.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs.

<original_idea>
<idea_content>
</original_idea>

<generated_tasks_yaml>
```yaml
<tasks_yaml>
```
</generated_tasks_yaml>

The following guide describes how AutoAgent executes tasks at runtime. Use it as
the authoritative reference for task types, schema, hierarchy rules, and best
practices when reviewing the generated tasks.

<task_design_guide>
<task_design_guide_content>
</task_design_guide>

<review_criteria>
... (审查标准)
</review_criteria>

<instructions>
If the tasks pass ALL criteria, respond with EXACTLY:
✅ completed

If the tasks need improvement:
1. DIRECTLY modify the YAML file at:
     <temp_tasks_path>
   Write the corrected full task list into that file.
   Do NOT include markdown code fences or any extra text in the file.
2. After modifying the file, respond with: ❌ not completed
</instructions>
```

### 4.3 任务修订 (Revision Prompt)
在人工反馈后，要求 AI 重新修订任务。

```
<updated_tasks_edited_by_human>
```yaml
<current_tasks_yaml>
```
</updated_tasks_edited_by_human>

<human_feedback>
<human_feedback>
</human_feedback>

<instructions>
Please revise the task decomposition based on the information above.
Write ONLY valid YAML (a dictionary containing a `description` string and a `tasks` list) into the following file:
  <temp_tasks_path>

Do NOT include markdown code fences or any extra text in the file.
</instructions>
```

## 5. 状态标记提醒提示词 (Marker Nudge Prompt)

### 5.1 状态标记提醒 (Marker Nudge)
当 AI 完成了工作但忘记输出完成状态标记时，会在同一会话中发送此轻量级提醒，而不是重置并重试整个任务。

```
Your previous response did not end with a status marker (possibly due to an unexpected interruption).
Review what you have done so far against the completion criteria. You may read files or run commands to verify.

CRITICAL: Do NOT re-run any command you have already executed. In particular, NEVER call autoagent-exec again — if you already called it (regardless of what output you saw), the background task is already running. Just reply with: ⏳ LONG_RUNNING_IN_PROGRESS

If the task is not yet finished and you did NOT use autoagent-exec, continue working on it until it is done (or you are sure it cannot be completed).
When you are done, end your response with EXACTLY one of:
  ✅ completed
  ❌ not completed: <reason>
  ⏳ LONG_RUNNING_IN_PROGRESS
```