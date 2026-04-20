# 系统架构

本文档描述 AutoAgent 的系统架构设计。

---

## 1. 架构总览

AutoAgent 采用 **编排器-执行器** 模式，通过 Mixin 组合实现功能扩展：

```
┌──────────────────────────────────────────────────────────┐
│              orchestrator.py (CLI 入口)                   │
│         参数解析 · 配置加载 · Preset 合并 · 模式分发        │
└────────────────────────┬─────────────────────────────────┘
                         │ 创建
                         ▼
┌─────────────────────────────────────────────────────────┐
│           TodoOrchestrator (AISchedulerMixin)           │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐   │
│  │ StateManager│  │ ConvLogger   │  │ IdeasWatcher  │   │
│  └─────────────┘  └──────────────┘  └───────────────┘   │
│                                                         │
│  三种执行模式：                                          │
│  • run()             — 线性顺序执行                      │
│  • run_ai_scheduled() — AI 调度执行                      │
│  • run_with_idle()   — Idle 监听模式                     │
└────────────┬────────────────────────────────────────────┘
             │ 按任务类型分发
     ┌───────┼───────────┐
     ▼       ▼           ▼
┌────────┐ ┌──────────┐ ┌──────────┐
│Simple  │ │ Nested   │ │ Looping  │
│Executor│ │ Executor │ │ Executor │
└───┬────┘ └────┬─────┘ └────┬─────┘
    │           │             │
    └───────────┼─────────────┘
                ▼
        ┌───────────────┐
        │SubtaskExecutor│  按子任务类型分发
        └──────┬────────┘
               │
               ▼
        ┌──────────────┐
        │  AIClient /  │  AI Provider 抽象
        │  AIClientSDK │
        └──────────────┘
```

---

## 2. 核心组件

### 2.1 TodoOrchestrator

**位置**：`src/orchestrator/linear_orchestrator.py`

系统的核心编排类，继承 `AISchedulerMixin`。职责：

- 加载和验证 `todos.yaml` 任务定义
- 管理任务执行生命周期
- 按任务类型分发到对应执行器
- 协调状态持久化和日志记录
- 处理 Ideas 监听和任务追加

**关键设计决策**：
- 每个任务创建独立的 `AIClient` 实例，实现对话上下文隔离
- 通过 `SessionHelper` 静态方法管理会话目录
- 支持断点续传：保存 `session_id` 和 `interrupt_pending` 标记

### 2.2 AISchedulerMixin

**位置**：`src/orchestrator/ai_orchestrator.py`

Mixin 类，为 `TodoOrchestrator` 提供 AI 驱动的任务调度能力。

**调度循环**：
```
初始化/恢复编排器状态
    ↓
检查中断任务 → 恢复执行
    ↓
检测孤儿信号文件 → 恢复
    ↓
┌─ While current_round < max_rounds:
│   ├── 重新加载 todos（Ideas 可能追加了新任务）
│   ├── 调用 _get_scheduler_decision() → AI 决定下一个任务
│   ├── action="stop" → 记录并退出
│   ├── action="execute" → _execute_scheduled_task()
│   ├── 记录结果到 schedule_history
│   └── 持久化编排器状态
└─ 生成任务统计摘要
```

**两级重试策略**：

| 级别 | 触发条件 | 行为 |
|------|---------|------|
| Level-1（会话内） | JSON 解析失败、无效 action/task_id、BashTimeout、StreamTimeout | 同一 AI 会话内重试，发送错误反馈 |
| Level-2（会话重置） | SessionTimeout、其他 AICallError、Level-1 耗尽 | 创建新 AI 会话，重发完整 prompt |

> `RateLimitError`（429/503）不消耗重试次数，由内部指数退避处理。

### 2.3 任务执行器

#### SimpleTaskExecutor

**位置**：`src/task_executor/simple_task_executor.py`

执行简单任务的 AI 自评估循环：

```
构建 prompt → 调用 AI → 检查完成标记
    ↓
✅ completed → 成功
❌ not completed → 重试（会话重置）
⏳ LONG_RUNNING_IN_PROGRESS → 委托 SubtaskExecutor
无标记 → 标记提醒（同会话轻量跟进）
```

