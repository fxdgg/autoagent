# TASK_DESIGN_GUIDE 修改方案

> **本文档为临时设计文档**，描述 AI Orchestrator 功能引入后对 `TASK_DESIGN_GUIDE.md` 的修改方案。实现完成后本文档将被删除，修改内容将直接合入 `TASK_DESIGN_GUIDE.md`。

---

## 1. 核心变更：Linear 与 AI 调度需要独立的设计指南

### 1.1 动机

Linear 模式和 AI 调度模式对任务设计的要求有本质差异：

| 维度 | Linear 模式 | AI 调度模式 |
|------|------------|------------|
| **执行顺序** | 用户定义，按 ID 顺序执行 | AI 决定，动态调度 |
| **任务间依赖** | 隐式依赖（ID 顺序保证） | 必须通过 `last_result` 显式传递 |
| **任务复用** | 每个任务只执行一次 | 同一任务可被多次调度（除非 `once: true`） |
| **状态传递** | 前一个任务的文件系统副作用自然传递 | 必须通过 `last_result` 文件显式传递结果 |
| **停止条件** | 所有任务执行完毕 | AI 根据策略和结果动态决定 |
| **description 作用** | 为执行 AI 提供项目上下文 | 同时为调度 AI 和执行 AI 提供上下文 |
| **ID 格式** | `Y.Z`（task.subtask） | `X.Y.Z`（schedule_round.task.subtask） |

因此，`TASK_DESIGN_GUIDE.md` 需要拆分为两份独立的指南，用户根据所选模式阅读对应的指南。

### 1.2 文档结构方案

```
task_design_guide/
├── TASK_DESIGN_GUIDE_AI_SCHED.md     # 新增：AI 调度模式指南
├── build_and_ship.md                 # 保持不变（通用）
├── iterative_optimization.md         # 保持不变（通用）
├── ...                               # 其他 type-specific 指南保持不变
```

**方案说明**：
- 现有的 `TASK_DESIGN_GUIDE.md` 保持不变，继续作为 Linear 模式的权威指南
- 新增 `TASK_DESIGN_GUIDE_AI_SCHED.md` 作为 AI 调度模式的指南
- §7 中的 type-specific 指南（`build_and_ship.md` 等）是通用的，两种模式共享
- Ideas Watcher 在生成任务时，根据 `todos.yaml` 中是否有 `ai_orchestrator` 字段来选择加载哪份指南

---

## 2. `TASK_DESIGN_GUIDE_AI_SCHED.md` 大纲

### 2.1 与 Linear 指南的差异概览

以下列出 AI 调度指南相对于 Linear 指南的**关键差异点**，未列出的部分（如 §2 Task Types、§3.2-3.4 Common/Type-Specific Fields、§5 Best Practice、§6 Retry and Failure Handling 等）与 Linear 指南基本一致，可直接复用。

### 2.2 §1 Execution Model Overview — 修改

Linear 指南中的执行模型描述需要替换：

| 属性 | Linear 模式 | AI 调度模式（新） |
|------|------------|------------------|
| **Sequential execution** | 按 ID 顺序执行 | AI 每轮从可用任务中选择一个执行 |
| **Failed tasks don't block** | 失败不阻塞后续任务 | AI 根据失败结果决定下一步（可能重试、跳过、或执行诊断任务） |
| **Task reuse** | 每个任务只执行一次 | 同一任务可被多次调度（除非 `once: true`） |
| **Termination** | 所有任务执行完毕 | AI 决定停止，或达到 `max_rounds` |

### 2.3 §3.1 Root-Level Fields — 修改

新增 `ai_orchestrator` 字段的文档：

```yaml
ai_orchestrator:
  strategy: |           # 必填：调度策略描述
  max_rounds: 30        # 可选：最大调度轮次（默认 50）
  stop_condition: |     # 可选：停止条件描述
  last_result:          # 可选：每个 task 的结果文件配置
    <task_id>:
      type: file|response|none
      path: /absolute/path  # 仅 type=file 时需要
```

新增 `tasks[].description` 字段：

