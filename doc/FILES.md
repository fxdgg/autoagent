# 项目文件说明

本文档详细说明 AutoAgent 的项目结构和各个文件的作用。

## 📁 目录结构

```
autoagent/
├── README.md                    # 项目介绍和快速开始
├── doc/                         # 文档目录
│   ├── INDEX.md                 # 文档索引
│   ├── ARCHITECTURE.md          # 架构设计文档
│   ├── USAGE.md                 # 使用指南
│   ├── API_REFERENCE.md         # API 参考文档
│   ├── EXAMPLES.md              # 实际使用示例
│   └── FILES.md                 # 本文件：项目文件说明
├── requirements.txt             # Python 依赖列表
├── .gitignore                   # Git 忽略规则
├── config.yaml                  # 全局配置（session_timeout, bash_timeout 等）
├── todos.example.yaml           # 任务配置示例
├── TASK_DESIGN_GUIDE.md         # 任务设计指南（供 AI 参考）
│
├── orchestrator.py              # 主程序、CLI 入口
├── ai_providers.py              # AI Provider 抽象层（多 CLI 工具支持）
├── task_executor.py             # 任务执行器 (Simple/Nested/Looping/Subtask)
├── autoagent_exec.py            # long_running 任务启动器（AI 通过 wrapper 脚本调用）
├── codebuddy_client.py          # AIClient（统一 AI 客户端，支持 SDK 和 CLI）
├── state_manager.py             # 状态持久化管理
├── conversation_logger.py       # 对话日志记录
├── ideas_watcher.py             # Ideas 文件监控与任务分解
├── truncation_limits.py         # 提示词截断限制（从 config.yaml 加载）
├── run_test.py                  # 测试运行脚本
│
│   ├── prompts/                     # AI Prompt 模板
│   │   ├── __init__.py              # 包初始化，导出所有 prompt 构造函数
│   │   ├── shared.py                # 共享常量：角色定义、状态标记、工具函数
│   │   ├── simple_task.py           # 简单任务执行 prompt 构造
│   │   ├── long_running_task.py     # 长时间任务启动与结果分析 prompt 构造
│   │   ├── failure_analysis.py      # 子任务失败分析 prompt（nested + looping）
│   │   ├── main_evaluation.py       # 主任务完成评估 prompt
│   │   ├── marker_nudge.py          # Marker nudge 机制（AI 忘记输出状态标记时的轻量级追问）
│   │   ├── ideas_decompose.py       # Idea 拆解为任务的 prompt
│   │   └── ideas_review.py          # 任务审查与修订 prompt│
├── sample/                      # 示例项目目录
│   ├── auto_run.bat             # 自动运行脚本
│   ├── manual_run.bat           # 手动运行脚本
│   ├── opencode_sample.bat      # OpenCode 示例运行脚本
│   ├── reset.bat                # 重置脚本
│   ├── ideas.md                 # 示例 ideas 文件
│   ├── todos.yaml               # 示例任务配置
│   ├── cufftdx_optimization/    # 示例项目：cuFFTDx 优化
│   └── mini_compiler/           # 示例项目：迷你编译器
│
├── test/                        # 测试目录
│   ├── _reset_test.bat          # 测试重置脚本
│   ├── _run_test.bat            # 测试运行脚本
│   └── simulation_test/         # 模拟测试（使用 TestProvider）
│
└── <log_dir>/                   # 日志根目录（默认 .autoagent，相对 CWD）
    ├── sessions.csv                    # 会话注册表（Tab 分隔：session_id, workspace, created_at）
    └── <project>_<random8>/     # 项目专属会话目录（由 .autoagent_log 指定）
│       ├── orchestrator.log             # Orchestrator 运行日志
│       ├── todos_state.yaml             # 任务状态（自动生成）
│       ├── plans_state.yaml             # Ideas 状态跟踪（含 plan_tasks 断点续传数据）
│       ├── .ideas_tasks_temp.yaml      # AI 生成的临时 YAML（会话期间使用，完成后清理）
│       ├── previous_subtask_summary.txt # 上一个子任务的摘要（断点续传用）
│       ├── lr_tasks/                    # long_running 任务文件目录        │   ├── lr_<task_id>_signal.json # long_running 信号文件
        │   └── lr_<task_id>_output.log  # long_running 命令输出日志
        └── conversations/               # 对话日志目录
            ├── ideas.md                 # Ideas 拆解日志
            ├── task_1_round_1.md        # 简单任务第 1 轮对话
            ├── task_1_round_2.md        # 简单任务第 2 轮对话
            └── subtask_2/               # 嵌套/循环任务的子任务目录
                ├── task_2.1_round_1.1.md                      # 子任务，主轮1 子轮1
                ├── task_2.1_round_1.2.md                      # failure 后重试，主轮1 子轮2
                ├── task_2.2_round_1.1.md
                ├── failure_analysis_2.2_round_1.1.md          # 子任务 2.2 失败分析
                ├── main_task_evaluation_round_1.md            # 主任务评估第 1 轮
                └── main_task_evaluation_round_2.md
```

