# 使用指南

本文档是 AutoAgent 的完整使用指南。

---

## 1. 安装

### 环境要求

- Python 3.8+
- 至少一个 AI 编程工具已安装并登录

### 安装步骤

```bash
cd autoagent
pip install -r requirements.txt
```

### AI Provider 配置

| Provider | 安装 | 验证 |
|----------|------|------|
| CodeBuddy（默认） | 安装 IDE 插件或 CLI | `codebuddy --version` |
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude --version` |
| Gemini CLI | `npm install -g @google/gemini-cli` | `gemini --version` |
| Codex | `npm install -g @openai/codex` | `codex --version` |
| OpenCode | 安装 CLI + 配置 API Key | `opencode --version` |

---

## 2. 快速开始

### Step 1：创建 `todos.yaml`

```yaml
description: |
  项目目标和全局上下文。AI 执行每个任务时都能看到这段描述。

tasks:
  - id: 1
    name: "运行测试并修复失败"
    type: simple
    completion_criteria: |
      1. pytest 全部通过
      2. 无新增 lint 警告
    initial_hint: |
      运行 pytest，分析失败原因，修复代码。
```

### Step 2：启动执行

```bash
python orchestrator.py --config todos.yaml --workspace ./my_project
```

### Step 3：查看结果

执行日志保存在 `.autoagent/` 目录下，包含完整的 AI 对话记录。

---

## 3. 执行模式

### 3.1 线性模式（默认）

按 `todos.yaml` 中的任务顺序依次执行：

```bash
python orchestrator.py --config todos.yaml
```

### 3.2 AI 调度模式

AI 调度器动态决定执行哪个任务。需要在 `todos.yaml` 中配置 `ai_orchestrator` 部分：

```yaml
ai_orchestrator:
  strategy: |
    1. 先执行 Task 1 建立基准
    2. 然后交替执行 Task 2（分析）和 Task 3（优化）
    3. 每次优化后执行 Task 4 验证正确性
  max_rounds: 20
  stop_condition: |
    性能提升 >= 20% 且正确性验证通过

tasks:
  - id: 1
    name: "建立基准"
    description: "编译项目并运行基准测试，生成 baseline.txt"
    # ...
```

启动方式（自动检测 `ai_orchestrator` 配置）：

```bash
python orchestrator.py --config todos.yaml
```

或显式指定模式：

```bash
python orchestrator.py --config todos.yaml --mode ai
```

### 3.3 Idle 监听模式

后台持续运行，监听 `ideas.md` 文件变化：

```bash
python orchestrator.py --ideas ideas.md --config todos.yaml --workspace ./project
```

在 `ideas.md` 中写入想法（用 `---` 分隔），AI 自动拆解为任务并执行。

### 3.4 仅处理 Ideas

只拆解 ideas 不执行任务：

```bash
python orchestrator.py --ideas ideas.md --config todos.yaml --ideas-only
```

---

## 4. 任务配置

### 4.1 根级字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `description` | string | 是 | 全局项目描述，所有任务可见 |
| `ai_orchestrator` | dict | 否 | AI 调度配置（启用 AI 调度模式） |
| `tasks` | list | 是 | 任务列表 |

### 4.2 任务通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | int/float | 是 | 唯一 ID（顶层整数，子任务点号表示法如 `1.1`） |
| `name` | string | 是 | 简短任务名 |
| `type` | string | 是 | 任务类型 |
| `completion_criteria` | string | 是 | 完成标准 |
| `description` | string | 否 | 任务描述（AI 调度模式下建议填写） |
| `initial_hint` | string | 否 | 执行提示 |
| `model` | string | 否 | 模型角色覆盖 |
| `max_attempts` | int | 否 | 最大重试次数（默认 5） |
| `system_prompt_prefix` | string | 否 | 自定义系统 prompt |

### 4.3 任务类型

| 类型 | 说明 | 适用范围 |
|------|------|---------|
| `simple` | 单步任务，AI 自评估完成 | 顶层 + 子任务 |
| `nested` | 包含子任务，有 AI 失败分析和主任务评估 | 顶层 + 子任务 |
| `looping` | 子任务重复 N 轮 | 顶层 + 子任务 |
| `long_running` | 后台运行长时间命令 | 顶层 + 子任务 |
| `simple_once` | 同 simple，但只执行一次 | 仅子任务 |
| `long_running_once` | 同 long_running，但只执行一次 | 仅子任务 |

### 4.4 类型特有字段

**nested：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |

**looping：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |
| `repeat_count` | int | 是 | 循环次数 |
| `max_attempts_per_loop` | int | 否 | 每轮最大重试次数（默认继承 `config.yaml` 的 `default_max_attempts`，即 5） |

### 4.5 AI 调度配置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `strategy` | string | 是 | 调度策略（注入 AI prompt） |
| `max_rounds` | int | 否 | 最大调度轮次（默认 50） |
| `max_attempts` | int | 否 | AI 调度器返回无效决策时的最大重试次数（默认继承 `config.yaml` 的 `scheduler_decision_max_retries`） |
| `stop_condition` | string | 否 | 停止条件 |
| `last_result` | dict | 否 | 任务结果配置 |

`last_result` 类型：

| 类型 | 说明 |
|------|------|
| `file` | 指定文件路径，调度器读取文件内容 |
| `response` | 自动保存 AI 最终响应 |
| `none` | 不向调度器展示结果 |

---

## 5. 命令行参数

### 通用

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config`, `-c` | `todos.yaml` | 任务配置文件路径 |
| `--workspace`, `-w` | `.` | AI 工作目录 |
| `--mode` | 自动检测 | `linear` 或 `ai` |
| `--task`, `-t` | 无 | 只执行指定任务 ID |

