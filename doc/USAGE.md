# 使用指南

本文档提供 CodeBuddy Todo Orchestrator 的详细使用说明。

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
- CodeBuddy 2.63.5+ (或其他 AI Provider)
- Linux/macOS/Windows 系统

### 2. 安装依赖

```bash
pip install pyyaml
```

### 3. 配置 AI Provider

确保 AI Provider 已正确安装：

```bash
# CodeBuddy
codebuddy --version

# Claude Code
claude --version

# Gemini CLI
gemini --version

# OpenCode
opencode --version
```

### 4. 配置 Preset（可选）

在 `config.yaml` 中定义常用配置预设：

```yaml
# config.yaml
bash_timeout: 3600

# Fast-fail timeout for autoagent-exec (in seconds, default: 10)
fast_fail_timeout: 10

# Maximum backoff wait time (in seconds) when AI CLI calls fail repeatedly.
# Uses exponential backoff: 5s, 10s, 20s, 40s, ... up to this limit.
backoff_max_wait: 300

# System prompt prefix (appended to the system prompt for all tasks)
system_prompt_prefix: "You are an AI coding agent. ..."

# Default AI model (used when no model is specified via CLI --model or preset)
default_model: glm-5.0-ioa

preset:
  - name: default
    ideas: ${workspace}/ideas.md
    config: ${workspace}/todos.yaml
    provider: codebuddy
    use_cli: false
    model: "plan:claude-opus-4.6;default:claude-opus-4.6;simple:claude-haiku-4.5"
    human_review: true
    verbose: true
  
  - name: test
    ideas: ${workspace}/../ideas.md
    config: ${workspace}/../todos.yaml
    provider: codebuddy
    use_cli: false
    model: "plan:glm-5.0-ioa;default:glm-5.0-ioa;simple:deepseek-v3-2-volc-ioa"
    human_review: true
    verbose: true
```

使用 `--preset` 参数选择预设：

```bash
# 使用 default 预设
python orchestrator.py

# 使用 claude 预设
python orchestrator.py --preset claude

# 使用 debug 预设（覆盖 verbose 为 true）
python orchestrator.py --preset debug --verbose
```

### 5. 配置截断限制（可选）

在 `config.yaml` 中可以调整提示词各字段的截断长度（单位：字符），防止上下文过长导致 token 浪费：

```yaml
# config.yaml
truncation_limits:
  suggested_fix: 1500        # AI 失败分析建议
  history_summary: 300       # 历史尝试摘要
  nested_latest_fix: 2000    # 嵌套任务的修复上下文
  looping_latest_fix: 1500   # 循环任务的修复上下文
  log_section: 6000          # 长时间任务日志汇总
  execution_results: 4000    # 子任务执行结果汇总
  idea_content: 8000         # Ideas 原文
  tasks_yaml: 10000          # 生成的任务 YAML
  review_feedback: 3000      # AI 审查反馈
  human_feedback: 3000       # 人工审核反馈
  error_text: 2000           # 错误信息
  log_file: 2000             # 单个日志文件内容
```

所有字段都有内置默认值，只需配置你想调整的项。

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
        type: simple
        completion_criteria: "代码修改完成"
        
      - id: 2.2
        name: "运行训练"
        type: long_running
        completion_criteria: "训练正常退出且验证集指标满足要求"
```

### 步骤 2：运行 Orchestrator

```bash
# 使用默认 provider（CodeBuddy）运行所有任务
python orchestrator.py

# 使用 Claude Code
python orchestrator.py --provider claude

# 使用 Gemini CLI
python orchestrator.py --provider gemini
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
      类型: simple
      
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
        type: simple
        completion_criteria: "配置修改完成"
        
      - id: 2.2
        name: "训练模型"
        type: long_running
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
| `type` | string | 是 | 顶层任务类型：`simple`、`nested`、`looping`；子任务类型：`simple`、`long_running`、`simple_once`、`long_running_once` |
| `completion_criteria` | string | 是 | 完成标准（自然语言描述） |

#### 简单任务 (type: simple)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `initial_hint` | string | 否 | 初始提示（给 AI 的参考信息） |

#### 嵌套任务 (type: nested)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |

#### 循环任务 (type: looping)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |
| `repeat_count` | int | 是 | 循环次数（正整数） |
| `max_attempts_per_loop` | int | 否 | 每轮循环内最大重试次数（默认 20） |
| `completion_criteria` | string | 是 | 完成标准 |