## 📄 文件说明

### 文档文件（doc/ 目录）

#### README.md（根目录）
- **作用**：项目的主入口文档
- **内容**：项目简介、核心特性、快速开始、核心概念、使用场景示例

#### doc/INDEX.md
- **作用**：文档导航和索引
- **内容**：所有文档的列表和说明、按需求查找指南

#### doc/ARCHITECTURE.md
- **作用**：系统架构设计文档
- **内容**：分层架构、核心组件、任务类型详解、数据流、长时间任务处理、Ideas 处理流程

#### doc/USAGE.md
- **作用**：详细使用指南
- **内容**：安装配置、任务类型说明、执行方式、最佳实践、故障排除

#### doc/API_REFERENCE.md
- **作用**：完整 API 参考文档
- **内容**：类定义、方法签名、CLI 参数、状态类型

#### doc/EXAMPLES.md
- **作用**：实际使用示例
- **内容**：ML 训练、代码质量、性能优化等场景示例

#### doc/FILES.md
- **作用**：项目文件说明（本文件）

### 配置文件

#### config.yaml

- **作用**：全局配置文件
- **内容**：
  ```yaml
  # System prompt prefix (appended to the system prompt for all tasks)
  # Can be overridden per-task in todos.yaml via the system_prompt_prefix field.
  system_prompt_prefix: "You are an AI coding agent. ..."

  # Default AI model (used when no model is specified via CLI --model or preset)
  default_model: glm-5.0-ioa

  # Session timeout (hard cap on total AI session time, in seconds).
  session_timeout: 3600

  # Bash timeout (no-new-output timeout, in seconds).
  # If the AI produces no new output for this many seconds, the session is killed.
  bash_timeout: 300

  # Fast-fail timeout for autoagent-exec (in seconds).
  # Code fallback: 10. Configures how long autoagent-exec waits before
  # treating a command as long-running.
  fast_fail_timeout: 30

  # Maximum backoff wait time (in seconds) when AI CLI calls fail repeatedly.
  # Uses exponential backoff: 5s, 10s, 20s, 40s, ... up to this limit.
  backoff_max_wait: 300

  # Maximum number of AI review rounds when processing ideas into TODO tasks.
  max_review_rounds: 5

  # Maximum number of schema-validation retries when processing ideas.
  max_validation_retries: 2

  # Truncation limits for auto-built prompts (in characters)
  # 4 keys are used:
  #   previous_subtask_summary: for subtask summaries, error text, log files
  #   previous_attempt_output: for previous attempt's full AI output on retry
  #   history_summary: for history attempt summaries, ai_reasoning
  #   max: defensive upper bound for fields that should not normally be truncated
  truncation_limits:
    previous_subtask_summary: 4000
    previous_attempt_output: 4000
    history_summary: 300
    max: 50000

  # Preset configurations
  preset:
    - name: default
      ideas: ${workspace}/ideas.md
      config: ${workspace}/todos.yaml
      provider: codebuddy
      use_cli: false
      model: "plan:claude-opus-4.6;default:claude-opus-4.6;lite:glm-5.0-ioa"
      human_review: true
      verbose: true

    - name: test
      ideas: ${workspace}/../ideas.md
      config: ${workspace}/../todos.yaml
      provider: codebuddy
      use_cli: false
      model: "plan:glm-5.0-ioa;default:glm-5.0-ioa;lite:deepseek-v3-2-volc-ioa"
      human_review: true
      verbose: true
  ```
