# TASK_DESIGN_GUIDE 修改方案

> **本文档为临时设计文档**，描述 AI Orchestrator 功能引入后对 `TASK_DESIGN_GUIDE.md` 及相关指南的修改方案。实现完成后本文档将被删除，修改内容将直接合入正式文档。

---

## 1. 调整后的文档策略

经过进一步澄清后，文档策略应调整为：

1. 现有的 `TASK_DESIGN_GUIDE.md` 继续保持 **Linear 模式指南** 的定位。
2. 该文档只新增一个与 task 本身相关、且对 Linear / AI 调度都不冲突的字段：`tasks[].description`。
3. **不在 `TASK_DESIGN_GUIDE.md` 中暴露任何 AI 调度相关概念**，包括：
   - `ai_orchestrator`
   - `last_result`
   - 调度策略 / 停止条件
   - 调度轮次和 `X.Y.Z` 命名
4. AI 调度模式所需的全部额外认知，放到新的 `TASK_DESIGN_GUIDE_AI_SCHED.md` 中。

这样做的原因是：

- `tasks[].description` 是 task 自身元信息，放进通用 schema 合理。
- 其余 AI 调度内容都属于执行模式语义，不应污染 Linear 指南。

---

## 2. 对 `TASK_DESIGN_GUIDE.md` 的唯一改动

### 2.1 在 Common Fields 中新增 `tasks[].description`

在现有 `TASK_DESIGN_GUIDE.md` 的 task 通用字段部分，新增：

| Field | Type | Required | Description |
|------|------|----------|-------------|
| `description` | string | No | Task-specific description: what this task does, what it is expected to produce, and any high-level context about its role |

### 2.2 对 `tasks[].description` 的解释

该字段在通用指南中的描述应保持 AI 调度无关，只说明它是 task 的补充说明字段。例如：

- `name` 是简短标签。
- `description` 是更详细的任务说明，可用于补充 task 做什么、产出什么、在整体工作流中的角色。
- 即使在 Linear 模式下，这个字段也可以提升 task 可读性和可维护性。

同时，原有执行 task 的 prompt 模板也应补上这个字段，而不是只在 schema 中声明。建议将 `<task>` 段统一为：

```xml
[system_prompt_prefix]

<task>
    <task_name>
        [task_name]
    </task_name>

    <task_description>  （仅在包含 task_description 时出现）
        [task_description]
    </task_description>

    <completion_criteria>
        [completion_criteria]
    </completion_criteria>

    <initial_hint>
        [initial_hint]
    </initial_hint>
</task>

<context>
（后面保持不变）
```

这仍然不属于“AI 调度特有语义”，因为它服务的是所有 task 执行 prompt，而 `description` 本身也是 task 通用字段。

### 2.3 不新增任何 AI 调度字段

以下内容**不要**加入 `TASK_DESIGN_GUIDE.md`：

- 顶层 `ai_orchestrator`
- `ai_orchestrator.last_result`
- `type=response` / `type=file` / `type=none`
- `X.Y.Z@A.B` 状态 key 规则
- 调度 prompt 规则

---

## 3. 新增 `TASK_DESIGN_GUIDE_AI_SCHED.md`

AI 调度模式需要独立指南，负责承载所有模式特有信息。

该文档应覆盖：

1. AI 调度模式的执行模型。
2. 顶层 `ai_orchestrator` schema。
3. `last_result` 设计与选择原则。
4. `tasks[].description` 在调度中的作用。
5. 重复调度、session 生命周期、`*_once` subtask 不重复执行等规则。
6. AI 调度模式专属的任务设计最佳实践。

---

## 4. Ideas Watcher 集成

Ideas Watcher 在生成和审查任务时，需要根据当前 `todos.yaml` 是否启用了 AI 调度模式来决定加载哪份指南。

推荐接口：

```python
def load_task_design_guide(mode: str = linear) -> str:
    if mode == "ai_scheduled":
        return _load_guide(TASK_DESIGN_GUIDE_AI_SCHED.md)
    return _load_guide(TASK_DESIGN_GUIDE.md)
```

选择规则：

- `todos.yaml` 没有 `ai_orchestrator`：加载 `TASK_DESIGN_GUIDE.md`
- `todos.yaml` 有 `ai_orchestrator`：加载 `TASK_DESIGN_GUIDE_AI_SCHED.md`

---

## 5. 需要同步修正的点

### 5.1 旧提法需要删除

之前文档中的这类说法需要删除或改写：

- “原始 `TASK_DESIGN_GUIDE.md` 也需要修改，加上 AI 调度相关字段”
- “`TASK_DESIGN_GUIDE.md` 需要拆成两份，因此原文内容大范围迁移”

正确说法应该是：

- `TASK_DESIGN_GUIDE.md` 只做最小改动，新增 `tasks[].description`。
- AI 调度特有内容全部进入新文档。

### 5.2 `tasks[].description` 的表述也应去 AI 化

在通用指南中，不要写成“供调度 AI 了解任务内容”。

更合适的表述是：

- “task-specific description，用于补充说明任务目的、产出和上下文”。

这样该字段在 Linear 和 AI 调度两种模式下都成立。

---

## 6. 实现优先级

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | 创建 `TASK_DESIGN_GUIDE_AI_SCHED.md` | 承载全部 AI 调度特有内容 |
| P0 | 修改 `TASK_DESIGN_GUIDE.md` | 只新增 `tasks[].description` 字段说明 |
| P1 | 修改 `load_task_design_guide()` | 支持按模式加载不同指南 |
| P1 | 让 Ideas Watcher 按 `ai_orchestrator` 选择指南 | 生成和审查阶段都要一致 |
| P2 | 补充 AI 调度模式示例 | 确保生成任务时有足够参考 |
