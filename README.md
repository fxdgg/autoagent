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
| **Claude Code** | `npm install -g @anthropic-ai/claude-code`，运行 `claude` 完成 OAuth 登录 |
| **Gemini CLI** | `npm install -g @anthropic-ai/gemini-cli`，运行 `gemini` 完成登录 |
| **OpenCode** | 安装 OpenCode CLI，配置 API Key |
| **Codex** | 安装 Codex CLI，配置 API Key |

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
    completion_criteria: |
      1. cmake --build build 编译成功
      2. build/main 运行输出 "Score: 100/100"
      3. 基准耗时已写入 results.tsv
    initial_hint: |
      1. mkdir -p build && cd build && cmake .. && cmake --build . -j$(nproc)
      2. 运行 ./build/main，确认输出 "Score: 100/100"
      3. 将耗时写入 results.tsv 作为 baseline（status=SOTA）
      4. git add -A && git commit -m "baseline established"

  # 核心：自动迭代优化循环，AI 自主跑 10 轮
  - id: 2
    name: "迭代优化 CUDA 内核"
    type: looping
    repeat_count: 100           # 自动循环 100 轮
    max_attempts_per_loop: 3   # 每轮最多重试 3 次
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
          Step 4: 基于 profiling 数据提出一个具体的优化假设
          Step 5: 将方案写入 ideas/<N>.md（含：假设、预期收益、风险）

      - id: 2.2
        name: "实现优化并运行基准测试"
        type: long_running
        completion_criteria: |
          1. 代码修改已提交
          2. 基准测试运行完成，Score 仍为 100/100
        initial_hint: |
          1. 读取 ideas/<N>.md 了解本轮优化方案
          2. 修改代码，保持改动最小化（一次只改一个点）
          3. cmake --build build -j$(nproc) 编译
          4. 运行 ./build/main 2>&1 | tee logs/exp_<N>.log
          5. 确认 Score 仍为 100/100（正确性不能退化）
          6. git add -A && git commit -m "opt: experiment <N> - <描述>"

      - id: 2.3
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

> **关键设计**：`initial_hint` 是真正驱动 AI 工作的指令——告诉它具体做什么、怎么做、先后顺序；`completion_criteria` 只负责验收关键结果。`looping` 类型让 AI 自动循环执行「分析 → 优化 → 验证」，每轮自主决策。你只需要 `python orchestrator.py` 启动，然后去睡觉——醒来看结果就好。

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

### 🔌 多 AI Provider 一键切换

内置支持 CodeBuddy、Claude Code、Gemini CLI、OpenCode、Codex，一个参数切换：

```bash
python orchestrator.py --provider claude
python orchestrator.py --provider gemini
```

### 💾 断点续传：中断后从上次进度继续

长时间任务不怕中断，状态自动持久化：

```bash
python orchestrator.py --continue          # 继续上次会话
python orchestrator.py --resume abc12345   # 恢复指定会话
```

---

## ✨ 核心特性一览

| 特性 | 说明 |
|------|------|
| **4 种任务类型** | simple（单步）、nested（多子任务）、looping（N 轮迭代）、long_running（后台运行） |
| **Ideas 自动拆解** | 自然语言 ideas → 结构化任务，支持人工审核 |
| **Preset 配置** | `config.yaml` 预设参数组合，避免每次输入大量参数 |
| **Idle 监听模式** | 任务完成后持续监听，检测到新 ideas 自动执行 |
| **完整日志系统** | 记录 AI 对话全过程，支持回溯和调试 |
| **智能失败分析** | AI 自动分析失败根因，决定从哪个步骤重试 |

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
                  │ /Gemini/OpenCode│
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