- **用途**：
  - `system_prompt_prefix`: 全局系统提示词前缀，附加到所有任务的系统提示词中，可在 todos.yaml 中按任务覆盖
  - `default_model`: 默认 AI 模型，当 CLI `--model` 和 preset 均未指定时使用
  - `session_timeout`: 会话超时配置值（总时间硬上限）
  - `bash_timeout`: 无新输出超时配置值（检测 AI 卡住）
  - `fast_fail_timeout`: autoagent-exec 快速失败超时时间，命令在此时间内退出则立即报告结果，否则转为后台运行（代码兜底值 10 秒，shipped config.yaml 中设为 30 秒）
  - `backoff_max_wait`: AI CLI 连续失败时的最大退避等待时间（指数退避：5s→10s→20s→...→上限）
  - `max_review_rounds`: Ideas 拆解时 AI 审查的最大轮数（代码兜底值 3，shipped config.yaml 中设为 5）
  - `max_validation_retries`: Ideas 拆解时 schema 校验的最大重试次数（默认 2）
  - `max_marker_nudges`: 当 AI 未输出完成状态标记时的最大 nudge 次数（默认 2）。在同一 session 中发送轻量级追问（允许 AI 继续工作），耗尽后回退到正常 retry 循环。发送 nudge 前会先检查信号文件，若已有后台任务在运行则跳过 nudge 直接走 long_running 流程
  - `truncation_limits`: 控制各类提示词字段的最大字符数，防止上下文过长
  - `preset`: 定义常用参数预设，通过 `--preset <name>` 快速切换配置
- **变量替换**：Preset 中支持 `${workspace}` 变量，会被替换为当前工作目录

#### requirements.txt
- **作用**：Python 依赖列表
- **用途**：通过 `pip install -r requirements.txt` 安装依赖

#### .gitignore
- **作用**：Git 忽略规则

#### todos.example.yaml
- **作用**：任务配置示例文件
- **内容**：包含 simple、nested、looping、long_running、simple_once、long_running_once 六种任务类型的配置示例
- **用途**：用户可以复制此文件作为 `todos.yaml` 的模板

#### TASK_DESIGN_GUIDE.md
- **作用**：任务设计指南
- **内容**：详细的任务设计最佳实践和规范说明
- **用途**：供 AI 在 Ideas 拆解为任务时参考，通过 `prompts/shared.py` 的 `load_task_design_guide()` 函数加载

### 程序文件

#### orchestrator.py
- **作用**：主程序入口和 CLI
- **核心类**：`TodoOrchestrator` — 任务编排器，负责任务调度和执行
- **主要职责**：
  - 解析 CLI 参数和配置文件
  - 加载和验证 todos.yaml
  - 调度任务执行（委托给各 Executor）
  - 管理 AI 客户端生命周期
  - 协调 Ideas 处理和 Idle 模式

#### ai_providers.py
- **作用**：AI Provider 抽象层
- **核心类**：
  - `AIProvider`：基类，提供 `set_model(model_name)` 方法用于运行时切换模型
  - `CodeBuddyProvider`：CodeBuddy CLI（默认模型从 `config.yaml` 的 `default_model` 加载，回退到 `deepseek-v3.2`）
  - `ClaudeCodeProvider`：Claude Code（默认模型 `claude-sonnet-4-6`）
  - `GeminiCLIProvider`：Gemini Cli（默认模型 `gemini-2.5-pro`）
  - `OpenCodeProvider`：OpenCode CLI（使用自身配置默认模型）
  - `TestProvider`：测试用 Provider（从规则文件读取预定义响应）