```yaml
tasks:
  - id: 1
    name: "Baseline training"
    description: |      # AI 调度模式下必填
      Run the baseline training pipeline with default hyperparameters.
      Produces baseline_metrics.txt containing E2E NRMSE and training time.
    type: nested
    ...
```

#### `tasks[].description` 设计说明

| 属性 | 说明 |
|------|------|
| **作用** | 供调度 AI 了解任务内容，替代调度 prompt 中的 completion_criteria |
| **必填性** | AI 调度模式下必填；Linear 模式下可不填（不修改现有 TASK_DESIGN_GUIDE.md） |
| **内容要求** | 描述任务做什么、产出什么结果，帮助调度 AI 判断何时应该调度该任务 |
| **与 name 的区别** | `name` 是简短标识（一行），`description` 是详细描述（可多行） |
| **与 completion_criteria 的区别** | `completion_criteria` 是给执行 AI 看的“完成标准”，`description` 是给调度 AI 看的“任务简介” |
| **截断** | 调度 prompt 中截断到 `truncation_limits.max` 字符 |

注：原始 `TASK_DESIGN_GUIDE.md` 也需要修改，加上新增的 `tasks[].description` 字段。

### 2.4 §3.1+ 新增：`last_result` 设计指南 — 新增章节

这是 AI 调度模式最关键的新增内容，需要详细说明。

#### 2.4.1 为什么需要 `last_result`

在 Linear 模式中，任务按固定顺序执行，前一个任务的文件系统副作用自然传递给下一个任务。但在 AI 调度模式中：

1. **调度 AI 需要了解任务结果才能做出决策**：调度 AI 不执行任务，它只看到任务的元信息。如果没有结构化的结果传递机制，调度 AI 无法知道"baseline 的 NRMSE 是多少"或"优化实验是否成功"。

2. **AI 原始 response 不适合直接作为调度依据**：
   - 对于 `simple` 任务，AI 的 response 可能包含大量代码编辑、命令输出等无关信息
   - 对于 `nested` 任务，最终结果分散在多个 subtask 的 response 中
   - 对于 `looping` 任务，结果分散在多轮迭代中

3. **结果必须是一个文件路径**：调度 prompt 中只传递文件路径（而非文件内容），调度 AI 在需要时可以读取文件内容。这避免了 prompt 膨胀。

#### 2.4.2 `last_result.type` 选择指南

| type | 适用场景 | 示例 |
|------|---------|------|
| `file` | 任务会生成明确的结果文件（推荐） | 训练日志、benchmark 报告、实验结果 TSV |
| `response` | 任务是 simple 类型且结果就在 AI response 中 | 代码分析报告、诊断结论 |
| `none` | 任务不产生需要传递给调度 AI 的结果 | 环境准备、清理任务 |

**推荐优先级**：`file` > `response` > `none`

- **`file` 是首选**：用户在 `completion_criteria` 或 `initial_hint` 中要求执行 AI 将结果写入指定文件，然后在 `last_result` 中配置该文件路径。这样结果是结构化的、可控的。
- **`response` 作为兜底**：当任务结果难以提前规划文件路径时使用。系统会自动将 AI 最终 response 的前 4000 字节截断版本保存到 `.autoagent/<run>/task_results/result_<task_id>.txt`。保存的始终是最后一个执行单元的 response（simple 任务为该任务的 response，nested/looping 任务为最后一个 subtask 的 response）。**注意**：`nested` 任务通常不应使用 `type=response`，因为最后一个 subtask 的 response 往往不能代表整个任务的结果。
- **`none` 用于无结果任务**：如环境准备、数据下载等，调度 AI 只需知道任务是否完成，不需要具体结果。

#### 2.4.3 `file` 类型的设计模式

**关键原则**：`last_result.path` 指向的文件必须由任务的 `completion_criteria` 或 `initial_hint` 保证生成。

