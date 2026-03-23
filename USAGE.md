# 使用指南

本文档提供 LangGraph + CodeBuddy Todo Orchestrator 的详细使用说明。

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [配置文件](#配置文件)
- [任务类型](#任务类型)
- [执行方式](#执行方式)
- [最佳实践](#最佳实践)
- [故障排除](#故障排除)

## 安装

### 1. 环境要求

- Python 3.8+
- CodeBuddy 2.63.5+
- Linux/macOS 系统

### 2. 安装依赖

```bash
pip install langgraph pyyaml
```

### 3. 配置 CodeBuddy

确保 CodeBuddy 已正确安装：

```bash
# 检查版本
codebuddy --version

# 如果需要登录（在交互式终端执行一次）
codebuddy -p "login_test"
```

**重要**：如果使用 nohup 后台运行，必须先在交互式终端完成登录，确保 `~/.codebuddy/settings.json` 存在。

## 快速开始

### 步骤 1：创建配置文件

创建 `todos.yaml` 文件：

```yaml
tasks:
  # 简单任务示例
  - id: 1
    name: "下载数据集"
    type: simple
    completion_criteria: "data.csv 文件存在且大小 > 10MB"
    initial_hint: "使用 python download.py"
    
  # 嵌套任务示例
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

### 步骤 2：运行 Orchestrator

```bash
# 运行所有任务
python orchestrator.py
```

### 步骤 3：查看输出

Orchestrator 会实时输出执行日志：

```
📋 执行任务 1: 下载数据集
   类型: simple

   尝试 #1
      AI 尝试完成任务...
   ✅ 任务 1 完成！

📋 执行任务 2: 优化模型性能
   类型: nested

   📌 执行子任务 2.1: 修改训练代码
      类型: ai_action
      
      尝试 #1
         AI 尝试完成任务...
      ✅ 子任务 2.1 完成！

   📌 执行子任务 2.2: 运行训练
      类型: long_running
      
      启动长时间任务...
      命令: python train.py --config modified_config.yaml
      日志: logs/2.2.log
      ✅ 任务已启动，正在监控...

   📊 子任务全部完成，检查主任务完成条件...
      AI 检查结果...
   ✅ 主任务 2 完成！
```

## 配置文件

### 完整配置示例

```yaml
tasks:
  # 简单任务
  - id: 1
    name: "prepare_data"
    type: simple
    completion_criteria: "data.csv 文件存在且包含 10000 条数据"
    initial_hint: "运行 python prepare_data.py"
    
  # 嵌套任务
  - id: 2
    name: "optimize_accuracy"
    type: nested
    completion_criteria: |
      训练成功完成
      验证集精度 >= 0.9
      验证集 loss < 0.1
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

### 配置字段说明

#### 全局字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tasks` | list | 是 | 任务列表 |

#### 任务通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | int/string | 是 | 任务 ID（唯一标识） |
| `name` | string | 是 | 任务名称 |
| `type` | string | 是 | 任务类型：`simple`、`nested`、`ai_action`、`long_running` |
| `completion_criteria` | string | 是 | 完成标准（自然语言描述） |

#### 简单任务 (type: simple)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `initial_hint` | string | 否 | 初始提示（给 AI 的参考信息） |

#### 嵌套任务 (type: nested)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |

#### AI 操作任务 (type: ai_action)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| 无额外字段 | - | - | 使用通用的 completion_criteria |

#### 长时间任务 (type: long_running)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 要执行的命令 |
| `completion_criteria` | string | 是 | 完成标准 |

## 任务类型

### 1. 简单任务 (simple)

**适用场景**：一次性执行的任务，由 AI 判断是否完成

**配置示例**：
```yaml
- id: 1
  name: "下载数据集"
  type: simple
  completion_criteria: "data.csv 文件存在且大小 > 10MB"
  initial_hint: "使用 python download.py"
```

**执行流程**：
1. AI 根据 initial_hint 尝试完成任务
2. AI 自我评估是否满足完成条件
3. 如果满足：标记完成
4. 如果不满足：AI 决定如何改进，重新尝试
5. 循环直到满足条件或达到最大尝试次数

### 2. 嵌套任务 (nested)

**适用场景**：需要多个步骤的复杂任务

**配置示例**：
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

**执行流程**：
1. 按顺序执行所有子任务
2. 所有子任务完成后，AI 判断主任务是否完成
3. 如果未完成，重新从第一个子任务开始
4. 循环直到满足条件或达到最大尝试次数

### 3. AI 操作任务 (ai_action)

**适用场景**：需要 AI 修改代码或执行其他操作的任务

**配置示例**：
```yaml
- id: 2.1
  name: "修改训练代码"
  type: ai_action
  completion_criteria: "代码修改完成"
```

**执行流程**：
1. 调用 CodeBuddy 执行操作
2. AI 自我评估是否满足完成条件
3. 如果满足：标记完成
4. 如果不满足：继续改进
5. 循环直到满足条件或达到最大尝试次数

### 4. 长时间任务 (long_running)

**适用场景**：可能超过 CodeBuddy 超时限制的任务（如模型训练）

**配置示例**：
```yaml
- id: 2.2
  name: "运行训练"
  type: long_running
  command: "python train.py --config modified_config.yaml"
  completion_criteria: "训练正常退出且验证集指标满足要求"
```

**执行流程**：
1. 使用 nohup 在后台运行命令
2. 启动监控进程持续检查日志
3. 检测到完成标志后通知 AI
4. AI 判断是否满足完成条件

**技术细节**：
- 使用 `nohup` 避免超时
- 独立的监控进程检查日志
- 自动检测错误和完成标志

## 执行方式

### 1. 交互式执行

默认模式，实时输出日志：

```bash
python orchestrator.py
```

### 2. 后台执行

```bash
nohup python orchestrator.py > orchestrator.log 2>&1 &
```

### 3. 断点续传

如果执行中断，可以从断点继续：

```bash
# 会自动检测未完成的任务
python orchestrator.py
```

状态保存在 `todos_state.yaml` 中，程序会自动读取并继续执行。

### 4. 查看状态

```bash
# 查看状态文件
cat todos_state.yaml
```

## 最佳实践

### 1. 任务设计原则

- ✅ 任务描述要清晰明确
- ✅ 完成标准要可验证
- ✅ 合理设置初始提示
- ✅ 避免任务过于复杂

**示例**：

```yaml
# ❌ 不好：任务过于复杂
- id: 1
  name: "优化整个项目"
  type: simple
  completion_criteria: "所有指标都好"

# ✅ 好：任务拆分
- id: 1
  name: "优化数据加载速度"
  type: simple
  completion_criteria: "数据加载时间 < 1s"

- id: 2
  name: "优化训练速度"
  type: nested
  completion_criteria: "每个 epoch < 5min"
  subtasks:
    - id: 2.1
      name: "修改训练代码"
      type: ai_action
      completion_criteria: "代码修改完成"
    - id: 2.2
      name: "运行训练测试"
      type: simple
      completion_criteria: "测试完成且性能达标"
```

### 2. 完成标准编写

- ✅ 使用具体数值
- ✅ 明确验证方式
- ✅ 考虑边界情况

**示例**：

```yaml
# ❌ 不好：模糊不清
completion_criteria: "精度要高"

# ✅ 好：具体明确
completion_criteria: |
  模型精度（accuracy）需要 >= 0.9
  在验证集上的 loss < 0.1
  训练过程中无 OOM 错误
  最后 3 个 epoch 的准确率方差 < 0.01
```

### 3. 嵌套任务使用

**适用场景**：
- 需要多步骤的复杂任务
- 某些步骤可能需要很长时间（如训练）
- 需要根据后续步骤的结果判断整体是否完成

**示例**：

```yaml
- id: 2
  name: "优化模型性能"
  type: nested
  completion_criteria: "训练成功完成且 val_loss < 0.5"
  subtasks:
    # 步骤1：AI 修改代码
    - id: 2.1
      name: "修改训练代码"
      type: ai_action
      completion_criteria: "代码修改完成"
      
    # 步骤2：长时间训练（避免超时）
    - id: 2.2
      name: "运行训练"
      type: long_running
      command: "python train.py --config modified_config.yaml"
      completion_criteria: "训练正常退出且验证集指标满足要求"
```

### 4. 长时间任务使用

**适用场景**：
- 任务执行时间可能超过 CodeBuddy 超时限制
- 模型训练、数据处理等长时间任务

**注意事项**：
- 确保日志中有明确的完成标志
- 监控进程会定期检查日志
- CodeBuddy 必须先登录（settings.json 存在）

### 5. 日志管理

```bash
# 查看长时间任务的日志
tail -f logs/2.2.log

# 查看监控进程的日志
tail -f monitors/2.2.log
```

## 故障排除

### 问题 1：CodeBuddy 认证失败

**错误信息**：
```
Authentication required. Please use /login command to sign in to your account
```

**解决方案**：

```bash
# 在交互式终端执行登录
codebuddy -p "login_test"

# 验证 settings.json 存在
ls ~/.codebuddy/settings.json
```

### 问题 2：长时间任务卡住

**检查步骤**：

```bash
# 查看任务状态
cat todos_state.yaml

# 查看日志文件
tail -f logs/2.2.log

# 查看监控进程
ps aux | grep monitor

# 查看训练进程
ps aux | grep train.py
```

### 问题 3：AI 无限循环

**原因**：完成条件设置不合理，AI 无法满足

**解决方案**：
- 检查完成条件是否合理
- 重新设计任务，拆分为更小的任务
- 设置更合理的初始提示

### 问题 4：状态文件损坏

**解决方案**：

```bash
# 删除状态文件，重新开始
rm todos_state.yaml
```

### 问题 5：监控进程无法启动

**检查步骤**：

```bash
# 检查 monitors 目录权限
ls -la monitors/

# 检查监控脚本内容
cat monitors/2.2.sh

# 手动执行监控脚本测试
bash monitors/2.2.sh
```

## 常见问题

### Q: 如何查看当前任务进度？

```bash
# 查看状态文件
cat todos_state.yaml
```

### Q: 如何中断执行？

```bash
# Ctrl+C 中断当前任务
# 下次运行时可以从中断点继续
python orchestrator.py
```

### Q: 如何重新开始某个任务？

```bash
# 删除该任务的状态，重新运行
# 编辑 todos_state.yaml，删除对应任务的状态
python orchestrator.py
```

### Q: 支持哪些模型？

目前支持的模型包括：
- glm-4.7
- Gemini-3-Flash
- Gemini-3-Pro
- Gemini-2.5-Pro
- DeepSeek-V3.1-Terminus
- DeepSeek-V3.2

### Q: 如何自定义 CodeBuddy 模型？

可以在代码中指定：

```python
codebuddy = CodeBuddyClient(model="glm-4.7")
```

## 总结

本文档涵盖了：

- ✅ 完整的安装和配置流程
- ✅ 详细的任务类型说明
- ✅ 完整的使用指南
- ✅ 最佳实践建议
- ✅ 常见问题和解决方案

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