- **核心函数**：
  - `get_provider(name, model)`：工厂函数，根据名称创建 provider 实例
  - `parse_model_spec(model_str)`：解析多模型规格字符串，支持 `"plan:X;default:Y;lite:Z"` 格式和单模型 `"glm-5"` 格式，返回 `{"plan": ..., "default": ..., "lite": ...}` 字典

#### task_executor.py
- **作用**：任务执行器
- **核心类**：
  - `SimpleTaskExecutor`：简单任务执行
  - `NestedTaskExecutor`：嵌套任务执行（含 AI 失败分析和主任务评估），接收 `model_roles` 参数
  - `LoopingTaskExecutor`：循环任务执行（固定 N 次迭代），接收 `model_roles` 参数
  - `SubtaskExecutor`：子任务执行，根据子任务的 `model` 字段切换 provider 模型

#### autoagent_exec.py
- **作用**：long_running 任务启动器
- **用途**：AI 通过 wrapper 脚本（`autoagent-exec.bat` / `autoagent-exec.sh`）调用此脚本启动长时间命令，支持快速失败检测 + 信号文件通信 + 智能输出（短输出内联打印，长输出只给路径）
- **重复启动防护**：启动命令前检查信号文件，如果同一 task-id 已有 `status="running"` 的任务则拒绝启动（exit 1），防止 AI 在同一 session 中重复启动后台任务

#### codebuddy_client.py
- **作用**：统一 AI 客户端封装
- **核心类**：
  - `AIClient`：CLI 模式客户端（通过子进程调用 AI CLI 工具）
  - `AIClientSDK`：SDK 模式客户端（通过 CodeBuddy Agent SDK 调用）
  - `AIClientTest`：测试模式客户端（使用 TestProvider 的预定义响应）
- **错误处理**：
  - `_parse_cli_error()`：结构化解析 JSON 错误（支持 Anthropic 嵌套格式、扁平格式、纯文本 fallback）
  - `system/api_retry` 事件实时显示（rate_limit、server_error 等 CLI 内部重试进度）
  - `result` 事件 `is_error` 传播（避免空 response 丢失错误原因）

#### state_manager.py
- **作用**：状态持久化管理
- **核心类**：`StateManager` — 管理任务状态的加载、保存、更新，写入操作通过 `threading.Lock` 保证线程安全
- **Round-scoped keys**：子任务状态使用 `task_id@round_label` 格式的 key（如 `"1.2@3.1"`），实现精确的断点续传。`*_once` 类型使用 plain key 跨轮次共享。`round_key()` 静态方法构造 key，`get_summary()`/`get_in_progress_tasks()` 自动跳过 `@` key

#### conversation_logger.py
- **作用**：对话日志记录
- **核心类**：`ConversationLogger` — 记录每次 AI 调用的 prompt 和 response

#### ideas_watcher.py
- **作用**：Ideas 文件监控与任务分解
- **核心类**：`IdeasWatcher` — 监控 ideas.md 变更，调用 AI 分解为 TODO 任务，支持人工审核

#### truncation_limits.py
- **作用**：提示词截断限制的集中管理
- **核心类**：`_Limits` — 从 `config.yaml` 的 `truncation_limits` 段加载截断阈值，带默认值兜底
- **用途**：所有 prompt 构造器和 task_executor 通过 `from truncation_limits import limits` 获取截断阈值，避免硬编码

#### run_test.py
- **作用**：测试运行脚本
- **用途**：提供便捷的测试运行入口，支持模拟测试和集成测试

### Prompt 模板（prompts/ 目录）

