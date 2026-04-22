# 项目文件结构

本文档描述 AutoAgent 重构后的项目文件结构。

---

## 目录总览

```
autoagent/
├── config.yaml                  # 全局配置文件
├── todos.example.yaml           # 任务定义示例
├── requirements.txt             # Python 依赖
├── README.md                    # 项目 README
│
├── src/                         # 源代码（Python 包）
│   ├── orchestrator.py          # CLI 入口（main()）
│   │
│   ├── orchestrator/            # 编排器
│   │   ├── linear_orchestrator.py    # TodoOrchestrator 主类
│   │   ├── ai_orchestrator.py        # AISchedulerMixin（AI 调度）
│   │   └── orchestrator_common.py    # SessionHelper、create_ai_client 等
│   │
│   ├── task_executor/           # 任务执行器
│   │   ├── simple_task_executor.py   # SimpleTaskExecutor
│   │   ├── nested_task_executor.py   # NestedTaskExecutor
│   │   ├── looping_task_executor.py  # LoopingTaskExecutor
│   │   ├── subtask_executor.py       # SubtaskExecutor（子任务分发）
│   │   └── task_executor_common.py   # 共享工具函数和类型
│   │
│   ├── ai_client/               # AI 客户端抽象层
│   │   ├── ai_providers.py          # AIProvider 基类及各 Provider 实现
│   │   ├── ai_client.py             # AIClient（CLI 子进程模式）
│   │   ├── ai_client_sdk.py         # AIClientSDK（SDK 模式）
│   │   ├── ai_client_test.py        # AIClientTest（测试模式）
│   │   └── ai_client_common.py      # 异常类型和共享常量
│   │
│   ├── ideas/                   # Ideas 系统
│   │   ├── ideas_watcher.py         # IdeasWatcher（文件监听 + 处理）
│   │   ├── ideas_decomposer.py      # IdeasDecomposerMixin（AI 拆解）
│   │   └── ideas_reviewer.py        # IdeasReviewerMixin（AI 审查）
│   │
│   ├── state_manager/           # 状态管理
│   │   └── state_manager.py         # StateManager（YAML 持久化）
│   │
│   ├── logger/                  # 日志系统
│   │   ├── conversation_logger.py         # ConversationLogger
│   │   └── schedule_aware_conv_logger.py  # ScheduleAwareConvLogger
│   │
│   ├── prompts/                 # Prompt 模板
│   │   ├── shared.py                # 系统 prompt 构建、公共工具
│   │   ├── simple_task.py           # 简单任务 prompt
│   │   ├── long_running_task.py     # 长时间任务 prompt
│   │   ├── failure_analysis.py      # 失败分析 prompt
│   │   ├── main_evaluation.py       # 主任务评估 prompt
│   │   ├── scheduler.py            # AI 调度 prompt
│   │   ├── marker_nudge.py         # 标记提醒 prompt
│   │   ├── timeout_continuation.py  # 超时续传 prompt
│   │   ├── ideas_decompose.py      # Ideas 拆解 prompt
│   │   └── ideas_review.py         # Ideas 审查 prompt
│   │
│   └── util/                    # 工具模块
│       ├── default_value.py         # DEFAULTS 字典、默认配置模板
│       ├── truncation_limits.py     # Prompt 截断限制
│       └── autoagent_exec.py        # 长时间任务启动器
│
├── doc/                         # 文档
│   ├── INDEX.md                     # 文档索引
│   ├── ARCHITECTURE.md              # 系统架构
│   ├── USAGE.md                     # 使用指南
│   ├── EXAMPLES.md                  # 使用示例
│   ├── FILES.md                     # 文件结构（本文档）
│   ├── PROMPT.md                    # Prompt 工程
│   └── ai_orchestrator/
│       └── DESIGN.md                # AI 调度器设计方案
│
├── task_design_guide/           # 任务设计指南（供 AI 消费）
│   ├── TASK_DESIGN_GUIDE.md         # 线性模式任务设计指南
│   ├── TASK_DESIGN_GUIDE_AI_SCHED.md # AI 调度模式任务设计指南
│   ├── build_and_ship.md            # 构建与发布模式
│   ├── data_pipelines.md            # 数据管线模式
│   ├── iterative_optimization.md    # 迭代优化模式
│   ├── research_and_analysis.md     # 研究与分析模式
│   ├── setup_and_deployment.md      # 环境与部署模式
│   └── testing_and_verification.md  # 测试与验证模式
│
├── sample/                      # 示例项目
│   ├── mini_compiler/
│   ├── cufftdx_optimization/
│   └── ai_cufftdx_optimization/
│
└── test/                        # 测试
    ├── run_test.py
    └── simulation_test/
```

---

## 核心模块说明

### `src/orchestrator.py` — CLI 入口

项目的唯一入口点。`main()` 函数负责：
- 解析命令行参数
- 加载 `config.yaml` 配置
- 合并 Preset 配置
- 创建 AI Provider 和 TodoOrchestrator
- 根据模式分发执行（线性 / AI 调度 / Idle）

### `src/orchestrator/` — 编排器包

| 文件 | 职责 |
|------|------|
| `linear_orchestrator.py` | `TodoOrchestrator` 主类：任务加载、验证、线性执行、Ideas 处理 |
| `ai_orchestrator.py` | `AISchedulerMixin`：AI 调度循环、决策获取、两级重试、孤儿恢复 |
| `orchestrator_common.py` | `SessionHelper`（会话管理）、`create_ai_client()`（工厂函数） |

