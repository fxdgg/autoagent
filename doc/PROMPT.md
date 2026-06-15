# AutoAgent 提示词构建文档 (PROMPT.md)

本文档总结了 AutoAgent 中使用的所有核心提示词（Prompt）的构建方式。提示词中的可变部分使用 `[xxx]` 标识，条件渲染的 section 用 *(条件)* 标注。

**核心原则**：每个可能包含长文本的字段都用独立的 XML tag 包裹，tag 内的文本缩进一级（4 空格）。短标量字段（如 ID、名称）可以在同一行。

---

## 1. 共享组件 (Shared Components)

### 1.1 系统提示词前缀 (System Prompt Prefix)
用户可以在 `config.yaml` 或任务定义中配置 `system_prompt_prefix`，用于自定义 AI 的角色或添加特定指令。
如果配置了该前缀，它会被放置在用户提示词的最前面（Continuation prompt 除外，见 §3.4）：
```
[system_prompt_prefix]

[user_prompt]
```

### 1.2 编码代理系统指令 (Coding Agent System Instructions)
对于执行代码任务的 AI，会生成编号规则列表作为系统指令（如果模型支持原生 system prompt，通过 `--append-system-prompt` 传递；否则包裹在 `<instructions>` 标签中附加到用户 prompt 末尾）：
```
1. You are fully autonomous — make all decisions independently. NEVER ask the user questions or wait for confirmation.

2. For any command that may run longer than a few minutes,   *(有 exec_script_path 时)*
you MUST use autoagent-exec instead of running it directly in Bash (which may cause **session timeout**):
  "[exec_script_path]" "<your entire command>"
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
  "[exec_script_path]" --stdout build.log --stderr build_err.log "make"

⚠️ If you can't see autoagent-exec's any of the three outcomes:
The output may have been already redirected. DO NOT run autoagent-exec again before checking the process by PID.
Output ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately if it's still running.
Check the command outputs in redirected files and continue working if it has already finished.
DO NOT use `sleep` or any wait command in your session.

3. When you are done, end your response with EXACTLY one of:
  ✅ completed
  ❌ not completed: <reason>
  ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED")
```

> **Note**: 规则编号根据 `exec_script_path` 是否存在动态调整（无 exec_script_path 时规则 2 省略，编号变为 1/2）。

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

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result ([id])>                                   *(有 previous_subtask_summary 时)*
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
    ⏰ TIMEOUT WARNING: The previous session was killed due to session timeout.
    If your task involves a long-running command, remember to use `autoagent-exec` (see system instructions).
</constraints>
```

### 2.2 长时间运行任务执行 (Long-Running Task)
用于 `long_running` 和 `long_running_once` 任务的执行。

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

        IMPORTANT: Only work on the current step (→). Do NOT perform work that belongs to later steps.
    </workflow>

    <previous_step_result ([id])>                                   *(有 previous_subtask_summary 时)*
        [previous_subtask_summary]
    </previous_step_result>
</context>

<previous_attempts>                                                 *(attempt > 1 时)*
    <attempt_history>                                               *(有非 completed 的 history 时；注：无 previous_attempt_output）*
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

<constraints>                                                       *(始终存在)*
    ⏰ TIMEOUT WARNING: The previous session was killed due to session timeout.    *(有超时反馈时，替代下面的 reminder)*
    If your task involves a long-running command, remember to use `autoagent-exec` (see system instructions).

    ⚠️ Long-Running Task: You MUST use autoagent-exec to run your command, Do NOT run it directly in Bash (see system instructions).    *(无超时反馈时显示)*
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
    <task_name>
        [task_name]                                                 *(注：是父任务 name，非子任务)*
    </task_name>

    <main_task_completion_criteria>
        [task_completion_criteria]
    </main_task_completion_criteria>

    <workflow>                                                      *(有 subtasks_with_status 时)*
          [other_id]. [other_name] (COMPLETED)
                Criteria:
                    [criteria]
                Summary:
                    [ai_reasoning]
        → [failed_id]. [failed_name] (FAILED)
                Criteria:
                    [criteria]
          [other_id]. [other_name]
          ...
    </workflow>
</failed_subtask>

<outputs>                                                           *(有任何输出内容时)*
    <previous_step_context ([id])>                                  *(有 previous_context 时)*
        [previous_context_text]
    </previous_step_context>

    <failed_subtask_output ([id])>                                  *(有实际输出时)*
        [error_text]
    </failed_subtask_output>

    <failed_subtask_attempt_history ([id])>                         *(有 attempt history 时)*
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

<context>
    <main_task>
        [task_name]
    </main_task>

    <completion_criteria>
        [task_completion_criteria]
    </completion_criteria>
</context>

<workflow>                                                          *(有 subtasks_with_status 时)*
    [id]. [name] (COMPLETED)
        Criteria:
            [criteria]
        Result:                                                     *(注：是 Result 非 Summary)*
            [ai_reasoning]
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
Your previous response did not end with a status marker.
If you already called autoagent-exec, do NOT call it again — 
just reply with: ⏳ LONG_RUNNING_IN_PROGRESS and end your session immediately.
Otherwise, continue working on the task from where you left off.
When you are done, end your response with EXACTLY one of:
  ✅ completed
  ❌ not completed: <reason>
  ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED")
```

### 3.4 In-Session Continuation（会话内继续）
当 session 仍然存活但被中断时（BashTimeout、StreamTimeout、用户 Ctrl+C），在同一 session 中发送轻量级 follow-up（不重置 session，不重建完整 prompt）。

> **Note**: Continuation prompt 不会添加 `system_prompt_prefix`，因为 session 上下文里已包含原始 prompt 的角色设定。

