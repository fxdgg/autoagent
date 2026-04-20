# 使用示例

本文档提供 AutoAgent 的实际使用示例，覆盖三种执行模式。

---

## 1. 线性模式示例

### 1.1 简单任务：修复测试

```yaml
description: |
  Python Web 项目，使用 pytest 测试框架。
  项目根目录：./webapp

tasks:
  - id: 1
    name: "修复失败的单元测试"
    type: simple
    completion_criteria: |
      1. pytest tests/ 全部通过（exit code 0）
      2. 无新增 pylint 警告
    initial_hint: |
      运行 pytest tests/ -v 查看失败详情。
      修复代码后重新运行确认通过。
```

```bash
python orchestrator.py --config todos.yaml --workspace ./webapp
```

### 1.2 嵌套任务：实现功能

```yaml
description: |
  Node.js REST API 项目。
  构建：npm run build
  测试：npm test

tasks:
  - id: 1
    name: "实现用户注册 API"
    type: nested
    completion_criteria: |
      POST /api/register 接口可用，输入验证完整，测试覆盖 > 80%
    subtasks:
      - id: 1.1
        name: "实现注册逻辑"
        type: simple
        completion_criteria: |
          src/routes/register.ts 存在，包含输入验证和数据库写入
        initial_hint: |
          参考 src/routes/login.ts 的结构。
          需要：邮箱格式验证、密码强度检查、重复注册检测。

      - id: 1.2
        name: "编写测试并验证"
        type: simple
        completion_criteria: |
          1. npm test 通过
          2. tests/register.test.ts 覆盖正常和异常场景
        max_attempts: 3
```

### 1.3 循环任务：迭代优化

```yaml
description: |
  CUDA 图像处理项目。
  构建：cmake --build build --config Release
  运行：build/Release/main.exe
  正确性：输出 "Score: 100/100"
  性能数据：results.tsv

tasks:
  - id: 1
    name: "建立基准"
    type: simple
    model: lite
    completion_criteria: |
      1. 编译成功
      2. Score: 100/100
      3. 基准耗时写入 results.tsv
    initial_hint: |
      cmake --build build --config Release
      运行 main.exe，记录耗时到 results.tsv

  - id: 2
    name: "迭代优化"
    type: looping
    repeat_count: 50
    max_attempts_per_loop: 3
    completion_criteria: "完成一轮分析→优化→验证循环"
    subtasks:
      - id: 2.1
        name: "分析瓶颈并提出方案"
        type: simple
        completion_criteria: |
          优化方案已记录到 ideas/ 目录
        initial_hint: |
          读取 results.tsv 中 SOTA 数据。
          用 ncu profiling 找到瓶颈。
          方案写入 ideas/<N>.md。

      - id: 2.2
        name: "实现优化"
        type: simple
        completion_criteria: "代码修改已提交"

      - id: 2.3
        name: "编译并运行基准"
        type: long_running
        model: lite
        completion_criteria: "基准测试完成，日志已保存"
        initial_hint: |
          cmake --build build --config Release
          ./main.exe 2>&1 | tee logs/exp_<N>.log

      - id: 2.4
        name: "评估结果"
        type: simple
        completion_criteria: |
          结果已追加到 results.tsv。
          提升 >= 5% 则保留，否则回滚。
```

### 1.4 长时间任务：模型训练

```yaml
description: |
  PyTorch 模型训练项目。
  训练脚本：python train.py --config configs/base.yaml
  预计训练时间：2-4 小时

tasks:
  - id: 1
    name: "准备训练环境"
    type: simple
    model: lite
    completion_criteria: |
      1. pip install -r requirements.txt 成功
      2. python -c "import torch; print(torch.cuda.is_available())" 输出 True

  - id: 2
    name: "训练模型"
    type: nested
    completion_criteria: "模型训练完成，验证集准确率 > 90%"
    subtasks:
      - id: 2.1
        name: "启动训练"
        type: long_running
        model: lite
        completion_criteria: |
          训练完成，输出日志包含 "Training complete"
        initial_hint: |
          python train.py --config configs/base.yaml --epochs 50

      - id: 2.2
        name: "评估模型"
        type: simple
        completion_criteria: |
          评估报告保存到 results/eval_report.txt，准确率 > 90%
        initial_hint: |
          python evaluate.py --checkpoint checkpoints/best.pt
          将结果写入 results/eval_report.txt
```

---

## 2. AI 调度模式示例

### 2.1 性能优化（AI 自主决策循环）