```yaml
# 在 ai_orchestrator 中配置
ai_orchestrator:
  last_result:
    1:
      type: file
      path: D:/project/results/baseline_metrics.txt

# 在 task 中确保文件生成
tasks:
  - id: 1
    name: "Baseline training"
    type: nested
    completion_criteria: |
      1. Training completes with exit code 0.
      2. results/baseline_metrics.txt contains E2E NRMSE value.
    subtasks:
      # ... subtasks that produce the result file ...
```

**对于 nested 任务**：结果文件应该是一份经过总结的 summary，而非原始的 subtask 输出。建议在最后一个 subtask 中生成汇总文件：

```yaml
subtasks:
  - id: 1.1
    name: "Run training"
    type: long_running
    # ...
  - id: 1.2
    name: "Evaluate and summarize results"
    type: simple
    completion_criteria: |
      1. results/baseline_metrics.txt exists.
      2. File contains: model name, E2E NRMSE, training time, key hyperparameters.
    initial_hint: |
      Read the training log and evaluation output.
      Write a concise summary to results/baseline_metrics.txt including:
      - E2E NRMSE value
      - Training time
      - Key hyperparameters used
```

#### 2.4.4 Schema 校验规则

| 规则 | 说明 |
|------|------|
| `type` 必须是 `"none"` / `"response"` / `"file"` 之一 | 其他值报 ConfigError |
| `type=file` 时 `path` 必填 | 缺少 `path` 报 ConfigError |
| `type=file` 时 `path` 必须是绝对路径 | `os.path.isabs(path)` 为 False 时报 ConfigError |
| `type=response` 或 `type=none` 时 `path` 被忽略 | 即使提供了 `path` 也不使用 |
| `last_result` 中的 task_id 必须在 `tasks` 中存在 | 引用不存在的 task_id 报 ConfigError |

### 2.5 §3.5 ID Assignment Rules — 修改

#### 背景：现有 round_scoped key 格式（Linear 模式）

在现有的 Linear 模式中，`todos_state.yaml` 中的子任务状态使用 **round-scoped key** 格式：

```
subtask_id @ A.B
```

其中 `@` 是分隔符，`A.B` 是 **round_label**：

| 部分 | 含义 | Nested task | Looping task |
|------|------|-------------|-------------|
| `subtask_id` | 子任务 ID（如 `1.2`、`2.3`） | task_id.subtask_id | task_id.subtask_id |
| `A` | 主轮次 | main evaluation round（主任务评估轮次，每次 main_task_evaluation 后 +1） | loop_idx（循环索引） |
| `B` | 子轮次 | failure sub-round（失败分析子轮次，每次 failure_analysis 后 +1） | failure sub-round（同左） |

**Linear 模式示例**：

```yaml
# Nested task（Task 1，含 subtask 1.1, 1.2, 1.3）
"1.1@1.1":   # subtask 1.1, main round 1, failure sub-round 1（初始执行）
"1.2@1.1":   # subtask 1.2, main round 1, failure sub-round 1
"1.3@1.1":   # subtask 1.3, main round 1, failure sub-round 1 → 失败
"1.3@1.2":   # subtask 1.3, main round 1, failure sub-round 2（failure_analysis 后重试）
"1.1@2.1":   # subtask 1.1, main round 2（main_task_evaluation 后重新执行）

# Looping task（Task 2，repeat_count=3，含 subtask 2.1, 2.2）
"2.1@1.1":   # subtask 2.1, loop 1, failure sub-round 1
"2.2@1.1":   # subtask 2.2, loop 1, failure sub-round 1
"2.1@2.1":   # subtask 2.1, loop 2, failure sub-round 1
"2.2@2.1":   # subtask 2.2, loop 2, failure sub-round 1 → 失败
"2.2@2.2":   # subtask 2.2, loop 2, failure sub-round 2（failure_analysis 后重试）
```

> **注意**：`*_once` 类型的子任务使用 plain key（不带 `@`），跨所有轮次共享状态。

#### round_scoped key 格式变更：subtask_id 从 `Y.Z` 扩展为 `X.Y.Z`

在 AI 调度模式下，subtask_id 从二级格式 `Y.Z` 扩展为三级格式 `X.Y.Z`：

