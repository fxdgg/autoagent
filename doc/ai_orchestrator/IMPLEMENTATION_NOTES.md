# AI Orchestrator 实现说明

> 临时文档，记录每一部分的实现细节。

---

## 一、文件变更总览

| 文件 | 操作 | 说明 |
|------|------|------|
| `prompts/scheduler.py` | **新建** | 调度器 prompt 构建模块 |
| `prompts/__init__.py` | 修改 | 导出 scheduler 模块 |
| `ai_providers.py` | 修改 | MODEL_ROLES 新增 `scheduler` |
| `config.yaml` | 修改 | 新增 3 个配置项 + preset 更新 |
| `prompts/simple_task.py` | 修改 | `<task>` 段新增 `<task_description>` |
| `prompts/long_running_task.py` | 修改 | 同上 |
| `state_manager.py` | 修改 | 新增 orchestrator 状态读写方法 |
| `orchestrator.py` | 修改（大量） | 核心调度逻辑 |

---

## 二、各部分实现细节

### 2.1 `prompts/scheduler.py`（新建）

**职责**：构建调度器的 system prompt 和 user prompt，以及保存 `type=response` 的结果文件。

#### 2.1.1 `SCHEDULER_SYSTEM_PROMPT`

常量字符串，指导 AI 以严格 JSON 格式返回调度决策。要求返回格式为：

```json
{"action": "execute", "task_id": "2", "reasoning": "..."}
// 或
{"action": "stop", "reasoning": "..."}
```

强调：只返回 JSON，不要包含其他文本；`task_id` 必须是 `available_tasks` 中列出的有效 ID。

#### 2.1.2 `build_scheduler_prompt()`

签名：
```python
def build_scheduler_prompt(
    current_round: int,
    max_rounds: int,
    project_description: str,
    strategy: str,
    stop_condition: str,
    tasks: list[dict],
    task_execution_counts: dict,
    schedule_history: list[dict],
    last_result_config: dict,
    session_dir: str,
    scheduler_history_limit: int = 10,
) -> str
```

构建的 prompt 包含以下 XML 段：

1. **`<project_description>`** — 项目描述（来自 `_get_latest_description()`）
2. **`<scheduling_strategy>`** — 用户定义的调度策略文本
3. **`<stop_condition>`** — 停止条件（可选，为空则不渲染）
4. **`<scheduling_state>`** — 当前轮次 / 最大轮次
5. **`<available_tasks>`** — 每个任务一行，格式：
   ```
   - Task ID: 1 | Name: xxx | Type: simple | Executed: 2 times | Last Result: [见下]
     Description: xxx
   ```
   其中 "Last Result" 由 `_build_last_result_line()` 生成
6. **`<schedule_history>`** — 最近 N 轮历史（由 `scheduler_history_limit` 控制），格式：
   ```
   Round 1: task_id=1 (Baseline) -> success | Reasoning: ...
   ```

#### 2.1.3 `_build_last_result_line()`

根据 `last_result_config` 中该任务的 `type` 字段：

- **`type=none`（或未配置）**：返回 `"N/A"`
- **`type=response`**：读取 `<session_dir>/task_results/result_<task_id>.txt`，如果文件存在则返回其内容（截断到合理长度），否则返回 `"(no result yet)"`
- **`type=file`**：读取指定路径的文件内容。支持单个路径（字符串）或多个路径（列表）。每个文件内容截断到 2000 字符，格式为 `"[path]: content..."`

#### 2.1.4 `save_response_result()` 和 `_get_response_result_path()`

- `_get_response_result_path(task_id, session_dir)` → `<session_dir>/task_results/result_<task_id>.txt`
- `save_response_result(task_id, response_text, session_dir, max_length)` → 创建目录并写入截断后的响应文本

---

### 2.2 `ai_providers.py`

**变更**：`MODEL_ROLES` 元组从 `("plan", "default", "lite", "evaluation")` 扩展为 `("plan", "default", "lite", "evaluation", "scheduler")`。

