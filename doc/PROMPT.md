# AutoAgent 提示词构建文档 (PROMPT.md)

本文档总结了 AutoAgent 中使用的所有核心提示词（Prompt）的构建方式。提示词中的可变部分使用 `[xxx]` 标识，条件渲染的 section 用 *(条件)* 标注。

**核心原则**：每个可能包含长文本的字段都用独立的 XML tag 包裹，tag 内的文本缩进一级（4 空格）。短标量字段（如 ID、名称）可以在同一行。

---

## 1. 共享组件 (Shared Components)

### 1.1 系统提示词前缀 (System Prompt Prefix)
用户可以在 `config.yaml` 或任务定义中配置 `system_prompt_prefix`，用于自定义 AI 的角色或添加特定指令。
如果配置了该前缀，它会被放置在用户提示词的最前面：
```
[system_prompt_prefix]

[user_prompt]
```

### 1.2 编码代理系统指令 (Coding Agent System Instructions)
对于执行代码任务的 AI，会附加以下状态标记和长任务执行指令（如果模型支持原生 system prompt，通过 `--append-system-prompt` 传递；否则作为普通 prompt 附加到用户 prompt 末尾）：
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
  "[exec_script_path]" "<your entire command>"
Always wrap your command in double quotes so that shell operators (&&, |, ;, etc.) are passed correctly. For example:
  "[exec_script_path]" "cd build && cmake .. && make -j8"
The launcher will auto-detach after the fast-run window and print "TASK SUBMITTED". When you see that, output: ⏳ LONG_RUNNING_IN_PROGRESS

## ⚠️ IMPORTANT
1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or end your response with prompts like "What would you like to do?" or "Should I proceed?" — just do the work.
2. You MUST always use autoagent-exec for long-running commands. Running them directly in Bash will cause the session to hang and be killed. Even if autoagent-exec fails, fix the command arguments and retry with autoagent-exec — NEVER fall back to running directly in Bash.
```

---

## 2. 任务执行提示词 (Task Execution Prompts)

### 2.1 简单任务执行 (Simple Task)
用于 `simple` 和 `simple_once` 子任务的执行。

```
[system_prompt_prefix]

<task>
    <task_name>
        [task_name]
    </task_name>

    <completion_criteria>
        [completion_criteria]
    </completion_criteria>

    <initial_hint>                                                  *(有 initial_hint 时)*
        [initial_hint]
    </initial_hint>
</task>

<context>                                                           *(有任何 context 内容时)*
    <project_description>                                           *(有 project_description 时)*
        [project_description]
    </project_description>

    <subtask_goal>                                                  *(作为子任务时)*
        [main_task_criteria]
    </subtask_goal>

    <workflow>                                                      *(有兄弟子任务时)*
        → [current_id]. [current_name]
          [other_id]. [other_name]
          ...
    </workflow>

    <previous_step_result ([id])>                                   *(有 previous_subtask_summary 时，注：不需要给AI提供严格正确的XML格式，关键是易于理解，直接加括号即可)*
        [previous_subtask_summary]
    </previous_step_result>
</context>

<previous_attempts>                                                 *(attempt > 1 时)*
    <previous_attempt_output>                                       *(session 被 reset 且有上次输出时)*
        [previous_attempt_output_text]
    </previous_attempt_output>

    <attempt_history>                                               *(有非 completed 的 history 时)*
        - Attempt [N]: [result_str]
            Error: [error_msg]                                      *(result=error)*
            Note: [summary]                                         *(result=interrupted)*
            Summary: [summary]                                      *(result=not_completed 且非 "cannot find")*
    </attempt_history>

    Please analyze what went wrong and try a different approach.
</previous_attempts>

<guidance_from_previous_failure>                                    *(有 suggested_fix 时)*
    [suggested_fix]

    Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>

<guidance_from_main_task_evaluator>                                 *(有 next_strategy 时)*
    The last round didn't match the subtask goal. Please take this analysis into account and try a different approach.

    [next_strategy]
</guidance_from_main_task_evaluator>

<constraints>                                                       *(有超时反馈时)*
    ⏰ TIMEOUT WARNING: The previous session was terminated because no new output was produced for an extended period. If your task involves a long-running command, remember to use `autoagent-exec` (see system instructions).
</constraints>
```

### 2.2 长时间运行任务执行 (Long-Running Task)
用于 `long_running` 和 `long_running_once` 子任务的执行。

```
[system_prompt_prefix]

<task>
    <task_name>
        [task_name]
    </task_name>

    <completion_criteria>
        [completion_criteria]
    </completion_criteria>

    <initial_hint>                                                  *(有 initial_hint 时)*
        [initial_hint]
    </initial_hint>
