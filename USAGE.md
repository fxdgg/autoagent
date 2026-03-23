# 使用指南

本文档提供 LangGraph + CodeBuddy Todo Orchestrator 的详细使用说明。

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [配置文件](#配置文件)
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
version: 1
workspace: /path/to/your/project

tasks:
  # 简单任务示例
  - id: 1
    description: "准备数据集"
    type: simple
    command: "python prepare_data.py"
    expected_output: "数据准备完成"
    
  # 循环任务示例
  - id: 2
    description: "优化模型精度到 90% 以上"
    type: loop
    max_retries: 5
    completion_criteria: |
      模型精度（accuracy）需要 >= 0.9
      训练无崩溃，无 OOM
    initial_instruction: "将学习率从 0.001 调整到 0.0001"
```

### 步骤 2：运行 Orchestrator

```bash
# 运行所有任务
python todo_orchestrator.py

# 运行特定任务
python todo_orchestrator.py --task 2

# 使用指定的配置文件
python todo_orchestrator.py --config custom_todos.yaml
```

### 步骤 3：查看输出

Orchestrator 会实时输出执行日志：

```
============================================================
开始执行任务 1: 准备数据集
============================================================

📝 执行任务 1: 准备数据集
   命令: python prepare_data.py
   结果: ✅ 成功

============================================================
开始执行任务 2: 优化模型精度到 90% 以上
============================================================

🔄 第 1 次尝试: AI 修改代码
   AI 决策: 调整学习率为 0.0001
🏋️ 运行训练...
   训练结果: ✅ 成功
🔍 AI 检查完成情况...
   AI 判断: ❌ 未完成
   理由: accuracy = 0.85，未达到 0.9

🔄 第 2 次尝试: AI 修改代码
   AI 决策: 增加 batch_size 到 128
🏋️ 运行训练...
   训练结果: ✅ 成功
🔍 AI 检查完成情况...
   AI 判断: ✅ 已完成
   理由: accuracy = 0.92，达到要求

============================================================
执行总结:
  ✅ 任务 1: 准备数据集
  ✅ 任务 2: 优化模型精度到 90% 以上
============================================================
```

## 配置文件

### 完整配置示例

```yaml
version: 1
workspace: /data/workspace/project
codebuddy:
  path: /root/.local/bin/codebuddy
  model: glm-4.7
  timeout: 3600

tasks:
  # 简单任务
  - id: 1
    name: "prepare_data"
    description: "准备数据集"
    type: simple
    command: "python prepare_data.py"
    timeout: 300
    working_dir: ./scripts
    expected_output: "数据准备完成"
    
  # 循环任务
  - id: 2
    name: "optimize_accuracy"
    description: "优化模型精度"
    type: loop
    max_retries: 5
    timeout: 1800
    completion_criteria: |
      模型精度（accuracy）需要 >= 0.9
      训练无崩溃，无 OOM
      损失函数 loss < 0.1
    initial_instruction: "将学习率从 0.001 调整到 0.0001"
    success_criteria:
      - "accuracy >= 0.9"
      - "loss < 0.1"
```

### 配置字段说明

#### 全局配置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `version` | int | 是 | 配置文件版本 |
| `workspace` | string | 是 | 项目工作目录 |
| `codebuddy.path` | string | 否 | CodeBuddy 路径（默认：/root/.local/bin/codebuddy） |
| `codebuddy.model` | string | 否 | 使用的模型（默认：glm-4.7） |
| `codebuddy.timeout` | int | 否 | CodeBuddy 调用超时时间（默认：3600秒） |

#### 任务配置

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | int | 是 | 任务 ID（唯一标识） |
| `name` | string | 否 | 任务名称（用于日志和状态管理） |
| `description` | string | 是 | 任务描述（发送给 AI） |
| `type` | string | 是 | 任务类型：`simple` 或 `loop` |
| `timeout` | int | 否 | 执行超时时间（秒） |
| `working_dir` | string | 否 | 工作目录（相对于 workspace） |

#### 简单任务（type: simple）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 是 | 要执行的命令 |
| `expected_output` | string | 否 | 预期的输出内容（可选验证） |

#### 循环任务（type: loop）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `max_retries` | int | 否 | 最大重试次数（默认：3） |
| `completion_criteria` | string | 是 | 完成标准（自然语言描述） |
| `initial_instruction` | string | 否 | 初始修改指令 |
| `success_criteria` | list | 否 | 成功标准列表（可选） |

### 配置验证

Orchestrator 会自动验证配置文件：

```bash
# 仅验证配置，不执行任务
python todo_orchestrator.py --validate
```

## 执行方式

### 1. 交互式执行

默认模式，实时输出日志：

```bash
python todo_orchestrator.py
```

### 2. 静默执行

输出到日志文件：

```bash
python todo_orchestrator.py --silent --log orchestrator.log
```

### 3. 后台执行

```bash
nohup python todo_orchestrator.py > orchestrator.log 2>&1 &
```

### 4. 断点续传

如果执行中断，可以从断点继续：

```bash
# 会自动检测未完成的任务
python todo_orchestrator.py --continue
```

### 5. 指定任务

执行特定任务：

```bash
# 执行单个任务
python todo_orchestrator.py --task 3

# 执行多个任务
python todo_orchestrator.py --tasks 1,2,5

# 执行指定范围的任务
python todo_orchestrator.py --task-range 1-5
```

### 6. 跳过任务

跳过某些任务：

```bash
# 跳过已完成的任务
python todo_orchestrator.py --skip-completed

# 跳过特定任务
python todo_orchestrator.py --skip 2,4
```

## 高级用法

### 1. 条件任务

使用 `depends_on` 定义任务依赖：

```yaml
tasks:
  - id: 1
    description: "准备数据"
    type: simple
    command: "python prepare_data.py"
    
  - id: 2
    description: "训练模型"
    type: loop
    depends_on: [1]  # 依赖任务 1
    completion_criteria: "accuracy >= 0.9"
```

### 2. 并行任务

使用 `parallel` 关键字：

```yaml
tasks:
  - id: 1
    description: "并行数据预处理"
    type: parallel
    commands:
      - "python process_part1.py"
      - "python process_part2.py"
      - "python process_part3.py"
```

### 3. 任务组

使用 `group` 组织相关任务：

```yaml
groups:
  - name: "数据准备"
    tasks: [1, 2, 3]
    
  - name: "模型训练"
    tasks: [4, 5, 6]

tasks:
  - id: 1
    description: "下载数据"
    type: simple
    command: "python download.py"
  
  # ... 其他任务
```

### 4. 环境变量

在任务中使用环境变量：

```yaml
tasks:
  - id: 1
    description: "使用 GPU 训练"
    type: simple
    command: "CUDA_VISIBLE_DEVICES=0 python train.py"
    
  - id: 2
    description: "设置学习率"
    type: simple
    command: "LEARNING_RATE=0.001 python train.py"
```

### 5. Git 集成

自动提交代码修改：

```yaml
tasks:
  - id: 1
    description: "优化代码"
    type: loop
    completion_criteria: "性能提升 20%"
    git:
      auto_commit: true
      commit_message: "优化: ${task.description}"
      branch: "feature/optimization"
```

## 最佳实践

### 1. 任务设计原则

- ✅ 任务描述要清晰明确
- ✅ 完成标准要可验证
- ✅ 合理设置重试次数
- ✅ 避免任务过于复杂

**示例**：

```yaml
# ❌ 不好：任务过于复杂
- id: 1
  description: "优化整个项目"
  type: loop
  completion_criteria: "所有指标都好"

# ✅ 好：任务拆分
- id: 1
  description: "优化数据加载速度"
  type: loop
  completion_criteria: "数据加载时间 < 1s"

- id: 2
  description: "优化训练速度"
  type: loop
  completion_criteria: "每个 epoch < 5min"

- id: 3
  description: "优化模型精度"
  type: loop
  completion_criteria: "accuracy >= 0.9"
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

### 3. 重试策略

- ✅ 合理设置 max_retries
- ✅ 考虑收敛时间
- ✅ 避免无限循环

**示例**：

```yaml
# ❌ 不好：重试次数过多
- id: 1
  max_retries: 100  # 可能需要几天

# ✅ 好：合理设置
- id: 1
  max_retries: 5  # 根据任务复杂度调整
```

### 4. 日志管理

- ✅ 定期清理日志
- ✅ 使用日志轮转
- ✅ 保存重要日志

```bash
# 设置日志轮转
python todo_orchestrator.py --log orchestrator.log --log-max-size 100M --log-keep 5
```

### 5. 错误处理

- ✅ 配置错误通知
- ✅ 设置合理的超时
- ✅ 保存失败状态

```yaml
# 全局错误处理配置
error_handling:
  notify_on_failure: true
  save_failure_state: true
  max_consecutive_failures: 3
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

# 使用 API Key（备选方案）
export CODEBUDDY_API_KEY="your-api-key"
```

### 问题 2：训练超时

**错误信息**：
```
TimeoutError: Command timed out after 1800 seconds
```

**解决方案**：

```yaml
# 增加超时时间
- id: 1
  type: loop
  timeout: 7200  # 2 小时
```

### 问题 3：AI 返回无效 JSON

**错误信息**：
```
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**解决方案**：

1. 检查 AI 模型是否正确配置
2. 尝试使用其他模型（如 glm-4.7）
3. 增加提示词中的 JSON 格式要求

```python
# 在提示词中明确要求 JSON
prompt = """
请严格按照以下 JSON 格式返回：
{
  "completed": true/false,
  "reason": "理由"
}

不要返回其他任何内容。
"""
```

### 问题 4：任务卡住不执行

**检查步骤**：

```bash
# 查看进程状态
ps aux | grep todo_orchestrator

# 查看日志文件
tail -f orchestrator.log

# 检查 CodeBuddy 进程
ps aux | grep codebuddy

# 查看状态文件
cat .orchestrator_state.json
```

### 问题 5：状态文件损坏

**解决方案**：

```bash
# 删除状态文件，重新开始
rm .orchestrator_state.json

# 或使用 --reset 参数
python todo_orchestrator.py --reset
```

### 问题 6：内存溢出（OOM）

**解决方案**：

```yaml
# 减少批量大小
- id: 1
  type: loop
  initial_instruction: "将 batch_size 减少到 32"

# 或在命令中限制内存
- id: 1
  command: "ulimit -v 8388608 && python train.py"
```

## 性能优化

### 1. 并行执行

```yaml
# 使用并行任务提高效率
- id: 1
  type: parallel
  commands:
    - "python script1.py"
    - "python script2.py"
    - "python script3.py"
```

### 2. 缓存 AI 响应

```python
# 启用缓存
codebuddy = CodeBuddyClient(cache_enabled=True)
```

### 3. 减少不必要的 AI 调用

```yaml
# 对于简单的判断，不使用 AI
- id: 1
  type: simple
  command: "python test.py"
  # 不使用 check_completion，直接检查退出码
```

## 调试技巧

### 1. 启用详细日志

```bash
python todo_orchestrator.py --verbose
```

### 2. 单步执行

```bash
# 执行单个任务并暂停
python todo_orchestrator.py --task 1 --pause-after
```

### 3. 查看 LangGraph 图

```python
# 查看执行图
from todo_orchestrator import TodoOrchestrator

orchestrator = TodoOrchestrator()
print(orchestrator.loop_graph.get_graph().print_ascii())
```

### 4. 导出执行历史

```bash
# 导出为 JSON
python todo_orchestrator.py --export history.json
```

## 常见问题

### Q: 如何查看当前任务进度？

```bash
# 查看状态文件
cat .orchestrator_state.json

# 或使用命令行
python todo_orchestrator.py --status
```

### Q: 如何中断执行？

```bash
# Ctrl+C 中断当前任务
# 下次运行时可以从中断点继续
python todo_orchestrator.py --continue
```

### Q: 如何回滚到之前的状态？

```bash
# Git 方式
git checkout HEAD~1

# 或删除状态文件重新开始
rm .orchestrator_state.json
```

### Q: 如何自定义 AI 模型？

```yaml
# 在配置文件中指定
codebuddy:
  model: "glm-4.7"  # 或其他支持的模型
```

### Q: 支持哪些模型？

目前支持的模型包括：
- glm-4.7
- Gemini-3-Flash
- Gemini-3-Pro
- Gemini-2.5-Pro
- DeepSeek-V3.1-Terminus
- DeepSeek-V3.2

### Q: 如何集成到 CI/CD？

```yaml
# GitHub Actions 示例
name: Run Orchestrator
on: [push]
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Install dependencies
        run: pip install langgraph pyyaml
      - name: Run orchestrator
        run: python todo_orchestrator.py
```

## 总结

本文档涵盖了：

- ✅ 完整的安装和配置流程
- ✅ 详细的使用说明
- ✅ 高级用法和最佳实践
- ✅ 常见问题和解决方案

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [API_REFERENCE.md](API_REFERENCE.md) - API 文档
