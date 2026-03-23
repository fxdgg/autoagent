# 文档索引

欢迎使用 CodeBuddy Todo Orchestrator！

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
   - 任务类型详解
   - 数据流和状态管理
   - 长时间任务处理
   - 扩展性设计

4. **[USAGE.md](USAGE.md)** 📖
   - 完整使用指南
   - 配置文件详解
   - 任务类型说明
   - 执行方式说明
   - 最佳实践
   - 故障排除

5. **[FILES.md](FILES.md)** 📁
   - 项目文件说明
   - 目录结构

6. **[API_REFERENCE.md](API_REFERENCE.md)** 🔧
   - 完整 API 参考
   - 类定义和方法说明
   - 状态类型和配置类型

## 🎯 按需求查找

### 我想快速上手

→ 阅读 [README.md](README.md) 的 **快速开始** 章节

### 我想了解系统架构

→ 阅读 [ARCHITECTURE.md](ARCHITECTURE.md)

### 我想配置任务

→ 阅读 [USAGE.md](USAGE.md) 的 **配置文件** 和 **任务类型** 章节

### 我想了解长时间任务处理

→ 阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 的 **长时间任务处理** 章节

### 我遇到了问题

→ 阅读 [USAGE.md](USAGE.md) 的 **故障排除** 章节

## 📖 阅读建议

### 新手推荐阅读顺序

1. [README.md](README.md) - 了解项目
2. [USAGE.md](USAGE.md) 的 **快速开始** - 实践操作
3. [ARCHITECTURE.md](ARCHITECTURE.md) 的 **任务类型** - 理解任务模型
4. [USAGE.md](USAGE.md) 的 **最佳实践** - 学习使用技巧

### 开发者推荐阅读顺序

1. [ARCHITECTURE.md](ARCHITECTURE.md) - 理解架构
2. [USAGE.md](USAGE.md) - 使用指南
3. [FILES.md](FILES.md) - 了解文件结构

### 高级用户推荐阅读顺序

1. [ARCHITECTURE.md](ARCHITECTURE.md) 的 **长时间任务处理** 章节
2. [USAGE.md](USAGE.md) 的 **最佳实践** 章节
3. [ARCHITECTURE.md](ARCHITECTURE.md) 的 **扩展性设计** 章节

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install pyyaml
```

### 2. 配置 CodeBuddy

```bash
# 检查 CodeBuddy 版本
codebuddy --version

# 如果需要登录（在交互式终端执行）
codebuddy -p "login_test"
```

### 3. 创建配置文件

创建 `todos.yaml`：

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
        type: ai_action
        completion_criteria: "代码修改完成"
        
      - id: 2.2
        name: "运行训练"
        type: long_running
        command: "python train.py --config modified_config.yaml"
        completion_criteria: "训练正常退出且验证集指标满足要求"
```

### 4. 运行 Orchestrator

```bash
python orchestrator.py
```

## 📊 任务类型速查

### 简单任务 (simple)

一次性执行，由 AI 判断是否完成。

```yaml
- id: 1
  name: "下载数据集"
  type: simple
  completion_criteria: "data.csv 文件存在且大小 > 10MB"
  initial_hint: "使用 python download.py"
```

**适用场景**：
- 一次性完成的任务
- 不需要长时间运行的任务
- AI 可以直接判断完成状态

### 嵌套任务 (nested)

包含多个子任务的复杂任务。

```yaml
- id: 2
  name: "优化模型性能"
  type: nested
  completion_criteria: "训练成功完成且 val_loss < 0.5"
  subtasks:
    - id: 2.1
      name: "修改训练代码"
      type: ai_action
      completion_criteria: "代码修改完成"
      
    - id: 2.2
      name: "运行训练"
      type: long_running
      command: "python train.py --config modified_config.yaml"
      completion_criteria: "训练正常退出且验证集指标满足要求"
```

**适用场景**：
- 需要多步骤的复杂任务
- 某些步骤可能需要很长时间（如训练）
- 需要根据后续步骤的结果判断整体是否完成

### AI 操作任务 (ai_action)

调用 AI 修改代码或执行其他操作。

```yaml
- id: 2.1
  name: "修改训练代码"
  type: ai_action
  completion_criteria: "代码修改完成"
```

**适用场景**：
- 需要修改代码
- 需要执行复杂的逻辑判断
- 需要 AI 的决策能力

### 长时间任务 (long_running)

使用 nohup 后台运行，避免超时。