</task>

<context>                                                           *(有任何 context 内容时)*
    <project_description>                                           *(有 project_description 时)*
        [project_description]
    </project_description>

    <subtask_goal>                                                  *(作为子任务时)*
        [main_task_criteria]
    </subtask_goal>

    <workflow>                                                      *(有兄弟子任务时)*
        → [current_id]. [current_name]
          [other_id]. [other_name]
          ...
    </workflow>

    <previous_step_result ([id])>                                   *(有 previous_subtask_summary 时，注：不需要给AI提供严格正确的XML格式，关键是易于理解，直接加括号即可)*
        [previous_subtask_summary]
    </previous_step_result>
</context>

<previous_attempts>                                                 *(attempt > 1 时)*
    <previous_attempt_output>                                       *(session 被 reset 且有上次输出时)*
        [previous_attempt_output_text]
    </previous_attempt_output>

    <attempt_history>                                               *(有非 completed 的 history 时)*
        - Attempt [N]: [result_str]
            Error: [error_msg]                                      *(result=error)*
            Note: [summary]                                         *(result=interrupted)*
            Summary: [summary]                                      *(result=not_completed 且非 "cannot find")*
    </attempt_history>

    Please analyze what went wrong and try a different approach.    *(注：这两处原来可能不一致，现在令它们一致)*
</previous_attempts>

<guidance_from_previous_failure>                                    *(有 suggested_fix 时)*
    [suggested_fix]

    Please take this analysis into account and try a different approach.
</guidance_from_previous_failure>

<guidance_from_main_task_evaluator>                                 *(有 next_strategy 时)*
    The last round didn't match the subtask goal. Please take this analysis into account and try a different approach.

    [next_strategy]
</guidance_from_main_task_evaluator>

<constraints>
    ⏰ TIMEOUT WARNING: ...                                         *(有超时反馈时，替代下面的 reminder)*

    ⚠️ Long-Running Task: You MUST use `autoagent-exec` to run your command. Do NOT run it directly in Bash. Example:
      "[exec_script_path]" "cd build && cmake .. && make -j8"
    See system instructions for full details.                       *(无超时反馈时显示)*
</constraints>
```

### 2.3 长时间运行结果分析 (Long-Running Analysis)
任务完成后重启 AI 分析结果（在同一会话上下文中，AI 已知任务背景）：

```
You previously launched this task using autoagent-exec:
    [command_info]
The task has now finished. Output has been saved to:
    [output_log_path]
```

---

## 3. AI 决策提示词 (AI Decision Prompts)

### 3.1 失败分析 (Failure Analysis)
当子任务失败时，AI 分析原因并决定重试策略。用于 Nested 和 Looping 任务。

```
You are a failure analysis expert. Analyze the subtask failure below and decide the best retry strategy.

<failed_subtask>
    <task_name>                                                     *(注：改成task_name)*
        [task_name]
    </task_name>

    <main_task_completion_criteria>                    
        [task_completion_criteria]
    </main_task_completion_criteria>                                 *(注：loop_progress删掉，没有必要)*

    <workflow>                                                      *(注：将原来的Failed Subtask ID, Name, Type改成workflow，失败任务用FAILED标注，更加清晰)*
          [other_id]. [other_name] (COMPLETED)                       *(后面的all_subtasks_status一节也可以删除)*
                Criteria: 
                    [criteria] 
                Summary: 
                    [ai_reasoning] 
        → [current_id]. [current_name] (FAILED)                      
          [other_id]. [other_name]
          ...
    </workflow>
</failed_subtask>
 
<outputs>                                                              *(添加outputs标题)*
    <previous_step_context ([id])>                                     *(有 previous_context 时)*
        [previous_context_text]
    </previous_step_context>

    <failed_subtask_output ([id])>                                      *(有实际输出时)*
        [error_text]
    </failed_subtask_output>

    <failed_subtask_attempt_history ([id])>                              *(有 attempt history 时)*
        - Attempt [N]: [result]
            Detail: [summary_or_error]
    </failed_subtask_attempt_history>
</outputs>

<previous_failure_analyses>                                         *(有当前 round 的历史 decisions 时)*
    - Round [N]: failed at [id], retried from [id]
        Fix attempted: [suggested_fix]
</previous_failure_analyses>

<instructions>
    ⚠️ Do NOT suggest the same fix that was already tried. Try a fundamentally different approach.

    Respond with a JSON object:
    ```json
    {
        "analysis": "Why the failure occurred and why retry from the chosen subtask",
        "retry_from": "<subtask_id>",
        "suggested_fix": "Specific, actionable fix for the retried subtask"
    }
    ```

    - `retry_from`: The failed subtask itself, or an earlier one if the root cause is there.
    - `suggested_fix`: Will be shown to the AI executing the retry — be specific.
    - Available subtask IDs: [available_ids]