| 层级 | 含义 | 示例 |
|------|------|------|
| `X` | 调度轮次（schedule round），全局累加 | `1`, `2`, `3`, ... |
| `Y` | 任务 ID（task_id） | `1`, `2`, `3`, ... |
| `Z` | 子任务 ID（subtask_id），与原有格式一致 | `1`, `2`, `3`, ... |

**subtask_id 示例**：

```
调度轮次 1 → 执行 Task 1（nested，含 subtask 1.1, 1.2）
  1.1.1  — 调度轮次 1，Task 1，Subtask 1
  1.1.2  — 调度轮次 1，Task 1，Subtask 2

调度轮次 2 → 执行 Task 2（simple）
  2.2    — 调度轮次 2，Task 2（simple 任务没有 Z 层级）

调度轮次 3 → 执行 Task 2（再次调度，nested）
  3.2.1  — 调度轮次 3，Task 2，Subtask 1
  3.2.2  — 调度轮次 3，Task 2，Subtask 2

调度轮次 4 → 执行 Task 1（再次调度）
  4.1.1  — 调度轮次 4，Task 1，Subtask 1
  4.1.2  — 调度轮次 4，Task 1，Subtask 2
```

#### 完整的 state key 格式：`X.Y.Z@A.B`

在 AI 调度模式下，完整的 round-scoped state key 是 **subtask_id + `@` + round_label** 的组合：

```
X.Y.Z @ A.B
└─┬─┘   └┬┘
  │      └── round_label（与 Linear 模式含义一致）
  └── subtask_id（AI 调度模式下扩展为三级）
```

**完整 state key 示例**：

```yaml
# 调度轮次 1 → 执行 Task 1（nested，含 subtask 1.1, 1.2, 1.3）
"1.1.1@1.1":   # 调度轮次 1, Task 1, Subtask 1, main round 1, failure sub-round 1
"1.1.2@1.1":   # 调度轮次 1, Task 1, Subtask 2, main round 1, failure sub-round 1
"1.1.3@1.1":   # 调度轮次 1, Task 1, Subtask 3, main round 1, failure sub-round 1 → 失败
"1.1.3@1.2":   # failure_analysis 后重试 → failure sub-round 2

# 调度轮次 3 → 再次执行 Task 1（nested）
"3.1.1@1.1":   # 调度轮次 3, Task 1, Subtask 1, main round 1, failure sub-round 1
"3.1.2@1.1":   # 调度轮次 3, Task 1, Subtask 2, main round 1, failure sub-round 1
```

> **对比**：同一个 Task 1 的 Subtask 1 在不同调度轮次中的 state key：
> - 调度轮次 1：`1.1.1@1.1`（X=1）
> - 调度轮次 3：`3.1.1@1.1`（X=3）

**设计理由**：
- `X` 全局累加（不按 task 独立计数），使得在 log 文件中可以看到清晰的全局工作流时间线
- 通过 `X` 前缀，可以立即区分同一个 task 的不同调度轮次的日志
- `@A.B` 部分与 Linear 模式完全一致，复用现有的 round_label 机制
- 在 Linear 模式下，`X` 层级不存在，保持现有的 `Y.Z@A.B` 格式不变

### 2.6 round_scoped description — 行为修改

#### 现有行为（Linear 模式）

`description@N` 表示从 Task N 开始生效的 scoped description。执行器选择 `scope_id <= task_id` 的最大 scope 对应的 description。

#### AI 调度模式下的行为

在 AI 调度模式下，`description@N` 的语义变为：**每次传入最新的 description，忽略更早的 description**。

具体规则：
1. 调度 AI 的 prompt 中，`<project_description>` 始终使用**最新的** scoped description
2. "最新"的定义：`scope_id` 最大且 `scope_id <= 当前最大已定义 task_id` 的 description
3. 如果 Ideas Watcher 追加了新任务并带有新的 `description@N`，后续所有调度轮次都使用这个新 description
4. 执行 AI 的 prompt 中，`<project_description>` 也使用同样的最新 description