```yaml
description: |
  cuFFTDx 3D DCT 性能优化项目。
  核心文件：cufftdx_dct3d.cuh（CUDA kernel）
  构建：cmake --build build --config Release
  正确性：main.exe 输出 "Score: 100/100"
  目标：性能提升 >= 20%

ai_orchestrator:
  strategy: |
    调度规则：
    1. 若 Task 1 未执行过，先执行 Task 1 建立基准。
    2. 基准建立后，执行 Task 2 分析性能瓶颈。
    3. 分析完成后，执行 Task 3 实施一轮优化。
    4. 优化后执行 Task 4 验证正确性。
       - Task 4 失败 → 再次执行 Task 3 修复回归。
       - Task 4 成功且提升 >= 20% → 执行 Task 5 生成报告并停止。
       - 否则 → 回到 Task 2 重新分析。
    5. Task 3 连续失败 3 次 → 回到 Task 2 重新分析。
  max_rounds: 20
  stop_condition: |
    性能提升 >= 20% 且 Score: 100/100，或 20 轮调度耗尽。
  last_result:
    1:
      type: file
      path: ${workspace}/baseline_profile.txt
    2:
      type: response
    3:
      type: response
    4:
      type: file
      path: ${workspace}/test_result.txt
    5:
      type: file
      path: ${workspace}/final_report.txt

tasks:
  - id: 1
    name: "环境搭建与基准测试"
    description: "编译项目，验证正确性，运行 ncu profiling 建立基准。"
    type: nested
    completion_criteria: |
      1. 编译成功
      2. Score: 100/100
      3. baseline_profile.txt 存在
    subtasks:
      - id: 1.1
        name: "编译项目"
        type: simple_once
        completion_criteria: "编译成功，可执行文件存在"
        max_attempts: 3
      - id: 1.2
        name: "运行正确性测试和 profiling"
        type: simple
        completion_criteria: "Score: 100/100，baseline_profile.txt 已保存"
        max_attempts: 3

  - id: 2
    name: "性能分析"
    description: "分析 ncu profiling 数据，识别瓶颈并提出优化策略。"
    type: simple
    completion_criteria: |
      识别至少 2 个瓶颈，提出排序的优化策略。
    max_attempts: 3

  - id: 3
    name: "实施优化"
    description: "实施一轮优化，重新编译并 profiling 测量效果。"
    type: nested
    completion_criteria: "代码修改完成，重新编译和 profiling 成功"
    subtasks:
      - id: 3.1
        name: "实现优化"
        type: simple
        completion_criteria: "代码修改完成"
        max_attempts: 3
      - id: 3.2
        name: "重新编译和 profiling"
        type: simple
        completion_criteria: "编译成功，新 profiling 数据已生成"
        max_attempts: 3

  - id: 4
    name: "正确性验证"
    description: "运行正确性测试，结果保存到 test_result.txt。"
    type: simple
    completion_criteria: "Score: 100/100，结果保存到 test_result.txt"
    max_attempts: 2

  - id: 5
    name: "生成最终报告"
    description: "汇总所有优化轮次，生成 final_report.txt。"
    type: simple
    completion_criteria: "final_report.txt 包含基准、优化内容和最终提升百分比"
    max_attempts: 2
```

```bash
python orchestrator.py --config todos.yaml --workspace ./cufftdx_project
```

### 2.2 自动化 Bug 修复

```yaml
description: |
  Go 微服务项目，存在多个已知 bug。
  测试：go test ./...
  Lint：golangci-lint run

ai_orchestrator:
  strategy: |
    1. 先执行 Task 1 获取当前测试状态。
    2. 根据失败测试数量，执行 Task 2 修复 bug。
    3. 每次修复后执行 Task 3 验证。
       - 全部通过 → 执行 Task 4 并停止。
       - 仍有失败 → 回到 Task 2 继续修复。
  max_rounds: 15
  stop_condition: "所有测试通过且 lint 无错误"
  last_result:
    1: { type: file, path: "${workspace}/test_status.txt" }
    2: { type: response }
    3: { type: file, path: "${workspace}/test_status.txt" }

tasks:
  - id: 1
    name: "获取测试状态"
    description: "运行全部测试，将结果摘要保存到 test_status.txt。"
    type: simple
    model: lite
    completion_criteria: "test_status.txt 包含测试通过/失败统计"

  - id: 2
    name: "修复 Bug"
    description: "分析失败测试，修复一个 bug。"
    type: simple
    completion_criteria: "代码修改完成并提交"

  - id: 3
    name: "验证修复"
    description: "重新运行测试，更新 test_status.txt。"
    type: simple
    model: lite
    completion_criteria: "test_status.txt 已更新"

  - id: 4
    name: "最终清理"
    description: "运行 lint，修复警告，提交最终代码。"
    type: simple
    completion_criteria: "golangci-lint run 无错误，代码已提交"
```

---

## 3. Ideas 模式示例

### 启动 Idle 监听

```bash
python orchestrator.py --ideas ideas.md --config todos.yaml --workspace ./project --preset general
```

### ideas.md 内容

```markdown
把项目的单元测试覆盖率从 60% 提升到 90%，优先覆盖 core/ 目录下的关键模块

---

给 API 添加 rate limiting 中间件，每个 IP 每分钟最多 100 次请求
```

AI 会自动将每个 idea 拆解为结构化任务并执行。

### 带人工审核

```bash
python orchestrator.py --ideas ideas.md --config todos.yaml --human-review
```

AI 生成任务后会暂停等待确认，输入 `y` 接受或 `n` 拒绝并提供反馈。

---

## 4. 多 Provider 示例

```bash
# 使用 Claude Code
python orchestrator.py --provider claude --config todos.yaml

# 使用 Gemini CLI
python orchestrator.py --provider gemini --config todos.yaml

# 使用 Codex
python orchestrator.py --provider codex --config todos.yaml

# 使用 CodeBuddy SDK 模式（默认）
python orchestrator.py --config todos.yaml

# 使用 CodeBuddy CLI 模式
python orchestrator.py --use-cli --config todos.yaml
```

---

## 5. 常用命令组合

```bash
# 验证配置
python orchestrator.py --config todos.yaml --validate

# 重置状态重新开始
python orchestrator.py --config todos.yaml --reset

# 只执行某个任务
python orchestrator.py --config todos.yaml --task 2

# 使用 Preset + 指定工作目录
python orchestrator.py --preset general --workspace ./my_project

# 生成默认配置文件
python orchestrator.py --generate-default-config
```
