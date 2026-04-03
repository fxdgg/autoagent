# API 参考文档

本文档提供 AutoAgent 的完整 API 参考。

## 目录

- [TodoOrchestrator](#todoorchestrator)
- [AIProvider](#aiprovider)
- [AIClient](#aiclient)
- [任务执行器](#任务执行器)
- [ConversationLogger](#conversationlogger)
- [IdeasWatcher](#ideaswatcher)
- [StateManager](#statemanager)
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
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        bash_timeout: int = 300,
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = 30,
        use_cli: bool = False,
        backoff_max_wait: int = 300,
        model_roles: dict = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `provider` | AIProvider | None | AI 提供者实例（支持 CodeBuddy/Claude/Gemini/OpenCode/Test） |
| `workspace` | str | "." | 工作目录（项目根目录） |
| `timeout` | int | 3600 | AI 会话超时时间（秒，总时间硬上限）。来自 `config.yaml` 中的 `session_timeout`，CLI 参数 `--timeout` 可覆盖 |
| `bash_timeout` | int | 300 | 无新输出超时时间（秒）。如果 AI 在此时间内无新输出，会话将被终止，下次 prompt 会包含长时间任务引导 |
| `log_dir` | str | None | 日志根目录（相对于 CWD，默认 `.autoagent`）|
| `ideas_file` | str | None | ideas.md 文件路径（None 则禁用 ideas 监控） |
| `idle_interval` | int | 30 | idle 模式检查间隔（秒） |
| `use_cli` | bool | False | 强制使用 CLI 子进程模式（而非 CodeBuddy Agent SDK）。非 codebuddy provider 自动启用 |
| `backoff_max_wait` | int | 300 | AI CLI 连续失败时的最大退避等待时间（秒），来自 `config.yaml` 的 `backoff_max_wait` |
| `model_roles` | dict | None | 模型角色字典（`{"plan": ..., "default": ..., "lite": ...}`），由 `parse_model_spec()` 解析生成 |

> `todos_state.yaml`、`orchestrator.log`、`plans_state.yaml` 等运行时文件
> 统一放置在由 `log_dir` + `.autoagent_log` 推导出的会话目录下，不出现在项目目录中。

### 方法

#### load_todos / reload_todos

```python
def _load_todos(self, allow_empty: bool = False) -> list
def reload_todos(self) -> None
```

加载任务配置。`_load_todos` 从 YAML 文件加载并验证；`reload_todos` 在新任务追加后重新加载。`allow_empty=True` 时允许空配置（用于 idle 模式）。

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

获取当前执行状态 / 重置所有状态（删除整个会话目录和 `.autoagent_log` 标记文件）。

#### check_and_process_ideas

```python
def check_and_process_ideas(self, human_review: bool = False) -> int
```

检查 ideas.md 是否有新内容，如果有则调用 AI 分解为 TODO 任务并追加到 todos.yaml。生成的任务会经过独立 AI 审查，审查不通过则自动修订重审。返回处理的新 idea 数量。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `human_review` | bool | False | 如果为 True，AI 审查通过后挂起等待人工确认 |

#### validate_config

```python
def validate_config(self) -> bool
```

验证已加载的任务配置文件。检查所有任务的字段完整性和类型正确性，返回 True 表示验证通过。对应 CLI 的 `--validate` 参数。

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

## AIProvider

AI CLI 工具的抽象基类，封装不同 AI 工具之间的命令行差异。

### 类定义

```python
class AIProvider:
    name: str = "base"
    default_executable: str = "ai-tool"
    default_model: str = ""

    # Whether this provider supports --append-system-prompt CLI parameter.
    supports_system_prompt: bool = False

    def __init__(
        self,
        executable: str = None,
        model: str = None,
        extra_args: Optional[str] = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `executable` | str | None | CLI 可执行文件路径（None 使用 provider 默认值） |
| `model` | str | None | AI 模型名（None 使用 provider 默认值） |
| `extra_args` | str | None | 额外 CLI 参数（原样追加到命令末尾） |

### 方法

#### build_command

```python
def build_command(self, session_id: str = None, system_prompt: str = None) -> str
```

构造 CLI 命令字符串（不含 prompt）。Prompt 始终通过 stdin 管道传递。如果提供了 `session_id`，CLI 将恢复该会话；否则启动新会话。如果提供了 `system_prompt` 且 provider 支持，则通过 `--append-system-prompt` 传递。

#### get_stdin_command

```python
def get_stdin_command(self, prompt_file_path: str, cmd_args: str) -> str
```

构造包含 stdin 管道的完整命令。在 Windows 上使用 `type`，在 Linux/macOS 上使用 `cat`。

#### set_model

```python
def set_model(self, model_name: str)
```

切换 provider 使用的模型。由于任务执行是单线程的，直接修改 `self.model` 是安全的。仅在 `model_name` 非空且与当前模型不同时才切换。

### 模块级函数

#### parse_model_spec

```python
def parse_model_spec(model_str: str) -> dict
```

解析模型规格字符串为角色→模型字典。

**输入格式**：
- 单模型：`"glm-5"` → `{"plan": "glm-5", "default": "glm-5", "lite": "glm-5"}`
- 多角色：`"plan:X;default:Y;lite:Z"` → `{"plan": "X", "default": "Y", "lite": "Z"}`

**规则**：
- 只允许 `plan`、`default`、`lite` 三个角色
- 多角色格式必须包含 `default`
- 缺失的角色用 `default` 值填充

### 内置 Provider

#### CodeBuddyProvider

| 属性 | 值 |
|------|----|
| `name` | `"codebuddy"` |
| `default_executable` | `"codebuddy"` |
| `default_model` | 从 `config.yaml` 的 `default_model` 加载（回退到 `"deepseek-v3.2"`） |
| `supports_system_prompt` | `True` |

**命令模式**：
```bash
type prompt.txt | codebuddy --debug --verbose --print --output-format stream-json [--resume <session_id>] --model <model> -y -
```

#### ClaudeCodeProvider

| 属性 | 值 |
|------|----|
| `name` | `"claude"` |
| `default_executable` | `"claude"` |
| `default_model` | `"claude-sonnet-4-6"` |
| `supports_system_prompt` | `True` |

**命令模式**：
```bash
type prompt.txt | claude --verbose --print --output-format stream-json [--resume <session_id>] --model <model> --dangerously-skip-permissions -
```

与 CodeBuddy 的关键差异：使用 `--dangerously-skip-permissions` 替代 `-y`。

#### GeminiCLIProvider

| 属性 | 值 |
|------|----|
| `name` | `"gemini"` |
| `default_executable` | `"gemini"` |
| `default_model` | `"gemini-2.5-pro"` |
| `supports_system_prompt` | `False` |

**命令模式**：
```bash
type prompt.txt | gemini --output-format stream-json [--resume <session_id>] --model <model> --yolo [--include-directories <dirs>] -p -
```

与 CodeBuddy 的关键差异：使用 `-p` 指定非交互模式，使用 `--resume <session_id>` 恢复会话，使用 `--yolo` 替代 `-y`。当配置了 `include_directories` 时，通过 `--include-directories` 传递额外目录。

#### OpenCodeProvider

| 属性 | 值 |
|------|----|
| `name` | `"opencode"` |
| `default_executable` | `"opencode"` |
| `default_model` | `""` （使用 opencode 自身配置的默认模型） |
| `supports_system_prompt` | `False` |

**命令模式**：
```bash
# 新会话
type prompt.txt | opencode run --format json [-m <model>]

# 继续会话
type prompt.txt | opencode run --format json [-m <model>] -s <session_id>
```

与 CodeBuddy 的关键差异：
- 使用 `--format json` 替代 `--output-format stream-json`
- 会话续接使用 `-s <session_id>`，session ID 从首次 JSON 事件中提取
- 输出格式使用行分隔 JSON，事件类型包括：`step_start`、`text`、`tool_call`、`tool_result`、`step_finish`
- 不设默认模型，使用 opencode 自身配置

#### TestProvider

| 属性 | 值 |
|------|----|
| `name` | `"test"` |
| `default_executable` | `"test"` |
| `default_model` | `"test"` |

**说明**：测试用 Provider，不调用真实 AI CLI 工具。从 `--test-rules` 指定的规则文件中按顺序读取预定义响应，用于测试编排逻辑。配合 `AIClientTest` 使用。

### 工厂函数

#### get_provider

```python
def get_provider(
    name: str,
    executable: str = None,
    model: str = None,
    extra_args: str = None,
    test_rules_file: str = None,
    include_directories: List[str] = None,
) -> AIProvider
```

按名称或别名创建 provider 实例。

| 名称 | 别名 |
|------|------|
| `codebuddy` | `cb` |
| `claude` | `claude-code`, `claude` |
| `gemini` | `gemini-cli`, `gemini` |
| `opencode` | `oc` |
| `test` | - |

#### list_providers

```python
def list_providers() -> dict
```

列出所有可用 provider 及其信息（名称、默认可执行文件、默认模型、别名）。

---

## AIClient

统一 AI CLI 客户端，封装 AI 调用、Context 管理和 stream-json 解析。

### 类定义

```python
class AIClient:
    def __init__(
        self,
        provider: AIProvider,
        workspace: str = ".",
        timeout: int = 3600,
        bash_timeout: int = 300,
        context_id: str = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | AIProvider | - | AI provider 实例 |
| `workspace` | str | "." | 工作目录 |
| `timeout` | int | 3600 | 超时时间（秒）。实际使用中由 TodoOrchestrator 传入（来自 config.yaml 或 CLI `--timeout`） |
| `bash_timeout` | int | 300 | 无新输出超时时间（秒）。如果 AI 在此时间内无新输出，会话将被终止 |
| `context_id` | str | None | Context 标识符，用于状态记录和日志追踪 |

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `last_full_log` | str | 最近一次 `ask()` 的完整对话日志（包含工具调用），供 ConversationLogger 使用 |
| `_session_id` | str | 会话 ID，用于 `--resume` 续接参数。首次调用后自动从 stream 事件中捕获 |
| `_consecutive_failures` | int | 连续失败计数器，用于指数退避 |
| `_backoff_base` | int | 退避基础等待时间（默认 5 秒） |
| `_backoff_max` | int | 退避最大等待时间（默认 300 秒，由 `config.yaml` 的 `backoff_max_wait` 覆盖） |

### Context 管理策略

| 层级 | 策略 | 说明 |
|------|------|------|
| 主任务 | 独立 context | 每个主任务创建独立的 AIClient，互不干扰 |
| 子任务 | 独立 session | 每个子任务重置 session，通过 previous_subtask_summary 传递上下文 |
| 重试 | 重置 session | 每次 retry 前重置 session，防止上下文累积导致输出截断。完整任务描述和历史摘要包含在每次 prompt 中 |

```python
from ai_providers import get_provider
from codebuddy_client import AIClient

provider = get_provider("claude", model="claude-sonnet-4-6")

# 主任务 1
client1 = AIClient(provider=provider, context_id="task_1")
client1.ask("修改模型代码")   # 创建新 session
client1.ask("检查修改结果")    # 自动通过 session_id 复用 context

# 主任务 2（完全隔离）
client2 = AIClient(provider=provider, context_id="task_2")
client2.ask("修改另一个模型")  # 独立 session
```

### 方法

#### ask

向 AI 工具发送提示并获取响应。会话续接通过 session_id 自动管理：首次调用创建新会话，后续调用自动通过 `--resume <session_id>` 复用会话。

```python
def ask(
    self,
    prompt: str,
    expect_json: bool = False,
    timeout: int = None,
    system_prompt: str = None,
    **kwargs,
) -> Union[str, dict]
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | str | - | 提示词 |
| `expect_json` | bool | False | 是否期望 JSON 响应 |
| `timeout` | int | None | 超时时间（覆盖默认值） |
| `system_prompt` | str | None | 可选的系统提示词。对于支持 `supports_system_prompt` 的 provider，通过 `--append-system-prompt` CLI 参数传递；否则附加到用户 prompt 末尾 |

**执行流程**：
1. 将 prompt 写入临时文件（避免 shell 转义问题）
2. 通过 provider 构造 CLI 命令
3. 启动子进程，实时解析 stream-json 输出
   - 处理 `system/api_retry` 事件：实时显示 API 重试进度（rate_limit、server_error 等）
   - 处理 `result` 事件的 `is_error`：错误详情附加到 response 避免空响应
4. 进程退出码非零时，通过 `_parse_cli_error()` 结构化解析错误 JSON
5. 收集 assistant 文本和完整日志（含工具调用）
6. 调用完成后保存到 `last_full_log`

**示例**：

```python
from ai_providers import get_provider
from codebuddy_client import AIClient

provider = get_provider("codebuddy")
client = AIClient(provider=provider, context_id="task_2")

# 第一次调用：创建新 session
result = client.ask("请阅读 program.md 并开始执行任务 2")

# 后续调用：自动通过 session_id 复用 context
result = client.ask("检查子任务 2.1 的结果")

# 获取结构化 JSON 响应
decision = client.ask("分析失败原因", expect_json=True)
print(decision['retry_from'])

# 获取包含工具调用的完整日志
full_log = client.last_full_log
```

#### reset_session

```python
def reset_session(self)
```

重置会话状态（清除 session_id），使下一次调用启动新会话。

#### resume_session

```python
def resume_session(self, session_id: str)
```

恢复指定的会话。设置 session_id 后，下一次 `ask()` 调用将通过 `--resume` 参数续接该会话。由 orchestrator 在任务有已保存的 session_id 时调用。

#### session_id（属性）

```python
@property
def session_id(self) -> str
```

返回当前会话 ID（如果没有则返回空字符串）。首次 `ask()` 调用后自动从 stream 事件中捕获。

### stream-json 解析

AI CLI 工具的 `--output-format stream-json` 模式输出逐行 JSON 对象。AIClient 通过 `_handle_stream_line()` 方法实时解析：

| 事件类型 | 处理方式 |
|----------|----------|
| `assistant` | 提取文本块追加到响应；提取工具调用（`tool_use`）并实时显示摘要 |
| `user` | 提取 `tool_result` 并显示预览（前 500 字符） |
| `result` | 提取最终结果文本（含 turns 数、耗时等），追加到 assistant 文本 |
| `system` | 系统/会话初始化消息（忽略） |

工具调用的实时显示格式：

| 工具名 | 显示格式 |
|--------|----------|
| `Bash` | 🔧 [Bash] `<command>` |
| `Edit`/`Write` | 📝 [Edit] `<file_path>` |
| `Read` | 📖 [Read] `<file_path>` |
| `Glob`/`Grep` | 🔍 [Glob] `<pattern>` |
| 其他 | 🔧 [ToolName] |

---

## 任务执行器

### SimpleTaskExecutor

执行简单任务（simple 类型），AI 自主判断完成条件。

```python
class SimpleTaskExecutor:
    def __init__(self, session_dir: str = None)
    def execute(self, task: dict, client: AIClient, state_manager, conv_logger=None, parent_task_id: str = None, parent_context: dict = None, **kwargs) -> bool
```

**执行逻辑**：

```python
should_reset = True
last_ai_output = None

while attempts < max_attempts:
    # 根据失败类型决定是否重置 session
    if attempts > 1 and should_reset:
        client.reset_session()
        # 将 last_ai_output 注入 prompt 的 "Previous Attempt Output" section

    result = client.ask(prompt)
    last_ai_output = result

    if is_completed(result):
        return True

    # BashTimeoutError → should_reset = False（session 存活，in-session follow-up）
    # SessionTimeoutError / not_completed / 其他 → should_reset = True
    attempts += 1

return False
```

### LoopingTaskExecutor

执行循环任务（looping 类型），固定循环 N 次执行所有子任务。

```python
class LoopingTaskExecutor:
    def __init__(self, session_dir: str = None, model_roles: dict = None)
    def execute(self, task: dict, client: AIClient, state_manager, conv_logger=None) -> bool
```

**构造函数参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_dir` | str | None | 日志会话目录（从 orchestrator 传入） |
| `model_roles` | dict | None | 模型角色字典，用于子任务模型切换 |

**执行逻辑**：

```python
for loop in range(task['repeat_count']):
    # 每轮使用独立的 round-scoped state keys（如 1.1@2.1）
    # 无需 reset，新 round 的 key 自动为 pending

    for subtask in task['subtasks']:
        result = subtask_executor.execute(subtask, client)
        if not result.success:
            # AI 分析失败原因并决定重试策略（在当前轮内重试）
            handle_failure(subtask, result)
    
    # 本轮完成，进入下一轮
```

**与 NestedTaskExecutor 的区别**：
- 不做主任务完成度评估
- 固定循环 N 次，不会提前结束
- 每轮使用独立的 round-scoped state keys，无需重置
- 使用 `max_attempts_per_loop` 控制每轮内的重试次数

### NestedTaskExecutor

执行嵌套任务（nested 类型），包含 AI 决策机制。

```python
class NestedTaskExecutor:
    def __init__(self, session_dir: str = None, model_roles: dict = None)
    def execute(self, task: dict, client: AIClient, state_manager, conv_logger=None) -> bool
```

**构造函数参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_dir` | str | None | 日志会话目录（从 orchestrator 传入，传递给 SubtaskExecutor） |
| `model_roles` | dict | None | 模型角色字典，用于子任务模型切换 |

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
    "suggested_fix": "修复建议"
}
```

**AI 主任务评估响应格式**：

```json
{
    "main_task_completed": false,
    "analysis": "结果分析",
    "retry_from": "task_2.1",
    "next_strategy": "优化方向"
}
```

### SubtaskResult

子任务执行结果数据类。

```python
class SubtaskResult:
    success: bool          # 是否成功
    output: str            # 输出摘要
    logs: str              # 完整日志
    error_type: str        # 错误类型（失败时）
    response_text: str     # AI 原始响应文本
```

### SubtaskExecutor

执行单个子任务，根据子任务类型分发。

```python
class SubtaskExecutor:
    def __init__(self, session_dir: str = None, model_roles: dict = None)
    def execute(self, subtask: dict, client: AIClient, state_manager, conv_logger=None, parent_task_id: str = None, parent_context: dict = None) -> SubtaskResult
```

**构造函数参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_dir` | str | None | 日志会话目录（long_running 任务必须提供，用于构造 wrapper 脚本中的 `--log-dir` 参数） |
| `model_roles` | dict | None | 模型角色字典，根据子任务的 `model` 字段切换 provider 模型 |

支持的子任务类型：

| 类型 | 说明 | 执行方式 |
|------|------|----------|
| `simple` | AI 自主完成（含代码修改、命令执行等） | 调用 `client.ask()` |
| `long_running` | 长时间任务 | AI 通过 wrapper 脚本调用 `autoagent-exec` 启动，AutoAgent 轮询信号文件 + AI 分析结果 |

**long_running 子任务执行流程**：

1. 构造 prompt，告知 AI 使用 `autoagent-exec` wrapper 脚本启动命令（内部参数由 wrapper 预填）
2. AI 通过 wrapper 脚本调用 `autoagent-exec`
3. 如果 AI 报告 `LONG_RUNNING_IN_PROGRESS`，轮询信号文件等待完成
4. 如果 AI 未输出任何标记，`_nudge_for_marker()` 会先检查信号文件：若已有后台任务在运行则跳过 nudge，直接合成 `LONG_RUNNING_IN_PROGRESS` 进入轮询流程
5. 完成后重启 AI 会话，让 AI 读取输出日志并评估结果

### autoagent_exec.py

long_running 任务启动器，AI 通过 wrapper 脚本（`autoagent-exec.bat` / `autoagent-exec.sh`）调用的独立脚本。

**调用方式**（AI 通过 wrapper 脚本调用，内部参数由 wrapper 预填）：
```bash
# Windows
autoagent-exec.bat <command...>
# Linux/macOS
bash autoagent-exec.sh <command...>
```

**内部参数**（由 wrapper 脚本预填，AI 不需要手动指定，`--help` 中已隐藏）：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--log-dir` | str | 日志会话目录绝对路径（由 SubtaskExecutor 的 `session_dir` 提供） |
| `--task-id` | str | 子任务 ID（如 `1.2`） |
| `--fast-fail-timeout` | int | 快速失败超时时间（秒），由 `config.yaml` 的 `fast_fail_timeout` 配置 |
| `--cmd <command>` | str | 要执行的命令（由 wrapper 脚本拼接用户参数后传入） |

**行为**（以下 `N` 秒由 `--fast-fail-timeout` 控制）：

| 场景 | 行为 |
|------|------|
| 同一 task-id 已有 `running` 状态的信号文件 | 拒绝启动，输出错误信息，返回退出码 1（防止重复启动后台任务） |
| 命令在 N 秒内失败（退出码≠ 0） | 智能输出（短输出内联打印，长输出只给路径），不写信号文件，返回非零退出码 |
| 命令在 N 秒内成功（退出码 = 0） | 智能输出（短输出内联打印，长输出只给路径），写入 `finished` 信号文件，返回 0 |
| 命令 N 秒后仍在运行 | 写入 `running` 信号文件，打印 `TASK SUBMITTED`，启动监控线程 |

**智能输出策略**（命令在 N 秒内退出时，无论成功或失败）：

| 输出长度 | 行为 |
|----------|------|
| 无输出 | 打印 `(no output captured)` |
| ≤ 3000 字符 | 直接内联打印完整内容，标注 `(complete, not truncated)` 避免 AI 再去读文件 |
| > 3000 字符 | 只打印 output log 文件路径，AI 可自行读取 |

**生成的文件**：

| 文件 | 说明 |
|------|------|
| `<log-dir>/lr_tasks/lr_<task_id>_signal.json` | 信号文件（status: running/finished/error） |
| `<log-dir>/lr_tasks/lr_<task_id>_output.log` | 命令的完整 stdout+stderr 输出 |

---

## ConversationLogger

对话日志记录器，将 AI 交互的完整内容输出到 Markdown 文件。

### 类定义

```python
class ConversationLogger:
    def __init__(self, session_dir: str)
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_dir` | str | - | 项目专属会话目录 |

初始化时会在 `session_dir` 下创建固定的 `conversations/` 子目录。

### 方法

#### log_prompt（推荐：崩溃安全写入）

```python
def log_prompt(
    self,
    task_id: str,
    task_name: str,
    prompt: str,
    attempt: Union[int, str],
    parent_task_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    system_prompt: Optional[str] = None,
)
```

在 AI 调用**之前**将 prompt 写入日志文件。这确保即使进程在等待 AI 响应时被中断（如 Ctrl+C），prompt 也已持久化。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `task_name` | str | 任务名称 |
| `prompt` | str | 发送给 AI 的提示词 |
| `attempt` | Union[int, str] | 尝试次数 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |
| `metadata` | dict | 额外信息（如 `{"type": "failure_analysis"}`） |
| `system_prompt` | str | 可选的系统提示词（如果提供，会在 prompt 之前记录） |

#### log_response（推荐：崩溃安全写入）

```python
def log_response(
    self,
    task_id: str,
    response: str,
    parent_task_id: Optional[str] = None,
    attempt: Optional[Union[int, str]] = None,
)
```

在 AI 返回**之后**将 response 写入对应的 per-round 日志文件。必须在 `log_prompt()` 之后调用，`attempt` 参数需与 `log_prompt()` 传入的值一致。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `response` | str | AI 的响应 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |
| `attempt` | Union[int, str] | 尝试次数（用于定位 round 文件，需与 `log_prompt` 一致） |

#### log_conversation（便捷包装器）

```python
def log_conversation(
    self,
    task_id: str,
    task_name: str,
    prompt: str,
    response: str,
    attempt: Union[int, str],
    parent_task_id: Optional[str] = None,
    metadata: Optional[dict] = None,
)
```

一次性记录 prompt + response（内部调用 `log_prompt` + `log_response`）。新代码建议使用两步方法以获得崩溃安全性。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `task_name` | str | 任务名称 |
| `prompt` | str | 发送给 AI 的提示词 |
| `response` | str | AI 的响应 |
| `attempt` | Union[int, str] | 尝试次数 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |
| `metadata` | dict | 额外信息（如 `{"type": "failure_analysis"}`） |

#### log_nested_prompt / log_nested_response（推荐）

```python
def log_nested_prompt(self, task_id: str, task_name: str, call_type: str, prompt: str, round_num: Union[int, str], failed_subtask_id: Optional[str] = None)
def log_nested_response(self, task_id: str, task_name: str, response, call_type: Optional[str] = None, round_num: Optional[Union[int, str]] = None, failed_subtask_id: Optional[str] = None)
```

嵌套任务 AI 决策调用的两步写入方法。每个决策写入独立文件：

- `failure_analysis_{subtask_id}_round_{N}.md` — 子任务失败分析
- `looping_failure_analysis_{subtask_id}_round_{N}.md` — 循环任务失败分析
- `main_task_evaluation_round_{N}.md` — 主任务完成评估

`failed_subtask_id` 参数在 failure_analysis 类型时提供，用于在文件名中标识失败的子任务。

#### log_nested_task_ai_call（便捷包装器）

```python
def log_nested_task_ai_call(
    self,
    task_id: str,
    task_name: str,
    call_type: str,
    prompt: str,
    response: str,
    round_num: Union[int, str],
    metadata: Optional[dict] = None,
    failed_subtask_id: Optional[str] = None,
)
```

一次性记录嵌套任务的 AI 决策调用（内部调用 `log_nested_prompt` + `log_nested_response`）。

#### log_ideas_prompt（Ideas 拆解日志）

```python
def log_ideas_prompt(
    self,
    idea_title: str,
    idea_index: int,
    prompt: str,
)
```

在 AI 调用**之前**将 ideas 拆解的 prompt 写入 `conversations/ideas.md`。所有 ideas 拆解日志写入同一个文件。

| 参数 | 类型 | 说明 |
|------|------|------|
| `idea_title` | str | 想法标题 |
| `idea_index` | int | 1-based 想法序号 |
| `prompt` | str | 发送给 AI 的拆解提示词 |

#### log_ideas_response（Ideas 拆解日志）

```python
def log_ideas_response(
    self,
    response: str,
)
```

在 AI 返回**之后**将 response 追加到 `conversations/ideas.md`。必须在 `log_ideas_prompt()` 之后调用。Response 以 YAML 代码块格式记录。

| 参数 | 类型 | 说明 |
|------|------|------|
| `response` | str | AI 返回的 YAML 任务定义 |

#### log_ideas_review_prompt（Ideas 审查日志）

```python
def log_ideas_review_prompt(
    self,
    review_round: int,
    prompt: str,
)
```

将 ideas 审查的 prompt 写入 `conversations/ideas.md`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `review_round` | int | 1-based 审查轮次 |
| `prompt` | str | 发送给审查 AI 的提示词 |

#### log_ideas_review_response（Ideas 审查日志）

```python
def log_ideas_review_response(
    self,
    response: str,
)
```

将审查 AI 的响应追加到 `conversations/ideas.md`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `response` | str | 审查 AI 的响应（包含 ✅ completed 或 ❌ not completed） |

#### log_ideas_revision_prompt（Ideas 修订日志）

```python
def log_ideas_revision_prompt(
    self,
    revision_round: int,
    prompt: str,
)
```

将 ideas 修订的 prompt 写入 `conversations/ideas.md`。当审查被拒绝后，将反馈发送给原 AI 进行修订时调用。也用于记录人工反馈（以 `[Human Feedback]` 前缀标记）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `revision_round` | int | 1-based 修订轮次 |
| `prompt` | str | 修订提示词（含审查反馈或人工反馈） |

#### log_ideas_revision_response（Ideas 修订日志）

```python
def log_ideas_revision_response(
    self,
    response: str,
)
```

将修订后的 AI 响应追加到 `conversations/ideas.md`。

| 参数 | 类型 | 说明 |
|------|------|------|
| `response` | str | 修订后的 YAML 任务定义 |

#### get_session_dir

```python
def get_session_dir(self) -> str
```

返回会话日志目录路径。

#### log_ideas_section_end

```python
def log_ideas_section_end(self)
```

写入分隔符（`---`）标记一个 idea 处理段落的结束。

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
        plans_state_file: str = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ideas_file` | str | "ideas.md" | Ideas 文件路径 |
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `plans_state_file` | str | None | Ideas 状态文件路径（默认为会话目录下的 `plans_state.yaml`）。存储 idea 处理状态及 plan 阶段的断点续传数据（`plan_tasks`） |

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
    'title': str,     # 标题（从内容首行派生的短显示字符串）
    'content': str,   # 原始内容
    'hash': str,      # SHA256 hash（前 16 位，用于去重）
}
```

#### process_new_ideas

```python
def process_new_ideas(
    self,
    client: AIClient,
    review_client: AIClient = None,
    conv_logger: ConversationLogger = None,
    human_review: bool = False,
) -> int
```

处理所有新 ideas：解析 → 调用 AI 分解（或从断点续传恢复） → AI 审查 → 可选人工审核 → 追加到 todos.yaml → 归档并从 ideas.md 删除。返回处理的 idea 数量。

Plan 阶段内置重试机制（`max_plan_retries`，默认 3）：如果 AI 调用失败、YAML 解析失败或结果为空，会使用全新 AI session 重试。超过重试上限则跳过该 idea。处理失败的 idea 保持 `in_progress` 状态，下次运行时自动重试。如果 plan 阶段已完成（`plan_tasks` 已保存），重试时会跳过 plan 直接进入 review 阶段。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `client` | AIClient | - | AI 客户端实例（用于任务分解） |
| `review_client` | AIClient | None | 可选的独立 AI 客户端（全新上下文，用于审查）。如果为 None 则跳过审查步骤 |
| `conv_logger` | ConversationLogger | None | 可选的对话日志记录器 |
| `human_review` | bool | False | 如果为 True，AI 审查通过后挂起等待人工确认 |

#### mark_all_processed / reset

```python
def mark_all_processed(self)
def reset(self)
```

标记所有当前 ideas 为已处理（不生成任务） / 重置所有处理状态。

---

## StateManager

任务状态持久化管理器，负责加载、保存和更新任务执行状态。写入操作通过 `threading.Lock` 保证线程安全。

子任务状态使用 **round-scoped key**（`task_id@round_label`，如 `"1.2@3.1"`），每个轮次/retry 有独立状态，实现精确断点续传。`*_once` 类型的子任务使用 plain key 跨轮次共享。

### 类定义

```python
class StateManager:
    ROUND_SEP = "@"  # round-scoped key 分隔符
    def __init__(self, state_file: str = "todos_state.yaml")
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `state_file` | str | "todos_state.yaml" | 状态持久化文件路径（位于会话目录下） |

### 静态方法

#### round_key

```python
@staticmethod
def round_key(task_id: str, round_label: str | None) -> str
```

构造 round-scoped state key。返回 `"task_id@round_label"`（如 `"1.2@3.1"`），或在 `round_label` 为 `None` 时返回 plain `task_id`。

### 方法

#### save_state

```python
def save_state(self)
```

将当前状态保存到文件。通过 `threading.Lock` 保证线程安全。其他修改方法（`mark_task_status`、`add_task_history` 等）内部自动调用此方法。

#### get_task_state

```python
def get_task_state(self, task_id: str) -> dict
```

获取指定任务的状态。如果任务不存在，返回 `{"status": "pending", "attempts": 0}`。

#### mark_task_status

```python
def mark_task_status(self, task_id: str, status: str, **kwargs)
```

更新任务状态和额外字段。自动触发 `save_state()`。

#### update_task_field

```python
def update_task_field(self, task_id: str, field: str, value)
```

更新任务状态中的单个字段。自动触发 `save_state()`。

#### add_task_history

```python
def add_task_history(self, task_id: str, entry: dict)
```

向任务的执行历史中追加一条记录。自动触发 `save_state()`。

#### add_ai_decision

```python
def add_ai_decision(self, task_id: str, decision: dict)
```

记录一次 AI 决策（子任务失败分析）。追加到 `ai_decisions` 列表。

#### add_main_task_evaluation

```python
def add_main_task_evaluation(self, task_id: str, evaluation: dict)
```

记录一次主任务评估结果。追加到 `main_task_evaluations` 列表。

#### reset

```python
def reset(self)
```

重置所有状态，清空 `tasks` 字典并保存。

#### get_summary

```python
def get_summary(self) -> dict
```

获取所有任务状态的汇总信息，返回各状态的计数：

```python
{
    "total": 5,
    "pending": 1,
    "in_progress": 1,
    "completed": 2,
    "failed": 1,
}
```

#### get_in_progress_tasks

```python
def get_in_progress_tasks(self) -> list
```

获取当前状态为 `in_progress` 的所有任务 ID 列表。

#### record_interrupt

```python
def record_interrupt(self, task_id: str, attempt: int = 0)
```

记录一次中断事件（如 Ctrl+C）到任务的执行历史中。自动触发 `save_state()`。

---

## 状态类型

### TaskState

任务状态结构（持久化在会话目录的 `todos_state.yaml` 中）。

```python
class TaskState(TypedDict, total=False):
    status: str           # "pending" | "in_progress" | "completed" | "failed"
    attempts: int         # 尝试次数
    max_attempts: int     # 最大尝试次数
    session_id: str       # AI 会话 ID（用于 --resume 续接）
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
    error_type: str       # "ai_failed" | "nested_failed" | "looping_failed" | "max_attempts_exceeded" | "validation_failed"
    log_file: str         # 日志文件路径（long_running 类型）
    ai_reasoning: str     # AI 的推理记录
    history: list         # 执行历史
```

> **注意**：`in_progress` 状态同时覆盖"正在执行命令"和"长时间任务正在后台运行"两种场景。可通过 `log_file` 字段和信号文件（`lr_<task_id>_signal.json`）区分是否为长时间任务。

---

## 配置类型

### TaskConfig

```python
class TaskConfig(TypedDict, total=False):
    id: Union[int, str]                               # 必填，唯一标识
    name: str                                          # 必填，任务名称
    type: Literal["simple", "nested", "looping"]  # 必填，任务类型（顶层）
    completion_criteria: str                            # 必填，完成标准
    initial_hint: str                                  # simple 可选
    max_attempts: int                                  # 可选，默认 5
    subtasks: List['SubtaskConfig']                    # nested/looping 必填
    repeat_count: int                                  # looping 必填，循环次数
    max_attempts_per_loop: int                         # looping 可选，每轮最大重试次数（默认 5）
```

### SubtaskConfig

```python
class SubtaskConfig(TypedDict, total=False):
    id: Union[int, str]                                # 必填
    name: str                                          # 必填
    type: Literal["simple", "long_running", "simple_once", "long_running_once", "nested", "looping"]  # 必填
    completion_criteria: str                            # 必填
    initial_hint: str                                  # simple 可选
    max_attempts: int                                  # 可选，默认 5
```

> **注意**：`long_running` 类型的子任务不再需要 `command` 字段。AI 会根据任务描述自主决定要运行的命令，并通过 `autoagent-exec` 启动。

---

## 异常类

```python
# task_executor.py 中定义
class ConfigError(Exception):
    """配置文件错误（YAML 语法、缺少字段等）"""

class ExecutionError(Exception):
    """任务执行错误（命令失败、超时等）"""

# codebuddy_client.py 中定义
class AICallError(Exception):
    """AI 调用错误（认证失败、响应解析失败等）"""

class BashTimeoutError(AICallError):
    """无新输出超时（AI 在 bash_timeout 秒内无新输出）。
    通常意味着长时间命令阻塞了会话，下次 prompt 应包含 autoagent-exec 引导。"""

class SessionTimeoutError(AICallError):
    """会话总时间超时（超过 session_timeout 秒）。
    调用方应告知 AI 它被用户中断（Ctrl+C）。"""
```

---

## CLI 参数

`orchestrator.py` 作为 CLI 入口，支持以下命令行参数：

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--config` | `-c` | `todos.yaml` | 任务配置文件路径 |
| `--task` | `-t` | None | 只执行指定任务 ID |
| `--provider` | `-P` | `codebuddy` | AI provider：`codebuddy`、`claude`、`gemini`、`opencode`、`test` |
| `--executable` | - | None | 覆盖 provider 默认可执行文件路径 |
| `--extra-args` | - | None | 传递给 AI 工具的额外 CLI 参数 |
| `--use-cli` | - | - | 强制使用 CLI 模式（而非 SDK 模式） |
| `--test-rules` | - | None | 测试规则文件路径（使用 `test` provider 时必须指定） |
| `--include-directories` | - | None | 逗号分隔的额外目录列表，允许 AI 工具访问工作区外的目录（仅 Gemini） |
| `--list-providers` | - | - | 列出所有可用 AI provider 并退出 |
| `--model` | `-m` | 取决于 provider | AI 模型。支持单模型（如 `glm-5`）和多角色格式（如 `"plan:X;default:Y;lite:Z"`）。codebuddy 默认从 config.yaml 的 `default_model` 加载 |
| `--workspace` | `-w` | `.` | 工作目录 |
| `--timeout` | - | 3600 | AI 会话超时时间（秒），默认值来自 `config.yaml` 的 `session_timeout`（如果 config.yaml 不存在则为 3600） |
| `--log-dir` | - | `.autoagent` | 日志根目录（相对于 CWD） |
| `--ideas` | - | None | ideas.md 文件路径 |
| `--ideas-only` | - | - | 只处理 ideas.md，不运行 todo list（需搭配 `--ideas`） |
| `--no-idle` | - | - | 禁用 idle 模式（默认当 `--ideas` 指定时自动开启 idle） |
| `--idle-interval` | - | 30 | idle 轮询间隔（秒） |
| `--preset` | - | `default` | Preset 配置名称，从 config.yaml 加载预设参数 |
| `--human-review` | - | - | 启用 ideas 处理的人工审核。AI 审查通过后暂停等待人工确认 |
| `--status` | - | - | 显示当前任务状态并退出 |
| `--reset` | - | - | 重置所有状态并退出 |
| `--validate` | - | - | 验证配置文件并退出 |
| `--no-skip` | - | - | 不跳过已完成的任务 |
| `--verbose` | `-v` | - | 启用 debug 级别日志 |

**Preset 配置**：

通过 `--preset <name>` 从 `config.yaml` 加载预设配置。Preset 支持的字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `config` | str | 任务配置文件路径 |
| `ideas` | str | ideas.md 文件路径 |
| `provider` | str | AI provider 名称 |
| `model` | str | AI 模型名称 |
| `executable` | str | 可执行文件路径 |
| `workspace` | str | 工作目录 |
| `timeout` | int | AI 调用超时时间 |
| `log_dir` | str | 日志根目录 |
| `idle_interval` | int | idle 轮询间隔 |
| `include_directories` | str | 额外目录列表（Gemini 专用） |
| `test_rules` | str | 测试规则文件路径 |
| `verbose` | bool | 是否启用详细日志 |
| `no_skip` | bool | 是否不跳过已完成任务 |
| `no_idle` | bool | 是否禁用 idle 模式 |
| `use_cli` | bool | 是否使用 CLI 模式 |
| `ideas_only` | bool | 是否仅处理 ideas |
| `human_review` | bool | 是否启用人工审核 |

**示例**：

```bash
# 使用 default preset
python orchestrator.py

# 使用指定 preset
python orchestrator.py --preset test

# 使用 preset 但覆盖特定参数
python orchestrator.py --preset default --model claude-sonnet-4-6
```

**示例**：

```bash
# 使用 CodeBuddy 运行所有任务
python orchestrator.py

# 使用 Claude Code 运行特定任务
python orchestrator.py --provider claude --task 2

# 使用 Gemini CLI 并指定模型
python orchestrator.py --provider gemini --model gemini-2.5-pro

# 使用 OpenCode
python orchestrator.py --provider opencode

# 使用自定义可执行文件路径
python orchestrator.py --provider claude --executable /usr/local/bin/claude

# 带 Ideas 监控和 Idle 模式（--ideas 自动开启 idle）
python orchestrator.py --ideas ideas.md --idle-interval 60

# 带 Ideas 但禁用 idle（处理完即退出）
python orchestrator.py --ideas ideas.md --no-idle

# 只处理 ideas（可搭配 --human-review 进行人工审核）
python orchestrator.py --ideas ideas.md --ideas-only --human-review

# 查看所有可用 provider
python orchestrator.py --list-providers

# 验证配置文件
python orchestrator.py --validate

# 不跳过已完成任务，全部重新执行
python orchestrator.py --no-skip
```

---

## truncation_limits（config.yaml）

控制自动构建提示词时各字段的最大字符数，防止上下文过长。通过 `truncation_limits.py` 模块加载，所有 prompt 构造器和 task_executor 共享。

### 配置字段

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `previous_subtask_summary` | 4000 | 子任务摘要、错误文本、日志文件的截断限制 |
| `history_summary` | 300 | 历史尝试摘要、AI 推理记录的截断限制 |
| `max` | 50000 | 防御性上限，用于不应被截断的字段 |

### 使用方式

```python
from truncation_limits import limits

max_len = limits.get('previous_subtask_summary')  # 返回配置值或默认值
limits.reload()                                    # 重新从 config.yaml 加载
```

所有字段都有内置默认值，`config.yaml` 中只需配置想调整的项。

---

## Ideas 处理配置（config.yaml）

控制 Ideas 拆解过程中的 AI 审查和校验行为。通过 `ideas_watcher.py` 的 `_load_ideas_config()` 加载。

### 配置字段

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_review_rounds` | 3 | AI 审查最大轮数。每轮将生成的任务发送给独立的审查 AI 检查质量，如果审查持续拒绝，达到此轮数后强制接受 |
| `max_validation_retries` | 2 | Schema 校验最大重试次数。如果生成的任务未通过 schema 校验，将错误反馈给 AI 修正，达到此次数后按原样接受 |

所有字段都有内置默认值，`config.yaml` 中只需配置想调整的项。

---

## Marker Nudge 配置（config.yaml）

控制当 AI 未输出完成状态标记时的轻量级追问机制（标记缺失可能是 AI 遗漏，也可能是 CLI/SDK 异常中断）。通过 `prompts/marker_nudge.py` 加载。

### 配置字段

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `max_marker_nudges` | 2 | 最大 nudge 次数。当 AI 未输出状态标记（✅/❌/⏳）时，在同一 session 中发送轻量级追问（允许 AI 继续工作，但禁止重复执行已跑过的命令）。发送前会先检查信号文件，若已有后台任务在运行则跳过 nudge。耗尽后回退到正常 retry 循环 |

---

## setup_logging()

模块级日志配置函数，配置 logging 输出。

```python
def setup_logging(verbose: bool = False, log_file: str = None)
```

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `verbose` | bool | False | 启用 debug 级别日志 |
| `log_file` | str | None | orchestrator.log 路径，None 则只输出到控制台 |

日志同时输出到 stdout 和文件（如果指定了 `log_file`）。`log_file` 通常位于会话目录下（如 `<log_dir>/<session>/orchestrator.log`）。
```

---

## 完整使用示例

```python
from orchestrator import TodoOrchestrator
from ai_providers import get_provider

# 1. 基本用法：使用默认 CodeBuddy provider
# log_dir 默认为 ".autoagent"（相对于 CWD）
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
)

results = orchestrator.run(skip_completed=True)
print(f"成功: {results['successful_tasks']} / 失败: {results['failed_tasks']}")

# 2. 使用其他 AI provider
provider = get_provider("claude", model="claude-sonnet-4-6")
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    provider=provider,
)
results = orchestrator.run()

# 3. 指定日志目录：所有运行时文件都在该目录下
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    log_dir="logs",
)
results = orchestrator.run()
if orchestrator.conv_logger:
    orchestrator.conv_logger.finalize()

# 4. 带 Ideas 监控：自动处理 ideas.md
orchestrator = TodoOrchestrator(
    todos_file="todos.yaml",
    ideas_file="ideas.md",
)
orchestrator.check_and_process_ideas()  # 处理新 ideas 后运行任务
results = orchestrator.run()

# 5. Idle 模式：持续运行等待新 ideas
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
| **AIProvider** | AI CLI 工具抽象基类、命令构造 |
| **CodeBuddyProvider / ClaudeCodeProvider / GeminiCLIProvider / OpenCodeProvider** | 具体 AI 工具的命令构造 |
| **AIClient** | AI 调用、Context 管理、stream-json 解析 |
| **SimpleTaskExecutor** | 简单任务执行（自循环完成检测，按失败类型决定是否 reset session） |
| **NestedTaskExecutor** | 嵌套任务执行、AI 决策调度 |
| **LoopingTaskExecutor** | 循环任务执行（固定 N 次迭代） |
| **SubtaskExecutor** | 子任务分发执行（接收 session_dir） |
| **autoagent_exec.py** | long_running 任务启动器（快速失败检测 + 信号文件，超时可通过 `config.yaml` 的 `fast_fail_timeout` 配置） |
| **StateManager** | 任务状态持久化（todos_state.yaml），round-scoped key 实现精确断点续传 |
| **ConversationLogger** | 对话日志记录、索引生成、Ideas 拆解/审查/修订日志 |
| **IdeasWatcher** | ideas.md 监控、AI 分解、AI 审查、人工审核、任务追加（支持日志记录） |
| **setup_logging()** | 日志配置（控制台 + orchestrator.log） |

如有其他问题，请参考：
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
