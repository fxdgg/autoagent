# 项目文件说明

本文档详细说明 CodeBuddy Todo Orchestrator 的项目结构和各个文件的作用。

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
├── config.yaml                  # 全局配置（bash_timeout 等）
├── todos.example.yaml           # 任务配置示例
│
├── orchestrator.py              # 主程序、CLI 入口
├── ai_providers.py              # AI Provider 抽象层（多 CLI 工具支持）
├── task_executor.py             # 任务执行器 (Simple/Nested/Looping/Subtask)
├── autoagent_exec.py            # long_running 任务启动器（AI 通过 Bash 调用）
├── codebuddy_client.py          # AIClient（统一 AI 客户端，支持 SDK 和 CLI）
├── state_manager.py             # 状态持久化管理
├── conversation_logger.py       # 对话日志记录
├── ideas_watcher.py             # Ideas 文件监控与任务分解
├── truncation_limits.py         # 提示词截断限制（从 config.yaml 加载）
├── run_test.py                  # 测试运行脚本
│
├── prompts/                     # AI Prompt 模板
│   ├── __init__.py              # 包初始化，导出所有 prompt 构造函数
│   ├── shared.py                # 共享常量：角色定义、状态标记、工具函数
│   ├── simple_task.py           # 简单任务执行 prompt 构造
│   ├── long_running_task.py     # 长时间任务启动与结果分析 prompt 构造
│   ├── failure_analysis.py      # 子任务失败分析 prompt（nested + looping）
│   ├── main_evaluation.py       # 主任务完成评估 prompt
│   ├── ideas_decompose.py       # Idea 拆解为任务的 prompt
│   └── ideas_review.py          # 任务审查与修订 prompt
│
├── sample/                      # 示例项目目录
│   ├── auto_run.bat             # 自动运行脚本
│   ├── manual_run.bat           # 手动运行脚本
│   ├── opencode_sample.bat      # OpenCode 示例运行脚本
│   ├── reset.bat                # 重置脚本
│   ├── ideas.md                 # 示例 ideas 文件
│   ├── todos.yaml               # 示例任务配置
│   └── cufftdx_optimization/    # 示例项目：cuFFTDx 优化
│
├── test/                        # 测试目录
│   ├── simulation_test/         # 模拟测试（使用 TestProvider）
│   └── cufftdx_optimization/    # cuFFTDx 优化测试
│
└── <log_dir>/                   # 日志根目录（默认 .autoagent，相对 CWD）
    └── <project>_<random>/      # 项目专属会话目录（由 .autoagent_log 指定）
        ├── orchestrator.log             # Orchestrator 运行日志
        ├── todos_state.yaml             # 任务状态（自动生成）
        ├── .ideas_processed.md          # Ideas 归档（已处理的 idea 原文）
        ├── lr_tasks/                    # long_running 任务文件目录
        │   ├── lr_<task_id>_signal.json # long_running 信号文件
        │   └── lr_<task_id>_output.log  # long_running 命令输出日志
        └── conversations/               # 对话日志目录
            ├── ideas.md                 # Ideas 拆解日志
            ├── task_1.md                # 简单任务的对话日志
            └── subtask_2/               # 嵌套/循环任务的子任务目录
                ├── task_2.1.md
                └── _decisions.md        # AI 决策日志
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

  # Timeout for each AI call (in seconds).
  bash_timeout: 3600

  # Maximum backoff wait time (in seconds) when AI CLI calls fail repeatedly.
  # Uses exponential backoff: 5s, 10s, 20s, 40s, ... up to this limit.
  backoff_max_wait: 300

  # Truncation limits for auto-built prompts (in characters)
  truncation_limits:
    suggested_fix: 1500
    history_summary: 300
    nested_latest_fix: 2000
    looping_latest_fix: 1500
    log_section: 6000
    execution_results: 4000
    idea_content: 8000
    tasks_yaml: 10000
    review_feedback: 3000
    human_feedback: 3000
    error_text: 2000
    log_file: 2000

  # Preset configurations
  preset:
    - name: default
      ideas: ${workspace}/ideas.md
      config: ${workspace}/todos.yaml
      provider: codebuddy
      use_cli: false
      model: "plan:claude-opus-4.6;default:claude-opus-4.6;simple:claude-haiku-4.5"
      human_review: true
      verbose: true

    - name: test
      ideas: ${workspace}/../ideas.md
      config: ${workspace}/../todos.yaml
      provider: codebuddy
      use_cli: false
      model: "plan:glm-5.0-ioa;default:glm-5.0-ioa;simple:deepseek-v3-2-volc-ioa"
      human_review: true
      verbose: true
  ```
- **用途**：
  - `system_prompt_prefix`: 全局系统提示词前缀，附加到所有任务的系统提示词中，可在 todos.yaml 中按任务覆盖
  - `default_model`: 默认 AI 模型，当 CLI `--model` 和 preset 均未指定时使用
  - `bash_timeout`: 提供默认超时配置值
  - `backoff_max_wait`: AI CLI 连续失败时的最大退避等待时间（指数退避：5s→10s→20s→...→上限）
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
  - `parse_model_spec(model_str)`：解析多模型规格字符串，支持 `"plan:X;default:Y;simple:Z"` 格式和单模型 `"glm-5"` 格式，返回 `{"plan": ..., "default": ..., "simple": ...}` 字典

#### task_executor.py
- **作用**：任务执行器
- **核心类**：
  - `SimpleTaskExecutor`：简单任务执行
  - `NestedTaskExecutor`：嵌套任务执行（含 AI 失败分析和主任务评估），接收 `model_roles` 参数
  - `LoopingTaskExecutor`：循环任务执行（固定 N 次迭代），接收 `model_roles` 参数
  - `SubtaskExecutor`：子任务执行，根据子任务的 `model` 字段切换 provider 模型

#### autoagent_exec.py
- **作用**：long_running 任务启动器
- **用途**：AI 通过 Bash 调用此脚本启动长时间命令，支持 10 秒快速失败检测 + 信号文件通信

#### codebuddy_client.py
- **作用**：统一 AI 客户端封装
- **核心类**：
  - `AIClient`：CLI 模式客户端（通过子进程调用 AI CLI 工具）
  - `AIClientSDK`：SDK 模式客户端（通过 CodeBuddy Agent SDK 调用）
  - `AIClientTest`：测试模式客户端（使用 TestProvider 的预定义响应）

#### state_manager.py
- **作用**：状态持久化管理
- **核心类**：`StateManager` — 管理任务状态的加载、保存、更新，写入操作通过 `threading.Lock` 保证线程安全

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
  - `build_system_prompt_coding_agent(exec_script_path, supports_system_prompt, task)`: 构建编码代理的系统提示词（含状态标记指令和 autoagent-exec 使用说明）
  - `load_system_prompt_prefix()`: 从 config.yaml 加载并缓存 `system_prompt_prefix`
  - `get_system_prompt_prefix(task)`: 获取有效的系统提示词前缀（任务级覆盖全局）
  - `apply_system_prompt_prefix(parts, task)`: 将前缀插入到 prompt 部件列表的开头
  - `load_task_design_guide()`: 加载并缓存 TASK_DESIGN_GUIDE.md 内容
  - `build_timeout_guidance(exec_script_path, timeout_feedback)`: 构建超时警告提示

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
- **作用**：记录项目对应的日志子文件夹名称
- **内容**：如 `cufftdx_optimization_ko53bi1b`
- **用途**：确保同一项目始终写入同一个日志子文件夹

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
| `model` | string | 否 | 模型选择：`"default"` 或 `"simple"`（默认 `"default"`） |

#### 简单任务 (type: simple)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `initial_hint` | string | 否 | 初始提示（给 AI 的参考信息） |

#### 嵌套任务 (type: nested)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |
| `max_attempts` | int | 否 | 最大重试轮数（默认 20） |

#### 循环任务 (type: looping)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |
| `repeat_count` | int | 是 | 循环次数（正整数） |
| `max_attempts_per_loop` | int | 否 | 每轮循环内最大重试次数（默认 20） |

#### 长时间任务 (type: long_running)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `command` | string | 否 | 要执行的命令（可选，AI 可自行决定） |

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