### Provider 与模型

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--provider`, `-P` | `codebuddy` | AI Provider |
| `--model`, `-m` | 配置默认 | 模型指定 |
| `--executable` | 无 | 覆盖 Provider 可执行文件路径 |
| `--extra-args` | 无 | 传递给 AI 工具的额外参数 |
| `--use-cli` | false | 使用 CLI 子进程模式 |
| `--list-providers` | false | 列出所有可用 Provider 并退出 |
| `--include-directories` | 无 | 允许 AI 访问的额外目录（仅 Gemini），逗号分隔 |
| `--allow-unsupported-models` | false | 跳过对 CodeBuddy 支持模型列表的校验，适用于 CodeBuddy 尚未更新 --help 的新模型 |

### Ideas

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--ideas` | 无 | ideas.md 文件路径 |
| `--ideas-only` | false | 只处理 ideas 不执行任务 |
| `--human-review` | false | Ideas 人工审核 |
| `--no-idle` | false | 禁用 Idle 模式 |

### 会话管理

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--continue` | false | 继续最近访问的会话（基于 `last_accessed_at`） |
| `--resume` | 无 | 恢复指定会话 ID |
| `--list-sessions` | false | 列出所有会话 |
| `--rename OLD NEW` | 无 | 重命名 sessions.csv 中的 workspace 路径（将所有匹配 OLD 的条目更新为 NEW） |

### Preset 与配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--preset` | `default` | 使用的 Preset 名称 |
| `--settings` | 无 | 自定义配置文件路径，字段覆盖默认 config.yaml（浅合并） |
| `--generate-default-config` | false | 生成默认配置文件 |

### 工具

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--validate` | false | 验证配置后退出 |
| `--reset` | false | 重置所有任务状态 |
| `--log-dir` | `.autoagent` | 输出目录 |
| `--verbose`, `-v` | false | 调试日志 |

### 测试

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--test-schema` | 无 | 测试 schema JSON 文件路径（内部测试用） |
| `--use-test` | 无 | 测试用例 ID（1-based，需配合 `--test-schema`） |

---

## 6. Preset 配置

Preset 是 `config.yaml` 中预定义的参数组合，避免每次输入大量命令行参数。

### 定义 Preset

```yaml
# config.yaml
preset:
  - name: default

  - name: general
    ideas: "${workspace}/ideas.md"
    config: "${workspace}/todos.yaml"
    provider: codebuddy
    use_cli: false
    model: 
      plan: claude-opus-4.6
      default: claude-opus-4.6
      lite: glm-5.0
      evaluation: claude-opus-4.6
      scheduler: claude-opus-4.6
    human_review: true
    verbose: true
```

