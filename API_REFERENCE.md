# API 参考文档

本文档提供 CodeBuddy Todo Orchestrator 的完整 API 参考。

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
        log_dir: str = None,
        ideas_file: str = None,
        idle_interval: int = 30,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `provider` | AIProvider | None | AI 提供者实例（支持 CodeBuddy/Claude/Gemini） |
| `workspace` | str | "." | 工作目录（项目根目录） |
| `timeout` | int | 3600 | AI 调用超时时间（秒） |
| `log_dir` | str | None | 日志根目录（相对于 CWD，默认 `.autoagent`）|
| `ideas_file` | str | None | ideas.md 文件路径（None 则禁用 ideas 监控） |
| `idle_interval` | int | 30 | idle 模式检查间隔（秒） |

> **注意**：`state_file` 参数已废弃。`todos_state.yaml`、`orchestrator.log`、`.ideas_processed.md` 等运行时文件
> 现在统一放置在由 `log_dir` + `.autoagent_log` 推导出的会话目录下，不再出现在项目目录中。

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
def check_and_process_ideas(self, human_review: bool = False) -> int
```

检查 ideas.md 是否有新内容，如果有则调用 AI 分解为 TODO 任务并追加到 todos.yaml。生成的任务会经过独立 AI 审查，审查不通过则自动修订重审。返回处理的新 idea 数量。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `human_review` | bool | False | 如果为 True，AI 审查通过后挂起等待人工确认 |

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
def build_command(self, continue_session: bool = False) -> str
```

构造 CLI 命令字符串（不含 prompt）。Prompt 始终通过 stdin 管道传递。

#### get_stdin_command

```python
def get_stdin_command(self, prompt_file_path: str, cmd_args: str) -> str
```

构造包含 stdin 管道的完整命令。在 Windows 上使用 `type`，在 Linux/macOS 上使用 `cat`。

### 内置 Provider

#### CodeBuddyProvider

| 属性 | 值 |
|------|----|
| `name` | `"codebuddy"` |
| `default_executable` | `"codebuddy"` |
| `default_model` | `"glm-5.0-ioa"` |

**命令模式**：
```bash
type prompt.txt | codebuddy --debug --verbose --print --output-format stream-json [--continue] --model <model> -y -
```

#### ClaudeCodeProvider

| 属性 | 值 |
|------|----|
| `name` | `"claude"` |
| `default_executable` | `"claude-internal"` |
| `default_model` | `"claude-sonnet-4-6"` |

**命令模式**：
```bash
type prompt.txt | claude-internal --verbose --print --output-format stream-json [--continue] --model <model> --dangerously-skip-permissions -
```

与 CodeBuddy 的关键差异：使用 `--dangerously-skip-permissions` 替代 `-y`。

#### GeminiCLIProvider

| 属性 | 值 |
|------|----|
| `name` | `"gemini"` |
| `default_executable` | `"gemini-internal"` |
| `default_model` | `"gemini-2.5-pro"` |

**命令模式**：
```bash
type prompt.txt | gemini-internal --output-format stream-json [--resume latest] --model <model> --yolo -p -
```

与 CodeBuddy 的关键差异：使用 `-p` 指定非交互模式，使用 `--resume latest` 替代 `--continue`，使用 `--yolo` 替代 `-y`。

### 工厂函数

#### get_provider

```python
def get_provider(
    name: str,
    executable: str = None,
    model: str = None,
    extra_args: str = None,
) -> AIProvider
```

按名称或别名创建 provider 实例。

| 名称 | 别名 |
|------|------|
| `codebuddy` | `cb` |
| `claude` | `claude-code`, `claude-internal` |
| `gemini` | `gemini-cli`, `gemini-internal` |

#### list_providers

```python
def list_providers() -> dict
```

列出所有可用 provider 及其信息（名称、默认可执行文件、默认模型、别名）。

---

## AIClient

统一 AI CLI 客户端，封装 AI 调用、Context 管理和 stream-json 解析。

> **注意**：`AIClient` 是主类名，`CodeBuddyClient` 是为向后兼容保留的别名。

### 类定义