```yaml
- id: 2.2
  name: "运行训练"
  type: long_running
  command: "python train.py --config modified_config.yaml"
  completion_criteria: "训练正常退出且验证集指标满足要求"
```

**适用场景**：
- 任务执行时间可能超过 CodeBuddy 超时限制
- 模型训练、数据处理等长时间任务
- 需要在后台运行的任务

## 🔑 核心概念

### 统一的任务执行模型

**不再有"循环任务"的概念，所有任务都遵循相同的执行逻辑：**

```
for task in tasks:
    while True:
        # 1. AI 尝试完成任务
        result = call_codebuddy(task)
        
        # 2. AI 自己判断是否达标
        if result.completed:
            mark_task_completed(task.id)
            break
        
        # 3. AI 决定如何改进，然后继续循环
```

**关键点：**
- ✅ AI 自主判断完成条件
- ✅ AI 自主决定如何改进
- ✅ 持续迭代直到达标
- ✅ 防止无限循环

### 嵌套任务

**主任务可以包含多个子任务，子任务按顺序执行：**

**执行流程：**
1. 执行所有子任务
2. 所有子任务完成后，AI 判断主任务是否完成
3. 如果未完成，AI 决定从哪个子任务重新开始

### 长时间任务处理

**使用 nohup 后台运行，避免 CodeBuddy timeout：**

**技术实现：**
- 使用 `nohup` 在后台运行
- 启动监控进程持续检查日志
- 完成后自动通知 AI 检查结果

### Orchestrator

任务编排引擎，负责：
- ✅ 管理任务队列和状态
- ✅ 执行任务调度
- ✅ 根据 AI 决策控制流程

### CodeBuddy

AI 编程助手，负责：
- ✅ 代码修改
- ✅ 任务判断
- ✅ 调用 LLM API

### 协作关系

```
Orchestrator: "执行任务 2"
    ↓
Orchestrator: "执行子任务 2.1（ai_action）"
    ↓
Orchestrator: "调用 CodeBuddy"
    ↓
CodeBuddy: "让我看看任务描述...返回修改方案"
    ↓
Orchestrator: "执行子任务 2.2（long_running）"
    ↓
Orchestrator: "使用 nohup 后台运行，启动监控"
    ↓
Monitor: "检测到训练完成，通知 AI"
    ↓
CodeBuddy: "检查结果...判断是否满足完成条件"
    ↓
Orchestrator: "更新任务状态"
```

## 💡 常见场景

### 机器学习

自动优化模型训练：

```yaml
- id: 1
  name: "优化模型精度"
  type: nested
  completion_criteria: "accuracy >= 0.9 且 loss < 0.1"
  subtasks:
    - id: 1.1
      name: "修改模型配置"
      type: ai_action
      completion_criteria: "配置修改完成"
      
    - id: 1.2
      name: "训练模型"
      type: long_running
      command: "python train.py --config config.yaml"
      completion_criteria: "训练成功完成且指标达标"
```

### 代码质量

自动修复代码问题：

```yaml
- id: 1
  name: "修复所有 Pylint 警告"
  type: nested
  completion_criteria: "Pylint 评分 >= 9.0 且符合 PEP8 规范"
  subtasks:
    - id: 1.1
      name: "分析警告信息"
      type: ai_action
      completion_criteria: "警告分析完成"
      
    - id: 1.2
      name: "修复代码"
      type: ai_action
      completion_criteria: "代码修复完成"
```

### 性能优化

自动优化代码性能：

```yaml
- id: 1
  name: "优化代码性能"
  type: nested
  completion_criteria: "运行时间 < 5 秒且功能不变"
  subtasks:
    - id: 1.1
      name: "优化热点代码"
      type: ai_action
      completion_criteria: "热点代码优化完成"
      
    - id: 1.2
      name: "运行基准测试"
      type: simple
      completion_criteria: "基准测试完成且性能达标"
      initial_hint: "运行 python benchmark.py"
```

## 🔗 相关资源

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
- 查看 [USAGE.md](USAGE.md) 的 **最佳实践** 章节

## 📝 文档更新记录

- **2026-03-23 v2**: 更新为统一任务模型
  - 去掉"循环任务"概念
  - 新增嵌套任务支持
  - 新增长时间任务处理
  - AI 完全自主判断完成条件
  
- **2026-03-23 v1**: 初始版本发布
  - 完成核心文档编写
  - 添加使用示例

---

💡 **提示**: 如果你是第一次使用，建议从 [README.md](README.md) 开始阅读。
