# API 参考

本文档是 AutoAgent 各模块的公开接口参考。

---

## 1. 编排器层

### TodoOrchestrator

**位置**：`src/orchestrator/linear_orchestrator.py`

```python
class TodoOrchestrator(AISchedulerMixin):
    def __init__(self, todos_file, provider, workspace, timeout, bash_timeout,
                 session_dir, ideas_file, use_cli, backoff_max_wait,
                 model_roles, default_max_attempts, ...)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `todos_file` | str | todos.yaml 路径 |
| `provider` | AIProvider | AI Provider 实例 |
| `workspace` | str | AI 工作目录 |
| `timeout` | int | 会话超时（秒） |
| `bash_timeout` | int | 无输出超时（秒） |
| `session_dir` | str | 会话输出目录 |
| `ideas_file` | str \| None | ideas.md 路径 |
| `use_cli` | bool | 是否使用 CLI 子进程模式 |
| `backoff_max_wait` | int | 最大退避等待（秒） |
| `model_roles` | dict | 模型角色映射 |
| `default_max_attempts` | int | 默认最大重试次数 |

**主要方法**：

| 方法 | 说明 |
|------|------|
| `run(task_id=None)` | 线性执行所有任务（或指定任务） |
| `run_ai_scheduled()` | AI 调度执行（来自 AISchedulerMixin） |
| `run_with_idle()` | Idle 监听模式 |
| `execute_task(task, client)` | 执行单个任务 |
| `validate_config()` | 验证 todos.yaml 配置 |
| `reset()` | 重置所有任务状态 |
| `check_and_process_ideas()` | 处理 ideas.md 中的新想法 |

### AISchedulerMixin

**位置**：`src/orchestrator/ai_orchestrator.py`

| 方法 | 说明 |
|------|------|
| `run_ai_scheduled()` | AI 调度主循环 |
| `_get_scheduler_decision()` | 获取 AI 调度决策（两级重试） |
| `_execute_scheduled_task(task, round_num)` | 执行调度选中的任务 |
| `_build_scheduled_task(task, round_num)` | 构建带轮次前缀的任务 |
| `_parse_scheduler_response(response)` | 解析 AI 返回的 JSON |
| `_detect_orphan_signal_file()` | 检测孤儿信号文件 |

### SessionHelper

**位置**：`src/orchestrator/orchestrator_common.py`

静态方法类，管理会话目录：

| 方法 | 说明 |
|------|------|
| `generate_session_name(workspace)` | 生成会话名称 |
| `write_marker_file(session_dir)` | 写入 `.autoagent_log` 标记 |
| `read_marker_file(workspace)` | 读取上次会话路径 |
| `register_session(session_dir, workspace)` | 注册到 sessions.csv |
| `list_sessions(log_dir)` | 列出所有会话 |

### create_ai_client()

**位置**：`src/orchestrator/orchestrator_common.py`

```python
def create_ai_client(provider, workspace, timeout, bash_timeout,
                     use_cli, backoff_max_wait, conv_logger, ...) -> AIClient | AIClientSDK | AIClientTest
```

工厂函数，根据 Provider 类型创建对应的 AI 客户端实例。

---

## 2. 任务执行器层

### SimpleTaskExecutor

**位置**：`src/task_executor/simple_task_executor.py`

```python
class SimpleTaskExecutor:
    def __init__(self, session_dir, default_max_attempts)
    def execute(self, task, client, state_manager, ...) -> bool
```

| 方法 | 说明 |
|------|------|
| `execute(task, client, state_manager, ...)` | 执行简单任务，返回是否成功 |

### NestedTaskExecutor

**位置**：`src/task_executor/nested_task_executor.py`

```python
class NestedTaskExecutor:
    def __init__(self, session_dir, model_roles, default_max_attempts)
    def execute(self, task, client, state_manager, ...) -> bool
