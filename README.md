<div align="center">

# AutoAgent

**AI 驱动的智能任务编排系统**

让 AI 自主规划、执行、评估和迭代，自动完成复杂的多步骤工作流。

[快速开始](#-快速开始) · [核心特性](#-核心特性) · [使用场景](#-使用场景) · [文档](#-文档)

</div>

---

## 什么是 AutoAgent？

AutoAgent 是一个 **AI 任务编排引擎**，通过简洁的 YAML 配置定义任务目标和完成标准，由 AI 自主完成代码修改、命令执行、结果评估和迭代优化的全过程。

**核心理念**：你只需要描述"做什么"和"做到什么程度"，AutoAgent 负责"怎么做"和"做到为止"。

```
你的目标 → YAML 配置 → AutoAgent 编排 → AI 自主执行 → 任务完成
```

## 为什么选择 AutoAgent？

| 传统方式 | 使用 AutoAgent |
|---------|---------------|
| 手动拆解任务，逐步指导 AI | 一次配置，全自动执行 |
| 遇到失败需要人工介入分析 | AI 自主分析失败原因并重试 |
| 长时间任务需要人工监控 | 后台运行，自动监控和回调 |
| 多步骤流程难以持续跟踪 | 完整的状态持久化和断点续传 |
| 单一 AI 工具绑定 | 多 AI Provider 灵活切换 |

## ✨ 核心特性

### 智能任务执行

- **AI 自主决策** — AI 完全掌控任务的执行策略、完成判断和失败恢复
- **自动迭代优化** — 尝试 → 评估 → 改进 → 重试，持续迭代直到达标
- **智能失败分析** — AI 自动分析失败根因，决定从哪个步骤重试

### 灵活的任务模型

- **简单任务（simple）** — AI 自主完成的单步任务
- **嵌套任务（nested）** — 包含多个子任务的复杂工作流，AI 评估整体完成度
- **循环任务（looping）** — 固定 N 轮迭代，适合 profile → optimize → benchmark 场景
- **长时间任务（long_running）** — 后台运行，避免超时，自动监控状态

### 多 AI Provider 支持

内置支持多种 AI 编程助手，轻松切换：

```bash
# CodeBuddy（默认）
python orchestrator.py --provider codebuddy

# Claude Code
python orchestrator.py --provider claude --model claude-sonnet-4-6

# Gemini
python orchestrator.py --provider gemini --model gemini-2.5-pro

# OpenCode
python orchestrator.py --provider opencode
```

### 其他能力

- **Ideas 自动拆解** — 将自然语言 ideas 自动拆解为结构化任务
- **状态持久化** — 支持断点续传，中断后从上次进度继续
- **Idle 模式** — 任务完成后持续监听，检测到新 ideas 自动执行
- **完整日志系统** — 记录 AI 对话全过程，支持回溯和调试

## 🚀 快速开始

### 1. 安装

```bash
pip install -r requirements.txt
```

### 2. 配置 AI 工具

确保已安装并登录你选用的 AI 编程助手（如 CodeBuddy、Claude Code 等）：

```bash
# 以 CodeBuddy 为例
codebuddy --version
```

### 3. 创建任务配置

创建 `todos.yaml`（可参考 `todos.example.yaml`）：

```yaml
tasks:
  - id: 1
    name: "下载数据集"
    type: simple
    completion_criteria: "data.csv 文件存在且大小 > 10MB"
    initial_hint: "使用 python download.py"

  - id: 2
    name: "优化模型性能"
    type: nested
    completion_criteria: "训练成功完成且 val_loss < 0.5"
    subtasks:
      - id: 2.1
        name: "修改训练代码"
        type: simple
        completion_criteria: "代码修改完成"

      - id: 2.2
        name: "运行训练"
        type: long_running
        completion_criteria: "训练正常退出且验证集指标满足要求"
```

### 4. 运行

```bash
# 基本运行
python orchestrator.py

# 全自动模式：从 ideas 自动拆解并执行
python orchestrator.py --ideas ideas.md --config todos.yaml --workspace ./my_project

# 查看状态
python orchestrator.py --status
```

## 📖 使用指南

### 命令行参数

| 参数 | 简写 | 说明 |
|------|------|------|
| `--config` | `-c` | 任务配置文件路径（默认 `todos.yaml`） |
| `--task` | `-t` | 只执行指定的任务 ID |
| `--provider` | `-P` | AI Provider（`codebuddy` / `claude` / `gemini` / `opencode` / `test`） |
| `--model` | `-m` | AI 模型名称 |
| `--workspace` | `-w` | 工作目录（默认当前目录） |
| `--ideas` | | ideas 文件路径，启用自动拆解 |
| `--ideas-only` | | 仅拆解 ideas，不运行任务（支持人工审核） |
| `--human-review` | | 启用 ideas 处理的人工审核 |
| `--no-idle` | | 禁用 idle 模式 |
| `--idle-interval` | | idle 模式检查间隔秒数（默认 30） |
| `--preset` | | Preset 配置名称（默认 `default`），从 config.yaml 加载预设参数 |
| `--timeout` | | AI 调用超时秒数 |
| `--log-dir` | | 日志目录（默认 `.autoagent`） |
| `--status` | | 显示当前任务状态 |
| `--reset` | | 重置所有任务状态 |
| `--validate` | | 验证配置文件并退出 |
| `--continue` | | 继续当前会话（从 `.autoagent_log` 读取） |
| `--resume` | | 恢复指定会话（支持完整名称或短 ID） |
| `--list-sessions` | | 列出所有历史会话 |
| `--no-skip` | | 不跳过已完成的任务 |
| `--verbose` | `-v` | 启用详细日志 |
| `--list-providers` | | 列出所有可用 AI Provider |

### 常用工作流

```bash
# 全自动：ideas → 任务拆解 → 执行
python orchestrator.py --ideas ideas.md --config todos.yaml --workspace ./project

# 半自动：先拆解 ideas 并人工审核，再运行
python orchestrator.py --ideas ideas.md --config todos.yaml --ideas-only
# （审核 todos.yaml 后）
python orchestrator.py --config todos.yaml --workspace ./project

# 继续上次中断的会话
python orchestrator.py --continue

# 恢复特定历史会话（支持短 ID）
python orchestrator.py --list-sessions        # 查看所有会话
python orchestrator.py --resume abc12345      # 恢复指定会话

# 重跑某个任务
python orchestrator.py --task 2

# 全部重来
python orchestrator.py --reset
```

### Preset 配置

通过 `config.yaml` 中的 preset 快速切换常用配置组合，避免每次输入大量参数：

```yaml
# config.yaml
preset:
  - name: default
    ideas: ${workspace}/ideas.md
    config: ${workspace}/todos.yaml
    provider: codebuddy
    model: "plan:claude-opus-4.6;default:claude-opus-4.6;lite:glm-5.0-ioa"
```

```bash
# 使用 default 预设
python orchestrator.py

# 使用指定预设
python orchestrator.py --preset test

# 使用预设但覆盖特定参数（命令行参数优先级更高）
python orchestrator.py --preset default --model claude-sonnet-4-6
```

Preset 支持所有命令行参数对应的字段（`config`、`ideas`、`provider`、`model`、`workspace`、`timeout`、`verbose` 等），详见 [使用指南](doc/USAGE.md)。

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

**核心模块**：

| 模块 | 说明 |
|------|------|
| `orchestrator.py` | 主入口，任务调度引擎 |
| `task_executor.py` | 任务执行器（Simple / Nested / Looping） |
| `ai_providers.py` | AI Provider 抽象层，支持多种 AI 工具 |
| `codebuddy_client.py` | AI 客户端，封装与 AI 工具的交互 |
| `state_manager.py` | 状态持久化管理 |
| `conversation_logger.py` | 对话日志记录 |
| `ideas_watcher.py` | Ideas 文件监控与任务分解 |
| `autoagent_exec.py` | 长时间任务后台执行器 |

## 🎯 使用场景

### 模型训练与优化

```yaml
tasks:
  - id: 1
    name: "优化模型精度"
    type: nested
    completion_criteria: "accuracy >= 0.9 且 loss < 0.1"
    subtasks:
      - id: 1.1
        name: "修改模型配置"
        type: simple
        completion_criteria: "配置修改完成"
      - id: 1.2
        name: "训练模型"
        type: long_running
        completion_criteria: "训练正常完成且指标达标"
```

### CUDA 内核迭代优化

```yaml
tasks:
  - id: 1
    name: "迭代优化 CUDA 内核"
    type: looping
    repeat_count: 5
    subtasks:
      - id: 1.1
        name: "性能分析"
        type: long_running
        completion_criteria: "ncu 分析完成"
      - id: 1.2
        name: "优化代码"
        type: simple
        completion_criteria: "代码优化完成，编译通过"
      - id: 1.3
        name: "基准测试"
        type: simple
        completion_criteria: "基准测试完成，记录性能数据"
```

### 代码质量改进

```yaml
tasks:
  - id: 1
    name: "修复代码质量问题"
    type: nested
    completion_criteria: "pylint 评分 >= 9.0，无严重警告"
    subtasks:
      - id: 1.1
        name: "分析代码警告"
        type: simple
        completion_criteria: "警告分析完成"
      - id: 1.2
        name: "修复代码"
        type: simple
        completion_criteria: "所有问题已修复"
```

## 📚 文档

| 文档 | 说明 |
|------|------|
| [架构设计](doc/ARCHITECTURE.md) | 系统架构和核心概念详解 |
| [使用指南](doc/USAGE.md) | 完整使用指南和最佳实践 |
| [API 参考](doc/API_REFERENCE.md) | 模块接口和配置项说明 |
| [示例集合](doc/EXAMPLES.md) | 更多实际使用示例 |
| [文件说明](doc/FILES.md) | 项目文件结构说明 |

## 📁 项目结构

```
autoagent/
├── orchestrator.py          # 主入口
├── task_executor.py         # 任务执行器
├── ai_providers.py          # AI Provider 抽象
├── codebuddy_client.py      # AI 客户端
├── state_manager.py         # 状态管理
├── conversation_logger.py   # 日志系统
├── ideas_watcher.py         # Ideas 监控
├── truncation_limits.py     # 提示词截断限制配置
├── autoagent_exec.py        # 后台执行器
├── prompts/                 # AI Prompt 模板
├── config.yaml              # 默认配置
├── todos.example.yaml       # 任务配置模板
├── sample/                  # 示例项目
├── doc/                     # 详细文档
└── test/                    # 测试
```

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