**标记提醒机制**：当 AI 完成工作但忘记输出状态标记时，发送轻量级跟进 prompt（同一会话），避免昂贵的会话重置。最多 `max_marker_nudges` 次（默认 3）。

#### NestedTaskExecutor

**位置**：`src/task_executor/nested_task_executor.py`

执行包含子任务的嵌套任务，有两个 AI 决策点：

1. **失败分析**：子任务失败时，AI 分析原因并决定从哪个子任务重试
2. **主任务评估**：所有子任务完成后，AI 评估主任务是否达标

**已完成子任务状态前传**：当 AI 决定从某个子任务重试时，之前已完成的子任务状态会被复制到新轮次，避免重复执行。

#### LoopingTaskExecutor

**位置**：`src/task_executor/looping_task_executor.py`

执行固定 N 轮迭代的循环任务。与 Nested 类似但更简单：
- 无主任务评估（跑完 `repeat_count` 轮即结束）
- 每轮重置所有子任务状态
- 单轮内失败触发 AI 失败分析

#### SubtaskExecutor

**位置**：`src/task_executor/subtask_executor.py`

子任务分发器，按类型路由：
- `simple` / `simple_once` → SimpleTaskExecutor
- `long_running` / `long_running_once` → 后台命令执行 + 信号文件轮询
- `nested` → NestedTaskExecutor（递归嵌套）
- `looping` → LoopingTaskExecutor（递归嵌套）

---

## 3. AI 客户端层

### 3.1 Provider 抽象

```
AIProvider (基类)
├── CodeBuddyProvider   — 默认，支持 system prompt
├── ClaudeCodeProvider  — Claude Code CLI
├── GeminiCLIProvider   — Gemini CLI
├── OpenCodeProvider    — OpenCode CLI
├── CodexProvider       — Codex CLI
└── TestProvider        — 测试用，读取预定义响应
```

每个 Provider 实现 `build_command()` 和 `get_stdin_command()`，封装不同 AI 工具的 CLI 差异。

### 3.2 客户端实现

| 客户端 | 模式 | 适用场景 |
|--------|------|---------|
| `AIClient` | CLI 子进程 | 所有 Provider |
| `AIClientSDK` | SDK 直接调用 | 仅 CodeBuddy |
| `AIClientTest` | 测试模拟 | 自动化测试 |

**会话管理**：通过 `session_id` 实现对话连续性。中断后可恢复同一会话。

### 3.3 异常层次

```
AICallError (基类)
├── BashTimeoutError     — 无输出超时（bash_timeout 秒无新输出）
├── SessionTimeoutError  — 会话总时间超限
├── StreamTimeoutError   — SDK 流超时
└── RateLimitError       — HTTP 429/503
```

---

## 4. 执行模式

### 4.1 线性模式

```
orchestrator.run()
    → 按 ID 顺序遍历任务
    → 跳过已完成的任务
    → 每个任务创建独立 AIClient
    → 分发到对应执行器
    → 更新状态
```

### 4.2 AI 调度模式

```
orchestrator.run_ai_scheduled()
    → AI 调度器决定下一个任务
    → 使用 scheduler 模型角色
    → 任务 ID 加调度轮次前缀（状态隔离）
    → 持续直到 AI 返回 stop 或达到 max_rounds
```

**状态隔离**：AI 调度模式下，任务 ID 加上调度轮次前缀（如 `3.1` = 第 3 轮执行任务 1），确保同一任务多次执行时状态互不干扰。

### 4.3 Idle 监听模式

```
orchestrator.run_with_idle()
    → 处理 ideas.md 中的新想法
    → 执行所有待处理任务
    → 进入轮询循环（idle_interval 间隔）
    → 检测到新 idea → 拆解 → 追加 → 执行
    → 直到 Ctrl+C
```

---

## 5. 状态管理

### 5.1 StateManager

**位置**：`src/state_manager/state_manager.py`

YAML 持久化的状态管理器，线程安全，原子写入（写临时文件 → fsync → 重命名）。

### 5.2 状态键设计

| 场景 | 键格式 | 示例 |
|------|--------|------|
| 顶层任务 | `"task_id"` | `"1"` |
| 轮次作用域子任务 | `"task_id@round_label"` | `"1.2@3.1"` |
| AI 调度轮次前缀 | `"round.task_id"` | `"3.1"` |
| `*_once` 子任务 | `"task_id"`（无轮次前缀） | `"1.1"` |