```python
class AIClient:
    def __init__(
        self,
        provider: AIProvider = None,
        workspace: str = ".",
        timeout: int = 3600,
        context_id: str = None,
        # Legacy parameters
        codebuddy_path: str = None,
        model: str = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | AIProvider | None | AI provider 实例（优先于 legacy 参数） |
| `workspace` | str | "." | 工作目录 |
| `timeout` | int | 3600 | 超时时间（秒） |
| `context_id` | str | None | Context 标识符，用于状态记录和日志追踪（注意：`--continue` 只能继续最近一次对话，不支持指定 context ID） |
| `codebuddy_path` | str | None | （Legacy）CodeBuddy 可执行文件路径 |
| `model` | str | None | （Legacy）AI 模型名 |

> 如果不提供 `provider`，会根据 legacy 参数或默认值创建 `CodeBuddyProvider(model="glm-5.0-ioa")`。

### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `last_full_log` | str | 最近一次 `ask()` 的完整对话日志（包含工具调用），供 ConversationLogger 使用 |
| `_session_started` | bool | 内部标志，控制是否使用 `--continue` 参数 |

### Context 管理策略

| 层级 | 策略 | 说明 |
|------|------|------|
| 主任务 | 独立 context | 每个主任务创建独立的 AIClient，互不干扰 |
| 子任务 | 共享 context | 同一主任务内的子任务使用 `--continue` 共享上下文 |

```python
from ai_providers import get_provider
from codebuddy_client import AIClient

provider = get_provider("claude", model="claude-sonnet-4-6")

# 主任务 1
client1 = AIClient(provider=provider, context_id="task_1")
client1.ask("修改模型代码", continue_session=False)   # 创建新 context
client1.ask("检查修改结果", continue_session=True)    # 复用 context

# 主任务 2（完全隔离）
client2 = AIClient(provider=provider, context_id="task_2")
client2.ask("修改另一个模型", continue_session=False)  # 独立 context
```

### 方法

#### ask

向 AI 工具发送提示并获取响应。

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

**执行流程**：
1. 将 prompt 写入临时文件（避免 shell 转义问题）
2. 通过 provider 构造 CLI 命令
3. 启动子进程，实时解析 stream-json 输出
4. 收集 assistant 文本和完整日志（含工具调用）
5. 调用完成后保存到 `last_full_log`

**示例**：

```python
from ai_providers import get_provider
from codebuddy_client import AIClient

provider = get_provider("codebuddy")
client = AIClient(provider=provider, context_id="task_2")

# 第一次调用：创建新 context
result = client.ask("请阅读 program.md 并开始执行任务 2", continue_session=False)

# 后续调用：复用 context
result = client.ask("检查子任务 2.1 的结果", continue_session=True)

# 获取结构化 JSON 响应
decision = client.ask("分析失败原因", expect_json=True, continue_session=True)
print(decision['retry_from'])

# 获取包含工具调用的完整日志
full_log = client.last_full_log
```

#### reset_session

```python
def reset_session(self)
```

重置会话状态，使下一次调用不使用 `--continue`。

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
    def __init__(self, session_dir: str = None)
    def execute(self, task: dict, client: CodeBuddyClient) -> bool
```

**构造函数参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_dir` | str | None | 日志会话目录（从 orchestrator 传入，传递给 SubtaskExecutor） |

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
    def __init__(self, session_dir: str = None)
    def execute(self, subtask: dict, client: CodeBuddyClient) -> SubtaskResult
```

**构造函数参数**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_dir` | str | None | 日志会话目录（long_running 任务必须提供，用于构造 AI prompt 中的 `--log-dir` 参数） |

支持的子任务类型：

| 类型 | 说明 | 执行方式 |
|------|------|----------|
| `simple` | AI 自主完成（含代码修改、命令执行等） | 调用 `client.ask()` |
| `long_running` | 长时间任务 | AI 通过 Bash 调用 `autoagent-exec` 启动，AutoAgent 轮询信号文件 + AI 分析结果 |

**long_running 子任务执行流程**：

1. 构造 prompt，告知 AI 使用 `autoagent-exec` 启动命令（`--log-dir` 使用 `self.session_dir`）
2. AI 通过 Bash 调用 `autoagent-exec`
3. 如果 AI 报告 `LONG_RUNNING_IN_PROGRESS`，轮询信号文件等待完成
4. 完成后重启 AI 会话，让 AI 读取输出日志并评估结果

### autoagent_exec.py

long_running 任务启动器，AI 通过 Bash 调用的独立脚本。

**调用方式**：
```bash
python autoagent_exec.py --log-dir <log_session_dir> --task-id <id> -- <command...>
```

**参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `--log-dir` | str | 日志会话目录绝对路径（由 SubtaskExecutor 的 `session_dir` 提供） |
| `--task-id` | str | 子任务 ID（如 `1.2`） |
| `-- <command>` | str | `--` 之后的所有内容作为要执行的命令 |

**行为**：

| 场景 | 行为 |
|------|------|
| 命令在 10s 内失败（退出码≠ 0） | 打印错误输出，不写信号文件，返回非零退出码 |
| 命令在 10s 内成功（退出码 = 0） | 写入 `finished` 信号文件，返回 0 |
| 命令 10s 后仍在运行 | 写入 `running` 信号文件，打印 `TASK SUBMITTED`，启动监控线程 |

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
    attempt: int,
    parent_task_id: Optional[str] = None,
    metadata: Optional[dict] = None,
)
```