**影响**：`parse_model_spec()` 函数现在能识别 `scheduler:model_name` 格式的模型指定，例如：
```
--model "default:glm-5;scheduler:claude-opus"
```

---

### 2.3 `config.yaml`

新增两个顶层配置项（位于 `max_nudge_followups` 之前）：

```yaml
scheduler_history_limit: 10
scheduler_decision_max_retries: 3
```

两个 preset（`default` 和 `test`）的 `model` 字段均新增 `scheduler` 角色：

```yaml
model:
  plan: claude-opus-4.6
  default: claude-opus-4.6
  lite: glm-5.0-ioa
  evaluation: claude-opus-4.6
  scheduler: claude-opus-4.6    # ← 新增
```

---

### 2.4 `prompts/simple_task.py` 和 `prompts/long_running_task.py`

**变更**：在 `<task>` 段的 `<task_name>` 和 `<completion_criteria>` 之间，插入可选的 `<task_description>` 子标签。

```python
# simple_task.py 中的变更
inner.append(f"    <task_name>\n{indent_block(task['name'], I8)}\n    </task_name>")
# ↓ 新增
if task.get('description'):
    inner.append(f"    <task_description>\n{indent_block(task['description'], I8)}\n    </task_description>")
# ↑ 新增
inner.append(f"    <completion_criteria>\n{indent_block(task['completion_criteria'], I8)}\n    </completion_criteria>")
```

`long_running_task.py` 同理，但使用 `subtask` 变量而非 `task`。

**行为**：仅当 `description` 字段存在且非空时才渲染，因此对非 AI 调度模式的 todos 完全无影响。

---

### 2.5 `state_manager.py`

新增两个方法（位于 `reset()` 之后、`get_summary()` 之前）：

```python
def get_orchestrator_state(self) -> dict | None:
    """读取 state["orchestrator"]，不存在则返回 None"""
    return self.state.get("orchestrator")

def save_orchestrator_state(self, orch_state: dict):
    """写入 state["orchestrator"] 并持久化到 todos_state.yaml"""
    self.state["orchestrator"] = orch_state
    self.save_state()
```

**状态结构**（`todos_state.yaml` 中的 `orchestrator` 键）：

```yaml
orchestrator:
  mode: ai
  current_round: 5
  max_rounds: 30
  status: in_progress  # in_progress | completed | stopped
  session_id: ""
  schedule_history:
    - round: 1
      task_id: "1"
      task_name: "Baseline"
      result: success  # success | failed | stopped | null(中断)
      reasoning: "Start with baseline"
      timestamp: "2026-04-16 17:00:00"
  task_execution_counts:
    "1": 2
    "2": 1
    "3": 0
```

---

### 2.6 `orchestrator.py`（核心变更）

#### 2.6.1 新增类：`_ScheduleAwareConvLogger`

**位置**：文件顶部，`TodoOrchestrator` 类之前。

**职责**：包装 `ConversationLogger`，为所有日志文件名添加 `schedule_N_` 前缀。

**实现方式**：代理模式。构造时接收 `inner: ConversationLogger` 和 `schedule_round: int`，所有方法调用都转发给 `inner`，但 `task_id` 参数会被加上 `schedule_{round}_` 前缀。

代理的方法包括：`register_nested_task`、`log_prompt`、`log_response`、`log_conversation`、`log_nested_prompt`、`log_nested_response`、`log_nested_task_ai_call`、`build_index_file`、`finalize`。

**效果**：调度轮次 3 的任务 2 的日志文件名会变为 `schedule_3_2_xxx.md`，而非 `2_xxx.md`。

#### 2.6.2 `__init__` 修改

1. `model_roles` 默认字典新增 `"scheduler": self.provider.model`
2. 新增 `self.ai_orchestrator = None`（在 `self.scoped_descriptions = {}` 之后）

#### 2.6.3 `_load_todos` 修改

在 scoped_descriptions 解析之后、task 验证之前，新增：

```python
ai_orch = config.get('ai_orchestrator')
if ai_orch is not None:
    self.ai_orchestrator = self._validate_ai_orchestrator(ai_orch, tasks)
else:
    self.ai_orchestrator = None
```

