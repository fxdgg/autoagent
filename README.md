# CodeBuddy Todo Orchestrator

基于 CodeBuddy AI 编程助手的智能任务编排系统。

## 📋 项目简介

本项目实现了一个灵活的 Todo 任务执行系统，能够：

- 📝 通过简洁的 YAML 配置定义任务
- 🤖 利用 CodeBuddy 的 AI 能力自动执行复杂任务
- 🔄 AI 自主判断完成条件，持续尝试直到达标
- 🎯 支持简单任务和嵌套任务
- 🚀 支持长时间任务的 nohup 后台运行
- 📊 完整的状态追踪和执行日志

## 🎯 核心特性

### 1. 统一的任务执行模型
**不再区分"循环任务"和"简单任务"，所有任务都遵循统一的执行模式：**
- 尝试执行 → AI 自主评估 → 未达标则改进 → 重新尝试
- AI 完全自主判断是否满足完成条件
- 持续迭代直到达成目标或达到最大尝试次数

### 2. 嵌套任务支持
支持任务包含子任务，每个子任务可以是：
- **简单任务**：直接执行命令
- **AI 操作任务**：调用 AI 修改代码
- **长时间任务**：使用 nohup 后台运行（避免超时）

**示例场景：**
```
主任务：优化模型性能
├── 子任务1：修改训练代码（AI 操作）
├── 子任务2：运行训练（长时间任务）
└── 根据子任务2的结果判断主任务是否完成
```

### 3. AI 驱动的智能执行

#### 完全自主的AI决策机制

系统会在两个关键决策点调用AI：

1. **子任务失败时**：
   - 系统自动收集失败信息、历史记录、错误日志等上下文
   - AI分析失败原因，识别根本原因（是当前子任务的问题，还是前面子任务的问题）
   - AI决定从哪个子任务开始重试（`retry_from`字段）
   - AI提出具体的修复建议（`suggested_fix`字段）
   - 系统完全听从AI的决策，重置相应的子任务状态

2. **主任务评估时**：
   - 系统提供所有子任务的执行结果、训练日志、指标数据等上下文
   - AI判断主任务是否满足完成条件（`main_task_completed`字段）
   - AI分析结果与目标的差距
   - AI提出下一轮的优化方向（`next_strategy`字段）
   - AI给出具体的改进措施（`suggested_improvements`字段）

#### 系统与AI的职责分工

**系统职责**：
- 执行框架：管理任务队列、执行命令、监控状态
- 状态管理：维护任务状态、追踪尝试次数、持久化数据
- AI调用：在关键时刻调用AI、提供结构化上下文、解析AI决策
- 流程控制：根据AI决策执行后续操作、控制最大重试次数

**AI职责**：
- 失败分析：分析子任务失败原因、识别根本原因
- 重试决策：决定从哪个子任务开始重试、提出修复方案
- 完成判断：判断主任务是否完成、评估结果与目标的差距
- 策略建议：提出下一轮的优化方向、给出具体的改进措施

#### 设计优势

- ✅ **避免死循环**：AI能够识别跨子任务的依赖问题，不会盲目重复失败的操作
- ✅ **完全自主性**：AI完全掌控重试策略，可以基于实际情况调整
- ✅ **灵活性**：AI可以要求从任意子任务重试，提出各种修复方案
- ✅ **可追踪性**：所有AI决策都被记录，可以回顾AI的推理过程
- ✅ **符合用户理念**：AI自主判断完成条件，系统只提供框架和支持

### 4. CodeBuddy 负责代码修改和完成判断
- Orchestrator 负责流程控制和状态管理
- AI 完全自主决定如何改进、何时停止

### 5. 灵活的配置方式
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
│  Simple Task   │  │  Nested Task   │
│  - 直接执行命令│  │  - 执行子任务  │
│  - AI 判断完成│  │  - AI 判断主任务│
└────────────────┘  └────────┬───────┘
                             │
                    ┌────────┴────────┐
                    │  子任务执行流程  │
                    │  - ai_action    │
                    │  - long_running │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  CodeBuddy      │
                    │  - AI 修改代码  │
                    │  - AI 判断完成  │
                    │  - Nohup 监控   │
                    └─────────────────┘
```

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| **[README.md](README.md)** | 项目介绍和快速开始（本文档） |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | 架构设计和核心概念 |
| **[USAGE.md](USAGE.md)** | 使用指南和最佳实践 |
| **[API_REFERENCE.md](API_REFERENCE.md)** | API 参考文档 |
| **[FILES.md](FILES.md)** | 项目文件说明 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install pyyaml
```

### 2. 配置 CodeBuddy