```

### LoopingTaskExecutor

**位置**：`src/task_executor/looping_task_executor.py`

```python
class LoopingTaskExecutor:
    def __init__(self, session_dir, model_roles, default_max_attempts)
    def execute(self, task, client, state_manager, ...) -> bool
```

### SubtaskExecutor

**位置**：`src/task_executor/subtask_executor.py`

```python
class SubtaskExecutor:
    def __init__(self, session_dir, simple_executor, model_roles, default_max_attempts)
    def execute_subtask(self, subtask, client, state_manager, ...) -> SubtaskResult
```

### SubtaskResult

**位置**：`src/task_executor/task_executor_common.py`

```python
@dataclass
class SubtaskResult:
    success: bool
    output: str
    logs: str
    error_type: str | None
    response_text: str
```

---

## 3. AI 客户端层

### AIProvider（基类）

**位置**：`src/ai_client/ai_providers.py`

```python
class AIProvider:
    name: str
    executable: str
    model: str
    supports_system_prompt: bool

    def build_command(self, session_id, system_prompt) -> list[str]
    def get_stdin_command(self, prompt) -> str
    def set_model(self, model_name)
```

### Provider 实现

| 类 | Provider 名 | 默认可执行文件 | 支持 System Prompt |
|----|------------|--------------|-------------------|
| `CodeBuddyProvider` | `codebuddy` | `codebuddy` | ✅ |
| `ClaudeCodeProvider` | `claude` | `claude` | ✅ |
| `GeminiCLIProvider` | `gemini` | `gemini` | ❌ |
| `OpenCodeProvider` | `opencode` | `opencode` | ❌ |
| `CodexProvider` | `codex` | `codex` | ❌ |
| `TestProvider` | `test` | `test` | ❌ |

**Provider 别名**：`cb` → codebuddy, `claude-code` → claude, `gemini-cli` → gemini, `oc` → opencode

### get_provider()

```python
def get_provider(name, executable=None, model=None, extra_args=None) -> AIProvider
```

### parse_model_spec()

```python
def parse_model_spec(spec: str) -> dict[str, str]
```

解析模型规格字符串为角色映射字典。支持格式：
- 单模型：`"claude-opus-4.6"` → 所有角色使用同一模型
- 多角色：`"plan:M1;default:M2;lite:M3"` → 按角色分配
- 缺失角色继承 `default`

### AIClient

**位置**：`src/ai_client/ai_client.py`

```python
class AIClient:
    def __init__(self, provider, workspace, timeout, bash_timeout, ...)
    def ask(self, prompt, system_prompt=None, expect_json=False) -> str
    def reset_session(self)
    def resume_session(self, session_id)
    @property
    def session_id(self) -> str | None
```

| 方法 | 说明 |
|------|------|
| `ask(prompt, ...)` | 发送 prompt 给 AI，返回响应文本 |
| `reset_session()` | 重置会话（下次 ask 创建新会话） |
| `resume_session(session_id)` | 恢复指定会话 |

### AIClientSDK

**位置**：`src/ai_client/ai_client_sdk.py`

与 `AIClient` 相同接口，使用 CodeBuddy Agent SDK 直接调用。

### 异常类型

**位置**：`src/ai_client/ai_client_common.py`

| 异常 | 说明 |
|------|------|
| `AICallError` | 基类 |
| `BashTimeoutError` | 无输出超时（会话仍存活） |
| `SessionTimeoutError` | 会话总时间超限（会话已死） |
| `StreamTimeoutError` | SDK 流超时（会话仍存活） |
| `RateLimitError` | HTTP 429/503（不消耗重试次数） |

---

## 4. 状态管理

### StateManager

**位置**：`src/state_manager/state_manager.py`

```python
class StateManager:
    ROUND_SEP = "@"

    def __init__(self, state_file: str)

    # 任务状态
    def get_task_state(self, task_id: str) -> dict
    def mark_task_status(self, task_id: str, status: str, **kwargs)
    def update_task_field(self, task_id: str, field: str, value)
    def add_task_history(self, task_id: str, entry: dict)
    def add_ai_decision(self, task_id: str, decision: dict)
    def add_main_task_evaluation(self, task_id: str, evaluation: dict)
    def get_in_progress_tasks(self) -> list[str]
    def record_interrupt(self, task_id: str, session_id: str)

    # 编排器状态
    def get_orchestrator_state(self) -> dict
    def save_orchestrator_state(self, state: dict)

    # 持久化
    def save_state(self)

    # 工具方法
    @staticmethod
    def round_key(task_id: str, round_label: str) -> str