</instructions>
```

### 3.2 主任务评估 (Main Task Evaluation)
所有子任务完成后，AI 评估主任务是否达成目标。仅用于 Nested 任务。

```
You are a task evaluation expert. Evaluate whether the main task's completion criteria have been fully met based on the execution results.

<context>                                                           *(注：改成context)*
    <main_task>
        [task_name]
    </main_task>

    <completion_criteria>
        [task_completion_criteria]
    </completion_criteria>
</context>

<workflow>                                                      *(注：一样改成workflow)*
    [other_id]. [other_name] (COMPLETED)         
        Criteria: 
            [criteria] 
        Summary: 
            [ai_reasoning] 
    → [current_id]. [current_name]                     
    [other_id]. [other_name]
    ...
</workflow>

<previous_evaluations>                                              *(有历史评估时)*
    - Round [N]: completed/not completed
        Analysis: [analysis]
        Strategy: [next_strategy]
</previous_evaluations>

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
    - Available subtask IDs: [available_ids]
</instructions>
```

### 3.3 Marker Nudge（标记追问）
当 AI 未输出完成标记时，在同一 session 中发送轻量级追问（不重建完整 prompt）：

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

---

## 4. Ideas 处理提示词 (Ideas Processing Prompts)

### 4.1 Idea 分解 (Ideas Decompose)
将 ideas.md 中的想法分解为结构化 TODO 任务：

```
You are a task planner. Your job is to decompose a given idea into concrete, actionable TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

<idea>
    [idea_content]
</idea>

The following guide describes how AutoAgent executes tasks at runtime. Understanding this is essential for designing effective tasks. Read it carefully before generating your task decomposition.

<task_design_guide>
    [TASK_DESIGN_GUIDE.md 内容]
</task_design_guide>

<output_instructions>
    - Task IDs start from **[next_id]** (integer for top-level, dot notation for subtasks, e.g., [next_id].1, [next_id].2).
    - Write ONLY valid YAML into the following file:
        [temp_tasks_path]
    - Do NOT include markdown code fences or any extra text in the file.
    - The file content must be a YAML dictionary containing a `description` string and a `tasks` list.

    ### Output Examples
    [simple / nested / looping 示例]
</output_instructions>
```

### 4.2 任务审查 (Ideas Review)
独立 AI 审查生成的任务质量：

```
You are a task review expert. Review the following TODO task decomposition for quality, completeness, and correctness.

These tasks will be executed by an AI coding agent that can read/modify files, run shell commands, and analyze code and outputs.

<original_idea>
    [idea_content]
</original_idea>

The generated tasks have been saved to the following file:
  [temp_tasks_path]

Please read this file to review the tasks.

The following guide describes how AutoAgent executes tasks at runtime. Use it as the authoritative reference for task types, schema, hierarchy rules, and best practices when reviewing the generated tasks.

<task_design_guide>
    [TASK_DESIGN_GUIDE.md 内容]
</task_design_guide>

<review_criteria>
    1. **Schema correctness**: Does every task have the required fields for its type?
    2. **ID consistency**: Are task IDs sequential integers and subtask IDs use correct dot notation?
    3. **Type appropriateness**: Are task types chosen correctly?
    4. **Completion criteria quality**: Is every completion_criteria specific, measurable, and objectively verifiable by an AI agent?
    5. **Decomposition granularity**: Does the decomposition fully cover the idea?
    6. **YAML validity**: Is the YAML structure well-formed and parseable?
    7. **Model field**: If present, must be "default", "lite", or a direct model name string.
</review_criteria>

<instructions>
    If the tasks pass ALL criteria, respond with EXACTLY:
    ✅ completed

    If the tasks need improvement:
    1. DIRECTLY modify the YAML file at:
         [temp_tasks_path]
    2. After modifying the file, respond with: ❌ not completed
</instructions>
```

### 4.3 任务修订 (Ideas Revision)
人工反馈后的修订提示（在 reviewer 的同一 session 中）：

```
The current tasks are saved in the following file:
  [temp_tasks_path]

Please read this file to see the current tasks.

<human_feedback>                                                    *(有人工反馈时)*
    [human_feedback_text]
</human_feedback>

<instructions>
    Please revise the task decomposition based on the information above.
    Write ONLY valid YAML (a dictionary containing a `description` string and a `tasks` list) into the following file:
      [temp_tasks_path]

    Do NOT include markdown code fences or any extra text in the file.
</instructions>
```