#### 长时间任务 (type: long_running)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command` | string | 否 | （已废弃）旧版配置字段，现在 AI 自主决定命令 |
| `completion_criteria` | string | 是 | 完成标准 |

## 任务类型

### 1. 简单任务 (simple)

**适用场景**：由 AI 自主完成的任务，包括命令执行、代码修改、分析等所有场景

**配置示例**：
```yaml
# 顶层任务
- id: 1
  name: "下载数据集"
  type: simple
  completion_criteria: "data.csv 文件存在且大小 > 10MB"
  initial_hint: "使用 python download.py"

# 作为子任务（代码修改）
- id: 2.1
  name: "修改训练代码"
  type: simple
  completion_criteria: "代码修改完成，添加了 dropout 层"
```

> **设计理念**：不区分"执行命令"和"修改代码"——对 AI 来说这是同一件事。用户只需要判断：**"这个任务需要在后台长时间运行吗？"** 需要就用 `long_running`，不需要就用 `simple`。

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
      type: simple
      completion_criteria: "代码修改完成"
      
      - id: 2.2
        name: "运行训练"
        type: long_running
        completion_criteria: "训练正常退出且验证集指标满足要求"
```

**执行流程**：
1. 按顺序执行所有子任务
2. 如果某个子任务失败，**立即停止后续子任务**，**调用AI分析失败原因**，AI决定从哪个子任务开始重试
3. 所有子任务完成后，**调用AI评估主任务是否完成**
4. 如果未完成，AI提出下一轮的优化策略，通过`retry_from`指定重试起点，开始新一轮尝试
5. 循环直到满足条件或达到最大尝试次数

**AI决策机制**：

系统会在两个关键时刻调用AI：

1. **子任务失败时**：
   - 系统提供失败信息、历史记录、错误日志等上下文
   - AI分析失败原因，决定从哪个子任务开始重试
   - AI提出具体的修复建议
   - 系统完全听从AI的决策，重置相应的子任务状态

2. **所有子任务完成后**：
   - 系统提供所有子任务的执行结果、训练日志、指标数据等上下文
   - AI判断主任务是否满足完成条件
   - 如果未完成，AI提出下一轮的优化方向和具体建议
   - 系统根据AI的评估决定是标记完成还是开始新一轮尝试

### 3. 循环任务 (looping)

**适用场景**：需要固定循环 N 次执行所有子任务的迭代优化场景（如 profile → optimize → benchmark → commit）

**配置示例**：
```yaml
- id: 15
  name: "迭代优化 CUDA 内核性能"
  type: looping
  repeat_count: 5
  max_attempts_per_loop: 10
  completion_criteria: |
    完成 5 轮优化迭代
    每轮包含：性能分析、代码优化、基准测试、提交
  subtasks:
    - id: 15.1
      name: "使用 ncu 分析性能瓶颈"
      type: long_running
      completion_criteria: "ncu 分析完成，生成性能报告"
      
    - id: 15.2
      name: "根据分析结果优化代码"
      type: simple
      completion_criteria: "代码优化完成，编译通过"
      
    - id: 15.3
      name: "运行基准测试验证优化效果"
      type: simple
      completion_criteria: "基准测试完成，记录性能数据"
```

**与 nested 的区别**：
- `nested`：AI 每轮评估是否完成，可能提前结束或继续重试
- `looping`：固定循环 N 次，不做完成度评估，每轮重置所有子任务状态重新执行

**执行流程**：
1. 每轮循环重置所有子任务状态
2. 按顺序执行所有子任务
3. 子任务失败时 AI 分析原因并决定重试策略（在当前轮内重试）
4. 循环完指定次数即完成

### 4. 长时间任务 (long_running)

**适用场景**：可能超过 CodeBuddy 超时限制的任务（如模型训练、Profiling）

**配置示例**：
```yaml
- id: 2.2
  name: "运行训练"
  type: long_running
  completion_criteria: "训练正常退出且验证集指标满足要求"