#### prompts/shared.py
- **作用**：共享常量和工具函数
- **内容**：角色定义（coding agent、task planner、task reviewer）、状态标记指令（✅/❌ completed/not completed）、通用辅助函数（构建历史记录、兄弟任务上下文、autoagent-exec 说明等）
- **核心函数**：
  - `build_system_prompt_coding_agent(exec_script_path, supports_system_prompt)`: 构建编码代理的系统提示词（含状态标记指令、自主行动指令和 autoagent-exec 使用说明）
  - `load_system_prompt_prefix()`: 从 config.yaml 加载并缓存 `system_prompt_prefix`
  - `get_system_prompt_prefix(task)`: 获取有效的系统提示词前缀（任务级覆盖全局）
  - `apply_system_prompt_prefix(parts, task)`: 将前缀插入到 prompt 部件列表的开头
  - `prepend_system_prompt_prefix(prompt, task)`: 将前缀拼接到 prompt 字符串的开头
  - `load_task_design_guide()`: 加载并缓存 TASK_DESIGN_GUIDE.md 内容
  - `build_timeout_guidance(exec_script_path, timeout_feedback, timeout_type)`: 构建超时警告提示（支持 bash 和 session 两种超时类型）
  - `build_sibling_context(task, parent_context)`: 构建兄弟任务上下文信息
  - `build_history_section(history, extract_summary_fn)`: 构建历史尝试记录
  - `build_suggested_fix_section(parent_context, fallback_msg)`: 构建修复建议
  - `build_previous_subtask_section(parent_context)`: 构建前一子任务摘要（用于上下文隔离的子任务间传递信息）
  - `build_long_running_reminder(exec_script_path)`: 构建长时间任务简短提醒

#### prompts/simple_task.py
- **作用**：简单任务执行 prompt 构造器
- **用途**：为 SimpleTaskExecutor 构造包含任务描述、完成标准、历史记录等信息的 prompt

#### prompts/long_running_task.py
- **作用**：长时间任务相关 prompt 构造器
- **用途**：构造启动 long_running 任务的 prompt 和结果分析 prompt

#### prompts/failure_analysis.py
- **作用**：子任务失败分析 prompt 构造器
- **用途**：为 nested 和 looping 任务的子任务失败场景构造分析 prompt

#### prompts/main_evaluation.py
- **作用**：主任务完成评估 prompt 构造器
- **用途**：在所有子任务完成后，构造主任务完成度评估 prompt

#### prompts/marker_nudge.py
- **作用**：Marker nudge 机制的 prompt 常量和配置加载
- **内容**：当 AI 未输出完成状态标记（✅/❌/⏳）时（可能是遗漏，也可能是 CLI/SDK 异常中断），发送轻量级追问 prompt。允许 AI 继续未完成的工作，但禁止重复执行已跑过的命令
- **核心常量**：
  - `MARKER_NUDGE_PROMPT`: nudge 追问的 prompt 文本
  - `MAX_MARKER_NUDGES`: 从 `config.yaml` 加载的最大 nudge 次数（默认 2）

#### prompts/ideas_decompose.py
- **作用**：Idea 拆解 prompt 构造器
- **用途**：将自然语言想法拆解为结构化 YAML 任务定义的 prompt

#### prompts/ideas_review.py
- **作用**：任务审查与修订 prompt 构造器
- **用途**：构造 AI 审查、修订和人工反馈修订的 prompt

### 用户文件

#### todos.yaml（用户创建）
- **作用**：用户的任务配置文件
- **创建方式**：用户复制 `todos.example.yaml` 并修改

#### .autoagent_log（自动生成）
- **作用**：记录当前活跃会话的目录名称
- **内容**：如 `cufftdx_optimization_2xrsx0i7`
- **用途**：`--continue` 时读取此文件定位会话目录；`--resume` 时自动更新此文件