在 AI 调用**之前**将 prompt 写入日志文件。这确保即使进程在等待 AI 响应时被中断（如 Ctrl+C），prompt 也已持久化。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `task_name` | str | 任务名称 |
| `prompt` | str | 发送给 AI 的提示词 |
| `attempt` | int | 尝试次数 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |
| `metadata` | dict | 额外信息（如 `{"type": "failure_analysis"}`） |

#### log_response（推荐：崩溃安全写入）

```python
def log_response(
    self,
    task_id: str,
    response: str,
    parent_task_id: Optional[str] = None,
)
```

在 AI 返回**之后**将 response 追加到日志文件。必须在 `log_prompt()` 之后调用。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `response` | str | AI 的响应 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |

#### log_conversation（便捷包装器）

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

一次性记录 prompt + response（内部调用 `log_prompt` + `log_response`）。新代码建议使用两步方法以获得崩溃安全性。

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | str | 任务 ID |
| `task_name` | str | 任务名称 |
| `prompt` | str | 发送给 AI 的提示词 |
| `response` | str | AI 的响应 |
| `attempt` | int | 尝试次数 |
| `parent_task_id` | str | 父任务 ID（子任务时提供） |
| `metadata` | dict | 额外信息（如 `{"type": "failure_analysis"}`） |

#### log_nested_prompt / log_nested_response（推荐）

```python
def log_nested_prompt(self, task_id: str, task_name: str, call_type: str, prompt: str, round_num: int)
def log_nested_response(self, task_id: str, task_name: str, response)
```

嵌套任务 AI 决策调用的两步写入方法。`log_nested_prompt` 在 AI 调用前写入 prompt，`log_nested_response` 在 AI 返回后追加 response，均写入 `subtask_<id>/_decisions.md`。

#### log_nested_task_ai_call（便捷包装器）

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
        processed_state_file: str = None,
    )
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ideas_file` | str | "ideas.md" | Ideas 文件路径 |
| `todos_file` | str | "todos.yaml" | 任务配置文件路径 |
| `processed_state_file` | str | ".ideas_processed.md" | 已处理 ideas 归档文件（位于会话目录下） |

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
def process_new_ideas(
    self,
    client: CodeBuddyClient,
    review_client: CodeBuddyClient = None,
    conv_logger: ConversationLogger = None,
    human_review: bool = False,
) -> int
```

处理所有新 ideas：解析 → 调用 AI 分解 → AI 审查 → 可选人工审核 → 追加到 todos.yaml → 归档并从 ideas.md 删除。返回处理的 idea 数量。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `client` | CodeBuddyClient | - | AI 客户端实例（用于任务分解） |
| `review_client` | CodeBuddyClient | None | 可选的独立 AI 客户端（全新上下文，用于审查）。如果为 None 则跳过审查步骤 |
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

任务状态持久化管理器，负责加载、保存和更新任务执行状态。

### 类定义

```python
class StateManager:
    def __init__(self, state_file: str = "todos_state.yaml")
```

### 构造函数参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `state_file` | str | "todos_state.yaml" | 状态持久化文件路径（位于会话目录下） |

### 方法

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

---

## 状态类型

### TaskState

任务状态结构（持久化在会话目录的 `todos_state.yaml` 中）。

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
    initial_hint: str                                  # simple 可选
    max_attempts: int                                  # 可选，默认 5