```

> **注意**：`long_running` 类型不需要在 YAML 中指定 `command` 字段。AI 会根据任务描述和上下文自主决定要运行的命令，并通过 `autoagent-exec` 启动。

**执行流程**：
1. AutoAgent 构造 prompt，告知 AI 使用 `autoagent-exec` wrapper 脚本启动长时间命令
2. AI 通过 wrapper 脚本调用 `autoagent-exec.bat <command>`（内部参数由 wrapper 预填）
3. `autoagent-exec` 启动命令并监视（超时时间由 `config.yaml` 的 `fast_fail_timeout` 配置）：
   - 超时内失败：智能输出（短输出内联打印，长输出只给路径），AI 可修复并重试
   - 超时内成功：智能输出（短输出内联打印并标注 not truncated，长输出只给路径）
   - 超时后仍在运行：输出 "TASK SUBMITTED"，AI 结束会话
4. AutoAgent 检测到 `LONG_RUNNING_IN_PROGRESS`，开始轮询信号文件
5. 任务完成后，重新启动 AI 分析输出日志并判断完成条件

**技术细节**：
- 使用 `autoagent_exec.py` 作为启动器（通过 wrapper 脚本调用），支持快速失败检测（超时时间由 `config.yaml` 的 `fast_fail_timeout` 配置）
- 信号文件（`lr_tasks/lr_<task_id>_signal.json`）用于进程间通信
- 输出日志（`lr_tasks/lr_<task_id>_output.log`）记录命令完整输出
- 信号文件和输出日志均位于 `session_dir/lr_tasks/`（由 orchestrator 的 `--log-dir` 参数决定）

## 执行方式

### 1. 使用 Preset 配置

通过 `config.yaml` 中的 preset 快速切换常用配置：

```bash
# 使用 default 预设
python orchestrator.py

# 使用 codebuddy 预设
python orchestrator.py --preset codebuddy

# 使用 claude 预设
python orchestrator.py --preset claude

# 使用预设但覆盖特定参数
python orchestrator.py --preset default --model claude-sonnet-4-6
```

**Preset 优先级**：命令行参数 > Preset 配置 > 默认值

支持的 Preset 字段：
- `config`: 任务配置文件路径
- `ideas`: ideas.md 文件路径
- `provider`: AI Provider 名称
- `model`: AI 模型名称
- `verbose`: 是否启用详细日志
- `no_skip`: 是否不跳过已完成任务
- `no_idle`: 是否禁用 idle 模式
- `use_cli`: 是否使用 CLI 模式
- `ideas_only`: 是否仅处理 ideas
- `human_review`: 是否启用人工审核
- `timeout`: AI 调用超时时间
- `log_dir`: 日志目录
- `idle_interval`: idle 轮询间隔
- `include_directories`: 额外目录（Gemini 专用）
- `test_rules`: 测试规则文件路径

### 2. 交互式执行

默认模式，实时输出日志：

```bash
python orchestrator.py
```

### 2. 选择 AI Provider

支持多种 AI CLI 工具：

```bash
# CodeBuddy（默认，默认模型从 config.yaml 的 default_model 加载）
python orchestrator.py

# Claude Code（默认模型 claude-sonnet-4-6）
python orchestrator.py --provider claude

# Gemini Cli（默认模型 gemini-2.5-pro）
python orchestrator.py --provider gemini

# OpenCode（使用 opencode 自身配置的默认模型）
python orchestrator.py --provider opencode

# 指定模型
python orchestrator.py --provider codebuddy --model deepseek-v3.2
python orchestrator.py --provider gemini --model gemini-2.5-pro

# 使用自定义可执行文件路径
python orchestrator.py --provider claude --executable /usr/local/bin/claude

# 传递额外 CLI 参数给 AI 工具
python orchestrator.py --extra-args "--max-turns 1000"

# 查看所有可用 provider
python orchestrator.py --list-providers
```

### 3. 后台执行

```bash
nohup python orchestrator.py > orchestrator.log 2>&1 &
```

### 4. 断点续传

如果执行中断，可以从断点继续：

```bash
# 会自动检测未完成的任务
python orchestrator.py
```

状态保存在 `todos_state.yaml` 中，程序会自动读取并继续执行。

### 5. 查看状态

```bash
# 查看任务状态
python orchestrator.py --status
```

### 6. 其他常用命令

```bash
# 验证配置文件是否合法
python orchestrator.py --validate

# 不跳过已完成的任务，全部重新执行
python orchestrator.py --no-skip

# 重置所有状态
python orchestrator.py --reset

# 启用详细日志
python orchestrator.py --verbose

# 使用预设配置
python orchestrator.py --preset claude

# 列出所有可用 provider
python orchestrator.py --list-providers
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
      type: simple
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
      type: simple
      completion_criteria: "代码修改完成"
      
    # 步骤2：长时间训练（避免超时）
      - id: 2.2
        name: "运行训练"
        type: long_running
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

### 6. AI决策的最佳实践

