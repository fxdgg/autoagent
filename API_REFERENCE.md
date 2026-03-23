# API 参考文档

本文档提供 LangGraph + CodeBuddy Todo Orchestrator 的完整 API 参考。

## 目录

- [TodoOrchestrator](#todoorchestrator)
- [CodeBuddyClient](#codebuddyclient)
- [状态类型](#状态类型)
- [配置类型](#配置类型)
- [节点函数](#节点函数)
- [条件边函数](#条件边函数)

## TodoOrchestrator

任务编排器，负责加载配置、调度任务、管理状态。

### 类定义

```python
class TodoOrchestrator:
    def __init__(
        self,
        todos_file: str = "todos.yaml",
        codebuddy_client: CodeBuddyClient = None,
        state_backend: StateBackend = None
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `codebuddy_client` | CodeBuddyClient | None | CodeBuddy 客户端（默认自动创建） |
| `state_backend` | StateBackend | None | 状态存储后端（默认使用文件存储） |

### 方法

#### load_todos

加载任务配置文件。

```python
def load_todos(self) -> list
```

**返回值**：任务列表 `List[dict]`

**示例**：

```python
orchestrator = TodoOrchestrator()
tasks = orchestrator.load_todos()
print(f"加载了 {len(tasks)} 个任务")
```

**返回格式**：

```python
[
    {
        "id": 1,
        "name": "prepare_data",
        "description": "准备数据集",
        "type": "simple",
        "command": "python prepare_data.py"
    },
    {
        "id": 2,
        "description": "优化模型精度",
        "type": "loop",
        "max_retries": 5,
        "completion_criteria": "accuracy >= 0.9"
    }
]
```

#### execute_task

执行单个任务。

```python
def execute_task(self, task: dict) -> bool
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `task` | dict | 任务配置对象 |

**返回值**：`bool` - 任务是否成功完成

**示例**：

```python
task = {
    "id": 1,
    "description": "准备数据集",
    "type": "simple",
    "command": "python prepare_data.py"
}

orchestrator = TodoOrchestrator()
success = orchestrator.execute_task(task)

if success:
    print("任务完成")
else:
    print("任务失败")
```

#### run

运行任务列表。

```python
def run(
    self,
    task_id: int = None,
    task_ids: list = None,
    skip_completed: bool = False,
    continue_on_failure: bool = True
) -> dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_id` | int | None | 执行单个任务 |
| `task_ids` | list | None | 执行多个任务 |
| `skip_completed` | bool | False | 跳过已完成的任务 |
| `continue_on_failure` | bool | True | 失败后是否继续 |

**返回值**：`dict` - 执行结果摘要

**示例**：

```python
# 运行所有任务
orchestrator = TodoOrchestrator()
results = orchestrator.run()

# 运行单个任务
results = orchestrator.run(task_id=2)

# 运行多个任务
results = orchestrator.run(task_ids=[1, 3, 5])

# 跳过已完成的任务
results = orchestrator.run(skip_completed=True)

# 失败后停止
results = orchestrator.run(continue_on_failure=False)
```

**返回格式**：

```python
{
    "total_tasks": 5,
    "successful_tasks": 4,
    "failed_tasks": 1,
    "skipped_tasks": 0,
    "results": {
        1: True,
        2: True,
        3: False,
        4: True,
        5: True
    },
    "duration": 3600.5
}
```

#### validate_config

验证配置文件。

```python
def validate_config(self) -> bool
```

**返回值**：`bool` - 配置是否有效

**示例**：

```python
orchestrator = TodoOrchestrator()
if orchestrator.validate_config():
    print("配置有效")
else:
    print("配置无效")
```

#### get_status

获取当前执行状态。

```python
def get_status(self) -> dict
```

**返回值**：`dict` - 当前状态

**示例**：

```python
orchestrator = TodoOrchestrator()
status = orchestrator.get_status()
print(status)
```

**返回格式**：

```python
{
    "current_task_id": 3,
    "current_task_name": "optimize_accuracy",
    "progress": "60%",
    "retry_count": 2,
    "max_retries": 5
}
```

#### reset

重置执行状态。

```python
def reset(self) -> None
```

**示例**：

```python
orchestrator = TodoOrchestrator()
orchestrator.reset()  # 清除所有状态
```

## CodeBuddyClient

CodeBuddy 调用客户端，提供统一的 AI 能力接口。

### 类定义

```python
class CodeBuddyClient:
    def __init__(
        self,
        codebuddy_path: str = "/root/.local/bin/codebuddy",
        model: str = "glm-4.7",
        workspace: str = "/data/workspace",
        timeout: int = 3600,
        cache_enabled: bool = False,
        context_id: str = None
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `codebuddy_path` | str | "/root/.local/bin/codebuddy" | CodeBuddy 可执行文件路径 |
| `model` | str | "glm-4.7" | 使用的模型 |
| `workspace` | str | "/data/workspace" | 工作目录 |
| `timeout` | int | 3600 | 超时时间（秒） |
| `cache_enabled` | bool | False | 是否启用缓存 |
| `context_id` | str | None | Context 标识符（用于区分不同的对话上下文） |

### Context 管理策略

**重要设计决策**：

1. **主任务级别的 Context**：
   - 每个主任务创建一个独立的 CodeBuddyClient 实例
   - 每个主任务对应一个独立的 codebuddy context
   - 不同主任务之间的实验完全隔离

2. **子任务级别的 Context 共享**：
   - 同一个主任务的子任务共享同一个 context
   - 子任务执行时使用 `--continue` 参数保持上下文连续性
   - AI 可以记住之前的修改、决策和上下文

3. **Context 生命周期**：
   - 主任务开始时创建新的 context
   - 主任务结束时 context 可以保留或清理
   - 如果支持断点续传，context 可以跨系统重启保留

**示例**：

```python
# 主任务 1：优化模型 A
client1 = CodeBuddyClient(context_id="task_1")
client1.ask("修改模型 A 的代码", continue_session=False)  # 第一次调用，不使用 --continue
client1.ask("检查修改是否正确", continue_session=True)    # 继续在同一 context
client1.ask("评估模型性能", continue_session=True)        # 继续在同一 context

# 主任务 2：优化模型 B（完全独立的 context）
client2 = CodeBuddyClient(context_id="task_2")
client2.ask("修改模型 B 的代码", continue_session=False)  # 新的 context
client2.ask("检查修改是否正确", continue_session=True)    # 继续 task_2 的 context
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
    continue_session: bool = False
) -> Union[str, dict]
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | str | - | 提示词 |
| `expect_json` | bool | False | 是否期望返回 JSON 格式 |
| `timeout` | int | None | 超时时间（秒，None 表示使用实例默认值） |
| `continue_session` | bool | False | 是否继续上一个会话（使用 --continue 参数） |

**返回值**：

- 如果 `expect_json=True`：返回解析后的字典
- 如果 `expect_json=False`：返回字符串

**示例**：

```python
# 第一次调用，创建新的 context
result = client.ask(
    "请阅读 program.md 并开始执行任务 1",
    continue_session=False  # 不使用 --continue
)

# 后续调用，继续同一个 context
result = client.ask(
    "检查上一个任务的执行结果",
    continue_session=True  # 使用 --continue
)

# 期望返回 JSON
decision = client.ask(
    "分析失败原因并决定重试策略",
    expect_json=True,
    continue_session=True
)
print(decision['retry_from'])  # "task_2.1"
print(decision['suggested_fix'])  # "减少网络层数"
```
| `expect_json` | bool | False | 是否期望返回 JSON |
| `timeout` | int | None | 超时时间（覆盖默认值） |

**返回值**：`str` 或 `dict` - AI 的响应

**示例**：

```python
client = CodeBuddyClient()

# 简单问答
response = client.ask("什么是 Python？")
print(response)

# 获取 JSON 响应
response = client.ask(
    "返回一个 JSON: {\"name\": \"test\"}",
    expect_json=True
)
print(response["name"])
```

#### modify_code

让 CodeBuddy 修改文件。

```python
def modify_code(
    self,
    file_path: str,
    instruction: str,
    context: dict = None
) -> dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file_path` | str | - | 要修改的文件路径 |
| `instruction` | str | - | 修改指令 |
| `context` | dict | None | 额外上下文信息 |

**返回值**：`dict` - 修改结果

**示例**：

```python
client = CodeBuddyClient()

result = client.modify_code(
    file_path="train.py",
    instruction="将学习率从 0.001 改为 0.0001"
)

if result["success"]:
    print("修改成功")
    print(result["changes"])
else:
    print("修改失败")
```

**返回格式**：

```python
{
    "success": True,
    "changes": [
        "将 learning_rate 从 0.001 改为 0.0001",
        "添加了学习率调度器"
    ],
    "reason": "根据任务要求调整学习率",
    "modified_files": ["train.py"]
}
```

#### check_completion

让 CodeBuddy 判断任务是否完成。

```python
def check_completion(
    self,
    task_description: str,
    completion_criteria: str,
    context: dict
) -> dict
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_description` | str | - | 任务描述 |
| `completion_criteria` | str | - | 完成标准 |
| `context` | dict | - | 相关上下文 |

**返回值**：`dict` - 判断结果

**示例**：

```python
client = CodeBuddyClient()

result = client.check_completion(
    task_description="优化模型精度",
    completion_criteria="accuracy >= 0.9",
    context={
        "accuracy": 0.92,
        "loss": 0.08,
        "training_log": "..."
    }
)

if result["completed"]:
    print("任务完成")
    print(result["reason"])
else:
    print("任务未完成")
    print(result["reason"])
```

**返回格式**：

```python
{
    "completed": True,
    "reason": "accuracy = 0.92，已达到 0.9 的要求",
    "metrics": {
        "accuracy": 0.92,
        "loss": 0.08
    }
}
```

#### generate_prompt

构造提示词。

```python
def generate_prompt(
    self,
    task_type: str,
    **kwargs
) -> str
```

**参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_type` | str | - | 任务类型：`modify_code` 或 `check_completion` |
| `**kwargs` | - | - | 其他参数 |

**返回值**：`str` - 构造的提示词

**示例**：

```python
client = CodeBuddyClient()

# 构造修改代码的提示词
prompt = client.generate_prompt(
    task_type="modify_code",
    task_description="优化模型精度",
    completion_criteria="accuracy >= 0.9",
    retry_count=2,
    max_retries=5
)
print(prompt)

# 构造检查完成的提示词
prompt = client.generate_prompt(
    task_type="check_completion",
    task_description="优化模型精度",
    completion_criteria="accuracy >= 0.9",
    training_result={"accuracy": 0.85}
)
print(prompt)
```

## 状态类型

### TodoState

LangGraph 的状态类型。

```python
class TodoState(TypedDict):
    current_task: dict           # 当前任务信息
    task_result: dict            # 任务执行结果
    ai_decision: dict            # AI 决策结果
    retry_count: int             # 当前重试次数
    should_continue: bool        # 是否继续循环
    completion_status: str       # 完成状态
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `current_task` | dict | 当前正在执行的任务配置 |
| `task_result` | dict | 命令执行的结果（退出码、输出等） |
| `ai_decision` | dict | CodeBuddy 返回的决策结果 |
| `retry_count` | int | 当前重试次数 |
| `should_continue` | bool | 是否继续循环（用于条件边判断） |
| `completion_status` | str | 完成状态：`"done"` / `"failed"` / `"continue"` |

### 使用示例

```python
from typing import TypedDict

class TodoState(TypedDict):
    current_task: dict
    task_result: dict
    ai_decision: dict
    retry_count: int
    should_continue: bool
    completion_status: str

# 初始化状态
initial_state: TodoState = {
    "current_task": {
        "id": 1,
        "description": "优化模型精度"
    },
    "task_result": {},
    "ai_decision": {},
    "retry_count": 0,
    "should_continue": True,
    "completion_status": "pending"
}

# 更新状态
updated_state = {
    **initial_state,
    "retry_count": initial_state["retry_count"] + 1,
    "task_result": {
        "exit_code": 0,
        "stdout": "训练完成",
        "stderr": ""
    }
}
```

## 配置类型

### TaskConfig

任务配置类型。

```python
class TaskConfig(TypedDict, total=False):
    id: int                       # 必填
    name: str                     # 可选
    description: str              # 必填
    type: Literal["simple", "loop", "parallel"]  # 必填
    command: str                  # simple 必填
    commands: list                # parallel 必填
    max_retries: int              # loop 可选
    timeout: int                  # 可选
    working_dir: str              # 可选
    completion_criteria: str      # loop 必填
    initial_instruction: str      # loop 可选
    expected_output: str          # simple 可选
    depends_on: list              # 可选
    git: dict                     # 可选
```

### GlobalConfig

全局配置类型。

```python
class GlobalConfig(TypedDict):
    version: int
    workspace: str
    codebuddy: CodeBuddyConfig

class CodeBuddyConfig(TypedDict, total=False):
    path: str
    model: str
    timeout: int
```

## 节点函数

LangGraph 图中的节点函数。

### modify_code_node

让 AI 修改代码。

```python
def modify_code_node(state: TodoState) -> TodoState:
    """AI 修改代码（循环任务的第一步）"""
    task = state['current_task']
    retry = state['retry_count']
    
    prompt = f"""
任务: {task['description']}
完成标准: {task['completion_criteria']}
当前重试次数: {retry}/{task['max_retries']}

请修改相关代码以完成任务。
如果有初始指令: {task.get('initial_instruction', '无')}

返回格式 JSON:
{{
  "success": true/false,
  "changes": ["修改1", "修改2"],
  "reason": "修改理由",
  "modified_files": ["file1.py", "file2.py"]
}}
"""
    
    ai_response = codebuddy.ask(prompt, expect_json=True)
    
    return {
        **state,
        'ai_decision': ai_response,
        'retry_count': retry + 1
    }
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | TodoState | 当前状态 |

**返回值**：`TodoState` - 更新后的状态

### run_training_node

运行训练。

```python
def run_training_node(state: TodoState) -> TodoState:
    """运行训练（循环任务第二步）"""
    result = subprocess.run(
        ["uv", "run", "train.py"],
        capture_output=True,
        text=True,
        timeout=1800
    )
    
    return {
        **state,
        'task_result': {
            'exit_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'success': result.returncode == 0
        }
    }
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | TodoState | 当前状态 |

**返回值**：`TodoState` - 更新后的状态

### check_completion_node

检查任务是否完成。

```python
def check_completion_node(state: TodoState) -> TodoState:
    """AI 检查是否完成任务（循环任务第三步）"""
    task = state['current_task']
    training_result = state['task_result']
    
    prompt = f"""
任务: {task['description']}
完成标准: {task['completion_criteria']}

训练结果:
- 退出码: {training_result['exit_code']}
- 输出: {training_result['stdout'][-500:]}

根据完成标准判断任务是否完成？
返回格式 JSON:
{{
  "completed": true/false,
  "reason": "判断理由",
  "metrics": {{"accuracy": 0.92, "params": 4500000}}
}}
"""
    
    ai_response = codebuddy.ask(prompt, expect_json=True)
    
    return {
        **state,
        'ai_decision': ai_response,
        'should_continue': not ai_response['completed'],
        'completion_status': 'done' if ai_response['completed'] else 'continue'
    }
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | TodoState | 当前状态 |

**返回值**：`TodoState` - 更新后的状态

### execute_simple_task_node

执行简单任务。

```python
def execute_simple_task_node(state: TodoState) -> TodoState:
    """执行简单任务（一次性命令）"""
    task = state['current_task']
    command = task['command']
    
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=task.get('timeout', 1800)
    )
    
    return {
        **state,
        'task_result': {
            'exit_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'success': result.returncode == 0
        },
        'should_continue': False
    }
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | TodoState | 当前状态 |

**返回值**：`TodoState` - 更新后的状态

## 条件边函数

LangGraph 的条件边函数，决定流程走向。

### should_continue_edge

决定是否继续循环。

```python
def should_continue_edge(state: TodoState) -> str:
    """决定是否继续循环"""
    task = state['current_task']
    retry = state['retry_count']
    max_retry = task.get('max_retries', 3)
    
    if not state['should_continue']:
        # AI 认为已完成
        return "done"
    
    if retry >= max_retry:
        # 达到最大重试次数
        return "failed"
    
    # 继续循环
    return "modify_code"
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | TodoState | 当前状态 |

**返回值**：`str` - 下一个节点名称

**可能的返回值**：

- `"modify_code"` - 继续修改代码
- `"done"` - 任务完成
- `"failed"` - 任务失败

## 辅助函数

### validate_task_config

验证任务配置。

```python
def validate_task_config(task: dict) -> bool:
    """验证任务配置是否有效"""
    required_fields = ['id', 'description', 'type']
    
    # 检查必需字段
    for field in required_fields:
        if field not in task:
            raise ConfigError(f"缺少必需字段: {field}")
    
    # 根据类型检查特定字段
    if task['type'] == 'simple':
        if 'command' not in task:
            raise ConfigError("简单任务需要 command 字段")
    
    elif task['type'] == 'loop':
        if 'completion_criteria' not in task:
            raise ConfigError("循环任务需要 completion_criteria 字段")
    
    return True
```

### parse_completion_criteria

解析完成标准。

```python
def parse_completion_criteria(criteria: str) -> dict:
    """解析自然语言的完成标准"""
    # 这里可以使用 AI 或规则引擎
    # 简化版本：提取关键词
    
    parsed = {
        "has_accuracy": "accuracy" in criteria.lower(),
        "has_loss": "loss" in criteria.lower(),
        "has_oom": "oom" in criteria.lower(),
        "thresholds": []
    }
    
    # 提取数值阈值
    import re
    numbers = re.findall(r'(\d+\.?\d*)', criteria)
    parsed["thresholds"] = [float(n) for n in numbers]
    
    return parsed
```

## 异常类

### ConfigError

配置错误。

```python
class ConfigError(Exception):
    """配置文件错误"""
    pass
```

### ExecutionError

执行错误。

```python
class ExecutionError(Exception):
    """任务执行错误"""
    pass
```

### AICallError

AI 调用错误。

```python
class AICallError(Exception):
    """CodeBuddy 调用错误"""
    pass
```

## 使用示例

### 完整示例

```python
from todo_orchestrator import TodoOrchestrator, CodeBuddyClient
from typing import TypedDict

# 1. 创建 CodeBuddy 客户端
codebuddy = CodeBuddyClient(
    codebuddy_path="/root/.local/bin/codebuddy",
    model="glm-4.7",
    timeout=3600
)

# 2. 创建 Orchestrator
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    codebuddy_client=codebuddy
)

# 3. 验证配置
if not orchestrator.validate_config():
    print("配置无效")
    exit(1)

# 4. 运行任务
try:
    results = orchestrator.run()
    
    print(f"总任务数: {results['total_tasks']}")
    print(f"成功: {results['successful_tasks']}")
    print(f"失败: {results['failed_tasks']}")
    
    # 打印详细结果
    for task_id, success in results['results'].items():
        status = "✅" if success else "❌"
        print(f"  {status} 任务 {task_id}")
        
except Exception as e:
    print(f"执行失败: {e}")
    exit(1)
```

### 单独使用 CodeBuddyClient

```python
from codebuddy_client import CodeBuddyClient

client = CodeBuddyClient()

# 修改代码
result = client.modify_code(
    file_path="train.py",
    instruction="将学习率改为 0.0001"
)

# 检查完成
result = client.check_completion(
    task_description="优化模型精度",
    completion_criteria="accuracy >= 0.9",
    context={
        "accuracy": 0.92,
        "loss": 0.08
    }
)

# 简单问答
response = client.ask("什么是 LangGraph？")
```

## 总结

本文档涵盖了：

- ✅ TodoOrchestrator 类的完整 API
- ✅ CodeBuddyClient 类的完整 API
- ✅ 状态类型和配置类型
- ✅ 节点函数和条件边函数
- ✅ 辅助函数和异常类
- ✅ 完整的使用示例

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