```

> **注意**：`long_running` 类型的子任务不再需要 `command` 字段。AI 会根据任务描述自主决定要运行的命令，并通过 `autoagent-exec` 启动。

---

## 异常类

```python
class ConfigError(Exception):
    """配置文件错误（YAML 语法、缺少字段等）"""

class ExecutionError(Exception):
    """任务执行错误（命令失败、超时等）"""

class AICallError(Exception):
    """AI 调用错误（认证失败、响应解析失败等）"""
```

---

## CLI 参数

`orchestrator.py` 作为 CLI 入口，支持以下命令行参数：

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `--config` | `-c` | `todos.yaml` | 任务配置文件路径 |
| `--task` | `-t` | None | 只执行指定任务 ID |
| `--provider` | `-P` | `codebuddy` | AI provider：`codebuddy`、`claude`、`gemini` |
| `--executable` | - | None | 覆盖 provider 默认可执行文件路径 |
| `--extra-args` | - | None | 传递给 AI 工具的额外 CLI 参数 |
| `--list-providers` | - | - | 列出所有可用 AI provider 并退出 |
| `--codebuddy-path` | - | None | （Legacy）CodeBuddy 可执行文件路径，建议用 `--provider` + `--executable` |
| `--model` | `-m` | 取决于 provider | AI 模型（codebuddy=glm-5.0-ioa, claude=claude-sonnet-4-6, gemini=gemini-2.5-pro） |
| `--workspace` | `-w` | `.` | 工作目录 |
| `--timeout` | - | 3600 | AI 调用超时时间（秒） |
| `--log-dir` | - | `.autoagent` | 日志根目录（相对于 CWD） |
| `--ideas` | - | None | ideas.md 文件路径 |
| `--ideas-only` | - | - | 只处理 ideas.md（带人工审核），不运行 todo list（需搭配 `--ideas`） |
| `--no-idle` | - | - | 禁用 idle 模式（默认当 `--ideas` 指定时自动开启 idle） |
| `--idle-interval` | - | 30 | idle 轮询间隔（秒） |
| `--status` | - | - | 显示当前任务状态并退出 |
| `--reset` | - | - | 重置所有状态并退出 |
| `--validate` | - | - | 验证配置文件并退出 |
| `--no-skip` | - | - | 不跳过已完成的任务 |
| `--verbose` | `-v` | - | 启用 debug 级别日志 |

**示例**：

```bash
# 使用 CodeBuddy 运行所有任务
python orchestrator.py

# 使用 Claude Code 运行特定任务
python orchestrator.py --provider claude --task 2

# 使用 Gemini CLI 并指定模型
python orchestrator.py --provider gemini --model gemini-2.5-pro

# 使用自定义可执行文件路径
python orchestrator.py --provider claude --executable /usr/local/bin/claude

# 带 Ideas 监控和 Idle 模式（--ideas 自动开启 idle）
python orchestrator.py --ideas ideas.md --idle-interval 60

# 带 Ideas 但禁用 idle（处理完即退出）
python orchestrator.py --ideas ideas.md --no-idle

# 只处理 ideas（带人工审核）
python orchestrator.py --ideas ideas.md --ideas-only

# 查看所有可用 provider
python orchestrator.py --list-providers

# 验证配置文件
python orchestrator.py --validate

# 不跳过已完成任务，全部重新执行
python orchestrator.py --no-skip
```

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
| **CodeBuddyProvider / ClaudeCodeProvider / GeminiCLIProvider** | 具体 AI 工具的命令构造 |
| **AIClient** (别名 CodeBuddyClient) | AI 调用、Context 管理、stream-json 解析 |
| **SimpleTaskExecutor** | 简单任务执行（三层完成检测） |
| **NestedTaskExecutor** | 嵌套任务执行、AI 决策调度 |
| **SubtaskExecutor** | 子任务分发执行（接收 session_dir） |
| **autoagent_exec.py** | long_running 任务启动器（10s 快速失败 + 信号文件） |
| **StateManager** | 任务状态持久化（todos_state.yaml） |
| **ConversationLogger** | 对话日志记录、索引生成、Ideas 拆解/审查/修订日志 |
| **IdeasWatcher** | ideas.md 监控、AI 分解、AI 审查、人工审核、任务追加（支持日志记录） |
| **setup_logging()** | 日志配置（控制台 + orchestrator.log） |

如有其他问题，请参考：
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
