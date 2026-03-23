# 文档索引

欢迎使用 LangGraph + CodeBuddy Todo Orchestrator！

本文档索引帮助你快速找到需要的文档。

## 📚 文档列表

### 入门文档

1. **[README.md](README.md)** ⭐ 从这里开始
   - 项目简介
   - 核心特性
   - 快速开始
   - 核心概念介绍

2. **[快速开始指南](#快速开始)**
   - 5 分钟快速上手
   - 常见场景配置

### 核心文档

3. **[ARCHITECTURE.md](ARCHITECTURE.md)** 🏗️
   - 系统架构设计
   - 核心组件说明
   - 数据流和状态管理
   - 扩展性设计

4. **[USAGE.md](USAGE.md)** 📖
   - 完整使用指南
   - 配置文件详解
   - 执行方式说明
   - 最佳实践
   - 故障排除

5. **[API_REFERENCE.md](API_REFERENCE.md)** 🔧
   - 完整 API 文档
   - 类和方法说明
   - 参数和返回值
   - 代码示例

6. **[EXAMPLES.md](EXAMPLES.md)** 💡
   - 实际使用示例
   - 不同场景的配置
   - 机器学习场景
   - 代码质量场景
   - 性能优化场景

## 🎯 按需求查找

### 我想快速上手

→ 阅读 [README.md](README.md) 的 **快速开始** 章节

### 我想了解系统架构

→ 阅读 [ARCHITECTURE.md](ARCHITECTURE.md)

### 我想配置任务

→ 阅读 [USAGE.md](USAGE.md) 的 **配置文件** 章节

### 我想查看 API

→ 阅读 [API_REFERENCE.md](API_REFERENCE.md)

### 我想找示例

→ 阅读 [EXAMPLES.md](EXAMPLES.md)

### 我遇到了问题

→ 阅读 [USAGE.md](USAGE.md) 的 **故障排除** 章节

## 📖 阅读建议

### 新手推荐阅读顺序

1. [README.md](README.md) - 了解项目
2. [USAGE.md](USAGE.md) 的 **快速开始** - 实践操作
3. [EXAMPLES.md](EXAMPLES.md) - 查看示例
4. [ARCHITECTURE.md](ARCHITECTURE.md) - 深入理解

### 开发者推荐阅读顺序

1. [ARCHITECTURE.md](ARCHITECTURE.md) - 理解架构
2. [API_REFERENCE.md](API_REFERENCE.md) - 查看接口
3. [USAGE.md](USAGE.md) - 使用指南
4. [EXAMPLES.md](EXAMPLES.md) - 参考实现

### 高级用户推荐阅读顺序

1. [ARCHITECTURE.md](ARCHITECTURE.md) 的 **扩展性设计** 章节
2. [USAGE.md](USAGE.md) 的 **高级用法** 章节
3. [EXAMPLES.md](EXAMPLES.md) 的 **高级用例** 章节

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install langgraph pyyaml
```

### 2. 配置 CodeBuddy

```bash
# 检查 CodeBuddy 版本
codebuddy --version

# 如果需要登录
codebuddy -p "login_test"
```

### 3. 创建配置文件

复制示例配置：

```bash
cp todos.example.yaml todos.yaml
```

编辑 `todos.yaml`：

```yaml
version: 1
workspace: /data/workspace

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

## 📊 任务类型速查

### 简单任务 (simple)

一次性执行命令，不需要 AI 参与。

```yaml
- id: 1
  description: "准备数据集"
  type: simple
  command: "python prepare_data.py"
```

### 循环任务 (loop)

需要 AI 参与的复杂任务，支持自动重试。

```yaml
- id: 1
  description: "优化模型精度"
  type: loop
  max_retries: 5
  completion_criteria: "accuracy >= 0.9"
```

## 🔑 核心概念

### LangGraph

流程编排框架，负责：
- ✅ 管理状态传递
- ✅ 执行节点函数
- ✅ 根据条件边路由流程

### CodeBuddy

AI 编程助手，负责：
- ✅ 代码修改
- ✅ 任务判断
- ✅ 调用 LLM API

### 协作关系

```
LangGraph 调度节点 → 节点调用 CodeBuddy → CodeBuddy 返回 AI 判断 → LangGraph 继续流程
```

## 💡 常见场景

### 机器学习

自动优化模型训练：

```yaml
- id: 1
  description: "优化模型精度到 90%"
  type: loop
  max_retries: 10
  completion_criteria: "accuracy >= 0.9"
```

### 代码质量

自动修复代码问题：

```yaml
- id: 1
  description: "修复所有 Pylint 警告"
  type: loop
  max_retries: 5
  completion_criteria: "Pylint 评分 >= 9.0"
```

### 性能优化

自动优化代码性能：

```yaml
- id: 1
  description: "减少运行时间 50%"
  type: loop
  max_retries: 8
  completion_criteria: "运行时间 < 1s"
```

## 🔗 相关资源

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [CodeBuddy 文档](https://iwiki.woa.com/space/CodeBuddy)
- [Karpathy AutoResearch](https://github.com/karpathy/autoresearch)

## 📞 获取帮助

### 文档问题

- 查看对应文档的详细说明
- 查看 [USAGE.md](USAGE.md) 的 **故障排除** 章节

### 功能建议

欢迎提交 Issue 或 Pull Request

### 技术交流

- 阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 理解设计原理
- 查看 [EXAMPLES.md](EXAMPLES.md) 参考实际案例

## 📝 文档更新记录

- **2026-03-23**: 初始版本发布
  - 完成核心文档编写
  - 添加使用示例
  - 完成 API 文档

---

💡 **提示**: 如果你是第一次使用，建议从 [README.md](README.md) 开始阅读。
