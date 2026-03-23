# API 参考文档

本文档提供 CodeBuddy Todo Orchestrator 的完整 API 参考。

## 目录

- [TaskOrchestrator](#todoorchestrator)
- [CodeBuddyClient](#codebuddyclient)
- [任务执行器](#任务执行器)
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
        codebuddy_client: CodeBuddyClient = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `state_file` | str | "todos_state.yaml" | 状态持久化文件路径 |
| `codebuddy_client` | CodeBuddyClient | None | CodeBuddy 客户端（默认自动创建） |

### 方法

#### load_todos

```python
def load_todos(self) -> list
```

加载任务配置文件，返回任务列表 `List[dict]`。

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

获取当前执行状态 / 重置所有状态。

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
| `context_id` | str | None | Context 标识符，用于区分不同主任务的对话上下文 |

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
| `ai_action` | AI 修改代码 | 调用 `client.ask()` |
| `simple` | 执行命令 | `subprocess.run()` + AI 判断 |
| `long_running` | 长时间任务 | `nohup` 后台 + 监控 + AI 判断 |

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
    status: str           # "pending" | "in_progress" | "completed" | "failed" | "running"
    attempts: int
    error_type: str       # "timeout" | "oom" | "crash" | "validation_failed"
    log_file: str         # 日志文件路径（long_running 类型）
    ai_reasoning: str     # AI 的推理记录
    history: list         # 执行历史
```

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
    type: Literal["ai_action", "simple", "long_running"]  # 必填
    completion_criteria: str                            # 必填
    command: str                                       # long_running / simple 必填
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
from todo_orchestrator import TodoOrchestrator, CodeBuddyClient

# 1. 创建 Orchestrator
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    state_file="todos_state.yaml",
)

# 2. 验证配置
if not orchestrator.validate_config():
    print("配置无效")
    exit(1)

# 3. 运行所有任务
results = orchestrator.run(skip_completed=True)

print(f"总任务数: {results['total_tasks']}")
print(f"成功: {results['successful_tasks']}")
print(f"失败: {results['failed_tasks']}")

for task_id, success in results['results'].items():
    print(f"  {'✅' if success else '❌'} 任务 {task_id}")
```

---

## 总结

| 组件 | 职责 |
|------|------|
| **TodoOrchestrator** | 任务调度、状态管理、配置解析 |
| **CodeBuddyClient** | AI 调用、Context 管理、命令构造 |
| **SimpleTaskExecutor** | 简单任务执行 |
| **NestedTaskExecutor** | 嵌套任务执行、AI 决策调度 |
| **SubtaskExecutor** | 子任务分发执行 |

如有其他问题，请参考：
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