**示例**：

```yaml
description: |
  Initial project description.

description@3: |
  Updated description after adding optimization tasks.

description@6: |
  Final phase: focus on deployment and validation.
```

- 调度轮次 1-2（执行 Task 1, 2）：使用 `description@3`（因为 task 3 已定义，`description@3` 是最新的）
- Ideas Watcher 追加 Task 6-8 并带有 `description@6`
- 调度轮次 3+：使用 `description@6`（最新的 scoped description）

**与 Linear 模式的区别**：
- Linear 模式：`description@3` 只对 Task 3+ 生效，Task 1-2 仍使用根 `description`
- AI 调度模式：一旦 `description@3` 存在，所有调度轮次都使用它（因为调度是全局的，不按 task_id 分段）

### 2.7 §4 Best Practice: Task Decomposition — 修改

新增 AI 调度模式特有的任务设计模式：

#### 任务粒度原则

在 AI 调度模式下，每个 task 应该是一个**自包含的、可独立调度的工作单元**：

| 原则 | 说明 |
|------|------|
| **自包含** | 任务不应假设特定的前置任务已执行（除非通过 `once` 保证） |
| **结果可观测** | 任务必须通过 `last_result` 产生可供调度 AI 读取的结果 |
| **可重复** | 非 `once` 任务应设计为可多次执行（每次可能在不同状态下） |
| **原子性** | 任务要么完全成功，要么完全失败，避免半完成状态 |

#### 与 Linear 模式的任务设计差异

```yaml
# Linear 模式：任务间通过顺序保证依赖
tasks:
  - id: 1
    name: "Setup environment"     # 先执行
  - id: 2
    name: "Run experiment"        # 后执行，隐式依赖 1
  - id: 3
    name: "Generate report"       # 最后执行，隐式依赖 2

# AI 调度模式：任务间通过 last_result 显式传递结果
ai_orchestrator:
  strategy: |
    1. 先执行 Setup（如果未执行过）
    2. 然后循环执行 Experiment
    3. 达到目标后执行 Report
  last_result:
    1:
      type: none                  # Setup 不需要传递结果
    2:
      type: file
      path: D:/project/results/experiment_result.txt
    3:
      type: file
      path: D:/project/results/final_report.txt

tasks:
  - id: 1
    name: "Setup environment"
    description: |
      Verify and set up the training environment, install dependencies,
      and validate GPU availability.
    once: true                    # 只执行一次
  - id: 2
    name: "Run experiment"
    description: |
      Execute one round of optimization experiment with a new configuration.
      Records results to experiment_result.txt for the scheduler to review.
                                  # 可被多次调度
  - id: 3
    name: "Generate report"
    description: |
      Compile all experiment results into a final summary report.
    once: true
```

---

## 3. 对现有 `TASK_DESIGN_GUIDE.md` 的修改

无需修改，原先 Linear 模式下的 AI 没有必要知道任何与 AI 调度模式相关的信息。

---

## 4. Ideas Watcher 集成

Ideas Watcher 在生成和审查任务时需要加载正确的 TASK_DESIGN_GUIDE：

```python
def load_task_design_guide(mode: str = 'linear') -> str:
    """Load the appropriate task design guide based on execution mode."""
    if mode == 'ai_scheduled':
        return _load_guide('TASK_DESIGN_GUIDE_AI_SCHED.md')
    else:
        return _load_guide('TASK_DESIGN_GUIDE.md')
```

Ideas Watcher 通过检查 `todos.yaml` 中是否存在 `ai_orchestrator` 字段来决定使用哪份指南。

---

## 5. 实现优先级

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | 创建 `TASK_DESIGN_GUIDE_AI_SCHED.md` | 基于现有指南，修改差异部分 |
| P1 | 修改 `load_task_design_guide()` | 支持按模式加载不同指南 |
| P1 | 实现 `last_result` schema 校验 | 在 `_load_todos()` 中添加 |
| P2 | 实现 `task_results/` 目录和 response 自动保存 | `type=response` 的支持 |