### `src/task_executor/` — 任务执行器包

| 文件 | 职责 |
|------|------|
| `simple_task_executor.py` | 简单任务执行：AI 自评估循环、标记提醒、长时间任务委托 |
| `nested_task_executor.py` | 嵌套任务执行：子任务顺序执行 + AI 失败分析 + 主任务评估 |
| `looping_task_executor.py` | 循环任务执行：固定 N 轮迭代 |
| `subtask_executor.py` | 子任务分发：按类型路由到对应执行器，处理长时间任务 |
| `task_executor_common.py` | 共享类型（`SubtaskResult`、异常类）、工具函数 |

### `src/ai_client/` — AI 客户端包

| 文件 | 职责 |
|------|------|
| `ai_providers.py` | `AIProvider` 基类 + 5 个 Provider 实现 + `TestProvider` + model 名称校验 |
| `ai_client.py` | `AIClient`：CLI 子进程模式，流式解析 AI 输出 |
| `ai_client_sdk.py` | `AIClientSDK`：CodeBuddy SDK 直接调用模式 |
| `ai_client_test.py` | `AIClientTest`：测试模式，读取预定义响应 |
| `ai_client_common.py` | 异常层次结构、默认模型常量 |

### `src/ideas/` — Ideas 系统包

| 文件 | 职责 |
|------|------|
| `ideas_watcher.py` | `IdeasWatcher`：监听 ideas.md、协调拆解-审查-验证流程 |
| `ideas_decomposer.py` | `IdeasDecomposerMixin`：AI 将自然语言 idea 转为结构化任务 |
| `ideas_reviewer.py` | `IdeasReviewerMixin`：AI 审查生成的任务质量 |

### `src/prompts/` — Prompt 模板包

所有 AI 交互的 prompt 构建逻辑集中在此。每个文件对应一种 prompt 类型。详见 [PROMPT.md](PROMPT.md)。

### `src/util/` — 工具包

| 文件 | 职责 |
|------|------|
| `default_value.py` | `DEFAULTS` 字典（所有默认值的唯一真相源）、配置模板生成 |
| `truncation_limits.py` | Prompt 字段截断限制 |
| `autoagent_exec.py` | 长时间任务启动脚本：快速失败检测、信号文件、后台分离、stdout/stderr 分离、防御性重定向检测 |

---

## 配置文件

### `config.yaml`

全局配置文件，包含以下部分：

| 部分 | 内容 |
|------|------|
| General | `system_prompt_prefix`、`default_model`、`truncation_limits` |
| Timeout & Wait | `session_timeout`、`bash_timeout`、`fast_fail_timeout`、`backoff_max_wait`、`idle_interval` |
| Max Rounds & Retries | `max_plan_retries`、`max_review_rounds`、`max_validation_retries`、`default_max_attempts`、`max_marker_nudges` |
| AI Scheduler | `scheduler_history_limit`、`scheduler_decision_max_retries`、`scheduler_max_session_retries` |
| Debug | `autoagent_exec_show_console` |
| Presets | 命名预设配置组合 |

> **注意**：部分默认值（如 `backoff_base`、`signal_check_interval`、`signal_max_wait`、`signal_max_initial_wait`、`max_signal_retry` 等）仅在代码的 `DEFAULTS` 字典中定义，不暴露在 `config.yaml` 中。

### `todos.yaml`（用户创建）

任务定义文件，包含：
- `description`：全局项目描述
- `ai_orchestrator`：AI 调度配置（可选，启用 AI 调度模式）
- `tasks`：任务列表

---

## 运行时目录结构

```
.autoagent/
├── sessions.csv                         # 会话注册表（Tab 分隔：session_id, workspace, created_at, last_accessed_at）
└── <session_name>/
    ├── orchestrator.log                 # 编排器日志
    ├── todos_state.yaml                 # 任务状态持久化
    ├── plans_state.yaml                 # Ideas 处理状态
    ├── previous_subtask_summary.txt     # 子任务间上下文传递
    ├── schedule_history.txt             # AI 调度模式的完整调度历史
    ├── task_results/                    # AI 调度模式的任务结果
    │   └── result_<task_id>.txt
    ├── conversations/                   # AI 对话日志
    │   ├── task_1.md
    │   ├── ai_scheduler/               # AI 调度器决策日志
    │   │   ├── schedule_1.md
    │   │   └── schedule_2.md
    │   └── subtask_1/
    │       ├── task_1.1_round_1.md
    │       ├── failure_analysis_1.2_round_1.md
    │       └── main_task_evaluation_round_1.md
    ├── lr_tasks/                        # 长时间任务产物
    │   ├── lr_<task_id>_signal.json     # 状态信号文件（含 stdout_log/stderr_log 路径）
    │   ├── lr_<task_id>_output.log      # 默认输出日志（stdout+stderr 合并）
    │   ├── <custom_stdout_path>         # --stdout 指定的 stdout 输出（可选）
    │   └── <custom_stderr_path>         # --stderr 指定的 stderr 输出（可选）
    └── scripts/
        └── autoagent-exec.{bat,sh}      # 长时间任务启动脚本
```
