# API 参考文档

本文档提供 CodeBuddy Todo Orchestrator 的完整 API 参考。

## 目录

- [TodoOrchestrator](#todoorchestrator)
- [CodeBuddyClient](#codebuddyclient)
- [任务执行器](#任务执行器)
- [ConversationLogger](#conversationlogger)
- [IdeasWatcher](#ideaswatcher)
- [状态类型](#状态类型)
- [配置类型](#配置类型)
- [异常类](#异常类)

## TodoOrchestrator

任务编排器，负责加载配置、调度任务、管理状态。

### 类定义

```python
class TodoOrchestrator:
    def __init__(
        self,
        todos_file: str = "todos.yaml",
        state_file: str = "todos_state.yaml",
        codebuddy_path: str = "codebuddy",
        model: str = "glm-5.0-ioa",
        workspace: str = ".",
        timeout: int = 3600,
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = 30,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `state_file` | str | "todos_state.yaml" | 状态持久化文件路径 |
| `codebuddy_path` | str | "codebuddy" | CodeBuddy 可执行文件路径 |
| `model` | str | "glm-5.0-ioa" | AI 模型 |
| `workspace` | str | "." | 工作目录 |
| `timeout` | int | 3600 | AI 调用超时时间（秒） |
| `log_dir` | str | None | 对话日志根目录（None 则禁用） |
| `ideas_file` | str | None | ideas.md 文件路径（None 则禁用 ideas 监控） |
| `idle_interval` | int | 30 | idle 模式检查间隔（秒） |

### 方法

#### load_todos / reload_todos

```python
def _load_todos(self, allow_empty: bool = False) -> list
def reload_todos(self) -> None
```

加载任务配置。`_load_todos` 从 YAML 文件加载并验证；`reload_todos` 在新任务追加后重新加载。`allow_empty=True` 时允许空配置（用于 idle 模式）。

#### load_state / save_state

```python
def load_state(self) -> dict
def save_state(self) -> None
```

加载/保存任务状态文件，支持断点续传。

#### run

```python
def run(
    self,
    task_id: int = None,
    skip_completed: bool = True,
) -> dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_id` | int | None | 执行单个任务（None 则执行所有） |
| `skip_completed` | bool | True | 跳过已完成的任务 |

**返回值**：

```python
{
    "total_tasks": 5,
    "successful_tasks": 4,
    "failed_tasks": 1,
    "results": { 1: True, 2: True, 3: False },
    "duration": 3600.5
}
```

#### execute_task

```python
def execute_task(self, task: dict) -> bool
```

执行单个任务，根据 `task['type']` 分发到对应的执行器。

#### get_status / reset

```python
def get_status(self) -> dict
def reset(self) -> None
```

获取当前执行状态 / 重置所有状态（包括 ideas 处理记录）。

#### check_and_process_ideas

```python
def check_and_process_ideas(self) -> int
```

检查 ideas.md 是否有新内容，如果有则调用 AI 分解为 TODO 任务并追加到 todos.yaml。返回处理的新 idea 数量。

#### run_with_idle

```python
def run_with_idle(
    self,
    task_id: int = None,
    skip_completed: bool = True,
) -> None
```

运行所有待处理任务，然后进入 idle 模式持续等待新 ideas。循环流程：处理新 ideas → 执行任务 → idle 等待 → 检测到变化后循环。通过 Ctrl+C 退出。

---

## CodeBuddyClient

CodeBuddy 调用客户端，封装 AI 能力和 Context 管理。

### 类定义

```python
class CodeBuddyClient:
    def __init__(
        self,
        codebuddy_path: str = "/root/.local/bin/codebuddy",
        model: str = "glm-4.7",
        workspace: str = "/data/workspace",
        timeout: int = 3600,
        context_id: str = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `codebuddy_path` | str | "/root/.local/bin/codebuddy" | CodeBuddy 可执行文件路径 |
| `model` | str | "glm-4.7" | 使用的模型 |
| `workspace` | str | "/data/workspace" | 工作目录 |
| `timeout` | int | 3600 | 超时时间（秒） |
| `context_id` | str | None | Context 标识符，用于状态记录和日志追踪（注意：`--continue` 只能继续最近一次对话，不支持指定 context ID） |

### Context 管理策略

| 层级 | 策略 | 说明 |
|------|------|------|
| 主任务 | 独立 context | 每个主任务创建独立的 CodeBuddyClient，互不干扰 |
| 子任务 | 共享 context | 同一主任务内的子任务使用 `--continue` 共享上下文 |

```python
# 主任务 1
client1 = CodeBuddyClient(context_id="task_1")
client1.ask("修改模型代码", continue_session=False)   # 创建新 context
client1.ask("检查修改结果", continue_session=True)    # 复用 context

# 主任务 2（完全隔离）
client2 = CodeBuddyClient(context_id="task_2")
client2.ask("修改另一个模型", continue_session=False)  # 独立 context
```

### 方法

#### ask

向 CodeBuddy 提问。

```python
def ask(
    self,
    prompt: str,
    expect_json: bool = False,
    timeout: int = None,
    continue_session: bool = False,
) -> Union[str, dict]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | str | - | 提示词 |
| `expect_json` | bool | False | 是否期望 JSON 响应 |
| `timeout` | int | None | 超时时间（覆盖默认值） |
| `continue_session` | bool | False | 是否使用 `--continue` 保持上下文 |

**命令构造**：

```bash
# continue_session=False（新 context）
codebuddy -m "glm-4.7" -y "<prompt>"

# continue_session=True（复用 context）
codebuddy --continue -m "glm-4.7" -y "<prompt>"
```

**示例**：

```python
client = CodeBuddyClient(context_id="task_2")

# 第一次调用：创建新 context
result = client.ask("请阅读 program.md 并开始执行任务 2", continue_session=False)

# 后续调用：复用 context
result = client.ask("检查子任务 2.1 的结果", continue_session=True)

# 获取结构化 JSON 响应
decision = client.ask("分析失败原因", expect_json=True, continue_session=True)
print(decision['retry_from'])
```

---

## 任务执行器

### SimpleTaskExecutor

执行简单任务（simple 类型），AI 自主判断完成条件。

```python
class SimpleTaskExecutor:
    def execute(self, task: dict, client: CodeBuddyClient) -> bool
```

**执行逻辑**：

```python
attempts = 0
max_attempts = task.get('max_attempts', 20)

while attempts < max_attempts:
    result = client.ask(prompt, continue_session=(attempts > 0))
    if is_completed(result):
        return True
    attempts += 1

return False
```

### NestedTaskExecutor

执行嵌套任务（nested 类型），包含 AI 决策机制。

```python
class NestedTaskExecutor:
    def execute(self, task: dict, client: CodeBuddyClient) -> bool
```

**两个 AI 决策点**：

1. **子任务失败时** → 调用 AI 分析失败原因，返回 `retry_from`
2. **所有子任务完成后** → 调用 AI 评估主任务，返回 `main_task_completed` 和 `retry_from`

**AI 失败分析请求格式**：

```python
# 系统提供的上下文
context = {
    "failed_subtask": { "id": "2.2", "exit_code": 137, "error_log": "..." },
    "task_history": [...],
    "related_files": [...]
}
```

**AI 失败分析响应格式**：

```json
{
    "analysis": "失败原因描述",
    "retry_from": "task_2.1",
    "reasoning": "推理过程",
    "suggested_fix": "修复建议",
    "confidence": "high"
}
```

**AI 主任务评估响应格式**：

```json
{
    "main_task_completed": false,
    "analysis": "结果分析",
    "retry_from": "task_2.1",
    "next_strategy": "优化方向",
    "suggested_improvements": ["建议1", "建议2"],
    "confidence": "medium"
}
```

### SubtaskExecutor

执行单个子任务，根据子任务类型分发。

```python
class SubtaskExecutor:
    def execute(self, subtask: dict, client: CodeBuddyClient) -> SubtaskResult
```

支持的子任务类型：

| 类型 | 说明 | 执行方式 |
|------|------|----------|
| `simple` | AI 自主完成（含代码修改、命令执行等） | 调用 `client.ask()` |
| `long_running` | 长时间任务 | `nohup` 后台 + 监控 + AI 判断 |

---

## ConversationLogger

对话日志记录器，将 AI 交互的完整内容输出到 Markdown 文件。

### 类定义

```python
class ConversationLogger:
    def __init__(self, log_root_dir: str)
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `log_root_dir` | str | - | 日志根目录（如 "logs"） |

初始化时会自动创建 `<log_root_dir>/<YYYYMMDDHHmm>/` 时间戳会话目录。

### 方法

#### log_conversation

```python
def log_conversation(
    self,
    task_id: str,
    task_name: str,
    prompt: str,
    response: str,
    attempt: int,
    parent_task_id: Optional[str] = None,
    metadata: Optional[dict] = None,
)
```

记录一次对话（prompt + response）。对于顶层简单任务，写入 `task_<id>.md`；对于嵌套任务的子任务，写入 `subtask_<parent_id>/task_<id>.md`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `task_name` | str | 任务名称 |
| `prompt` | str | 发送给 AI 的提示词 |
| `response` | str | AI 的响应 |
| `attempt` | int | 尝试次数 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |
| `metadata` | dict | 额外信息（如 `{"type": "failure_analysis"}`） |

#### log_nested_task_ai_call

```python
def log_nested_task_ai_call(
    self,
    task_id: str,
    task_name: str,
    call_type: str,
    prompt: str,
    response: str,
    round_num: int,
    metadata: Optional[dict] = None,
)
```

记录嵌套任务的 AI 决策调用（失败分析、主任务评估），写入 `subtask_<id>/_decisions.md`。

#### register_nested_task

```python
def register_nested_task(self, task_id: str, task_name: str, subtask_ids: list)
```

注册嵌套任务及其子任务 ID 列表，创建子任务目录并准备索引文件。

#### build_index_file / finalize

```python
def build_index_file(self, task_id: str)
def finalize(self)
```

构建/重建嵌套任务的索引文件（含子任务和 AI 决策的链接）。`finalize()` 在执行结束时调用，重建所有索引。

---

## IdeasWatcher

Ideas 文件监控器，监控 ideas.md 并通过 AI 将想法分解为结构化 TODO 任务。

### 类定义

```python
class IdeasWatcher:
    def __init__(
        self,
        ideas_file: str = "ideas.md",
        todos_file: str = "todos.yaml",
        processed_state_file: str = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ideas_file` | str | "ideas.md" | Ideas 文件路径 |
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `processed_state_file` | str | ".ideas_processed.yaml" | 已处理状态记录文件 |

### 方法

#### has_new_ideas

```python
def has_new_ideas(self) -> bool
```

检查 ideas.md 是否在上次检查后被修改。基于文件修改时间的快速检测。

#### parse_ideas

```python
def parse_ideas(self) -> List[dict]
```

解析 ideas.md，提取各个 idea 段落。返回未处理 ideas 的列表，每项包含：

```python
{
    'title': str,     # 标题（来自 heading 或首行）
    'content': str,   # 原始内容
    'body': str,      # 正文（不含标题）
    'hash': str,      # SHA256 hash（前 16 位，用于去重）
}
```

#### process_new_ideas

```python
def process_new_ideas(self, client: CodeBuddyClient) -> int
```

处理所有新 ideas：解析 → 调用 AI 分解 → 追加到 todos.yaml。返回处理的 idea 数量。

#### mark_all_processed / reset

```python
def mark_all_processed(self)
def reset(self)
```

标记所有当前 ideas 为已处理（不生成任务） / 重置所有处理状态。

---

## 状态类型

### TaskState

任务状态结构（持久化在 `todos_state.yaml` 中）。

```python
class TaskState(TypedDict, total=False):
    status: str           # "pending" | "in_progress" | "completed" | "failed"
    attempts: int         # 尝试次数
    max_attempts: int     # 最大尝试次数
    context_id: str       # CodeBuddy context 标识
    last_attempt: str     # 最后一次尝试时间
    subtasks: list        # 子任务状态列表（嵌套任务）
    ai_decisions: list    # AI 决策记录
    main_task_evaluations: list  # 主任务评估记录
```

### SubtaskState

```python
class SubtaskState(TypedDict, total=False):
    status: str           # "pending" | "in_progress" | "completed" | "failed"
    attempts: int
    error_type: str       # "timeout" | "oom" | "crash" | "validation_failed"
    log_file: str         # 日志文件路径（long_running 类型）
    pid_file: str         # PID 文件路径（long_running 类型）
    ai_reasoning: str     # AI 的推理记录
    history: list         # 执行历史
```

> **注意**：`in_progress` 状态同时覆盖"正在执行命令"和"长时间任务正在后台运行"两种场景。可通过 `log_file` 和 `pid_file` 字段区分是否为长时间任务。

---

## 配置类型

### TaskConfig

```python
class TaskConfig(TypedDict, total=False):
    id: Union[int, str]                               # 必填，唯一标识
    name: str                                          # 必填，任务名称
    type: Literal["simple", "nested"]                  # 必填，任务类型
    completion_criteria: str                            # 必填，完成标准
    initial_hint: str                                  # simple 可选
    max_attempts: int                                  # 可选，默认 20
    subtasks: List['SubtaskConfig']                    # nested 必填
```

### SubtaskConfig

```python
class SubtaskConfig(TypedDict, total=False):
    id: Union[int, str]                                # 必填
    name: str                                          # 必填
    type: Literal["simple", "long_running"]            # 必填
    completion_criteria: str                            # 必填
    command: str                                       # long_running 必填
    initial_hint: str                                  # simple 可选
    max_attempts: int                                  # 可选，默认 5
```

---

## 异常类

```python
class ConfigError(Exception):
    """配置文件错误（YAML 语法、缺少字段等）"""

class ExecutionError(Exception):
    """任务执行错误（命令失败、超时等）"""

class AICallError(Exception):
    """CodeBuddy 调用错误（认证失败、响应解析失败等）"""
```

---

## 完整使用示例

```python
from orchestrator import TodoOrchestrator

# 1. 基本用法：创建 Orchestrator 并运行所有任务
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    state_file="todos_state.yaml",
)

results = orchestrator.run(skip_completed=True)
print(f"成功: {results['successful_tasks']} / 失败: {results['failed_tasks']}")

# 2. 带对话日志：记录所有 AI 交互
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    log_dir="logs",
)
results = orchestrator.run()
if orchestrator.conv_logger:
    orchestrator.conv_logger.finalize()

# 3. 带 Ideas 监控：自动处理 ideas.md
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    ideas_file="ideas.md",
)
orchestrator.check_and_process_ideas()  # 处理新 ideas 后运行任务
results = orchestrator.run()

# 4. Idle 模式：持续运行等待新 ideas
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    ideas_file="ideas.md",
    idle_interval=30,
)
orchestrator.run_with_idle()  # 不会退出，直到 Ctrl+C
```

---

## 总结

| 组件 | 职责 |
|------|------|
| **TodoOrchestrator** | 任务调度、状态管理、配置解析、ideas 处理、idle 模式 |
| **CodeBuddyClient** | AI 调用、Context 管理、命令构造 |
| **SimpleTaskExecutor** | 简单任务执行 |
| **NestedTaskExecutor** | 嵌套任务执行、AI 决策调度 |
| **SubtaskExecutor** | 子任务分发执行 |
| **ConversationLogger** | 对话日志记录、索引生成 |
| **IdeasWatcher** | ideas.md 监控、AI 分解、任务追加 |

如有其他问题，请参考：
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