#### 子任务完成条件

- ✅ 明确且可验证
- ✅ 避免模糊的描述
- ✅ 考虑AI的判断能力

**示例**：

```yaml
# ❌ 不好：AI很难判断
- id: 2.1
  name: "优化模型"
  type: simple
  completion_criteria: "代码变好了"

# ✅ 好：明确的标准
- id: 2.1
  name: "优化模型"
  type: simple
  completion_criteria: |
    代码修改已完成，具体包括：
    1. 添加了dropout层
    2. 调整了学习率
    3. 代码可以正常运行
```

#### 主任务完成条件

- ✅ 基于具体的指标
- ✅ 考虑边界情况
- ✅ 给出明确的数值要求

**示例**：

```yaml
# ❌ 不好：模糊不清
- id: 2
  name: "优化模型性能"
  type: nested
  completion_criteria: "性能要好"

# ✅ 好：具体明确
- id: 2
  name: "优化模型性能"
  type: nested
  completion_criteria: |
    在验证集上满足以下所有条件：
    1. val_loss < 0.5
    2. val_accuracy >= 0.9
    3. 训练过程中无OOM错误
    4. 最后3个epoch的loss稳定（方差<0.01）
```

#### 利用AI的决策能力

系统会在两个关键点调用AI，你可以通过合理的任务设计来充分利用AI的决策能力：

1. **子任务失败时**：
   - AI会分析失败原因
   - AI会决定从哪个子任务开始重试
   - AI会提出修复建议

2. **主任务评估时**：
   - AI会评估是否满足完成条件
   - AI会分析结果与目标的差距
   - AI会提出下一轮的优化方向

**建议**：
- 提供足够的历史信息（系统会自动收集）
- 给出明确的完成条件（让AI有明确的判断标准）
- 信任AI的决策（系统完全听从AI）
- 记录AI的决策（便于回顾和调试）

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

### 问题 3.5：AI CLI 连续调用失败

**现象**：AI CLI 工具反复返回错误（网络问题、认证过期、服务端限流等）

**内置机制**：系统自动使用指数退避策略（5s → 10s → 20s → 40s → ... → `backoff_max_wait`），成功后自动重置。系统永远不会因为连续失败而主动退出。

**配置**：在 `config.yaml` 中调整 `backoff_max_wait`（默认 300 秒）。

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

### Q: 支持哪些 AI 工具和模型？

支持五种 AI CLI 工具：

| Provider | 命令 | 默认模型 | 别名 |
|----------|------|----------|------|
| CodeBuddy | `codebuddy` | 从 config.yaml 的 `default_model` 加载 | `cb` |
| Claude Code | `claude` | `claude-sonnet-4-6` | `claude-code`, `claude` |
| Gemini CLI | `gemini` | `gemini-2.5-pro` | `gemini-cli`, `gemini` |
| OpenCode | `opencode` | （使用自身配置默认） | `oc` |
| Test | `test` | `test` | - |

> **Test Provider** 不调用真实 AI，而是从 `--test-rules` 指定的规则文件中按顺序读取预定义响应，用于测试编排逻辑。

使用 `--list-providers` 查看所有可用 provider和别名。

### Q: 如何自定义模型？

通过命令行 `--model` 参数指定：

```bash
# 单模型（所有阶段使用同一模型）
python orchestrator.py --model deepseek-v3.2

# 多模型（不同阶段使用不同模型）
# 格式: "plan:模型A;default:模型B;simple:模型C"
# - plan: idea 分解为 TODO 阶段
# - default: 任务执行默认模型
# - simple: 简单任务使用的轻量模型
python orchestrator.py --model "plan:GLM-4-Flash;default:GLM-5;simple:GLM-4-Flash"

# 只指定部分角色（缺失的角色使用 default 的值）
python orchestrator.py --model "default:GLM-5;simple:GLM-4-Flash"
```

或在代码中指定：

```python
from ai_providers import get_provider
from orchestrator import TodoOrchestrator

provider = get_provider("codebuddy", model="deepseek-v3.2")
orchestrator = TodoOrchestrator(provider=provider)
```

## 总结

本文档涵盖了：

- ✅ 完整的安装和配置流程
- ✅ 详细的任务类型说明
- ✅ 多 AI Provider 支持（CodeBuddy / Claude Code / Gemini CLI / OpenCode）
- ✅ 完整的使用指南
- ✅ 最佳实践建议
- ✅ 常见问题和解决方案

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