确保 CodeBuddy 已正确安装并配置：

```bash
# 检查 CodeBuddy 版本
codebuddy --version

# 如果需要登录（在交互式终端执行）
codebuddy -p "login_test"
```

**重要**：如果使用 nohup 后台运行，必须先在交互式终端完成登录，确保 `~/.codebuddy/settings.json` 存在。

### 3. 创建任务配置

```yaml
# todos.yaml
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

## 💡 核心概念

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
        # （AI 自己决定改什么、怎么改）
```

**关键点：**
- ✅ AI 自主判断完成条件
- ✅ AI 自主决定如何改进
- ✅ 持续迭代直到达标
- ✅ 防止无限循环（设置最大尝试次数）

### 嵌套任务

**主任务可以包含多个子任务，子任务按顺序执行：**

```yaml
- id: 2
  name: "优化模型性能"
  type: nested
  completion_criteria: "训练成功完成且 val_loss < 0.5"
  subtasks:
    - id: 2.1
      name: "修改训练代码"
      type: ai_action
      
    - id: 2.2
      name: "运行训练"
      type: long_running
```

**执行流程：**
1. 执行子任务 2.1（AI 修改代码）
2. 如果子任务失败：立即停止，AI 分析并决定重试策略
3. 执行子任务 2.2（运行训练）
4. 所有子任务完成后，AI 判断主任务是否完成
5. 如果未完成，AI 决定从哪个子任务重新开始

### 长时间任务

**使用 nohup 后台运行，避免 CodeBuddy timeout：**

```yaml
- id: 2.2
  name: "运行训练"
  type: long_running
  command: "python train.py --config modified_config.yaml"
  completion_criteria: "训练正常退出且验证集指标满足要求"
```

**技术实现：**
- 使用 `nohup` 在后台运行
- 启动监控进程持续检查日志
- 完成后自动通知 AI 检查结果

### Orchestrator 是什么？

Orchestrator 是任务编排引擎，它：
- ✅ 管理任务队列和状态
- ✅ 执行任务调度
- ✅ 根据 AI 决策控制流程
- ✅ 持久化状态支持断点续传
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

## 🎨 使用场景

### 场景 1：自动化实验流程

```yaml
- id: 1
  name: "准备数据集"
  type: simple
  completion_criteria: "data.csv 存在且包含 10000 条数据"
  initial_hint: "运行 bash prepare_data.sh"
  
- id: 2
  name: "优化模型精度"
  type: nested
  completion_criteria: "accuracy >= 0.9 且 loss < 0.1"
  subtasks:
    - id: 2.1
      name: "修改模型配置"
      type: ai_action
      completion_criteria: "配置修改完成"
      
    - id: 2.2
      name: "训练模型"
      type: long_running
      command: "python train.py --config config.yaml"
      completion_criteria: "训练成功完成且指标达标"
```

### 场景 2：代码质量改进

```yaml
- id: 1
  name: "运行代码检查"
  type: simple
  completion_criteria: "pylint 评分 >= 9.0"
  initial_hint: "运行 pylint src/"
  
- id: 2
  name: "修复所有警告"
  type: nested
  completion_criteria: "pylint 输出无警告且符合 PEP8 规范"
  subtasks:
    - id: 2.1
      name: "分析警告信息"
      type: ai_action
      completion_criteria: "警告分析完成"
      
    - id: 2.2
      name: "修复代码"
      type: ai_action
      completion_criteria: "代码修复完成"
```

### 场景 3：性能优化

```yaml
- id: 1
  name: "分析性能瓶颈"
  type: simple
  completion_criteria: "生成性能分析报告"
  initial_hint: "运行 python profile.py"
  
- id: 2
  name: "优化代码性能"
  type: nested
  completion_criteria: "运行时间 < 5 秒且功能不变"
  subtasks:
    - id: 2.1
      name: "优化热点代码"
      type: ai_action
      completion_criteria: "热点代码优化完成"
      
    - id: 2.2
      name: "运行基准测试"
      type: simple
      completion_criteria: "基准测试完成且性能达标"
      initial_hint: "运行 python benchmark.py"
```

## 🛠️ 开发计划

- [x] 基础架构设计
- [x] 完整文档编写
- [ ] 实现 TaskOrchestrator 核心类
- [ ] 实现简单任务执行器
- [ ] 实现嵌套任务支持
- [ ] 实现长时间任务的 nohup 处理
- [ ] 实现监控进程
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

- [CodeBuddy 文档](https://iwiki.woa.com/space/CodeBuddy)
- [Karpathy AutoResearch](https://github.com/karpathy/autoresearch)