#### sessions.csv（自动生成）
- **位置**：`<log_dir>/sessions.csv`
- **作用**：会话注册表，记录所有历史会话
- **格式**：Tab 分隔，包含 `session_id`、`workspace`、`created_at` 三列
- **用途**：`--list-sessions` 列出所有会话；`--resume` 搜索匹配会话（支持完整名称或短 ID 后缀匹配）

## 📝 配置文件详解

### todos.yaml 完整示例

```yaml
tasks:
  # 简单任务示例
  - id: 1
    name: "下载数据集"
    type: simple
    completion_criteria: "data.csv 文件存在且大小 > 10MB"
    initial_hint: "使用 python download.py"
    
  # 嵌套任务示例
  - id: 2
    name: "优化模型性能"
    type: nested
    completion_criteria: |
      训练成功完成
      验证集精度 >= 0.9
      验证集 loss < 0.1
    subtasks:
      - id: 2.1
        name: "修改训练代码"
        type: simple
        completion_criteria: "代码修改完成"
        
      - id: 2.2
        name: "运行训练"
        type: long_running
        completion_criteria: "训练正常退出且验证集指标满足要求"

  # 循环任务示例
  - id: 3
    name: "迭代优化 CUDA 内核性能"
    type: looping
    repeat_count: 5
    max_attempts_per_loop: 10
    completion_criteria: |
      完成 5 轮优化迭代
    subtasks:
      - id: 3.1
        name: "使用 ncu 分析性能瓶颈"
        type: long_running
        completion_criteria: "ncu 分析完成，生成性能报告"
        
      - id: 3.2
        name: "根据分析结果优化代码"
        type: simple
        completion_criteria: "代码优化完成，编译通过"
```

### 字段说明

#### 任务通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | int/string | 是 | 任务 ID（唯一标识） |
| `name` | string | 是 | 任务名称 |
| `type` | string | 是 | 顶层任务类型：`simple`、`nested`、`looping`；子任务类型：`simple`、`long_running`、`simple_once`、`long_running_once` |
| `completion_criteria` | string | 是 | 完成标准（自然语言描述） |
| `model` | string | 否 | 模型选择：`"default"`、`"lite"` 或直接模型名称（默认 `"default"`） |
| `system_prompt_prefix` | string | 否 | 任务级系统提示词前缀，覆盖 config.yaml 中的全局设置 |

#### 简单任务 (type: simple)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `initial_hint` | string | 否 | 静态上下文提示（每次尝试都会传入） |

#### 嵌套任务 (type: nested)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |
| `max_attempts` | int | 否 | 最大重试轮数（默认 5） |

#### 循环任务 (type: looping)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |
| `repeat_count` | int | 是 | 循环次数（正整数） |
| `max_attempts_per_loop` | int | 否 | 每轮循环内最大重试次数（默认 5） |

#### 长时间任务 (type: long_running)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `initial_hint` | string | 否 | 静态上下文提示（每次尝试都会传入） |
| `command` | string | 否 | 可选的命令提示。AI 会根据任务描述自主决定要运行的命令，并通过 `autoagent-exec` 启动 |

## 📊 状态值说明

### 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 待执行 |
| `in_progress` | 执行中 |
| `completed` | 已完成 |
| `failed` | 失败 |

## 📝 文件维护

### 文档更新

- **README.md**：项目重大变更时更新
- **doc/INDEX.md**：文档结构变更时更新
- **doc/ARCHITECTURE.md**：架构设计变更时更新
- **doc/USAGE.md**：功能变更或新增功能时更新
- **doc/FILES.md**：项目结构变更时更新

### 配置更新

- **requirements.txt**：添加新依赖时更新
- **.gitignore**：发现新的需要忽略的文件时更新
- **config.yaml**：添加新的全局配置项时更新
- **todos.example.yaml**：新增任务类型或字段时更新

## 总结

本文档详细说明了：

- ✅ 完整的项目目录结构
- ✅ 每个文件的作用和说明
- ✅ 配置文件的详细格式
- ✅ 状态值说明

如有其他问题，请参考：
- [README.md](../README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