**Bash 超时**：
```
Your previous command was terminated and triggered session timeout.
The command was likely too long-running for direct Bash execution. 
Please use autoagent-exec for long-running commands (see system instructions).
Continue working on the task from where you left off.
When you are done, end your response with EXACTLY one of:
  ✅ completed
  ❌ not completed: <reason>
  ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED", then end your session immediately)
```

**Stream 超时**：
```
Your previous response was interrupted due to a network/stream timeout.
Please continue working on the task from where you left off.
When you are done, end your response with EXACTLY one of:
  ✅ completed
  ❌ not completed: <reason>
  ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED", then end your session immediately)
```

**用户中断（Ctrl+C）**：
```
Your session was interrupted by the user (Ctrl+C). Previous context is preserved.
Please continue working on the task from where you left off.
When you are done, end your response with EXACTLY one of:
  ✅ completed
  ❌ not completed: <reason>
  ⏳ LONG_RUNNING_IN_PROGRESS (only after autoagent-exec prints "TASK SUBMITTED", then end your session immediately)
```

> **Note**: 用户中断与超时的区别在于，中断通过持久化的 `interrupt_pending` 标志跨进程传递（因为 Ctrl+C 会终止整个进程），而超时在同一进程的 retry 循环内通过 transient 变量传递。当运行在 nested/looping 父任务内部时，`interrupt_pending` 设置在父任务 key 上，子任务恢复时会从父任务 state 中查找该标志。

---

## 4. Ideas 处理提示词 (Ideas Processing Prompts)

### 4.1 Idea 分解 (Ideas Decompose)
将 ideas.md 中的想法分解为结构化 TODO 任务：

```
You are a task planner. Your job is to decompose a given idea into concrete, actionable
TODO tasks in YAML format.

These tasks will be executed by an AI coding agent that can read/modify files, run shell
commands, and analyze code and outputs. Design your tasks and completion criteria accordingly.

<idea>
[idea_content]
</idea>

Understanding this following guide is essential for designing effective tasks. Read it carefully before generating your task decomposition.

<task_design_guide>
[TASK_DESIGN_GUIDE.md 内容]
</task_design_guide>

<output_instructions>
- Task IDs start from **[next_id]** (integer for top-level, dot notation for subtasks, e.g., [next_id].1, [next_id].2).
- Write ONLY valid YAML into the following file:
    [temp_tasks_path]
- Do NOT include markdown code fences or any extra text in the file.
- The file content must be a YAML dictionary containing a `description` string and a `tasks` list.
</output_instructions>
```

### 4.2 任务审查 (Ideas Review)
独立 AI 审查生成的任务质量。使用独立的 `ROLE_TASK_REVIEWER` 角色（非 `system_prompt_prefix`）：

```
You are a task decomposition review expert. You evaluate TODO task YAML files for schema correctness, appropriate task type selection, completion criteria quality, and decomposition granularity.
You focus on whether the tasks are actionable and verifiable by an autonomous AI coding agent. Review the following TODO task decomposition
for quality, completeness, and correctness.

<original_idea>
[idea_content]
</original_idea>

The generated tasks have been saved to the following file:
  [temp_tasks_path]

Please read this file to review the tasks.

The following guide serves as the authoritative reference for task types, schema, hierarchy rules,
and best practices when reviewing the generated tasks.

<task_design_guide>
[TASK_DESIGN_GUIDE.md 内容]
</task_design_guide>

<review_criteria>
Evaluate the generated tasks against these criteria. Refer to <task_design_guide> for
detailed rules and examples on each point.

1. **YAML & schema**: Well-formed YAML; correct IDs (integers + dot notation); all
   required fields present per type; `*_once` types only as subtasks.
2. **Type selection**: `nested` vs `looping` vs `simple` chosen correctly per §4.1;
   commands > 1 min use `long_running`; `*_once` used sparingly.
3. **Decomposition granularity**: No over-decomposition (merge steps that fail together)
   and no under-decomposition (split logically independent steps). See §4.2.
4. **Root-level `description`**: Present, meaningful, covers goal/architecture/key
   paths/commands/constraints as applicable. Missing = review failure.
   Order of tasks and description fields doesn't matter. See §3.1.
5. **`completion_criteria`**: Specific, measurable, AI-verifiable. Top-level criteria
   describe end state; subtask criteria describe step output. No unverifiable or
   process-describing criteria. See §5.1.
6. **`initial_hint`**: Provides context (paths, commands, constraints), not step-by-step
   playbooks. Subtasks use filesystem for state passing across sessions. See §5.2, §4.3.
7. **`system_prompt_prefix`**: Used appropriately (persona, restrictions); NOT set on
   top-level `nested`/`looping`. See §5.3.
8. **`model`**: `"default"` for reasoning, `"lite"` for execution. See §5.5.
9. **Retry strategy**: `max_attempts: 1` for execution-only subtasks; 2–5 for code-writing
   tasks. Hints mention residual state cleanup when relevant. See §5.4, §6.
10. **Looping discipline** (if applicable): Doc commits separated from code commits;
    failure pattern tracking; structured keep/discard rules; workspace cleanup. See §6.4.
</review_criteria>

<instructions>
If the tasks pass ALL criteria, respond with EXACTLY:
✅ completed

If the tasks need improvement:
DIRECTLY modify the YAML file at:
    [temp_tasks_path]
Do NOT include markdown code fences or any extra text in the file.
After modifying the file, respond with EXACTLY:
❌ not completed
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
Remember to validate against all review criteria from the initial review
(schema correctness, type appropriateness, completion criteria quality,
decomposition granularity, root-level description, hint quality, retry strategy, etc.).

Write ONLY valid YAML (a dictionary containing a `description` string and a `tasks` list) into the following file:
  [temp_tasks_path]

Do NOT include markdown code fences or any extra text in the file.
</instructions>
```
