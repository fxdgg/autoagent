# 示例和用例

本文档提供 CodeBuddy Todo Orchestrator 的实际使用示例。

## 目录

- [基础示例](#基础示例)
- [机器学习场景](#机器学习场景)
- [代码质量场景](#代码质量场景)
- [性能优化场景](#性能优化场景)

## 基础示例

### 示例 1：简单任务

创建一个简单的一次性任务，AI 自主判断如何完成。

**配置文件 (todos.yaml)**：

```yaml
tasks:
  - id: 1
    name: "下载数据集"
    type: simple
    completion_criteria: "data.csv 文件存在且大小 > 10MB"
    initial_hint: "使用 python download.py"
```

**执行流程**：

```
📋 执行任务 1: 下载数据集
   类型: simple

   尝试 #1
      AI 尝试完成任务...
      AI 判断: ✅ 完成
   任务 1 完成！
```

### 示例 2：多个简单任务

按顺序执行多个简单任务。

```yaml
tasks:
  - id: 1
    name: "准备环境"
    type: simple
    completion_criteria: "所有依赖安装完成，python -c 'import torch' 无报错"
    initial_hint: "运行 pip install -r requirements.txt"

  - id: 2
    name: "运行代码检查"
    type: simple
    completion_criteria: "pylint 评分 >= 9.0 且无严重错误"
    initial_hint: "运行 pylint src/"

  - id: 3
    name: "分析性能瓶颈"
    type: simple
    completion_criteria: "生成性能分析报告并保存到 profile_report.txt"
    initial_hint: "运行 python profile.py"
```

### 示例 3：嵌套任务

包含多个子任务的复杂任务，子任务失败时 AI 分析原因并决定重试策略。

```yaml
tasks:
  - id: 1
    name: "优化模型精度"
    type: nested
    completion_criteria: |
      训练成功完成
      验证集精度 >= 0.9
      验证集 loss < 0.1
    subtasks:
      - id: 1.1
        name: "修改模型配置"
        type: simple
        completion_criteria: "模型配置修改完成，包括学习率、网络结构等参数"

      - id: 1.2
        name: "训练模型"
        type: long_running
        command: "python train.py --config config.yaml"
        completion_criteria: "训练正常退出且验证集指标满足要求"
```

**执行流程**：

```
📋 执行任务 1: 优化模型精度
   类型: nested

   📌 子任务 1.1: 修改模型配置 (simple)
      AI 修改代码...
      ✅ 子任务 1.1 完成

   📌 子任务 1.2: 训练模型 (long_running)
      启动后台训练: nohup python train.py --config config.yaml > logs/1.2.log 2>&1 &
      监控中...
      ❌ 子任务 1.2 失败 (CUDA out of memory)

   🤖 【AI 决策点1：失败分析】
      AI 分析: "模型参数过多导致 GPU 内存不足，需要回到 1.1 减少网络层数"
      AI 决策: retry_from = "1.1"

   📌 子任务 1.1: 修改模型配置 (simple) [重试]
      AI 修改代码: 减少网络层数
      ✅ 子任务 1.1 完成

   📌 子任务 1.2: 训练模型 (long_running) [重试]
      启动后台训练...
      ✅ 子任务 1.2 完成 (accuracy=0.92, loss=0.08)

   🤖 【AI 决策点2：主任务评估】
      AI 评估: accuracy=0.92 >= 0.9 ✅, loss=0.08 < 0.1 ✅
      AI 决策: main_task_completed = true

   ✅ 主任务 1 完成！
```

## 机器学习场景

### 示例 4：端到端训练流程

```yaml
tasks:
  - id: 1
    name: "准备训练数据"
    type: simple
    completion_criteria: "训练数据和验证数据准备完成，文件格式正确"
    initial_hint: "运行 python prepare_data.py"

  - id: 2
    name: "训练并优化模型"
    type: nested
    completion_criteria: |
      验证集精度 >= 0.95
      验证集 loss < 0.05
      模型文件保存成功
    subtasks:
      - id: 2.1
        name: "实现数据增强"
        type: simple
        completion_criteria: "数据增强功能实现完成，包括随机裁剪、旋转等"

      - id: 2.2
        name: "训练模型"
        type: long_running
        command: "python train.py --data augmented_data --model model.yaml"
        completion_criteria: "训练正常完成，模型文件保存成功"

      - id: 2.3
        name: "评估模型"
        type: simple
        completion_criteria: "模型评估完成，生成评估报告"
        initial_hint: "运行 python evaluate.py --model model.pth"
```

**AI 决策场景**：

- 如果子任务 2.2 训练失败（OOM）→ AI 可能决定 `retry_from: "2.1"` 减少数据增强的复杂度
- 如果子任务 2.3 评估不达标 → 所有子任务完成后，AI 在主任务评估中决定 `retry_from: "2.1"` 调整策略
- 如果子任务 2.2 训练成功但指标不够 → AI 在主任务评估中建议调整学习率或网络结构

### 示例 5：模型压缩

```yaml
tasks:
  - id: 1
    name: "压缩模型参数量"
    type: nested
    completion_criteria: |
      模型参数量 < 2.5M（原模型 5M）
      精度下降 < 2%
      推理速度提升 > 30%
    subtasks:
      - id: 1.1
        name: "实现模型剪枝"
        type: simple
        completion_criteria: "模型剪枝代码实现完成"

      - id: 1.2
        name: "训练压缩模型"
        type: long_running
        command: "python train_compressed.py --prune-ratio 0.5"
        completion_criteria: "训练完成，模型保存成功"

      - id: 1.3
        name: "对比评估"
        type: simple
        completion_criteria: "生成压缩前后的对比报告"
        initial_hint: "运行 python compare_models.py"
```

## 代码质量场景

### 示例 6：修复代码规范问题

```yaml
tasks:
  - id: 1
    name: "修复所有 Pylint 警告"
    type: nested
    completion_criteria: |
      Pylint 评分 >= 9.0
      符合 PEP8 规范
      无严重警告
    subtasks:
      - id: 1.1
        name: "分析代码警告"
        type: simple
        completion_criteria: "分析所有 pylint 警告，生成问题列表和修复方案"

      - id: 1.2
        name: "修复代码问题"
        type: simple
        completion_criteria: "所有警告和问题已修复"
```

### 示例 7：提高测试覆盖率

```yaml
tasks:
  - id: 1
    name: "提高测试覆盖率到 90%"
    type: nested
    completion_criteria: |
      代码覆盖率 >= 90%
      所有测试通过
    subtasks:
      - id: 1.1
        name: "分析未覆盖代码"
        type: simple
        completion_criteria: "生成未覆盖代码的分析报告"

      - id: 1.2
        name: "编写测试用例"
        type: simple
        completion_criteria: "为未覆盖的代码编写测试用例"

      - id: 1.3
        name: "运行测试验证"
        type: simple
        completion_criteria: "所有测试通过且覆盖率 >= 90%"
        initial_hint: "运行 pytest --cov=src --cov-report=term"
```

## 性能优化场景

### 示例 8：算法优化

```yaml
tasks:
  - id: 1
    name: "优化核心算法性能"
    type: nested
    completion_criteria: |
      运行时间 < 1 秒
      结果正确
      内存使用 < 500MB
    subtasks:
      - id: 1.1
        name: "优化算法实现"
        type: simple
        completion_criteria: "使用更高效的算法和数据结构"

      - id: 1.2
        name: "运行基准测试"
        type: simple
        completion_criteria: "基准测试完成，运行时间 < 1s，结果正确"
        initial_hint: "运行 python benchmark.py"
```

### 示例 9：数据库查询优化

```yaml
tasks:
  - id: 1
    name: "优化慢查询"
    type: nested
    completion_criteria: |
      所有查询响应时间 < 100ms
      返回结果正确
    subtasks:
      - id: 1.1
        name: "分析并优化查询"
        type: simple
        completion_criteria: "查询优化完成，添加必要索引"

      - id: 1.2
        name: "运行查询测试"
        type: simple
        completion_criteria: "所有查询响应时间 < 100ms"
        initial_hint: "运行 python test_queries.py"
```

## 总结

所有示例都遵循统一的设计原则：

- ✅ 任务描述清晰明确
- ✅ 完成标准可量化验证
- ✅ 合理使用任务类型（simple / nested / long_running）
- ✅ 子任务粒度适中
- ✅ 充分利用 AI 的决策能力

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
- [API_REFERENCE.md](API_REFERENCE.md) - API 文档