#### 2.6.4 `_get_latest_description()`

**用途**：AI 调度模式下获取"最新"的项目描述。

**逻辑**：
1. 如果没有 scoped_descriptions，返回 root-level description
2. 否则，找到所有 scope_id ≤ max(task_id) 中最大的那个 scope_id 对应的描述
3. 如果没有匹配的 scope_id，回退到 root-level description

**与 `_get_description_for_task` 的区别**：后者是线性模式下根据当前执行的 task_id 选择描述；前者是 AI 模式下始终取"最新"描述。

#### 2.6.5 `_validate_ai_orchestrator(ai_orch, tasks)`

验证 `ai_orchestrator` 配置的合法性：

| 字段 | 验证规则 |
|------|----------|
| `strategy` | 必填，字符串 |
| `max_rounds` | 可选，正整数，默认 50 |
| `stop_condition` | 可选，字符串 |
| `last_result` | 可选，字典 |
| `last_result.<tid>.type` | 必须是 `none`/`response`/`file` |
| `last_result.<tid>.path` | `type=file` 时必填，必须是绝对路径（字符串或字符串列表） |
| `last_result.<tid>` 的 key | 必须是 tasks 中存在的 task_id |
| 所有 tasks 的 `description` | AI 模式下必填 |

返回标准化后的字典。

#### 2.6.6 `run_ai_scheduled()`

**主调度循环**，流程如下：

```
初始化/恢复 orchestrator 状态
    ↓
检测中断恢复（上一轮未完成的任务）
    ↓
┌─→ 检查 current_round < max_rounds
│       ↓
│   current_round += 1
│       ↓
│   reload_todos()（Ideas Watcher 可能添加了新任务）
│       ↓
│   调用 _get_scheduler_decision() 获取 AI 决策
│       ↓
│   decision.action == "stop"? → 记录历史，设置 status=stopped，退出循环
│       ↓
│   decision.action == "execute"
│       ↓
│   调用 _execute_scheduled_task() 执行选中任务
│       ↓
│   更新历史、执行计数、状态
│       ↓
└───────┘
```

**断点续传**：如果 `schedule_history` 最后一条记录的 `result` 为 `None`，说明上一轮任务被中断。检查该任务的 state key 是否为 `in_progress`，如果是则先恢复执行。

**Ideas Watcher 重启**：如果 orchestrator 状态为 `completed`/`stopped`，但检测到新的 task_id（不在 `task_execution_counts` 中），则自动将状态改回 `in_progress` 继续调度。

#### 2.6.7 `_get_scheduler_decision()`

调用 AI 获取调度决策：

1. 切换到 `scheduler` 模型
2. 创建新 AI client（通过 `_create_ai_client()`）
3. 构建 scheduler prompt（通过 `build_scheduler_prompt()`）
4. 发送请求，解析 JSON 响应
5. 验证 `action` 和 `task_id` 合法性
6. 如果解析失败，在同一 session 中发送错误反馈重试（最多 `max_retries` 次）
7. 恢复原始模型

#### 2.6.8 `_parse_scheduler_response(response)`

从 AI 响应中提取 JSON，三种策略依次尝试：

1. 直接 `json.loads(response.strip())`
2. 从 markdown 代码块 `` ```json ... ``` `` 中提取
3. 正则查找第一个 `{...}` 块

#### 2.6.9 `_create_ai_client(context_id)`

集中化的 AI client 创建逻辑，支持三种模式：
- `TestProvider` → `AIClientTest`
- `use_cli=True` → `AIClient`
- 其他 → `AIClientSDK`

**提取原因**：`run_ai_scheduled` 和 `_execute_scheduled_task` 都需要创建 client，避免代码重复。

#### 2.6.10 `_execute_scheduled_task(task, schedule_round, task_execution_counts)`

在调度上下文中执行单个任务：

