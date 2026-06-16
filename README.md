> **此分支为 v1.0 版本，v2.0 版本请切换到 `ai-schedule` 分支：**
>
> ```bash
> git checkout ai-schedule
> ```

<div align="center">

# AutoAgent

**写一份 YAML，让 AI 自己把活干完。**

你定义目标和完成标准，AutoAgent 驱动 AI 自主执行、评估、重试，直到任务完成。

[30 秒上手](#-30-秒上手) · [为什么用 AutoAgent](#-为什么用-autoagent) · [使用场景](#-使用场景) · [文档](#-文档)

</div>

---

## 🚀 30 秒上手

### Step 1：安装依赖

```bash
pip install -r requirements.txt
```

### Step 2：确保 AI 工具已登录 ⚠️

AutoAgent 通过调用 AI 编程助手来执行任务，**运行前必须确保你选用的 AI 工具已安装并完成登录认证**：

| AI Provider | 安装 & 登录 |
|-------------|------------|
| **CodeBuddy**（默认） | 安装 CodeBuddy IDE 插件或 CLI，确保已登录账号 |
| **Claude Code** | `npm install -g @anthropic-ai/claude-code`，运行 `claude` 完成登录 |
| **Gemini CLI** | `npm install -g @google/gemini-cli`，运行 `gemini` 完成登录 |
| **Codex** | `npm install -g @openai/codex`，运行 `codex` 完成登录 |
| **OpenCode** | 安装 OpenCode CLI，配置 API Key |

验证工具可用：

```bash
# 以 CodeBuddy 为例
codebuddy --version

# 或 Claude Code
claude --version
```

### Step 3：创建任务

创建 `todos.yaml`（可参考 `todos.example.yaml`），定义目标、完成标准和执行提示，这是一个全自动优化CUDA程序性能的todos示例：

```yaml
# description 提供全局上下文，AI 在执行每个任务时都能看到
description: |
  你的目标是优化 CUDA 图像处理管线的性能。
  项目使用 CMake + CUDA 12，目标 RTX 4090，正确性测试必须保持 100/100。
  基准数据记录在 results.tsv 中，SOTA 行为当前最优。
  你是全自动运行的，遇到问题请自行决策，不要停下来问问题。

tasks:
  # 一次性前置任务：编译项目、建立基准
  - id: 1
    name: "编译项目并建立基准性能"
    type: simple
    model: lite                # 只是跑编译命令，用便宜模型
    completion_criteria: |
      1. cmake --build build 编译成功
      2. build/main 运行输出 "Score: 100/100"
      3. 基准耗时已写入 results.tsv
    initial_hint: |
      1. mkdir -p build && cd build && cmake .. && cmake --build . -j$(nproc)
      2. 运行 ./build/main，确认输出 "Score: 100/100"
      3. 将耗时写入 results.tsv 作为 baseline（status=SOTA）
      4. git add -A && git commit -m "baseline established"

  # 核心：自动迭代优化循环，AI 自主跑 100 轮
  - id: 2
    name: "迭代优化 CUDA 内核"
    type: looping
    repeat_count: 100           # 自动循环 100 轮
    max_attempts_per_loop: 3   # 每轮遇到错误最多重试 3 次
    completion_criteria: "完成一轮 分析→优化→验证 循环"
    subtasks:
      - id: 2.1
        name: "分析瓶颈并提出优化方案"
        type: simple
        completion_criteria: |
          1. 已读取 results.tsv 中的 SOTA 数据
          2. 优化方案已记录到 ideas/<N>.md
        initial_hint: |
          Step 1: 读取 results.tsv 找到 status=SOTA 的行，了解当前最优性能
          Step 2: 读取 failure_log.md，了解哪些方向已经失败过，避免重复
          Step 3: 用 ncu --set full ./build/main 做 profiling，找到耗时最长的 kernel
          Step 4: 基于 profiling 数据提出一个具体的优化假设。注意优化假设一次只生成一个想法
          Step 5: 将方案写入 ideas/<N>.md（含：假设、预期收益、风险）并提交

      - id: 2.2
        name: "实现代码优化"
        type: simple
        completion_criteria: |
          代码修改已提交
        initial_hint: |
          1. 读取 ideas/<N>.md 了解本轮优化方案
          2. 修改代码
          3. 提交代码修改

      - id: 2.3
        name: "编译并运行基准测试"
        type: long_running
        model: lite            # 纯跑命令，用便宜模型
        completion_criteria: |
          基准测试运行完成，日志已保存到 logs/exp_<N>.log
        initial_hint: |
          1. cmake --build build -j$(nproc) 编译
          2. 运行 ./build/main 2>&1 | tee logs/exp_<N>.log

      - id: 2.4
        name: "评估结果：保留或回滚"
        type: simple
        completion_criteria: |
          1. 新结果已追加到 results.tsv
          2. 若性能提升 ≥5%：保留代码，更新 SOTA
             若无提升或正确性下降：git reset 回滚，记录失败原因到 failure_log.md
        initial_hint: |
          Step 1: 从 logs/exp_<N>.log 提取本轮耗时
          Step 2: 与 results.tsv 中 SOTA 行对比，计算提升百分比
          Step 3: 决策——
            - 提升 ≥5% 且 Score=100/100 → 保留，将新行写入 results.tsv（status=SOTA）
            - 否则 → git reset --hard HEAD~1 回滚代码，
              将失败原因追加到 failure_log.md（含：方向、现象、结论）
          Step 4: git add -A && git commit -m "doc: experiment <N> results"
```

> [!TIP]
> **不想手写这么复杂的 YAML？让 AI 帮你写。**
>
> 你只需要用自然语言描述你想做的事情，然后把 [TASK_DESIGN_GUIDE.md](TASK_DESIGN_GUIDE.md) 喂给任意 AI（ChatGPT、Claude、CodeBuddy 等），让它按照这份指南帮你拆解成 `todos.yaml`。这份指南详细定义了任务类型、字段含义、最佳实践和常见陷阱，AI 读完就能生成高质量的任务配置。
>
> ```
> 你：「我想让 AI 自动把项目的测试覆盖率从 60% 提到 90%」
> AI：（读取 TASK_DESIGN_GUIDE.md）→ 生成完整的 todos.yaml
> 你：python orchestrator.py --config todos.yaml
> ```

### Step 4：启动，然后去喝咖啡

```bash
python orchestrator.py --config todos.yaml
```

AutoAgent 会自动按顺序执行任务。遇到 `looping` 任务时，AI 会自主循环迭代，每轮独立决策，持续优化直到跑完所有轮次。

---

## 💡 为什么用 AutoAgent？

### 🎯 声明式：YAML 定义目标，不用写执行逻辑

你只描述"做什么"和"做到什么程度"，AutoAgent 负责"怎么做"和"做到为止"。

```
你的目标 → YAML 配置 → AutoAgent 编排 → AI 自主执行 → 任务完成
```

### 🔄 自主迭代：AI 自动 尝试 → 评估 → 改进 → 重试

不是跑一次就结束。AI 会评估自己的执行结果，分析失败原因，自动调整策略重试，直到满足你定义的完成标准。

### 💰 省 Token：按任务分配模型，简单活不烧钱

AI 迭代优化动辄跑几十轮，Token 消耗是真实痛点。AutoAgent 支持**四级模型分配**，让你把贵的模型用在刀刃上：

```bash
# 全局：plan 用强模型拆任务，default 执行复杂任务，lite 跑简单活，evaluation 做失败分析和主任务评估
python orchestrator.py --model "plan:claude-opus-4.6;default:claude-sonnet-4;lite:glm-4-flash;evaluation:claude-opus-4.6"
```

还可以在 `todos.yaml` 中**逐任务指定模型**——跑命令、提交代码这类不需要推理的任务用 `lite`，分析瓶颈、设计方案用 `default`：

```yaml
- id: 2.2
  name: "运行基准测试"
  type: long_running
  model: lite              # 只是跑命令，用便宜模型
  completion_criteria: "基准测试完成"

- id: 2.1
  name: "分析瓶颈并提出优化方案"
  type: simple
  model: default           # 需要深度推理，用强模型
  completion_criteria: "优化方案已记录"
```

### 💡 随时投喂想法：Ideas 自动监听 → 拆解 → 执行

AutoAgent 支持 **Idle 监听模式**——agent 在后台持续等待，你随时随地（手机、电脑、任何编辑器）往 `ideas.md` 里写一句想法，agent 自动检测到文件变化，立即将自然语言 idea 拆解成结构化任务并开始执行：

```bash
# 启动后 agent 进入监听状态，所有任务完成后不退出，持续等待新 ideas
python orchestrator.py --ideas ideas.md --config todos.yaml --workspace ./project
```

```markdown
<!-- ideas.md —— 你在地铁上用手机写下一句话 -->
把项目的单元测试覆盖率从 60% 提升到 90%，优先覆盖 core/ 目录下的关键模块
```

Agent 检测到 `ideas.md` 变化后会自动：
1. **AI 拆解**：将自然语言 idea 分解为多个结构化 TODO 任务（含 completion_criteria、initial_hint）
2. **人工审核**（可选）：生成的任务列表可以先让你确认，也可以跳过直接执行
3. **自动执行**：按顺序执行所有任务，失败自动重试，直到全部完成
4. **继续等待**：执行完毕后回到监听状态，等你下一个想法

> **你的工作流**：开着 agent → 想到什么写进 ideas.md → 去忙别的 → 回来看产出。AI 24 小时待命，你的想法随写随跑。

### 🔌 多 AI Provider 一键切换

内置支持 CodeBuddy、Claude Code、Gemini CLI、OpenCode、Codex，一个参数切换：

```bash
python orchestrator.py --provider claude
python orchestrator.py --provider gemini
```


### ⏸️ 断点续传：中断后从上次进度继续

长时间任务不怕中断，状态自动持久化：

```bash
python orchestrator.py --continue          # 继续上次会话
python orchestrator.py --resume abc12345   # 恢复指定会话
```

---

## ✨ 核心特性一览

| 特性 | 说明 |
|------|------|
| **6 种任务类型** | simple（单步）、nested（多子任务）、looping（N 轮迭代）、long_running（后台运行），以及 simple_once / long_running_once（一次性变体） |
| **Ideas 监听 & 自动拆解** | 后台监听 `ideas.md`，检测到变化自动拆解为任务并执行，随写随跑 |
| **Preset 配置** | `config.yaml` 预设参数组合，避免每次输入大量参数 |
| **完整日志系统** | 记录 AI 对话全过程，支持回溯和调试 |
| **智能失败分析** | AI 自动分析失败根因，决定从哪个步骤重试 |
| **模型分级调度** | 全局四角色（plan/default/lite/evaluation）+ 任务级 `model` 字段，Token 精细控制 |

---

## 🎯 使用场景

AutoAgent 适合任何需要 **AI 长时间自主工作** 的场景：

| 场景 | 任务类型 | AI 做什么 |
|------|---------|----------|
| **模型训练迭代优化** | `looping` | 每轮自主提出假设 → 改代码 → 跑训练 → 评估指标 → 保留或回滚 |
| **CUDA / 性能优化** | `looping` | 自动 profile → 找瓶颈 → 优化 → benchmark → 记录结果 |
| **代码质量改进** | `nested` | 分析 lint 警告 → 逐个修复 → 验证通过 |
| **数据处理管线** | `nested` + `long_running` | 下载 → 清洗 → 转换 → 验证，长时间步骤后台运行 |
| **自动化测试修复** | `simple` | 跑测试 → 分析失败 → 修复代码 → 重跑直到全绿 |

> 核心思路：**你定义「做什么」和「做到什么程度」，AI 负责 24 小时不间断地自主执行和迭代。**

更多示例见 [示例集合](doc/EXAMPLES.md) 和 `todos.example.yaml`。

---

## 📖 常用命令

```bash
# 全自动：ideas → 任务拆解 → 执行
python orchestrator.py --ideas ideas.md --config todos.yaml --workspace ./project

# 先拆解 ideas 并人工审核，再运行
python orchestrator.py --ideas ideas.md --config todos.yaml --ideas-only
python orchestrator.py --config todos.yaml --workspace ./project

# 只执行某个任务
python orchestrator.py --task 2

# 查看状态 / 重置
python orchestrator.py --status
python orchestrator.py --reset

# 使用 Preset 配置
python orchestrator.py --preset default
```

完整命令行参数和 Preset 配置说明见 [使用指南](doc/USAGE.md)。

---

## 🏗️ 架构概览

```
┌───────────────────────────────────┐
│         TodoOrchestrator          │
│     任务解析 · 调度 · 状态管理      │
└──────────────┬────────────────────┘
               │
       ┌───────┼───────┐
       ▼       ▼       ▼
 ┌──────────┐ ┌──────────┐ ┌──────────┐
 │  Simple  │ │  Nested  │ │ Looping  │
 │ Executor │ │ Executor │ │ Executor │
 └──────────┘ └────┬─────┘ └────┬─────┘
                   └──────┬─────┘
                          ▼
                  ┌─────────────────┐
                  │   AI Provider   │
                  │ CodeBuddy/Claude│
                  │/Gemini/OpenCode │
                  │     /Codex      │
                  └─────────────────┘
```

更多架构细节见 [架构设计文档](doc/ARCHITECTURE.md)。

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [架构设计](doc/ARCHITECTURE.md) | 系统架构和核心概念详解 |
| [使用指南](doc/USAGE.md) | 完整使用指南和最佳实践 |
| [API 参考](doc/API_REFERENCE.md) | 模块接口和配置项说明 |
| [示例集合](doc/EXAMPLES.md) | 更多实际使用示例 |
| [文件说明](doc/FILES.md) | 项目文件结构说明 |

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