```

**任务状态值**：

| 状态 | 说明 |
|------|------|
| `pending` | 待执行 |
| `in_progress` | 执行中 |
| `completed` | 已完成 |
| `failed` | 已失败 |

---

## 5. Ideas 系统

### IdeasWatcher

**位置**：`src/ideas/ideas_watcher.py`

```python
class IdeasWatcher(IdeasDecomposerMixin, IdeasReviewerMixin):
    def __init__(self, ideas_file, todos_file, plans_state_file, ...)
    def has_new_ideas(self) -> bool
    def process_new_ideas(self, client, ...) -> list[dict]
    def parse_ideas(self) -> list[dict]
```

### IdeasDecomposerMixin

**位置**：`src/ideas/ideas_decomposer.py`

```python
class IdeasDecomposerMixin:
    def _decompose_idea_to_tasks(self, idea, client, ...) -> list[dict]
```

### IdeasReviewerMixin

**位置**：`src/ideas/ideas_reviewer.py`

```python
class IdeasReviewerMixin:
    def _review_and_validate_loop(self, tasks, client, ...) -> list[dict]
    def _review_tasks(self, tasks, client, ...) -> dict
    def _human_review_loop(self, tasks) -> list[dict]
    def _validate_tasks_schema(self, tasks) -> list[str]
```

---

## 6. 日志系统

### ConversationLogger

**位置**：`src/logger/conversation_logger.py`

```python
class ConversationLogger:
    def __init__(self, session_dir)
    def log_prompt(self, task_id, prompt, round_label=None)
    def log_response(self, task_id, response, round_label=None)
    def register_nested_task(self, task_id)
    def finalize(self)
```

### ScheduleAwareConvLogger

**位置**：`src/logger/schedule_aware_conv_logger.py`

```python
class ScheduleAwareConvLogger:
    def __init__(self, conv_logger, schedule_round)
```

包装 `ConversationLogger`，为日志文件名添加调度轮次前缀。

---

## 7. 配置默认值

### DEFAULTS

**位置**：`src/util/default_value.py`

所有默认值的唯一真相源：

| 类别 | 键 | 默认值 |
|------|-----|--------|
| 模型 | `default_model` | `"deepseek-v3.2"` |
| 超时 | `session_timeout` | 3600 |
| | `bash_timeout` | 300 |
| | `fast_fail_timeout` | 30 |
| | `backoff_max_wait` | 600 |
| | `idle_interval` | 30 |
| 信号 | `signal_check_interval` | 15 |
| | `signal_max_wait` | 86400 |
| 重试 | `default_max_attempts` | 5 |
| | `max_marker_nudges` | 3 |
| | `max_plan_retries` | 3 |
| 调度 | `scheduler_history_limit` | 10 |
| | `scheduler_decision_max_retries` | 3 |
| | `scheduler_max_session_retries` | 2 |
| 截断 | `previous_subtask_summary` | 4000 |
| | `history_summary` | 300 |
| | `max` | 50000 |

### 模型角色

| 角色 | 用途 |
|------|------|
| `plan` | Ideas 拆解 |
| `default` | 任务执行 |
| `lite` | 轻量操作 |
| `evaluation` | 失败分析、主任务评估 |
| `scheduler` | AI 调度决策 |