### 使用 Preset

```bash
python orchestrator.py --preset general --workspace ./my_project
```

**优先级**：命令行参数 > Preset > `--settings` 文件 > config.yaml 全局设置 > 内置默认值

`${workspace}` 变量会在加载时自动展开为实际工作目录。

---

## 7. 模型配置

### 单模型

```bash
python orchestrator.py --model claude-opus-4.6
```

### 多角色模型

```bash
python orchestrator.py --model "plan:claude-opus-4.6;default:claude-sonnet-4;lite:glm-4-flash;evaluation:claude-opus-4.6;scheduler:claude-opus-4.6"
```

| 角色 | 用途 |
|------|------|
| `plan` | Ideas 拆解 |
| `default` | 任务执行 |
| `lite` | 轻量操作 |
| `evaluation` | 失败分析、主任务评估 |
| `scheduler` | AI 调度决策 |

### 逐任务覆盖

在 `todos.yaml` 中为特定任务指定模型：

```yaml
- id: 1
  name: "运行基准测试"
  type: long_running
  model: lite          # 只是跑命令，用便宜模型
```

---

## 8. 会话管理

### 会话存储

所有执行数据保存在 `.autoagent/` 目录下，每次运行创建一个会话目录。

### 断点续传

```bash
# 继续最近访问的会话（同一 workspace 下按 last_accessed_at 选取）
python orchestrator.py --continue

# 恢复指定会话
python orchestrator.py --resume <session_id>

# 查看所有会话
python orchestrator.py --list-sessions
```

### 中断恢复

`Ctrl+C` 中断时，系统自动保存当前状态。下次 `--continue` 时：
- 已完成的任务自动跳过
- 中断的任务从断点继续（同一 AI 会话）
- 后台长时间任务继续轮询

---

## 9. 故障排除

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| AI 反复重试同一错误 | completion_criteria 不够具体 | 添加更明确的成功/失败判断条件 |
| 任务超时 | 命令执行时间超过 session_timeout | 改用 `long_running` 类型 |
| AI 忘记输出完成标记 | 任务过于复杂 | 系统会自动 nudge，无需干预 |
| 子任务间信息丢失 | 未持久化中间结果 | 在 initial_hint 中指示写入文件 |
| AI 调度器选错任务 | strategy 规则不清晰 | 用更明确的条件-动作规则 |
| Rate limit 错误 | API 调用频率过高 | 系统自动退避，无需干预 |
| 会话恢复失败 | 会话目录被删除 | 使用 `--reset` 重新开始 |
| autoagent-exec 输出为空 | AI 在命令中添加了输出重定向 | 系统提示词已禁止重定向；如需重定向应使用 `--stdout`/`--stderr` 参数 |
| AI 看不到 autoagent-exec 三种输出 | 输出被重定向或进程仍在运行 | AI 应检查 PID，若进程仍在运行则输出 `LONG_RUNNING_IN_PROGRESS` |
| 启动时 model 名称 WARNING | model 名称不在 CodeBuddy 支持列表中 | 检查拼写；仅 warning 不阻止运行 |

---

## 10. FAQ

**Q: 任务失败后会阻塞后续任务吗？**

A: 不会。线性模式下，失败的任务不阻塞后续任务执行。AI 调度模式下，失败的任务同样不会阻塞——调度器会根据失败结果自主决定下一步操作（重试、换方向或停止）。

**Q: 如何在不同任务间传递数据？**

A: 通过文件系统。在 `initial_hint` 中指示 AI 将结果写入特定文件，后续任务读取该文件。

**Q: AI 调度模式和线性模式可以混用吗？**

A: 默认情况下不混用。如果 `todos.yaml` 包含 `ai_orchestrator` 配置，系统自动使用 AI 调度模式。但你可以通过 `--mode linear` 强制使用线性模式，此时 `ai_orchestrator` 配置会被忽略。

**Q: 如何查看 AI 的完整对话记录？**

A: 查看 `.autoagent/<session>/conversations/` 目录下的 Markdown 文件。

**Q: 支持哪些 AI Provider？**

A: CodeBuddy（默认）、Claude Code、Gemini CLI、OpenCode、Codex。使用 `--list-providers` 查看完整列表。
