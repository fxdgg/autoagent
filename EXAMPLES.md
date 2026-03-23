# 示例和用例

本文档提供 LangGraph + CodeBuddy Todo Orchestrator 的实际使用示例。

## 目录

- [基础示例](#基础示例)
- [机器学习场景](#机器学习场景)
- [代码质量场景](#代码质量场景)
- [性能优化场景](#性能优化场景)
- [数据处理场景](#数据处理场景)
- [高级用例](#高级用例)

## 基础示例

### 示例 1：简单任务

创建一个简单的一次性任务。

**配置文件 (todos.yaml)**：

```yaml
version: 1
workspace: /data/workspace/example

tasks:
  - id: 1
    name: "hello_world"
    description: "打印 Hello World"
    type: simple
    command: "echo 'Hello, World!'"
    expected_output: "Hello, World!"
```

**执行**：

```bash
python todo_orchestrator.py
```

**输出**：

```
============================================================
开始执行任务 1: 打印 Hello World
============================================================

📝 执行任务 1: 打印 Hello World
   命令: echo 'Hello, World!'
   结果: ✅ 成功

============================================================
执行总结:
  ✅ 任务 1: 打印 Hello World
============================================================
```

### 示例 2：多个简单任务

按顺序执行多个简单任务。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/example

tasks:
  - id: 1
    description: "创建目录"
    type: simple
    command: "mkdir -p output"
    
  - id: 2
    description: "生成数据"
    type: simple
    command: "python -c 'print(1, 2, 3)' > output/data.txt"
    
  - id: 3
    description: "查看数据"
    type: simple
    command: "cat output/data.txt"
```

### 示例 3：循环任务

创建一个需要 AI 优化的循环任务。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/example

tasks:
  - id: 1
    description: "优化代码性能"
    type: loop
    max_retries: 5
    completion_criteria: |
      运行时间 < 1 秒
      结果正确
    initial_instruction: "添加缓存机制"
```

**示例代码 (script.py)**：

```python
import time

def slow_function():
    time.sleep(2)  # 模拟慢操作
    return 42

if __name__ == "__main__":
    import time
    start = time.time()
    result = slow_function()
    duration = time.time() - start
    print(f"结果: {result}, 耗时: {duration:.2f}s")
```

**执行流程**：

```
🔄 第 1 次尝试: AI 修改代码
   AI 决策: 添加缓存机制
🏋️ 运行训练...
   结果: 结果: 42, 耗时: 0.01s
🔍 AI 检查完成情况...
   AI 判断: ✅ 已完成
   理由: 耗时 0.01s，满足 < 1s 的要求
```

## 机器学习场景

### 示例 4：模型训练优化

自动优化模型训练。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/ml-project

tasks:
  - id: 1
    description: "准备数据集"
    type: simple
    command: "python prepare_dataset.py"
    timeout: 600
    
  - id: 2
    description: "优化模型精度到 90% 以上"
    type: loop
    max_retries: 10
    timeout: 1800
    completion_criteria: |
      模型精度（accuracy）需要 >= 0.9
      训练无崩溃，无 OOM
      损失函数 loss < 0.1
      最后 3 个 epoch 的准确率方差 < 0.01
    initial_instruction: "将学习率从 0.001 调整到 0.0001"
```

**示例训练脚本 (train.py)**：

```python
import torch
import torch.nn as nn
import torch.optim as optim
import time

class SimpleModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(10, 50)
        self.fc2 = nn.Linear(50, 10)
    
    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = self.fc2(x)
        return x

def train(learning_rate=0.001, batch_size=32, epochs=10):
    model = SimpleModel()
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)
    
    # 模拟训练
    losses = []
    accuracies = []
    
    for epoch in range(epochs):
        # 模拟训练数据
        inputs = torch.randn(batch_size, 10)
        targets = torch.randint(0, 10, (batch_size,))
        
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, targets)
        loss.backward()
        optimizer.step()
        
        losses.append(loss.item())
        
        # 模拟准确率
        accuracy = 0.5 + epoch * 0.05
        accuracies.append(accuracy)
        
        print(f"Epoch {epoch+1}/{epochs}, Loss: {loss.item():.4f}, Accuracy: {accuracy:.2f}")
    
    final_accuracy = sum(accuracies[-3:]) / 3
    final_loss = sum(losses[-3:]) / 3
    
    return {
        "final_accuracy": final_accuracy,
        "final_loss": final_loss,
        "losses": losses,
        "accuracies": accuracies
    }

if __name__ == "__main__":
    learning_rate = 0.001  # 可以被 AI 修改
    batch_size = 32        # 可以被 AI 修改
    
    print(f"开始训练，学习率: {learning_rate}, batch_size: {batch_size}")
    result = train(learning_rate, batch_size)
    
    print(f"\n最终结果:")
    print(f"Accuracy: {result['final_accuracy']:.2f}")
    print(f"Loss: {result['final_loss']:.4f}")
```

**执行过程**：

```
============================================================
开始执行任务 2: 优化模型精度到 90% 以上
============================================================

🔄 第 1 次尝试: AI 修改代码
   AI 决策: 将学习率从 0.001 调整到 0.0001
🏋️ 运行训练...
   Epoch 1/10, Loss: 2.3456, Accuracy: 0.55
   Epoch 10/10, Loss: 1.2345, Accuracy: 0.95
🔍 AI 检查完成情况...
   AI 判断: ✅ 已完成
   理由: accuracy = 0.95，已达到 0.9 的要求
```

### 示例 5：超参数调优

自动搜索最优超参数。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/ml-project

tasks:
  - id: 1
    description: "搜索最优超参数组合"
    type: loop
    max_retries: 15
    timeout: 3600
    completion_criteria: |
      验证集准确率 >= 0.92
      测试集准确率 >= 0.90
      训练时间 < 10 分钟
    initial_instruction: "尝试调整学习率和 batch_size"
```

**执行流程**：

```
尝试 1: learning_rate=0.001, batch_size=32 → accuracy=0.85
尝试 2: learning_rate=0.0001, batch_size=64 → accuracy=0.88
尝试 3: learning_rate=0.0005, batch_size=128 → accuracy=0.91
尝试 4: learning_rate=0.0003, batch_size=128 → accuracy=0.93 ✅
```

### 示例 6：模型压缩

减少模型参数量。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/ml-project

tasks:
  - id: 1
    description: "压缩模型参数量 50%"
    type: loop
    max_retries: 8
    completion_criteria: |
      模型参数量 < 2.5M（原模型 5M）
      精度下降 < 2%
      推理速度提升 > 30%
    initial_instruction: "减少中间层神经元数量"
```

## 代码质量场景

### 示例 7：代码规范检查

自动修复代码规范问题。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/code-quality

tasks:
  - id: 1
    description: "运行代码检查"
    type: simple
    command: "pylint src/ --output-format=json > pylint_report.json"
    
  - id: 2
    description: "修复所有 Pylint 警告"
    type: loop
    max_retries: 5
    completion_criteria: |
      Pylint 报告中无警告和错误
      代码评分 >= 9.0
    initial_instruction: "修复所有 pylint 报告的问题"
```

**示例代码 (src/module.py)**：

```python
# 有问题的代码
def add(a,b):
    x=a+b
    return x

# 缺少文档字符串
class Calculator:
    def __init__(self):
        self.result=0
    
    def calculate(self, x, y):
        self.result=x*y
        return self.result
```

**执行流程**：

```
尝试 1: AI 添加文档字符串，修复命名规范
尝试 2: AI 添加类型注解
尝试 3: AI 添加空行和注释
尝试 4: ✅ Pylint 评分 9.5
```

### 示例 8：单元测试覆盖

提高测试覆盖率。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/code-quality

tasks:
  - id: 1
    description: "检查测试覆盖率"
    type: simple
    command: "pytest --cov=src --cov-report=json"
    
  - id: 2
    description: "提高测试覆盖率到 90%"
    type: loop
    max_retries: 5
    completion_criteria: |
      代码覆盖率 >= 90%
      所有测试通过
    initial_instruction: "为未覆盖的代码添加测试"
```

### 示例 9：重构代码

重构复杂代码。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/code-quality

tasks:
  - id: 1
    description: "重构复杂函数"
    type: loop
    max_retries: 5
    completion_criteria: |
      圈复杂度 <= 5
      函数长度 <= 50 行
      功能保持不变
    initial_instruction: "将大函数拆分为多个小函数"
```

**示例代码**：

```python
# 重构前：复杂的函数
def process_data(data):
    result = []
    for item in data:
        if item > 0:
            processed = item * 2
            if processed > 100:
                processed = 100
            result.append(processed)
        elif item < 0:
            processed = abs(item)
            if processed < 10:
                processed = 10
            result.append(processed)
    return result

# 重构后：拆分为多个小函数
def process_positive_item(item):
    processed = item * 2
    return min(processed, 100)

def process_negative_item(item):
    processed = abs(item)
    return max(processed, 10)

def process_data(data):
    result = []
    for item in data:
        if item > 0:
            result.append(process_positive_item(item))
        elif item < 0:
            result.append(process_negative_item(item))
    return result
```

## 性能优化场景

### 示例 10：算法优化

优化算法性能。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/performance

tasks:
  - id: 1
    description: "优化斐波那契数列计算"
    type: loop
    max_retries: 5
    completion_criteria: |
      计算 fib(40) 时间 < 1 秒
      结果正确
    initial_instruction: "使用记忆化优化"
```

**示例代码**：

```python
# 优化前：递归版本（慢）
def fib_recursive(n):
    if n <= 1:
        return n
    return fib_recursive(n-1) + fib_recursive(n-2)

# 优化后：记忆化版本（快）
from functools import lru_cache

@lru_cache(maxsize=None)
def fib_memoized(n):
    if n <= 1:
        return n
    return fib_memoized(n-1) + fib_memoized(n-2)

# 优化后：迭代版本（更快）
def fib_iterative(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n+1):
        a, b = b, a + b
    return b

if __name__ == "__main__":
    import time
    n = 40
    
    start = time.time()
    result = fib_iterative(n)
    duration = time.time() - start
    
    print(f"fib({n}) = {result}")
    print(f"耗时: {duration:.6f}s")
```

### 示例 11：数据库查询优化

优化数据库查询性能。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/performance

tasks:
  - id: 1
    description: "优化数据库查询"
    type: loop
    max_retries: 5
    completion_criteria: |
      查询时间 < 100ms
      返回正确结果
    initial_instruction: "添加索引或优化查询语句"
```

**示例代码**：

```python
# 优化前
def slow_query():
    query = """
    SELECT * FROM orders o
    JOIN customers c ON o.customer_id = c.id
    JOIN products p ON o.product_id = p.id
    WHERE o.order_date > '2024-01-01'
    """
    return execute(query)

# 优化后：添加索引
def optimized_query():
    query = """
    SELECT o.id, o.order_date, c.name, p.name
    FROM orders o
    JOIN customers c ON o.customer_id = c.id
    JOIN products p ON o.product_id = p.id
    WHERE o.order_date > '2024-01-01'
      AND c.active = 1
      AND p.active = 1
    """
    return execute(query)

# 索引定义
indexes = [
    "CREATE INDEX idx_orders_date ON orders(order_date)",
    "CREATE INDEX idx_customers_active ON customers(active)",
    "CREATE INDEX idx_products_active ON products(active)"
]
```

### 示例 12：内存优化

减少内存使用。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/performance

tasks:
  - id: 1
    description: "减少内存使用 50%"
    type: loop
    max_retries: 5
    completion_criteria: |
      内存使用 < 500MB
      功能保持不变
    initial_instruction: "使用生成器代替列表，及时释放内存"
```

**示例代码**：

```python
# 优化前：使用列表（内存占用大）
def process_large_file(filename):
    with open(filename) as f:
        lines = f.readlines()  # 一次性读取所有行
    
    results = []
    for line in lines:
        processed = line.strip().upper()
        results.append(processed)
    
    return results

# 优化后：使用生成器（内存占用小）
def process_large_file(filename):
    with open(filename) as f:
        for line in f:  # 逐行读取
            processed = line.strip().upper()
            yield processed

# 使用方式
for result in process_large_file("large_file.txt"):
    print(result)
```

## 数据处理场景

### 示例 13：数据清洗

自动清洗数据。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/data

tasks:
  - id: 1
    description: "清洗缺失数据"
    type: loop
    max_retries: 3
    completion_criteria: |
      无缺失值
      数据格式正确
      无异常值
    initial_instruction: "删除或填充缺失值"
```

**示例代码**：

```python
import pandas as pd

def clean_data(df):
    # 处理缺失值
    df = df.dropna(subset=['id'])  # 删除 id 为空的行
    df['age'] = df['age'].fillna(df['age'].mean())  # 填充年龄缺失值
    
    # 处理异常值
    df = df[df['age'] > 0]  # 删除年龄为负数的行
    df = df[df['age'] < 120]  # 删除年龄过大的行
    
    # 数据类型转换
    df['id'] = df['id'].astype(int)
    df['age'] = df['age'].astype(int)
    
    return df

if __name__ == "__main__":
    # 读取数据
    df = pd.read_csv("data.csv")
    print(f"原始数据: {len(df)} 行")
    print(f"缺失值: {df.isnull().sum().sum()}")
    
    # 清洗数据
    df = clean_data(df)
    
    print(f"清洗后数据: {len(df)} 行")
    print(f"缺失值: {df.isnull().sum().sum()}")
    
    # 保存
    df.to_csv("data_cleaned.csv", index=False)
```

### 示例 14：数据转换

转换数据格式。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/data

tasks:
  - id: 1
    description: "转换 CSV 到 JSON"
    type: simple
    command: "python convert_csv_to_json.py input.csv output.json"
```

**示例代码**：

```python
import csv
import json

def csv_to_json(csv_file, json_file):
    data = []
    
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    import sys
    csv_to_json(sys.argv[1], sys.argv[2])
    print("转换完成")
```

### 示例 15：数据聚合

聚合数据统计。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/data

tasks:
  - id: 1
    description: "生成月度统计报告"
    type: simple
    command: "python generate_report.py"
```

**示例代码**：

```python
import pandas as pd

def generate_monthly_report():
    # 读取数据
    df = pd.read_csv("sales.csv")
    
    # 转换日期
    df['date'] = pd.to_datetime(df['date'])
    df['month'] = df['date'].dt.to_period('M')
    
    # 按月聚合
    monthly_stats = df.groupby('month').agg({
        'amount': ['sum', 'mean', 'count'],
        'profit': 'sum'
    })
    
    # 保存报告
    monthly_stats.to_csv("monthly_report.csv")
    print("报告生成完成")

if __name__ == "__main__":
    generate_monthly_report()
```

## 高级用例

### 示例 16：任务依赖

定义任务之间的依赖关系。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/advanced

tasks:
  - id: 1
    description: "下载数据"
    type: simple
    command: "python download.py"
    
  - id: 2
    description: "预处理数据"
    type: simple
    command: "python preprocess.py"
    depends_on: [1]  # 依赖任务 1
    
  - id: 3
    description: "训练模型"
    type: loop
    max_retries: 5
    completion_criteria: "accuracy >= 0.9"
    depends_on: [2]  # 依赖任务 2
```

### 示例 17：条件任务

根据条件执行不同任务。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/advanced

tasks:
  - id: 1
    description: "检查 GPU 可用性"
    type: simple
    command: "python check_gpu.py"
    
  - id: 2
    description: "使用 GPU 训练"
    type: loop
    command: "CUDA_VISIBLE_DEVICES=0 python train.py"
    completion_criteria: "accuracy >= 0.9"
    condition: "has_gpu == true"
    
  - id: 3
    description: "使用 CPU 训练"
    type: loop
    command: "python train.py"
    completion_criteria: "accuracy >= 0.9"
    condition: "has_gpu == false"
```

### 示例 18：并行任务

并行执行多个独立任务。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/advanced

tasks:
  - id: 1
    description: "并行数据处理"
    type: parallel
    commands:
      - "python process_part1.py"
      - "python process_part2.py"
      - "python process_part3.py"
    
  - id: 2
    description: "合并结果"
    type: simple
    command: "python merge_results.py"
    depends_on: [1]
```

### 示例 19：Git 集成

自动提交代码修改。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/advanced

tasks:
  - id: 1
    description: "优化代码性能"
    type: loop
    max_retries: 5
    completion_criteria: "性能提升 20%"
    git:
      auto_commit: true
      commit_message: "perf: 优化 ${task.description}"
      branch: "feature/performance-optimization"
```

### 示例 20：通知集成

任务完成后发送通知。

**配置文件**：

```yaml
version: 1
workspace: /data/workspace/advanced

tasks:
  - id: 1
    description: "长时间训练任务"
    type: loop
    max_retries: 10
    completion_criteria: "accuracy >= 0.95"
    timeout: 7200
    notifications:
      on_start:
        - type: "email"
          to: "team@example.com"
          subject: "开始训练任务"
      on_complete:
        - type: "email"
          to: "team@example.com"
          subject: "训练完成"
        - type: "slack"
          channel: "#ml-team"
          message: "训练完成，accuracy: ${accuracy}"
      on_failure:
        - type: "email"
          to: "team@example.com"
          subject: "训练失败"
```

## 总结

本文档提供了丰富的示例：

- ✅ 基础用法示例
- ✅ 机器学习场景
- ✅ 代码质量场景
- ✅ 性能优化场景
- ✅ 数据处理场景
- ✅ 高级用例

每个示例都包含：
- 完整的配置文件
- 示例代码
- 执行流程说明

你可以根据实际需求调整这些示例。

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
- [API_REFERENCE.md](API_REFERENCE.md) - API 文档
