# LangGraph + CodeBuddy Todo Orchestrator

基于 LangGraph 框架和 CodeBuddy AI 编程助手的智能任务编排系统。

## 📋 项目简介

本项目实现了一个灵活的 Todo 任务执行系统，能够：

- 📝 通过简洁的 YAML 配置定义任务
- 🤖 利用 CodeBuddy 的 AI 能力自动执行复杂任务
- 🔄 支持循环执行直到任务完成
- 🎯 区分简单任务（一次性执行）和循环任务（需验证）
- 📊 完整的状态追踪和执行日志

## 🎯 核心特性

### 1. 任务类型分离
- **简单任务（Simple Task）**：执行一次命令就结束
- **循环任务（Loop Task）**：自动修改代码 → 训练 → 验证 → 循环直到完成

### 2. AI 驱动的智能执行
- CodeBuddy 负责代码修改和完成判断
- LangGraph 负责流程控制和状态管理
- 完全解耦，易于扩展

### 3. 灵活的配置方式
```yaml
tasks:
  - id: 1
    description: "准备数据集"
    type: simple
    command: "python prepare_data.py"
    
  - id: 2
    description: "优化模型精度到 90% 以上"
    type: loop
    max_retries: 5
    completion_criteria: |
      模型精度（accuracy）需要 >= 0.9
      训练无崩溃，无 OOM
```

## 🏗️ 架构设计

```
┌─────────────────────────────────────────┐
│  Todo Orchestrator                      │
│  - 解析 todos.yaml                      │
│  - 调度任务执行                         │
│  - 管理任务队列                         │
└────────────────┬────────────────────────┘
                 │
         ┌───────┴───────┐
         ▼               ▼
┌────────────────┐  ┌────────────────┐
│  Simple Task   │  │  Loop Task     │
│  - 直接执行命令│  │  - LangGraph   │
│  - 一次完成    │  │  - 循环重试    │
└────────────────┘  └────────┬───────┘
                             │
                    ┌────────┴────────┐
                    │  LangGraph 图   │
                    │  - modify_code  │
                    │  - run_training │
                    │  - check_...    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  CodeBuddy      │
                    │  - AI 修改代码  │
                    │  - AI 判断完成  │
                    └─────────────────┘
```

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| **[README.md](README.md)** | 项目介绍和快速开始（本文档） |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | 架构设计和核心概念 |
| **[USAGE.md](USAGE.md)** | 使用指南和最佳实践 |
| **[API_REFERENCE.md](API_REFERENCE.md)** | API 文档 |
| **[EXAMPLES.md](EXAMPLES.md)** | 示例和用例 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install langgraph pyyaml
```

### 2. 配置 CodeBuddy

确保 CodeBuddy 已正确安装并配置：

```bash
# 检查 CodeBuddy 版本
codebuddy --version

# 如果需要登录
codebuddy -p "login_test"
```

### 3. 创建任务配置

```yaml
# todos.yaml
tasks:
  - id: 1
    description: "准备数据集"
    type: simple
    command: "python prepare_data.py"
```

### 4. 运行 Orchestrator

```bash
python todo_orchestrator.py
```

## 💡 核心概念

### LangGraph 是什么？

LangGraph 是一个流程编排框架，它：
- ✅ 管理状态传递
- ✅ 执行节点函数
- ✅ 根据条件边路由流程
- ❌ 不提供 AI 能力
- ❌ 不调用 LLM API

### CodeBuddy 是什么？

CodeBuddy 是 AI 编程助手，它：
- ✅ 提供代码修改能力
- ✅ 提供任务判断能力
- ✅ 调用 LLM API
- ❌ 不管理流程状态

### 两者的协作关系

```
LangGraph: "现在到了 modify_code 节点，调用 modify_code_node 函数"
    ↓
modify_code_node: "我需要 AI 的帮助，调用 CodeBuddy"
    ↓
CodeBuddy: "让我看看任务描述...返回修改方案"
    ↓
modify_code_node: "收到 AI 响应，更新状态并返回"
    ↓
LangGraph: "收到返回，继续到下一个节点 run_training"
```

## 🎨 使用场景

### 场景 1：自动化实验流程

```yaml
- id: 1
  description: "准备数据集"
  type: simple
  command: "bash prepare_data.sh"
  
- id: 2
  description: "优化模型精度"
  type: loop
  max_retries: 10
  completion_criteria: |
    accuracy >= 0.9
    loss < 0.1
```

### 场景 2：代码质量改进

```yaml
- id: 1
  description: "运行代码检查"
  type: simple
  command: "pylint src/"
  
- id: 2
  description: "修复所有警告"
  type: loop
  max_retries: 5
  completion_criteria: |
    pylint 输出无警告
    代码符合 PEP8 规范
```

### 场景 3：性能优化

```yaml
- id: 1
  description: "分析性能瓶颈"
  type: simple
  command: "python profile.py"
  
- id: 2
  description: "优化代码使运行时间 < 5s"
  type: loop
  max_retries: 8
  completion_criteria: |
    运行时间 < 5 秒
    功能不变
```

## 🛠️ 开发计划

- [x] 基础架构设计
- [ ] 实现 TodoOrchestrator 核心类
- [ ] 实现 LangGraph 循环图
- [ ] 实现简单任务执行器
- [ ] 实现 CodeBuddy 调用封装
- [ ] 添加配置验证
- [ ] 添加错误处理
- [ ] 添加日志系统
- [ ] 编写单元测试
- [ ] 编写示例

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🔗 相关链接

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [CodeBuddy 文档](https://iwiki.woa.com/space/CodeBuddy)
- [Karpathy AutoResearch](https://github.com/karpathy/autoresearch)