`*_once` 类型使用全局键（不加轮次前缀），确保跨轮次只执行一次。

### 5.3 编排器状态

AI 调度模式额外维护编排器级别状态：

```yaml
orchestrator:
  mode: ai
  current_round: 5
  max_rounds: 50
  status: in_progress | stopped | completed
  session_id: "scheduler-session-xyz"
  schedule_history:
    - round: 1
      task_id: "1"
      task_name: "Task 1"
      result: success | failed | stopped
      reasoning: "..."
      timestamp: "2026-04-20 10:20:00"
  task_execution_counts:
    "1": 2
    "2": 1
```

---

## 6. AI 决策点

系统中有四个 AI 自主决策点：

| 决策点 | 触发场景 | AI 输出 | 使用模型角色 |
|--------|---------|---------|-------------|
| **任务调度** | AI 调度模式每轮 | `{action, task_id, reasoning}` | `scheduler` |
| **失败分析** | Nested/Looping 子任务失败 | `{retry_from, suggested_fix}` | `evaluation` |
| **主任务评估** | Nested 所有子任务完成 | `{main_task_completed, next_strategy}` | `evaluation` |
| **任务完成** | Simple 任务执行后 | `✅` / `❌` / `⏳` 标记 | `default` / `lite` |

---

## 7. 长时间任务处理

长时间任务通过 `autoagent-exec` 机制实现后台运行：

```
AI 调用 autoagent-exec --task-id <id> --cmd <command>
    ↓
autoagent-exec 启动命令
    ↓
快速失败检测（fast_fail_timeout 秒内）
    ├── 命令失败 → 立即报错
    └── 命令存活 → 后台分离
    ↓
写入信号文件（starting → running → finished/error）
    ↓
SubtaskExecutor 轮询信号文件
    ↓
命令完成 → AI 分析输出日志
```

**信号文件**：`<session_dir>/lr_tasks/lr_<task_id>_signal.json`
**输出日志**：`<session_dir>/lr_tasks/lr_<task_id>_output.log`

---

## 8. 上下文管理策略

| 策略 | 实现方式 |
|------|---------|
| 任务间隔离 | 每个任务创建独立 AIClient |
| 子任务间隔离 | 每个子任务重置会话 |
| 子任务间传递 | `previous_subtask_summary.txt` 文件 |
| 超时后续传 | 同会话发送轻量续传 prompt |
| 中断后恢复 | 保存 session_id，恢复同一会话 |
| Prompt 截断 | `truncation_limits` 控制各字段长度 |

---

## 9. 模型角色系统

支持五种模型角色，按职责分配不同模型：

| 角色 | 用途 | 典型选择 |
|------|------|---------|
| `plan` | Ideas 拆解 | 强推理模型 |
| `default` | 任务执行 | 强推理模型 |
| `lite` | 轻量操作（编译、跑命令） | 便宜模型 |
| `evaluation` | 失败分析、主任务评估 | 强推理模型 |
| `scheduler` | AI 调度决策 | 强推理模型 |

支持全局指定和逐任务覆盖。

---

## 10. 重试与容错

### 超时处理

| 超时类型 | 行为 |
|---------|------|
| `BashTimeoutError` | 会话仍存活，发送续传 prompt |
| `StreamTimeoutError` | 会话仍存活，发送续传 prompt |
| `SessionTimeoutError` | 会话已死，重置后重试 |
| `RateLimitError` | 不消耗重试次数，指数退避 |

### 中断恢复

- `Ctrl+C`：保存 session_id 和 interrupt_pending 标记
- `--continue`：从上次会话继续
- `--resume <id>`：恢复指定会话
- 孤儿信号文件检测：非正常退出后恢复后台任务

---

## 11. Ideas 处理流程

```
ideas.md 变化检测（SHA-256 哈希比对）
    ↓
AI 拆解（plan 模型）→ 生成结构化任务 YAML
    ↓
AI 审查（review 模型）→ 质量评估
    ↓
可选人工审核（--human-review）
    ↓
Schema 验证
    ↓
追加到 todos.yaml → 自动递增 ID
    ↓
从 ideas.md 移除已处理的 idea
```