1. **State key 隔离**：使用 `{schedule_round}.{task_id}` 格式（如 `3.2`），确保不同调度轮次的同一任务有独立状态
2. **日志隔离**：使用 `_ScheduleAwareConvLogger` 包装器
3. **模型切换**：根据 task 的 `model` 字段切换模型
4. **Session 管理**：每个调度轮次的任务使用新 session（不跨轮次复用）
5. **任务类型分发**：支持 `simple`/`nested`/`looping`/`long_running` 四种类型
6. **Response 保存**：执行后调用 `_save_task_response_result()` 处理 `type=response` 的结果

#### 2.6.11 `_build_scheduled_task(task, schedule_round)`

深拷贝 task 字典，将 ID 改为调度轮次前缀格式：
- 顶层 task ID：`{schedule_round}.{task_id}`（如 `3.2`）
- 子任务 ID：`{schedule_round}.{task_id}.{suffix}`（如 `3.2.1`）

递归处理深层嵌套子任务（通过 `_prefix_subtask_ids()`）。

#### 2.6.12 `_save_task_response_result(task_id, task_type, success)`

检查 `ai_orchestrator.last_result` 中该任务是否配置为 `type=response`，如果是则：
1. 从对应的 executor 获取 `last_response_text` 属性
2. 调用 `save_response_result()` 写入结果文件

#### 2.6.13 `run` 方法修改

新增模式冲突检测：

```python
orch_state = self.state_manager.get_orchestrator_state()
if orch_state:
    raise ConfigError(
        "Cannot run in linear mode: existing AI orchestrator state found. "
        "Use --reset to clear state before switching modes."
    )
```

#### 2.6.14 `run_with_idle` 方法修改

当 `self.ai_orchestrator` 存在时，调用 `run_ai_scheduled()` 而非线性模式的 `run()`。

#### 2.6.15 `_get_session_status` 修改

新增 AI orchestrator 状态显示：
- 进行中：`"ai_sched: round 3/30"`
- 已完成/停止：`"ai_sched: stopped (5/30 rounds)"`

#### 2.6.16 `main()` 修改

1. AI orchestrator 模式下禁止 `--task` 参数（打印错误并 `sys.exit(1)`）
2. 检测模式切换冲突（有线性模式状态但切换到 AI 模式，给出 warning）
3. 路由到 `run_ai_scheduled()` 并处理结果
4. `--model` 帮助文本新增 `scheduler` 角色说明

---

## 三、未实现的部分

根据用户要求，以下部分**暂未实现**：

1. **TASK_DESIGN_GUIDE 和 TASK_DESIGN_GUIDE_AI_SCHED 的变更** — 用户明确要求暂不实现
2. **单元测试** — 设计文档中提到但未要求在本次实现
3. **文档更新**（ARCHITECTURE.md、USAGE.md 等）— 未要求

---

## 四、关键设计决策

### 4.1 为什么用 `_ScheduleAwareConvLogger` 而不是修改 `ConversationLogger`？

- **最小侵入**：不修改现有 `ConversationLogger` 的接口和行为
- **职责清晰**：日志前缀是调度模式特有的关注点，不应污染通用日志器
- **向后兼容**：线性模式完全不受影响

### 4.2 为什么每个调度轮次创建新 AI client？

- **Session 隔离**：避免不同任务的上下文污染
- **与设计文档一致**：设计文档要求 "每个 schedule round 的 task 使用独立 session"
- **断点续传**：通过 `session_id` 保存/恢复机制支持中断恢复

### 4.3 State key 格式 `X.Y.Z@A.B` vs 实际实现

设计文档提到 `X.Y.Z@A.B` 格式（X=调度轮次，Y.Z=任务/子任务 ID，A.B=round-scoped key）。实际实现中：
- 顶层 task state key：`{schedule_round}.{task_id}`（如 `3.2`）
- 子任务 state key：`{schedule_round}.{task_id}.{subtask_suffix}`（如 `3.2.1`）
- 这与现有的 state key 格式（`task_id.subtask_id`）保持一致，只是在前面加了 `schedule_round` 前缀

### 4.4 `_create_ai_client` 的提取

原来 `execute_task` 中内联创建 client 的逻辑被提取为独立方法，因为调度器和任务执行都需要创建 client。这是一个纯粹的重构，不改变任何行为。
